from __future__ import annotations

from typing import Any

from backend.agent.rag_graph import run_rag
from backend.schemas.rag import RagQuery, RagResult


async def search_knowledge_base(
    *,
    request: RagQuery,
    user_id: int,
    config: Any | None = None,
) -> RagResult:
    """RAG 检索的业务服务层入口，供 REST 接口或工具层复用。

    这里保持原有执行逻辑不变，仅将 HTTP 层和业务层拆开。
    """
    return await run_rag(request, user_id=user_id, config=config)
