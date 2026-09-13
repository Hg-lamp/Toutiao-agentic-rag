import asyncio
from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from backend.agent.rag_planner import create_retrieval_plan
from backend.agent.rag_processing import (
    build_context_and_citations,
    deduplicate_chunks,
    diversify_evidence,
    merge_candidate_lists,
    merge_overlapping_evidence,
    rerank_chunks,
)
from backend.agent.rag_retrieval import (
    bm25_search,
    fetch_parent_window,
    vector_search,
)
from backend.agent.rag_state import RagState
from backend.config.rag_config import rag_settings
from backend.schemas.rag import (
    Evidence,
    RagDiagnostics,
    RagQuery,
    RagResult,
    RetrievalChannel,
    RetrievedChunk,
)


# RAG 图编排模块按“校验、规划、并行检索、融合、扩展、上下文、结果”组织流水线。
# 并行节点只追加 candidates 和 warnings，后续阶段再按固定顺序处理聚合结果。
RagNode = Callable[[RagState], Awaitable[dict[str, Any]]]
CHANNEL_ERROR_PREFIX = "检索通道异常"


# 从候选元数据中读取块序号，兼容新旧索引使用的字段名。
def _metadata_index(chunk: RetrievedChunk) -> int | None:
    value = chunk.metadata.get("chunk_index", chunk.metadata.get("num"))
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# 合并各阶段诊断数据；计数和耗时按字段更新，不影响已经产生的其他诊断信息。
def _merge_diagnostics(
    diagnostics: RagDiagnostics | None,
    *,
    stage_counts: dict[str, int] | None = None,
    timings_ms: dict[str, float] | None = None,
    **updates: Any,
) -> RagDiagnostics:
    current = diagnostics or RagDiagnostics(requested_mode="auto")
    merged_stage_counts = dict(current.stage_counts)
    merged_timings = dict(current.timings_ms)
    if stage_counts:
        merged_stage_counts.update(stage_counts)
    if timings_ms:
        merged_timings.update(timings_ms)
    return current.model_copy(
        update={
            **updates,
            "stage_counts": merged_stage_counts,
            "timings_ms": merged_timings,
        }
    )


# 图的第一步负责清理用户输入并创建初始诊断状态
async def validate_query(state: RagState) -> dict[str, Any]:
    request = state["request"]
    query = request.query.strip()
    if not query:
        raise ValueError("查询内容不能为空")
#更新重写搜索
    rewritten_query = request.rewritten_query.strip() if request.rewritten_query else None
#构建正式请求
    normalized_request = request.model_copy(
        update={
            "query": query,
            "rewritten_query": rewritten_query,
            "keywords": [keyword.strip() for keyword in request.keywords if keyword.strip()],
            "sub_queries": [item.strip() for item in request.sub_queries if item.strip()],
        }
    )
    diagnostics = RagDiagnostics(requested_mode=normalized_request.mode)
    return {
        "request": normalized_request,
        "warnings": [],
        "diagnostics": diagnostics,
    }


# 根据规范化请求生成确定性的检索任务，并记录有效模式、通道和任务数量。
async def build_retrieval_plan(state: RagState) -> dict[str, Any]:
    started = perf_counter()
    plan, warnings = create_retrieval_plan(state["request"])
    channels = list(dict.fromkeys(task.channel for task in plan.tasks))
    diagnostics = _merge_diagnostics(
        state.get("diagnostics"),
        effective_mode=plan.mode,
        planned_channels=channels,
        planned_task_count=len(plan.tasks),
        stage_counts={"planned_tasks": len(plan.tasks)},
        timings_ms={"plan": (perf_counter() - started) * 1000},
    )
    return {
        "plan": plan,
        "warnings": warnings,
        "diagnostics": diagnostics,
    }


