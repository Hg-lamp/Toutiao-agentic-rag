import math
import re
from collections import defaultdict
from typing import Any, Iterable

from backend.config.rag_config import rag_settings
from backend.schemas.rag import (
    Citation,
    Evidence,
    RagDiagnostics,
    RagFilters,
    RagQuery,
    RetrievedChunk,
)


# RAG 后处理模块负责候选合并、去重、重排、证据融合以及上下文构建。
# 这里不访问外部服务，所有函数都基于检索阶段产生的结构化数据计算结果。
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")


# 估算文本 token 数，用于在不加载 tokenizer 的情况下控制上下文预算。
def estimate_tokens(text: str) -> int:
    """近似 token 计数。

    CJK 字符按 1 token 估算，ASCII 单词和数字按约 4 字符 1 token 估算。
    该实现不依赖需要联网下载词表的 tokenizer，同时比纯字符截断更接近实际预算。
    """
    if not text:
        return 0

    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", text))
    non_cjk = re.sub(r"[\u4e00-\u9fff]", " ", text)
    ascii_count = sum(max(1, math.ceil(len(token) / 4)) for token in _TOKEN_RE.findall(non_cjk))
    punctuation_count = len(re.findall(r"[^\w\s\u4e00-\u9fff]", non_cjk))
    return cjk_count + ascii_count + punctuation_count


# 在不超过近似 token 预算的前提下截断文本；二分查找避免逐字符重复扫描。
def truncate_to_tokens(text: str, token_budget: int) -> str:
    if token_budget <= 0:
        return ""
    if estimate_tokens(text) <= token_budget:
        return text

    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if estimate_tokens(text[:middle]) <= token_budget:
            low = middle
        else:
            high = middle - 1
    return text[:low].rstrip() + "…"


# 读取候选块记录的多路检索命中信息，兼容尚未合并的单路结果。
def _metadata_hits(chunk: RetrievedChunk) -> list[dict[str, Any]]:
    hits = chunk.metadata.get("_retrieval_hits")
    if isinstance(hits, list):
        return [hit for hit in hits if isinstance(hit, dict)]
    return [
        {
            "task_id": chunk.metadata.get("_retrieval_task_id"),
            "source": chunk.retrieval_source,
            "rank": chunk.retrieval_rank,
            "score": chunk.retrieval_score,
        }
    ]


# 为每个候选初始化检索命中列表，复制模型和 metadata 以避免修改共享状态。
def merge_candidate_lists(candidates: Iterable[RetrievedChunk]) -> list[RetrievedChunk]:
    merged: list[RetrievedChunk] = []
    for chunk in candidates:
        copied = chunk.model_copy(deep=True)
        copied.metadata = dict(copied.metadata)
        copied.metadata["_retrieval_hits"] = _metadata_hits(copied)
        merged.append(copied)
    return merged


# 合并同一候选的多路命中信息，并保留更完整内容、最佳分数和最优排名。
def _merge_chunk(existing: RetrievedChunk, incoming: RetrievedChunk) -> RetrievedChunk:
    hits = _metadata_hits(existing) + _metadata_hits(incoming)
    unique_hits: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()
    for hit in hits:
        task_id = str(hit.get("task_id") or "")
        source = str(hit.get("source") or "")
        try:
            rank = int(hit.get("rank") or 0)
        except (TypeError, ValueError):
            rank = 0
        key = (task_id, source, rank)
        if key in seen:
            continue
        seen.add(key)
        unique_hits.append(hit)

    sources = [str(hit.get("source")) for hit in unique_hits if hit.get("source")]
    ranks = [int(hit["rank"]) for hit in unique_hits if isinstance(hit.get("rank"), int)]
    scores = [
        float(hit["score"])
        for hit in unique_hits
        if isinstance(hit.get("score"), (int, float))
    ]
    metadata = dict(existing.metadata)
    metadata.update(incoming.metadata)
    metadata["_retrieval_hits"] = unique_hits
    return existing.model_copy(
        update={
            "content": existing.content if len(existing.content) >= len(incoming.content) else incoming.content,
            "metadata": metadata,
            "retrieval_source": "+".join(dict.fromkeys(sources)) or existing.retrieval_source,
            "retrieval_rank": min(ranks or [existing.retrieval_rank, incoming.retrieval_rank]),
            "retrieval_score": max(scores) if scores else existing.retrieval_score,
            "rerank_score": max(existing.rerank_score or 0.0, incoming.rerank_score or 0.0),
        }
    )


