from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from fastapi import File, HTTPException, UploadFile
from langchain_core.documents import Document
from langchain_core.runnables import RunnableConfig
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from backend.config.cache_config import delete_cache_by_prefix
from backend.config.redis_vector import retriever_database
from backend.config.upload_config import (
    AI_IMAGE_EXTENSIONS,
    ALLOWED_EXTENSIONS,
    MAX_CHARS,
    MAX_FILE_SIZE,
    MAX_IMAGE_FILE_SIZE,
)
from backend.crud.ai_chat import (
    check_thread_id,
    create_conversation_by_id,
    delete_conversation_by_id,
    generate,
    get_conversations,
    get_messages_by_thread_id,
)
from backend.schemas.ai_chat_response import (
    AttachmentResponse,
    ConversationListResponse,
    ConversationResponse,
    MessageListResponse,
    RagUploadResponse,
    UploadResponse,
    UserChatRequest,
)
from backend.services.attachment_service import (
    AttachmentError,
    AttachmentNotFoundError,
    attachment_service,
)
from backend.services.file_parser import parse_content
from backend.services.vision_service import (
    VisionServiceError,
    VisionTimeoutError,
    VisionUnavailableError,
    vision_service,
)


def is_image_extension(extension: str) -> bool:
    return extension in AI_IMAGE_EXTENSIONS


async def parse_uploaded_content(content: bytes, extension: str, filename: str) -> str:
    """图片走共享视觉服务，其他文件继续走原解析器。"""
    if is_image_extension(extension):
        return await vision_service.analyze_image(content, filename=filename)
    return parse_content(content, extension)


async def upload_chat_attachment(*, user_id: int, file: UploadFile) -> AttachmentResponse:
    extension = Path(file.filename or "").suffix.lower()
    if not is_image_extension(extension):
        raise HTTPException(status_code=415, detail=f"不支持的图片类型: {extension}")
    if file.content_type and not file.content_type.startswith("image/"):
        raise HTTPException(status_code=415, detail="上传文件不是有效图片")

    content = await file.read()
    if len(content) > MAX_IMAGE_FILE_SIZE:
        raise HTTPException(status_code=413, detail="图片过大，最大支持 10MB")

    try:
        attachment = await attachment_service.save_image(
            user_id=user_id,
            filename=file.filename or f"image{extension}",
            content_type=file.content_type or "application/octet-stream",
            content=content,
        )
    except AttachmentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return AttachmentResponse(**attachment.to_response())


async def delete_chat_attachment(*, user_id: int, attachment_id: str) -> dict[str, str]:
    deleted = await attachment_service.delete(
        user_id=user_id,
        attachment_id=attachment_id,
    )
    return {"message": "附件已删除" if deleted else "附件不存在"}


async def build_chat_stream(
    *,
    request_body: UserChatRequest,
    user_id: int,
    db: AsyncSession,
) -> StreamingResponse:
    question = request_body.messages[-1].content.strip()
    if not question and not request_body.attachment_ids:
        raise HTTPException(status_code=400, detail="消息或图片至少需要提供一项")

    try:
        attachments = await attachment_service.get_many(
            user_id=user_id,
            attachment_ids=request_body.attachment_ids,
        )
    except AttachmentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    conversation_seed = question or (attachments[0].filename if attachments else "新会话")
    thread_id = await check_thread_id(request_body.thread_id, user_id, db, conversation_seed)
    config: RunnableConfig = {
        "configurable": {
            "thread_id": thread_id,
            "conversation_id": thread_id,
            "user_id": user_id,
            "tenant_id": f"user:{user_id}",
            "agent_id": "parent",
            "trace_id": str(uuid.uuid4()),
            "scopes": [
                "agent.delegate",
                "memory.write",
                "sandbox.command.execute",
            ],
        },
        "recursion_limit": 100,
    }
    return StreamingResponse(
        generate(
            thread_id=thread_id,
            question=question,
            user_id=user_id,
            attachments=attachments,
            config=config,
        ),
        media_type="text/event-stream",
    )


async def parse_upload_file(*, user_id: int, file: UploadFile) -> UploadResponse:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {ext}，仅支持 {', '.join(ALLOWED_EXTENSIONS)}",
        )

    content = await file.read()
    max_size = MAX_IMAGE_FILE_SIZE if is_image_extension(ext) else MAX_FILE_SIZE
    if len(content) > max_size:
        raise HTTPException(
            status_code=400,
            detail=f"文件过大（{len(content) / 1024 / 1024:.1f}MB），最大支持 {max_size // 1024 // 1024}MB",
        )

    try:
        text = await parse_uploaded_content(content, ext, file.filename or "unknown")
    except VisionTimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except VisionUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except VisionServiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"文件解析失败: {exc}") from exc

    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + "\n\n...（文件过长，已截断）"

    return UploadResponse(
        filename=file.filename or "unknown",
        text=text,
        size=len(content),
    )


async def parse_and_store_rag_file(*, user_id: int, file: UploadFile) -> RagUploadResponse:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext}")

    content = await file.read()
    max_size = MAX_IMAGE_FILE_SIZE if is_image_extension(ext) else MAX_FILE_SIZE
    if len(content) > max_size:
        raise HTTPException(status_code=400, detail=f"文件过大，最大支持 {max_size // 1024 // 1024}MB")

    try:
        text = await parse_uploaded_content(content, ext, file.filename or "unknown")
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
        separators=["\n\n", "\n", "。", "！", "？", "；", "，", " ", "",],
    )
    chunks = splitter.split_text(text)
    documents = [
        Document(
            page_content=chunk,
            metadata={
                "user_id": str(user_id),
                "document_id": document_id,
                "source": file.filename or "unknown",
                "category": "user_image" if is_image_extension(ext) else "user_upload",
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
    await delete_cache_by_prefix(f"rag:retries:{user_id}:")

    return RagUploadResponse(
        filename=file.filename or "unknown",
        size=len(content),
        chunks=len(documents),
        document_id=document_id,
    )


async def get_user_conversations(*, user_id: int, db: AsyncSession, page: int, limit: int) -> ConversationListResponse:
    total, conversations_list = await get_conversations(user_id=user_id, db=db, page=page, page_size=limit)
    return ConversationListResponse(total=total, list=conversations_list)


async def create_conversation(*, user_id: int, db: AsyncSession, title: str) -> ConversationResponse:
    conversation = await create_conversation_by_id(user_id, db, title)
    return ConversationResponse.model_validate(conversation).model_dump(by_alias=True)


async def get_conversation_messages(*, conversation_id: str, user_id: int, db: AsyncSession) -> MessageListResponse:
    messages = await get_messages_by_thread_id(conversation_id=conversation_id, db=db, user_id=user_id)
    return MessageListResponse(list=messages)


async def delete_conversation_for_user(*, conversation_id: str, user_id: int, db: AsyncSession) -> bool:
    return await delete_conversation_by_id(conversation_id=conversation_id, db=db, user_id=user_id)
