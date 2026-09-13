import re

from backend.schemas.rag import RagQuery, RetrievalPlan, RetrievalTask


# RAG 规划模块只根据结构化请求生成确定性的检索任务，不调用 LLM。
# 规划结果决定主查询、子查询以及向量/BM25 通道是否参与后续并行检索。
_EXPLICIT_TERM_RE = re.compile(
    r"(`[^`]+`|\"[^\"]+\"|'[^']+'|[A-Za-z_][A-Za-z0-9_.-]{1,}|\d+(?:\.\d+)?)"
)


# 判断原始查询中是否包含适合关键词检索的显式术语。
def _contains_explicit_terms(text: str) -> bool:
    return bool(_EXPLICIT_TERM_RE.search(text))


# 清理空白项并保持用户输入顺序，同时移除重复的查询词或子查询。
def _deduplicate_non_empty(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


# 根据请求模式生成 RetrievalPlan，并返回不会阻止流程继续执行的提示信息。
# complex 模式没有子查询时会回退为 hybrid；时间过滤字段目前只做兼容提示。
def create_retrieval_plan(request: RagQuery) -> tuple[RetrievalPlan, list[str]]:
    warnings: list[str] = []
    normalized_query = (request.rewritten_query or request.query).strip()
    sub_queries = _deduplicate_non_empty(request.sub_queries)
    keywords = _deduplicate_non_empty(request.keywords)

    if request.mode == "auto":
        effective_mode = "complex" if sub_queries else "hybrid"
        reason = "auto: 有子查询时使用 complex，否则使用主查询 hybrid"
    else:
        effective_mode = request.mode
        reason = f"显式指定 {effective_mode} 模式"

    if effective_mode == "complex" and not sub_queries:
        effective_mode = "hybrid"
        warnings.append("请求了 complex 模式但没有 sub_queries，已回退为 hybrid")

    tasks: list[RetrievalTask] = []
    main_query = normalized_query

    if effective_mode == "simple":
        tasks.append(
            RetrievalTask(
                task_id="main:vector",
                query=main_query,
                query_kind="main",
                channel="vector",
            )
        )
    elif effective_mode == "hybrid":
        tasks.append(
            RetrievalTask(
                task_id="main:vector",
                query=main_query,
                query_kind="main",
                channel="vector",
            )
        )
        tasks.append(
            RetrievalTask(
                task_id="main:bm25",
                query=" ".join(keywords) if keywords else main_query,
                query_kind="main",
                channel="bm25",
            )
        )
    else:
        tasks.append(
            RetrievalTask(
                task_id="main:vector",
                query=main_query,
                query_kind="main",
                channel="vector",
            )
        )

        keyword_query = " ".join(keywords)
        should_search_keywords = bool(keywords) or _contains_explicit_terms(request.query)
        if should_search_keywords:
            tasks.append(
                RetrievalTask(
                    task_id="main:bm25",
                    query=keyword_query or main_query,
                    query_kind="main",
                    channel="bm25",
                )
            )

        for index, sub_query in enumerate(sub_queries):
            tasks.append(
                RetrievalTask(
                    task_id=f"sub:{index}:vector",
                    query=sub_query,
                    query_kind="sub_query",
                    channel="vector",
                )
            )
            if should_search_keywords:
                tasks.append(
                    RetrievalTask(
                        task_id=f"sub:{index}:bm25",
                        query=f"{sub_query} {keyword_query}".strip(),
                        query_kind="sub_query",
                        channel="bm25",
                    )
                )

    if request.filters.time_from or request.filters.time_to:
        warnings.append("当前索引未声明时间字段，time_from/time_to 暂未生效")

    return (
        RetrievalPlan(
            mode=effective_mode,
            normalized_query=normalized_query,
            tasks=tasks,
            top_k=request.top_k,
            candidate_k=request.candidate_k,
            filters=request.filters,
            reason=reason,
        ),
        warnings,
    )
