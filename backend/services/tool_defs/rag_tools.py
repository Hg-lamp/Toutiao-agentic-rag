import json

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from backend.agent.rag_graph import run_rag
from backend.crud.memory import get_user_memory, save_user_memory
from backend.schemas.agent_response import AgentResult
from backend.schemas.rag import RagQuery, RagResult
from backend.services.tool_gateway import TOOL_REGISTRY, ToolSpec


@tool
async def rag_search(request: RagQuery, config: RunnableConfig) -> str:
    """检索当前用户的知识库，并返回结构化 RagResult."""
    user_id = (config or {}).get("configurable", {}).get("user_id")
    if user_id is None:
        return RagResult(
            status="failed",
            query=request.query,
            context="",
            warnings=["缺少当前用户信息，无法执行知识库检索"],
        ).model_dump_json()

    try:
        result = await run_rag(
            request=request,
            user_id=int(user_id),
            config=config,
        )
    except Exception as exc:
        result = RagResult(
            status="failed",
            query=request.query,
            context="",
            warnings=[f"知识库检索失败: {exc}"],
        )
    return result.model_dump_json()


@tool
async def agent(task: str, config: RunnableConfig) -> str:
    """
    任务下发工具（一个任务对应一个agent）
    一般在长难任务时候调用，用于下发单个任务给子agent。
    """
    from backend.agent.child_graph import child_output

    try:
        result = await child_output(task, config=config)
        return result
    except Exception as exc:
        return json.dumps(
            AgentResult(
                status="failed",
                task=task,
                summary="子 Agent 执行失败",
                error=str(exc),
            ).model_dump(),
            ensure_ascii=False,
        )


@tool
async def get_memory(
    config: RunnableConfig,
    memory_key: str = "",
) -> list[dict]:
    """读取当前用户保存的长期记忆。"""
    user_id = (config or {}).get("configurable", {}).get("user_id")
    if not user_id:
        raise ValueError("缺少当前用户信息")
    return await get_user_memory(user_id, memory_key or None)


@tool
async def save_memory(
    config: RunnableConfig,
    memory_key: str,
    memory_value: str,
    memory_type: str = "fact",
) -> dict:
    """保存当前用户的长期记忆。"""
    user_id = (config or {}).get("configurable", {}).get("user_id")
    if not user_id:
        raise ValueError("缺少当前用户信息")
    return await save_user_memory(
        user_id=user_id,
        memory_key=memory_key,
        memory_value=memory_value,
        memory_type=memory_type,
    )


TOOL_SPECS = [
    (agent, ToolSpec(
        name="agent", description="Delegate one bounded research task to a child agent.",
        risk_level="R3", side_effect=False, idempotent=True, required_scopes=("agent.delegate",),
    )),
    (rag_search, ToolSpec(
        name="rag_search", description="Search the current user's isolated knowledge base.",
        risk_level="R1", idempotent=True,
    )),
    (get_memory, ToolSpec(
        name="get_memory", description="Read durable memory belonging to the current authenticated user.",
        risk_level="R1", idempotent=True,
    )),
    (save_memory, ToolSpec(
        name="save_memory", description="Persist an explicit, non-sensitive user preference or fact.",
        risk_level="R3", side_effect=True, idempotent=True,
        required_scopes=("memory.write",),
    )),
]

for _tool, _spec in TOOL_SPECS:
    TOOL_REGISTRY.register(_tool, _spec)

PARENT_TOOLS = [agent, rag_search, get_memory, save_memory]
CHILD_TOOLS = [rag_search]