# 按稳定 chunk_id 和文档内容去重，同时保留多通道检索证据。
def deduplicate_chunks(candidates: Iterable[RetrievedChunk]) -> list[RetrievedChunk]:
    by_id: dict[str, RetrievedChunk] = {}
    content_keys: dict[tuple[str, str], str] = {}

    for chunk in candidates:
        normalized_content = re.sub(r"\s+", " ", chunk.content).strip()
        content_key = (chunk.document_id, normalized_content)
        existing_id = content_keys.get(content_key)
        chunk_id = existing_id or chunk.chunk_id

        existing = by_id.get(chunk_id)
        if existing:
            by_id[chunk_id] = _merge_chunk(existing, chunk)
        else:
            by_id[chunk_id] = chunk.model_copy(deep=True)
        content_keys[content_key] = chunk_id

    return sorted(
        by_id.values(),
        key=lambda item: (
            item.retrieval_rank,
            -(item.retrieval_score or 0.0),
            item.chunk_id,
        ),
    )


# 将一组数值缩放到 0 到 1；所有值相同时统一视为同等最高分。
def _min_max_normalize(values: list[float]) -> list[float]:
    if not values:
        return []
    minimum = min(values)
    maximum = max(values)
    if math.isclose(minimum, maximum):
        return [1.0 for _ in values]
    return [(value - minimum) / (maximum - minimum) for value in values]


# 计算查询词与候选内容的词法重合度，作为重排的辅助特征。
def _lexical_overlap(query: RagQuery, content: str) -> float:
    query_text = " ".join(
        [query.rewritten_query or query.query, *query.keywords, *query.sub_queries]
    )
    query_tokens = set(_TOKEN_RE.findall(query_text.lower()))
    content_tokens = set(_TOKEN_RE.findall(content.lower()))
    if not query_tokens:
        return 0.0
    return len(query_tokens & content_tokens) / len(query_tokens)


# 根据请求过滤条件和候选元数据计算业务匹配分。
def _metadata_score(request: RagQuery, chunk: RetrievedChunk) -> float:
    filters: RagFilters = request.filters
    score = 0.5
    if filters.document_ids and chunk.document_id in filters.document_ids:
        score += 0.2
    if filters.document_types and str(chunk.metadata.get("category") or "") in filters.document_types:
        score += 0.15
    if filters.sources and str(chunk.metadata.get("source") or "") in filters.sources:
        score += 0.15
    return min(score, 1.0)


