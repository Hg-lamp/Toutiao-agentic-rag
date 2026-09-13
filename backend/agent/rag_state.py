from operator import add
from typing import Annotated, Required, TypedDict

from backend.schemas.rag import (
    Citation,
    Evidence,
    RagDiagnostics,
    RagQuery,
    RagResult,
    RetrievalPlan,
    RetrievedChunk,
)


# RAG 图的内部状态定义。并行检索节点通过累加 reducer 合并 candidates
# 和 warnings，其余字段按阶段依次写入，避免并发节点互相覆盖结果。
class RagState(TypedDict, total=False):
    request: Required[RagQuery]
    user_id: int | None

    plan: RetrievalPlan
    candidates: Annotated[list[RetrievedChunk], add]
    merged: list[RetrievedChunk]
    deduplicated: list[RetrievedChunk]
    reranked: list[RetrievedChunk]
    expanded: list[Evidence]

    context: str
    citations: list[Citation]

    warnings: Annotated[list[str], add]
    diagnostics: RagDiagnostics
    result: RagResult