# 执行指定通道和查询类型的任务。每个任务受并发上限约束，单任务异常会转为 warning，
# 这样一个检索通道失败时其他通道仍可以继续提供部分结果。
async def _run_channel_tasks(state: RagState,*,channel: RetrievalChannel,query_kind: str) -> dict[str, Any]:
    plan = state["plan"]
    user_id = state.get("user_id")
    if user_id is None:
        return {
            "candidates": [],
            "warnings": [f"{CHANNEL_ERROR_PREFIX}: 缺少 user_id，拒绝执行 {channel} 检索"],
        }

    tasks = [
        task
        for task in plan.tasks
        if task.channel == channel and task.query_kind == query_kind
    ]
    if not tasks:
        return {"candidates": []}

    semaphore = asyncio.Semaphore(rag_settings.retrieval_concurrency)

    async def run_one(task):
        async with semaphore:
            if channel == "vector":
                return await vector_search(
                    task,
                    user_id=user_id,
                    filters=plan.filters,
                    limit=plan.candidate_k,
                )
            if channel == "bm25":
                return await bm25_search(
                    task,
                    user_id=user_id,
                    filters=plan.filters,
                    limit=plan.candidate_k,
                )
            raise ValueError(f"Unsupported retrieval channel: {channel}")

    results = await asyncio.gather(
        *(run_one(task) for task in tasks),
        return_exceptions=True,
    )
    candidates: list[RetrievedChunk] = []
    warnings: list[str] = []
    for task, result in zip(tasks, results):
        if isinstance(result, BaseException):
            warnings.append(
                f"{CHANNEL_ERROR_PREFIX}: {task.task_id} 执行失败: {result}"
            )
            continue
        candidates.extend(result)

    return {"candidates": candidates, "warnings": warnings}


# 主查询的向量检索节点；没有匹配任务时安全返回空候选。
async def retrieve_vector(state: RagState) -> dict[str, Any]:
    return await _run_channel_tasks(state, channel="vector", query_kind="main")


# 主查询的 BM25 检索节点；实际执行由统一通道调度器完成。
async def retrieve_bm25(state: RagState) -> dict[str, Any]:
    return await _run_channel_tasks(state, channel="bm25", query_kind="main")


# 子查询的向量检索节点，用于 complex 模式拆分后的语义检索。
async def retrieve_subquery_vector(state: RagState) -> dict[str, Any]:
    return await _run_channel_tasks(state, channel="vector", query_kind="sub_query")


# 子查询的 BM25 检索节点，用于补充关键词和显式术语匹配。
async def retrieve_subquery_bm25(state: RagState) -> dict[str, Any]:
    return await _run_channel_tasks(state, channel="bm25", query_kind="sub_query")


# 汇总四个并行检索节点产生的候选，并保留每个候选的多路命中信息。
async def merge_candidates(state: RagState) -> dict[str, Any]:
    started = perf_counter()
    candidates = merge_candidate_lists(state.get("candidates", []))
    diagnostics = _merge_diagnostics(
        state.get("diagnostics"),
        stage_counts={"candidates": len(candidates)},
        timings_ms={"merge": (perf_counter() - started) * 1000},
    )
    return {
        "merged": candidates,
        "diagnostics": diagnostics,
    }


# 对候选按稳定 ID 和内容去重，减少同一块内容在后续重排中的重复权重。
async def deduplicate(state: RagState) -> dict[str, Any]:
    started = perf_counter()
    chunks = deduplicate_chunks(state.get("merged", []))
    diagnostics = _merge_diagnostics(
        state.get("diagnostics"),
        stage_counts={"deduplicated": len(chunks)},
        timings_ms={"deduplicate": (perf_counter() - started) * 1000},
    )
    return {
        "deduplicated": chunks,
        "diagnostics": diagnostics,
    }


# 使用 RRF、词法、检索和元数据分数重排候选，并截取 top_k。
async def rerank(state: RagState) -> dict[str, Any]:
    started = perf_counter()
    request = state["request"]
    chunks = rerank_chunks(request, state.get("deduplicated", []))[: request.top_k]
    diagnostics = _merge_diagnostics(
        state.get("diagnostics"),
        stage_counts={"reranked": len(chunks)},
        timings_ms={"rerank": (perf_counter() - started) * 1000},
    )
    return {
        "reranked": chunks,
        "diagnostics": diagnostics,
    }


