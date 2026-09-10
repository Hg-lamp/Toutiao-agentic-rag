import json
import uuid
import asyncio

from fastapi import HTTPException
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.functions import count
from loguru import logger

from backend.agent.agent_graph import ai_response
from backend.config.mysql_config import AsyncSessionLocal, CHECKPOINTER_DATABASE_URL
from backend.models.conversations import Conversation
from backend.models.messages import Message


async def check_thread_id(thread_id:str|None,user_id:int,db:AsyncSession,question:str):
    #传空意味着这是新会话
    if thread_id is None:
        #直接生成一个
        new_id = str(uuid.uuid4())
        #更新conversation表
        db.add(Conversation(conversation_id=new_id,user_id=user_id,title=question[0:50],is_expired=0,message_count=0))
        await db.commit()
        return new_id
    #否则判断会话列表是否存在id
    stmt = select(Conversation).where(Conversation.user_id == user_id,Conversation.conversation_id == thread_id)
    res = await db.execute(stmt)
    res = res.scalar_one_or_none()
    if res is None:
        raise HTTPException(status_code=404, detail="Conversation not exists")
    return thread_id

async def add_message(thread_id:str,content:str,role:str,db:AsyncSession,user_id:int):
    message = Message(conversation_id=thread_id,content=content,role=role)
    db.add(message)
    stmt = update(Conversation).where(Conversation.conversation_id == thread_id,Conversation.user_id == user_id).values(message_count=Conversation.message_count + 1)
    await db.execute(stmt)
    await db.commit()
    return True


# ── SSE 工具函数 ──
def sse(event_type: str, **payload) -> str:
    payload["type"] = event_type
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

# ── 工具名 → 中文标签 ──
TOOL_LABELS = {
    "searxng_search_engine": "联网搜索",
    "calculator": "计算器",
    "get_current_time": "时间查询",
    "analyze_numeric_data": "数据分析",
    "rag_search": "知识库检索",
    "agent": "任务分发",
    "get_memory": "记忆查询",
    "generate_chart": "图表生成",
}


async def generate(thread_id:str,question:str,user_id:int,config:RunnableConfig):
    async with AsyncSessionLocal() as s:  # 独立 session
        # ① 存用户消息
        await add_message(db=s, thread_id=thread_id, role="user", content=question, user_id=user_id)

        # ② 发 session_start（修复 meta 缺失）
        conv = (await s.execute(
            select(Conversation).where(Conversation.conversation_id == thread_id)
        )).scalar_one_or_none()
        title = conv.title if conv else question[:50]
        yield sse("session_start", thread_id=thread_id, title=title)

        full = ""
        # ③ 遍历双流
        try:
            async for event, data in ai_response(user_question=question, config=config):
                # messages 流：文本 token
                if event == "messages":
                    chunk, metadata = data
                    if isinstance(chunk, AIMessageChunk) and chunk.content:
                        full += chunk.content
                        yield sse("text_delta", content=chunk.content)

                # updates 流：节点级输出
                elif event == "updates":
                    for node_name, node_output in (data or {}).items():
                        # llm_node → tool_calls → tool_start
                        if node_name == "llm_node":
                            for msg_obj in (node_output or {}).get("messages", []):
                                if isinstance(msg_obj, AIMessage) and getattr(msg_obj, "tool_calls", None):
                                    for tc in msg_obj.tool_calls:
                                        yield sse(
                                            "tool_start",
                                            tool_id=tc["id"],
                                            tool_name=tc["name"],
                                            tool_label=TOOL_LABELS.get(tc["name"], tc["name"]),
                                            tool_args=tc["args"],
                                        )

                        # tool_node → ToolMessage → tool_end
                        elif node_name == "tool_node":
                            for msg_obj in (node_output or {}).get("messages", []):
                                if isinstance(msg_obj, ToolMessage):
                                    result_str = str(msg_obj.content)
                                    if msg_obj.name == "generate_chart":
                                        try:
                                            chart_payload = json.loads(result_str)
                                        except (TypeError, json.JSONDecodeError) as exc:
                                            raise ValueError("图表工具返回了无效的 JSON") from exc
                                        if not isinstance(chart_payload, dict) or chart_payload.get("type") != "chart":
                                            raise ValueError("图表工具返回数据缺少 type=chart")
                                        chart_json = json.dumps(chart_payload, ensure_ascii=False)
                                        full += f"\n\n<!-- AI_CHART:{chart_json} -->"
                                        yield sse(
                                            "chart",
                                            tool_id=msg_obj.tool_call_id,
                                            chart=chart_payload,
                                        )
                                        result_str = "图表已生成"
                                    if len(result_str) > 800:
                                        result_str = result_str[:800] + "...(已截断)"
                                    yield sse(
                                        "tool_end",
                                        tool_id=msg_obj.tool_call_id,
                                        tool_name=msg_obj.name or msg_obj.tool_call_id,
                                        tool_label=TOOL_LABELS.get(msg_obj.name, msg_obj.name or "工具"),
                                        result=result_str,
                                    )
        except asyncio.CancelledError:
            # 客户端点击停止或断开连接时，立即终止上游模型流。
            logger.info("AI 流式响应被客户端中断")
            raise
        except asyncio.TimeoutError:
            logger.exception("AI 流式响应超时")
            error_message = "模型响应超时，请稍后重试。"
            full = full or error_message
            yield sse("error", message=error_message)
        except Exception:
            logger.exception("AI 流式响应失败")
            error_message = "AI 服务暂时不可用，请稍后重试。"
            full = full or error_message
            yield sse("error", message=error_message)

        # ④ 存 AI 回答
        await add_message(db=s, thread_id=thread_id, role="assistant", content=full, user_id=user_id)

    # ⑤ 结束
    yield sse("done")