# 融合 RRF、词法重合、原始检索分和元数据分，并生成最终排序分。
def rerank_chunks(request: RagQuery, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    if not chunks:
        return []

    rrf_scores: list[float] = []
    lexical_scores: list[float] = []
    retrieval_scores: list[float] = []
    metadata_scores: list[float] = []

    for chunk in chunks:
        rrf = sum(
            1.0 / (rag_settings.rrf_k + max(int(hit.get("rank") or 1), 1))
            for hit in _metadata_hits(chunk)
        )
        rrf_scores.append(rrf)
        lexical_scores.append(_lexical_overlap(request, chunk.content))
        retrieval_scores.append(float(chunk.retrieval_score or 0.0))
        metadata_scores.append(_metadata_score(request, chunk))

    normalized_rrf = _min_max_normalize(rrf_scores)
    normalized_retrieval = _min_max_normalize(retrieval_scores)
    normalized_metadata = _min_max_normalize(metadata_scores)

    total_weight = (
        rag_settings.rerank_weight
        + rag_settings.retrieval_weight
        + rag_settings.metadata_weight
    )
    if total_weight <= 0:
        total_weight = 1.0

    ranked: list[RetrievedChunk] = []
    for index, chunk in enumerate(chunks):
        rerank_score = min(1.0, (0.8 * normalized_rrf[index]) + (0.2 * lexical_scores[index]))
        final_score = (
            rag_settings.rerank_weight * rerank_score
            + rag_settings.retrieval_weight * normalized_retrieval[index]
            + rag_settings.metadata_weight * normalized_metadata[index]
        ) / total_weight
        ranked.append(
            chunk.model_copy(
                update={
                    "rerank_score": rerank_score,
                    "final_score": final_score,
                }
            )
        )

    return sorted(
        ranked,
        key=lambda item: (
            -(item.final_score or 0.0),
            item.retrieval_rank,
            item.chunk_id,
        ),
    )


# 合并同一文档中窗口重叠的证据，避免父块扩展后重复发送相同内容。
def merge_overlapping_evidence(evidences: list[Evidence]) -> list[Evidence]:
    by_document: dict[str, list[Evidence]] = defaultdict(list)
    for evidence in evidences:
        by_document[evidence.document_id].append(evidence)

    merged: list[Evidence] = []
    for document_id, document_evidences in by_document.items():
        groups: list[dict[str, Any]] = []
        for evidence in sorted(
            document_evidences,
            key=lambda item: min(item.metadata.get("_chunk_indices") or [10**9]),
        ):
            indices = sorted(
                {
                    int(index)
                    for index in evidence.metadata.get("_chunk_indices", [])
                    if isinstance(index, (int, float, str))
                    and str(index).isdigit()
                }
            )
            interval = (min(indices), max(indices)) if indices else None
            if groups and interval and groups[-1]["interval"] and interval[0] <= groups[-1]["interval"][1] + 1:
                groups[-1]["items"].append(evidence)
                groups[-1]["interval"] = (
                    min(groups[-1]["interval"][0], interval[0]),
                    max(groups[-1]["interval"][1], interval[1]),
                )
            else:
                groups.append({"items": [evidence], "interval": interval})

        for group in groups:
            items: list[Evidence] = group["items"]
            source_ids: list[str] = []
            for item in items:
                for chunk_id in item.source_chunk_ids:
                    if chunk_id not in source_ids:
                        source_ids.append(chunk_id)
            ordered_items = sorted(
                items,
                key=lambda item: min(item.metadata.get("_chunk_indices") or [10**9]),
            )
            content = "\n\n".join(
                item.content for item in ordered_items if item.content.strip()
            )
            interval = group["interval"]
            evidence_id = (
                f"{document_id}:{interval[0]}-{interval[1]}"
                if interval
                else f"{document_id}:{items[0].evidence_id}"
            )
            metadata = dict(ordered_items[0].metadata)
            metadata["_chunk_indices"] = (
                list(range(interval[0], interval[1] + 1)) if interval else []
            )
            merged.append(
                Evidence(
                    evidence_id=evidence_id,
                    document_id=document_id,
                    chunk_id=evidence_id,
                    content=content,
                    metadata=metadata,
                    source_chunk_ids=source_ids,
                    score=max(item.score or 0.0 for item in items),
                )
            )

    return sorted(
        merged,
        key=lambda item: (-(item.score or 0.0), item.document_id, item.chunk_id),
    )


# 按文档和来源控制证据多样性，避免 top_k 全部来自单一文档或单一路径。
def diversify_evidence(evidences: list[Evidence], limit: int) -> list[Evidence]:
    selected: list[Evidence] = []
    per_document: dict[str, int] = defaultdict(int)
    per_source: dict[str, int] = defaultdict(int)
    deferred: list[Evidence] = []

    for evidence in evidences:
        document_id = evidence.document_id
        source = str(evidence.metadata.get("source") or document_id)
        if (
            per_document[document_id] >= rag_settings.max_per_document
            or per_source[source] >= rag_settings.max_per_source
        ):
            deferred.append(evidence)
            continue
        selected.append(evidence)
        per_document[document_id] += 1
        per_source[source] += 1
        if len(selected) >= limit:
            return selected

    for evidence in deferred:
        if len(selected) >= limit:
            break
        selected.append(evidence)
    return selected


# 根据请求和配置计算上下文可用的 token 上限。
def context_token_budget(request: RagQuery) -> int:
    reserved = (
        rag_settings.system_token_reserve
        + rag_settings.history_token_reserve
        + rag_settings.output_token_reserve
        + rag_settings.safety_token_margin
        + estimate_tokens(request.rewritten_query or request.query)
    )
    return max(
        rag_settings.minimum_context_tokens,
        rag_settings.total_token_budget - reserved,
    )


# 在 token 预算内构建模型上下文和引用信息，保证引用与最终证据保持一致。
def build_context_and_citations(
    request: RagQuery,
    evidences: list[Evidence],
) -> tuple[str, list[Citation], RagDiagnostics | None]:
    token_budget = context_token_budget(request)
    sections: list[str] = []
    citations: list[Citation] = []
    used_tokens = 0

    for index, evidence in enumerate(evidences, start=1):
        metadata = evidence.metadata
        title = metadata.get("title")
        source = metadata.get("source")
        page = metadata.get("page")
        header = (
            f"[证据 {index}]\n"
            f"document_id: {evidence.document_id}\n"
            f"chunk_id: {evidence.chunk_id}\n"
            f"title: {title or ''}\n"
            f"source: {source or ''}\n"
            f"page: {page if page is not None else ''}\n"
            f"score: {evidence.score if evidence.score is not None else ''}\n"
            "content:\n"
        )
        remaining = token_budget - used_tokens
        if remaining <= 0:
            break

        fixed_tokens = estimate_tokens(header)
        content_budget = remaining - fixed_tokens
        if content_budget <= 0:
            break
        content = truncate_to_tokens(evidence.content, content_budget)
        if not content:
            break

        section = header + content
        section_tokens = estimate_tokens(section)
        if used_tokens + section_tokens > token_budget and sections:
            break
        sections.append(section)
        used_tokens += section_tokens

        if request.require_citations:
            try:
                page_number = int(page) if page is not None else None
            except (TypeError, ValueError):
                page_number = None
            citations.append(
                Citation(
                    document_id=evidence.document_id,
                    chunk_id=evidence.chunk_id,
                    title=str(title) if title else None,
                    source=str(source) if source else None,
                    page=page_number,
                    score=evidence.score,
                )
            )

    diagnostics = RagDiagnostics(
        requested_mode=request.mode,
        stage_counts={
            "context_evidence": len(sections),
            "context_tokens": used_tokens,
            "context_budget": token_budget,
        },
    )
    return "\n\n".join(sections), citations, diagnostics
