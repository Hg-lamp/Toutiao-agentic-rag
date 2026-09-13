from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


RagMode = Literal["auto", "simple", "hybrid", "complex"]
EffectiveRagMode = Literal["simple", "hybrid", "complex"]
RagStatus = Literal["success", "partial", "no_result", "failed"]
RetrievalChannel = Literal["vector", "bm25"]


class RagFilters(BaseModel):
    """RAG 查询过滤条件。模型只能传业务过滤字段，不能传权限字段。"""

    document_ids: list[str] = Field(default_factory=list)
    document_types: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    time_from: str | None = None
    time_to: str | None = None

    model_config = ConfigDict(extra="forbid")


class RagQuery(BaseModel):
    """外层模型提交给 rag_search 的结构化查询。"""

    query: str = Field(..., min_length=1, max_length=500)
    rewritten_query: str | None = Field(default=None, min_length=1, max_length=500)
    keywords: list[str] = Field(default_factory=list)
    sub_queries: list[str] = Field(default_factory=list)

    mode: RagMode = "auto"

    top_k: int = Field(default=8, ge=1, le=20)
    candidate_k: int = Field(default=30, ge=10, le=100)

    filters: RagFilters = Field(default_factory=RagFilters)

    require_citations: bool = True
    include_diagnostics: bool = False

    model_config = ConfigDict(extra="forbid")


class RetrievedChunk(BaseModel):
    """所有检索通道统一返回的候选块。"""

    chunk_id: str
    document_id: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    retrieval_source: str
    retrieval_rank: int
    retrieval_score: float | None = None

    rerank_score: float | None = None
    final_score: float | None = None


class RetrievalTask(BaseModel):
    """Planner 生成的单个确定性检索任务。"""

    task_id: str
    query: str
    query_kind: Literal["main", "sub_query"]
    channel: RetrievalChannel


class RetrievalPlan(BaseModel):
    """确定性 Planner 输出的检索计划。"""

    mode: EffectiveRagMode
    normalized_query: str
    tasks: list[RetrievalTask] = Field(default_factory=list)
    top_k: int
    candidate_k: int
    filters: RagFilters = Field(default_factory=RagFilters)
    reason: str | None = None


class Evidence(BaseModel):
    """父块扩展后，供上下文构建使用的证据块。"""

    evidence_id: str
    document_id: str
    chunk_id: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    source_chunk_ids: list[str] = Field(default_factory=list)
    score: float | None = None


class Citation(BaseModel):
    """返回给外层模型的引用信息。"""

    document_id: str
    chunk_id: str
    title: str | None = None
    source: str | None = None
    page: int | None = None
    score: float | None = None


class RagDiagnostics(BaseModel):
    """只在 include_diagnostics=True 时对外返回的诊断信息。"""

    requested_mode: RagMode
    effective_mode: EffectiveRagMode | None = None
    planned_channels: list[RetrievalChannel] = Field(default_factory=list)
    planned_task_count: int = 0
    stage_counts: dict[str, int] = Field(default_factory=dict)
    timings_ms: dict[str, float] = Field(default_factory=dict)


class RagResult(BaseModel):
    """rag_search 对外返回的统一结果。"""

    status: RagStatus
    query: str
    context: str
    citations: list[Citation] = Field(default_factory=list)

    warnings: list[str] = Field(default_factory=list)
    diagnostics: dict[str, Any] | None = None