# 为重排后的 child chunk 获取父块窗口；无法获取时保留原块并记录 warning。
async def expand_parent(state: RagState) -> dict[str, Any]:
    started = perf_counter()
    user_id = state.get("user_id")
    if user_id is None:
        return {"expanded": [], "warnings": []}

    semaphore = asyncio.Semaphore(rag_settings.parent_expansion_concurrency)

    async def expand_one(chunk: RetrievedChunk) -> tuple[Evidence, list[str]]:
        center_index = _metadata_index(chunk)
        if center_index is None or rag_settings.parent_window <= 0:
            return (
                Evidence(
                    evidence_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    chunk_id=chunk.chunk_id,
                    content=chunk.content,
                    metadata=dict(chunk.metadata),
                    source_chunk_ids=[chunk.chunk_id],
                    score=chunk.final_score,
                ),
                [],
            )

        warnings: list[str] = []
        async with semaphore:
            try:
                window_chunks = await fetch_parent_window(
                    user_id=user_id,
                    document_id=chunk.document_id,
                    center_index=center_index,
                    window=rag_settings.parent_window,
                )
            except Exception as exc:
                warnings.append(
                    f"父块扩展失败 [{chunk.document_id}:{center_index}]: {exc}"
                )
                window_chunks = []

        if not window_chunks:
            window_chunks = [chunk]
        window_chunks = sorted(
            window_chunks,
            key=lambda item: (
                _metadata_index(item)
                if _metadata_index(item) is not None
                else center_index
            ),
        )
        indices = sorted(
            index
            for index in (_metadata_index(item) for item in window_chunks)
            if index is not None
        )
        metadata = dict(chunk.metadata)
        if indices:
            metadata["_chunk_indices"] = indices
        evidence = Evidence(
            evidence_id=chunk.chunk_id,
            document_id=chunk.document_id,
            chunk_id=chunk.chunk_id,
            content="\n\n".join(
                item.content for item in window_chunks if item.content.strip()
            ),
            metadata=metadata,
            source_chunk_ids=[item.chunk_id for item in window_chunks],
            score=chunk.final_score,
        )
        return evidence, warnings

    results = await asyncio.gather(
        *(expand_one(chunk) for chunk in state.get("reranked", [])),
        return_exceptions=True,
    )
    expanded: list[Evidence] = []
    warnings: list[str] = []
    for result in results:
        if isinstance(result, BaseException):
            warnings.append(f"父块扩展任务异常: {result}")
            continue
        evidence, result_warnings = result
        expanded.append(evidence)
        warnings.extend(result_warnings)

    diagnostics = _merge_diagnostics(
        state.get("diagnostics"),
        stage_counts={"expanded": len(expanded)},
        timings_ms={"expand_parent": (perf_counter() - started) * 1000},
    )
    return {
        "expanded": expanded,
        "warnings": warnings,
        "diagnostics": diagnostics,
    }


# 合并父块扩展后相互重叠的证据，避免上下文重复。
async def post_process(state: RagState) -> dict[str, Any]:
    started = perf_counter()
    evidences = merge_overlapping_evidence(state.get("expanded", []))
    diagnostics = _merge_diagnostics(
        state.get("diagnostics"),
        stage_counts={"post_processed": len(evidences)},
        timings_ms={"post_process": (perf_counter() - started) * 1000},
    )
    return {
        "expanded": evidences,
        "diagnostics": diagnostics,
    }


# 按文档和来源控制证据多样性，避免结果被单一来源占满。
async def diversify(state: RagState) -> dict[str, Any]:
    started = perf_counter()
    request = state["request"]
    evidences = diversify_evidence(state.get("expanded", []), request.top_k)
    diagnostics = _merge_diagnostics(
        state.get("diagnostics"),
        stage_counts={"diversified": len(evidences)},
        timings_ms={"diversify": (perf_counter() - started) * 1000},
    )
    return {
        "expanded": evidences,
        "diagnostics": diagnostics,
    }


