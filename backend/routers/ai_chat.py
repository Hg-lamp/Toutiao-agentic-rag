from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile, HTTPException, Query, Path as FastAPIPath
import uuid
from langchain_core.runnables import RunnableConfig
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from backend.config.mysql_config import get_db
from backend.config.upload_config import ALLOWED_EXTENSIONS, MAX_FILE_SIZE, MAX_CHARS
from backend.crud.ai_chat import check_thread_id, generate, get_conversations, create_conversation_by_id, \
    get_messages_by_thread_id, delete_conversation_by_id
from backend.models.users import User
from backend.schemas.ai_chat_response import UserChatRequest, UploadResponse, RagUploadResponse, ConversationListResponse, \
    ConversationResponse, MessageListResponse
from backend.services.file_parser import parse_content
from backend.utils.auth import get_current_user
from backend.utils.response import success_response
from backend.config.redis_vector import retriever_database
from backend.config.cache_config import delete_cache_by_prefix
import asyncio

router = APIRouter(prefix="/api/ai", tags=["chat"])


@router.post('/chat')
async def chat(request_body: UserChatRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    # 检查线程id
    thread_id = await check_thread_id(request_body.thread_id, user.id, db, request_body.messages[-1].content)
    config:RunnableConfig = {
        "configurable": {
            "thread_id": thread_id,
            "user_id":user.id
        },
        "recursion_limit": 100,
    }
    # 流式返回结果
    return StreamingResponse(generate(thread_id=thread_id, question=request_body.messages[-1].content, user_id=user.id,config=config),media_type="text/event-stream")


@router.post('/upload', response_model=UploadResponse)
async def upload_file(file: UploadFile = File(...)):
    """上传文件，解析文本内容后返回，不存盘，供对话上下文注入。"""
    # 1. 校验文件类型
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {ext}，仅支持 {', '.join(ALLOWED_EXTENSIONS)}"
        )
    #2. 读取文件内容
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"文件过大（{len(content) / 1024 / 1024:.1f}MB），最大支持 5MB"
        )
    #3. 根据文件类型解析文本
    try:
        text = parse_content(content, ext)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"文件解析失败: {str(e)}")
    #4. 限制文本长度
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + "\n\n...（文件过长，已截断）"

    return UploadResponse(
        filename=file.filename or "unknown",
        text=text,
        size=len(content),
    )


@router.post('/rag-upload', response_model=RagUploadResponse)
async def upload_rag_file(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    """解析文件、切分并写入当前用户的知识库。"""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext}")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="文件过大，最大支持 5MB")
    try:
        text = parse_content(content, ext)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"文件解析失败: {exc}") from exc
    if not text.strip():
        raise HTTPException(status_code=400, detail="文件没有可入库的文本内容")
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS]

    document_id = str(uuid.uuid4())
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=120,
        separators=["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""],
    )
    chunks = splitter.split_text(text)
    documents = [
        Document(
            page_content=chunk,
            metadata={
                "user_id": str(user.id),
                "document_id": document_id,
                "source": file.filename or "unknown",
                "category": "user_upload",
                "chunk_index": index,
                "num": index,
            },
        )
        for index, chunk in enumerate(chunks)
        if chunk.strip()
    ]
    try:
        await asyncio.to_thread(
            retriever_database.add_documents,
            documents,
            batch_size=100,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"知识库写入失败: {exc}") from exc
    await delete_cache_by_prefix(f"rag:retries:{user.id}:")

    return RagUploadResponse(
        filename=file.filename or "unknown",
        size=len(content),
        chunks=len(documents),
        document_id=document_id,
    )

@router.get('/conversations')
async def get_user_conversations(user:User =Depends(get_current_user),db:AsyncSession =Depends(get_db),page:int =Query(1,ge=1,description="第几页"),limit:int =Query(20,ge=1,le=100,description="一页多少个会话")):
    total,conversations_list=await get_conversations(user_id=user.id,db=db,page=page,page_size=limit)
    return success_response(message="获取成功",data=ConversationListResponse(
        total=total,
        list=conversations_list
    ))


@router.post('/aicreate/conversations')
async def create_conversations(title:str,user:User=Depends(get_current_user),db:AsyncSession =Depends(get_db)):
    conversation = await create_conversation_by_id(user.id,db,title)
    return success_response(message="success",data=ConversationResponse.model_validate(conversation).model_dump(by_alias=True))

@router.get('/conversations/{id}/messages')
async def get_messages(id:str=FastAPIPath(...,description="会话id"),user:User=Depends(get_current_user),db:AsyncSession =Depends(get_db)):
    mes =await get_messages_by_thread_id(conversation_id=id,db=db,user_id=user.id)
    return success_response(message="success",data=MessageListResponse(list=mes))


@router.delete('/conversations/{id}')
async def delete_conversation(id:str=FastAPIPath(...,description="线程id"),user:User=Depends(get_current_user),db:AsyncSession =Depends(get_db)):
    res = await delete_conversation_by_id(conversation_id=id, db=db, user_id=user.id)
    if not res:
        raise HTTPException(status_code=404, detail="该会话不存在")
    return success_response(message="success", data=None)