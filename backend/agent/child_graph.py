import json
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import Command

from backend.config.graph_config import retry_policy
from backend.services.tools import CHILD_TOOLS
from backend.schemas.agent_response import AgentResult


CHILD_AGENT_PROMPT = """你是一个专职子 Agent，只负责完成父 Agent 分配的任务。
你可以调用已提供的工具，但最终必须只输出合法 JSON，不要输出 Markdown 或额外解释。
JSON 格式必须是：
{
  "status": "success",
  "task": "任务名称",
  "summary": "给父 Agent 的简短结论",
  "sources": [],
  "data": {},
  "error": null
}
status 只能是 success、partial、failed。信息不完整时使用 partial，无法完成时使用 failed。
不要编造数据；失败时在 error 中说明原因。"""


class ChildState(MessagesState):
    input:str
    output:str

class InputState(MessagesState):
    input:str

class OutputState(MessagesState):
    output:str

async def llm_node(child_state: ChildState)->ChildState:
    from backend.config.llm_config import child_model
    history_chat = list(child_state["messages"])
    if not history_chat or not isinstance(history_chat[0], SystemMessage):
        history_chat.insert(0, SystemMessage(content=CHILD_AGENT_PROMPT))
    res =await child_model.ainvoke(history_chat)
    return {
        "messages":[res]
    }

async def router(state:ChildState)->Command[Literal["__end__","tool_node"]]:
    last_message = state["messages"][-1]
    if getattr(last_message, "tool_calls", None):
        return Command(goto="tool_node")
    raw_output = last_message.content
    if isinstance(raw_output, list):
        raw_output = "".join(
            item.get("text", "") if isinstance(item, dict) else str(item)
            for item in raw_output
        )
    try:
        result = AgentResult.model_validate_json(raw_output)
    except Exception as exc:
        result = AgentResult(
            status="failed",
            task=state["input"],
            summary="子 Agent 返回格式不符合要求",
            error=str(exc),
            data={"raw_output": raw_output},
        )

    return Command(goto="__end__",
            update={
                "output": json.dumps(result.model_dump(), ensure_ascii=False)
            })


builder= StateGraph(state_schema=ChildState,input_schema=InputState,output_schema=OutputState)

builder.add_node('llm_node',llm_node,timeout=60,retry_policy=retry_policy)
builder.add_node('tool_node',ToolNode(tools=CHILD_TOOLS),timeout=60,retry_policy=retry_policy)
builder.add_node("router",router)

builder.add_edge(START,"llm_node")
builder.add_edge("llm_node","router")
builder.add_edge("tool_node","llm_node")

child_graph=builder.compile()

async def child_output(task: str, config=None):
    res =await child_graph.ainvoke({"input":task,"messages":[HumanMessage(content=task)]},config={
        **(config or {}),
        "callbacks": None,
    })
    return res["output"]