# 在上下文 token 预算内生成模型上下文和引用。
async def build_context(state: RagState) -> dict[str, Any]:
    started = perf_counter()
    request = state["request"]
    context, citations, context_diagnostics = build_context_and_citations(
        request,
        state.get("expanded", []),
    )
    diagnostics = _merge_diagnostics(
        state.get("diagnostics"),
        stage_counts=context_diagnostics.stage_counts,
        timings_ms={"build_context": (perf_counter() - started) * 1000},
    )
    return {
        "context": context,
        "citations": citations,
        "diagnostics": diagnostics,
    }


# 将最终上下文、引用、警告和诊断封装成对外统一的 RagResult。
async def build_result(state: RagState) -> dict[str, Any]:
    request = state["request"]
    context = state.get("context", "")
    warnings = list(dict.fromkeys(state.get("warnings", [])))
    has_channel_error = any(
        warning.startswith(CHANNEL_ERROR_PREFIX) for warning in warnings
    )

    if context and warnings:
        status = "partial"
    elif context:
        status = "success"
    elif has_channel_error:
        status = "failed"
    else:
        status = "no_result"

    diagnostics = state.get("diagnostics")
    result = RagResult(
        status=status,
        query=request.query,
        context=context,
        citations=state.get("citations", []) if request.require_citations else [],
        warnings=warnings,
        diagnostics=(
            diagnostics.model_dump(exclude_none=True)
            if request.include_diagnostics and diagnostics is not None
            else None
        ),
    )
    return {"result": result}


# 构建并编译 RAG 子图；四个检索节点从计划节点并行出发，再汇聚到同一处理链。
def build_rag_graph():
    builder = StateGraph(RagState)

    builder.add_node("validate_query", validate_query)
    builder.add_node("build_retrieval_plan", build_retrieval_plan)
    builder.add_node("retrieve_vector", retrieve_vector)
    builder.add_node("retrieve_bm25", retrieve_bm25)
    builder.add_node("retrieve_subquery_vector", retrieve_subquery_vector)
    builder.add_node("retrieve_subquery_bm25", retrieve_subquery_bm25)
    builder.add_node("merge_candidates", merge_candidates)
    builder.add_node("deduplicate", deduplicate)
    builder.add_node("rerank", rerank)
    builder.add_node("expand_parent", expand_parent)
    builder.add_node("post_process", post_process)
    builder.add_node("diversify", diversify)
    builder.add_node("build_context", build_context)
    builder.add_node("build_result", build_result)

    builder.add_edge(START, "validate_query")
    builder.add_edge("validate_query", "build_retrieval_plan")

    parallel_retrieval_nodes = (
        "retrieve_vector",
        "retrieve_bm25",
        "retrieve_subquery_vector",
        "retrieve_subquery_bm25",
    )
    for node_name in parallel_retrieval_nodes:
        builder.add_edge("build_retrieval_plan", node_name)
        builder.add_edge(node_name, "merge_candidates")

    builder.add_edge("merge_candidates", "deduplicate")
    builder.add_edge("deduplicate", "rerank")
    builder.add_edge("rerank", "expand_parent")
    builder.add_edge("expand_parent", "post_process")
    builder.add_edge("post_process", "diversify")
    builder.add_edge("diversify", "build_context")
    builder.add_edge("build_context", "build_result")
    builder.add_edge("build_result", END)

    return builder.compile()


rag_graph = build_rag_graph()


# 对外执行入口只返回 RagResult；user_id 缺失时在进入图前直接拒绝检索。
async def run_rag(
    request: RagQuery,
    *,
    user_id: int | None,
    config: RunnableConfig | None = None,
) -> RagResult:
    if user_id is None:
        return RagResult(
            status="failed",
            query=request.query,
            context="",
            warnings=["缺少当前用户信息，无法执行知识库检索"],
        )

    final_state = await rag_graph.ainvoke(
        {
            "request": request,
            "user_id": user_id,
        },
        config=config,
    )
    result = final_state.get("result")
    if result is None:
        raise RuntimeError("RAG 子图未生成 RagResult")
    return result
