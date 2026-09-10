from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile, HTTPException, Query, Path as FastAPIPath
import uuid
from langchain_core.runnables import RunnableConfig
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from backend.config.mysql_config import get_db
from backend.config.upload_config import (
    AI_IMAGE_EXTENSIONS,
    ALLOWED_EXTENSIONS,
    MAX_CHARS,
    MAX_FILE_SIZE,
    MAX_IMAGE_FILE_SIZE,
)
from backend.crud.ai_chat import check_thread_id, generate, get_conversations, create_conversation_by_id, \
    get_messages_by_thread_id, delete_conversation_by_id
from backend.models.users import User
from backend.schemas.ai_chat_response import UserChatRequest, UploadResponse, RagUploadResponse, ConversationListResponse, \
    ConversationResponse, MessageListResponse, AttachmentResponse
from backend.services.file_parser import parse_content
from backend.services.attachment_service import (
    AttachmentError,
    AttachmentNotFoundError,
    attachment_service,
)
from backend.services.vision_service import (
    VisionServiceError,
    VisionTimeoutError,
    VisionUnavailableError,
    vision_service,
)
from backend.utils.auth import get_current_user
from backend.utils.response import success_response
from backend.config.redis_vector import retriever_database
from backend.config.cache_config import delete_cache_by_prefix
import asyncio

router = APIRouter(prefix="/api/ai", tags=["chat"])


def _is_image_extension(extension: str) -> bool:
    return extension in AI_IMAGE_EXTENSIONS


async def _parse_uploaded_content(content: bytes, extension: str, filename: str) -> str:
    """图片走共享视觉服务，其他文件继续走原解析器。"""
    if _is_image_extension(extension):
        return await vision_service.analyze_image(
            content,
            filename=filename,
        )
    return parse_content(content, extension)


@router.post('/attachments', response_model=AttachmentResponse)
async def upload_chat_attachment(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    """上传聊天图片附件，暂不入库，等待用户发送消息时再分析。"""
    extension = Path(file.filename or "").suffix.lower()
    if not _is_image_extension(extension):
        raise HTTPException(status_code=415, detail=f"不支持的图片类型: {extension}")
    if file.content_type and not file.content_type.startswith("image/"):
        raise HTTPException(status_code=415, detail="上传文件不是有效图片")

    content = await file.read()
    if len(content) > MAX_IMAGE_FILE_SIZE:
        raise HTTPException(status_code=413, detail="图片过大，最大支持 10MB")

    try:
        attachment = await attachment_service.save_image(
            user_id=user.id,
            filename=file.filename or f"image{extension}",
            content_type=file.content_type or "application/octet-stream",
            content=content,
        )
    except AttachmentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return AttachmentResponse(**attachment.to_response())


@router.delete('/attachments/{attachment_id}')
async def delete_chat_attachment(
    attachment_id: str,
    user: User = Depends(get_current_user),
):
    """用户取消待发送图片时删除附件。"""
    deleted = await attachment_service.delete(
        user_id=user.id,
        attachment_id=attachment_id,
    )
    return success_response(message="附件已删除" if deleted else "附件不存在")


@router.post('/chat')
async def chat(request_body: UserChatRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    question = request_body.messages[-1].content.strip()
    if not question and not request_body.attachment_ids:
        raise HTTPException(status_code=400, detail="消息或图片至少需要提供一项")

    try:
        attachments = await attachment_service.get_many(
            user_id=user.id,
            attachment_ids=request_body.attachment_ids,
        )
    except AttachmentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    conversation_seed = question or (attachments[0].filename if attachments else "新会话")
    # 检查线程id
    thread_id = await check_thread_id(request_body.thread_id, user.id, db, conversation_seed)
    config:RunnableConfig = {
        "configurable": {
            "thread_id": thread_id,
            "user_id":user.id
        },
        "recursion_limit": 100,
    }
    # 流式返回结果
    return StreamingResponse(
        generate(
            thread_id=thread_id,
            question=question,
            user_id=user.id,
            attachments=attachments,
            config=config,
        ),
        media_type="text/event-stream",
    )


@router.post('/upload', response_model=UploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
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
    max_size = MAX_IMAGE_FILE_SIZE if _is_image_extension(ext) else MAX_FILE_SIZE
    if len(content) > max_size:
        raise HTTPException(
            status_code=400,
            detail=f"文件过大（{len(content) / 1024 / 1024:.1f}MB），最大支持 {max_size // 1024 // 1024}MB"
        )
    #3. 根据文件类型解析文本
    try:
        text = await _parse_uploaded_content(content, ext, file.filename or "unknown")
    except VisionTimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except VisionUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except VisionServiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
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
    max_size = MAX_IMAGE_FILE_SIZE if _is_image_extension(ext) else MAX_FILE_SIZE
    if len(content) > max_size:
        raise HTTPException(status_code=400, detail=f"文件过大，最大支持 {max_size // 1024 // 1024}MB")
    try:
        text = await _parse_uploaded_content(content, ext, file.filename or "unknown")
    except VisionTimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except VisionUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except VisionServiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
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
                "category": "user_image" if _is_image_extension(ext) else "user_upload",
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
