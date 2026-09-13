from typing import Literal
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from loguru import logger
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.errors import GraphRecursionError

from backend.config.llm_config import tool_model
from backend.config.mysql_config import CHECKPOINTER_DATABASE_URL
from backend.config.prompt_template import OVER_ALL_PROMPT
from backend.services.tools import PARENT_TOOLS
from backend.services.tool_gateway import GATEWAY


# 主 Agent 图的状态定义与执行节点集中在本模块。
# 其中 ParentState 保存完整对话，input_state/output_state 约束图的输入输出，
# private_state 供图内部传递临时状态；这些状态会被 StateGraph 组合使用。
class ParentState(MessagesState):
    input : str
    output:str


class input_state(MessagesState):
    input:str


class output_state(MessagesState):
    output:str



class private_state(MessagesState):
    pass


# LLM 节点负责将系统提示词、历史消息和当前用户消息交给模型。
# 调用模型前会清理没有对应 ToolMessage 的悬空 tool_calls，避免历史状态触发
# OpenAI 兼容接口的参数校验错误；模型返回后保留 AIMessage 供路由节点判断。
async def llm_node(parent_state: ParentState)->ParentState:
    history_msg = list(parent_state['messages'])

    if not history_msg or not isinstance(history_msg[0], SystemMessage):
        history_msg = [SystemMessage(OVER_ALL_PROMPT)] + history_msg

    cleaned = []
    pending_tool_ids = set()
    pending_ai_idx = None
    for msg in history_msg:
        if hasattr(msg, 'tool_calls') and msg.tool_calls:
            pending_tool_ids = {tc['id'] for tc in msg.tool_calls}
            pending_ai_idx = len(cleaned)
            cleaned.append(msg)
        elif hasattr(msg, 'tool_call_id') and msg.tool_call_id:
            if msg.tool_call_id in pending_tool_ids:
                pending_tool_ids.discard(msg.tool_call_id)
                cleaned.append(msg)
            else:
                pass
        else:
            if pending_tool_ids:
                pending_tool_ids.clear()
                pending_ai_idx = None
            cleaned.append(msg)

    if pending_tool_ids and pending_ai_idx is not None:
        from langchain_core.messages import AIMessage
        orphan = cleaned[pending_ai_idx]
        valid_tool_calls = [tc for tc in orphan.tool_calls if tc['id'] not in pending_tool_ids]
        cleaned[pending_ai_idx] = AIMessage(
            content=orphan.content or "",
            tool_calls=valid_tool_calls,
            additional_kwargs=orphan.additional_kwargs,
            response_metadata=orphan.response_metadata,
        )

    llm_output=await tool_model.ainvoke(cleaned)

    if hasattr(llm_output, 'tool_calls') and llm_output.tool_calls:
        logger.info(f"[llm_node] 模型决定调用工具: {[tc['name'] for tc in llm_output.tool_calls]}")
    else:
        logger.info("[llm_node] 模型未调用工具，直接作答")

    return {
        "messages":[llm_output],
    }

# 路由节点根据 LLM 的最后一条消息决定图下一步：存在 tool_calls 时进入工具节点，
# 否则将模型文本写入 output 并结束本轮执行。该节点只负责分支，不执行工具本身。
async def router(parent_state:ParentState)->Command[Literal["tool_node","__end__"]]:
    last_msg = parent_state['messages'][-1]
    if hasattr(last_msg, 'tool_calls') and last_msg.tool_calls:
        return Command(goto="tool_node")
    return Command(goto="__end__", update={
        "output": parent_state['messages'][-1].content
    })


# 构建主 Agent 图：LLM 节点先生成回复，路由节点决定是否调用工具，
# 工具执行完成后再次回到 LLM 节点，直到模型不再产生 tool_calls。
builder = StateGraph(state_schema=ParentState,input_state_schema=input_state,output_state_schema=output_state,private_state_schema=private_state)

builder.add_node("llm_node", llm_node,timeout=300)
builder.add_node("router", router)


# 工具节点包装器保留 LangGraph 官方 ToolNode 的调用和消息配对逻辑，
# 同时把实际工具调用交给统一 Gateway，并记录调用与返回内容便于排查问题。
class LoggingToolNode:
    def __init__(self, tools):
        self._tool_node = ToolNode(tools=tools, awrap_tool_call=GATEWAY.awrap_tool_call)


    # 执行当前批次的工具调用，并记录每个 ToolMessage 的简要结果。
    async def __call__(self, state, config=None):
        last_msg = state['messages'][-1]
        calls = getattr(last_msg, 'tool_calls', None)
        logger.info(f"[tool_node] 进入工具节点，待执行: {[tc['name'] for tc in calls] if calls else '无'}")
        result = await self._tool_node.ainvoke(state, config)
        for m in result.get('messages', []):
            if getattr(m, 'type', '') == 'tool':
                content = m.content
                logger.info(f"[tool_node] 工具返回: {m.name} -> {str(content)[:500]}")
        return result

builder.add_node("tool_node", LoggingToolNode(PARENT_TOOLS), timeout=120)


builder.add_edge(START, "llm_node")
builder.add_edge("llm_node", "router",)
builder.add_edge("tool_node","llm_node")

# 异步入口负责初始化 PostgreSQL checkpoint、编译图并以消息和状态更新两种模式
# 流式返回执行事件；递归超限时记录异常，避免工具循环问题难以定位。
async def ai_response(user_question:str,config:RunnableConfig):
    async with AsyncPostgresSaver.from_conn_string(CHECKPOINTER_DATABASE_URL) as saver:
        await saver.setup()
        graph = builder.compile(checkpointer=saver)

        try:
            async for event, data in graph.astream(
                {"input": user_question, "messages": [HumanMessage(content=user_question)]},
                config=config,
                stream_mode=["messages", "updates"],
            ):
                yield event, data
        except GraphRecursionError as e:
            logger.info(f"Graph recursion error: {e}")