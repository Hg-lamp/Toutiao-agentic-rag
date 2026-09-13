import asyncio
import hashlib
import json
from typing import Any

from langchain_core.documents import Document
from redisvl.query import FilterQuery, TextQuery
from redisvl.query.filter import FilterExpression, Num, Tag, Text

from backend.config.rag_config import rag_settings
from backend.schemas.rag import RagFilters, RetrievalTask, RetrievedChunk


# RAG 检索适配层统一封装 Redis 向量索引、向量相似度检索和 BM25 检索。
# 所有入口都返回 RetrievedChunk，并在服务端强制加入 user_id 过滤。
_REQUIRED_INDEX_FIELDS = {
    "text",
    "embedding",
    "_index_name",
    "_metadata_json",
    "category",
    "num",
    "user_id",
    "document_id",
    "source",
}
_VALIDATED_INDEXES: set[str] = set()


# 延迟加载向量库，避免仅导入 RAG 图时就初始化 Redis 和 embedding 服务。
def _get_vector_store():
    from backend.config.redis_vector import retriever_database
    return retriever_database


# 首次使用某个索引时校验检索所需字段，避免索引配置不完整导致隐晦失败。
def _ensure_index_fields(store) -> None:
    index_name = store.config.index_name
    if index_name in _VALIDATED_INDEXES:
        return

    info = store.index.info()
    attributes = info.get("attributes", [])
    fields = {
        str(attribute[1])
        for attribute in attributes
        if isinstance(attribute, (list, tuple)) and len(attribute) > 1
    }
    missing = sorted(_REQUIRED_INDEX_FIELDS - fields)
    if missing:
        raise RuntimeError(
            f"Redis 向量索引 {index_name} 缺少字段: {', '.join(missing)}。"
            "请清理并重建 RAG 向量索引后再执行检索。"
        )
    _VALIDATED_INDEXES.add(index_name)


# 将索引元数据安全转换为整数；无法转换时返回 None 供调用方选择回退逻辑。
def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# 统一处理 Redis 返回的字符串、字节和空值。
def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


# 解析索引中的 JSON 元数据；格式非法时返回空字典而不是传播解析异常。
def _metadata_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


# 为候选块生成稳定 ID，优先使用显式 chunk_id，其次使用文档和块序号，
# 最后使用内容摘要；稳定 ID 是后续去重和父块扩展的基础。
def make_chunk_id(metadata: dict[str, Any], content: str) -> str:
    explicit = metadata.get("chunk_id")
    if explicit:
        return str(explicit)

    document_id = str(metadata.get("document_id") or metadata.get("source") or "unknown")
    chunk_index = _as_int(metadata.get("chunk_index"))
    if chunk_index is None:
        chunk_index = _as_int(metadata.get("num"))
    if chunk_index is not None:
        return f"{document_id}:{chunk_index}"

    digest = hashlib.sha1(content.encode("utf-8")).hexdigest()[:16]
    return f"{document_id}:{digest}"


# 构造同时包含 ACL 和业务过滤条件的 Redis 表达式。
# user_id 始终由服务端传入，不能由模型通过 filters 绕过。
def build_filter_expression(
    user_id: int,
    filters: RagFilters | None = None,
) -> FilterExpression:
    """构造 ACL 与业务过滤组合，user_id 始终由服务端强制加入。"""
    expression: FilterExpression = Tag("user_id") == str(user_id)
    filters = filters or RagFilters()

    if filters.document_ids:
        values = [str(value) for value in filters.document_ids if value]
        if values:
            document_expression = Tag("document_id") == values[0]
            for value in values[1:]:
                document_expression = document_expression | (Tag("document_id") == value)
            expression = expression & document_expression

    if filters.document_types:
        values = [str(value) for value in filters.document_types if value]
        if values:
            category_expression = Tag("category") == values[0]
            for value in values[1:]:
                category_expression = category_expression | (Tag("category") == value)
            expression = expression & category_expression

    if filters.sources:
        values = [str(value) for value in filters.sources if value]
        if values:
            source_expression = Text("source") == values[0]
            for value in values[1:]:
                source_expression = source_expression | (Text("source") == value)
            expression = expression & source_expression

    return expression


# 将 LangChain Document 转换为统一的 RetrievedChunk，并记录来源任务。
def _document_to_chunk(
    document: Document,
    *,
    task: RetrievalTask,
    rank: int,
    retrieval_score: float | None,
) -> RetrievedChunk:
    metadata = dict(document.metadata or {})
    metadata["_retrieval_task_id"] = task.task_id
    document_id = str(metadata.get("document_id") or metadata.get("source") or "unknown")
    return RetrievedChunk(
        chunk_id=make_chunk_id(metadata, document.page_content),
        document_id=document_id,
        content=document.page_content,
        metadata=metadata,
        retrieval_source=task.channel,
        retrieval_rank=rank,
        retrieval_score=retrieval_score,
    )


