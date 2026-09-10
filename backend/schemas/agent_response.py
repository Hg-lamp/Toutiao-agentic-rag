from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentResult(BaseModel):
    """父 Agent 与子 Agent 之间传递的统一结果。"""

    status: Literal["success", "partial", "failed"]
    task: str
    summary: str = ""
    sources: list[dict[str, Any]] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