async def get_conversations(user_id:int,db:AsyncSession,page_size:int,page:int=1):
    #先计算总数
    stmt= select(count(Conversation.id)).where(Conversation.user_id == user_id)
    res =await db.execute(stmt)
    total=res.scalar_one_or_none()

    offset = (page-1)*page_size

    stmt = select(Conversation).where(Conversation.user_id == user_id).order_by(Conversation.updated_at.desc()).limit(page_size).offset(offset)
    result = await db.execute(stmt)
    conversations_list =result.scalars().all()
    return total,conversations_list


async def create_conversation_by_id(user_id:int,db:AsyncSession,title:str):
    conversation = Conversation(
        user_id=user_id,
        conversation_id=str(uuid.uuid4()),
        title=title,
        message_count=0,
        is_expired=0,
    )
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    return conversation

async def get_messages_by_thread_id(conversation_id:str,db:AsyncSession,user_id:int):
    stmt = select(Conversation).where(Conversation.conversation_id == conversation_id,Conversation.user_id == user_id)
    res = await db.execute(stmt)
    if res.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Conversation not exists")

    stmt = select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at.asc())
    res =await db.execute(stmt)
    messages_list =res.scalars().all()
    return messages_list


async def delete_checkpoint_by_thread(thread_id: str) -> None:
    async with AsyncPostgresSaver.from_conn_string(CHECKPOINTER_DATABASE_URL) as saver:
        await saver.setup()
        await saver.adelete_thread(thread_id=thread_id)



async def delete_conversation_by_id(conversation_id:str,db:AsyncSession,user_id:int):
    #先检查会话表是否存在数据
    stmt =select(Conversation).where(Conversation.conversation_id == conversation_id,Conversation.user_id == user_id)
    res = await db.execute(stmt)
    if res.scalar_one_or_none() is None:
        return False
    #删checkpoint
    await delete_checkpoint_by_thread(conversation_id)
    #删除会话表和消息表
    await db.execute(delete(Message).where(Message.conversation_id == conversation_id))
    await db.execute(delete(Conversation).where(Conversation.conversation_id == conversation_id,Conversation.user_id == user_id,))
    await db.commit()
    return True