# 执行向量相似度检索。阻塞式向量库调用在线程中执行，并受超时限制。
# raw distance 会转换为统一的 similarity 分数供后续融合。
async def vector_search(
    task: RetrievalTask,
    *,
    user_id: int,
    filters: RagFilters,
    limit: int,
) -> list[RetrievedChunk]:
    store = _get_vector_store()
    filter_expression = build_filter_expression(user_id, filters)

    def _search() -> list[RetrievedChunk]:
        _ensure_index_fields(store)
        results = store.similarity_search_with_score(
            task.query,
            k=limit,
            filter=filter_expression,
        )
        chunks: list[RetrievedChunk] = []
        for rank, item in enumerate(results, start=1):
            if not isinstance(item, tuple) or len(item) < 2:
                continue
            document, raw_distance = item[0], item[1]
            if not isinstance(document, Document):
                continue
            distance = float(raw_distance)
            similarity = 1.0 / (1.0 + max(distance, 0.0))
            chunks.append(
                _document_to_chunk(
                    document,
                    task=task,
                    rank=rank,
                    retrieval_score=similarity,
                )
            )
        return chunks

    return await asyncio.wait_for(
        asyncio.to_thread(_search),
        timeout=rag_settings.retrieval_timeout_seconds,
    )


# 执行 BM25 文本检索，并把 Redis 返回字段和 JSON 元数据规范化为候选块。
# 与向量检索一样，查询始终带有服务端 ACL 过滤和调用超时。
async def bm25_search(
    task: RetrievalTask,
    *,
    user_id: int,
    filters: RagFilters,
    limit: int,
) -> list[RetrievedChunk]:
    store = _get_vector_store()
    filter_expression = build_filter_expression(user_id, filters)
    content_field = store.config.content_field
    return_fields = [
        content_field,
        "_metadata_json",
        "document_id",
        "source",
        "category",
        "num",
    ]

    def _search() -> list[RetrievedChunk]:
        _ensure_index_fields(store)
        query = TextQuery(
            text=task.query,
            text_field_name=content_field,
            text_scorer="BM25STD",
            filter_expression=filter_expression,
            return_fields=return_fields,
            num_results=limit,
            stopwords=None,
        )
        results = store.index.query(query)
        chunks: list[RetrievedChunk] = []
        for rank, result in enumerate(results, start=1):
            content = _as_text(result.get(content_field))
            if not content:
                continue
            metadata = _metadata_json(result.get("_metadata_json"))
            metadata["_retrieval_task_id"] = task.task_id
            for field in ("document_id", "source", "category", "num"):
                if field in result and field not in metadata:
                    metadata[field] = result[field]
            raw_score = result.get("score")
            try:
                score = float(raw_score)
            except (TypeError, ValueError):
                score = None
            document_id = str(metadata.get("document_id") or metadata.get("source") or "unknown")
            chunks.append(
                RetrievedChunk(
                    chunk_id=make_chunk_id(metadata, content),
                    document_id=document_id,
                    content=content,
                    metadata=metadata,
                    retrieval_source=task.channel,
                    retrieval_rank=rank,
                    retrieval_score=score,
                )
            )
        return chunks

    return await asyncio.wait_for(
        asyncio.to_thread(_search),
        timeout=rag_settings.retrieval_timeout_seconds,
    )


async def fetch_parent_window(
    *,
    user_id: int,
    document_id: str,
    center_index: int,
    window: int,
) -> list[RetrievedChunk]:
    if window <= 0:
        return []

    store = _get_vector_store()
    content_field = store.config.content_field
    lower = max(0, center_index - window)
    upper = center_index + window
    expression = (
        (Tag("user_id") == str(user_id))
        & (Tag("document_id") == document_id)
        & Num("num").between(lower, upper)
    )
    return_fields = [
        content_field,
        "_metadata_json",
        "document_id",
        "source",
        "category",
        "num",
    ]

    def _fetch() -> list[RetrievedChunk]:
        _ensure_index_fields(store)
        query = FilterQuery(
            filter_expression=expression,
            return_fields=return_fields,
            num_results=(window * 2) + 1,
            sort_by=("num", "ASC"),
        )
        results = store.index.query(query)
        chunks: list[RetrievedChunk] = []
        for rank, result in enumerate(results, start=1):
            content = _as_text(result.get(content_field))
            if not content:
                continue
            metadata = _metadata_json(result.get("_metadata_json"))
            for field in ("document_id", "source", "category", "num"):
                if field in result and field not in metadata:
                    metadata[field] = result[field]
            chunks.append(
                RetrievedChunk(
                    chunk_id=make_chunk_id(metadata, content),
                    document_id=str(metadata.get("document_id") or document_id),
                    content=content,
                    metadata=metadata,
                    retrieval_source="parent",
                    retrieval_rank=rank,
                )
            )
        return chunks

    return await asyncio.wait_for(
        asyncio.to_thread(_fetch),
        timeout=rag_settings.retrieval_timeout_seconds,
    )
