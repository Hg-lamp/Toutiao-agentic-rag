from fastapi import APIRouter, Depends, File, HTTPException, Path as FastAPIPath, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config.mysql_config import get_db
from backend.models.users import User
from backend.schemas.ai_chat_response import (
    AttachmentResponse,
    ConversationListResponse,
    RagUploadResponse,
    UploadResponse,
    UserChatRequest,
)
from backend.services import chat_service
from backend.utils.auth import get_current_user
from backend.utils.response import success_response

router = APIRouter(prefix="/api/ai", tags=["chat"])


@router.post('/attachments', response_model=AttachmentResponse)
async def upload_chat_attachment(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    """上传聊天图片附件，暂不入库，等待用户发送消息时再分析。"""
    return await chat_service.upload_chat_attachment(user_id=user.id, file=file)


@router.delete('/attachments/{attachment_id}')
async def delete_chat_attachment(
    attachment_id: str,
    user: User = Depends(get_current_user),
):
    """用户取消待发送图片时删除附件。"""
    payload = await chat_service.delete_chat_attachment(user_id=user.id, attachment_id=attachment_id)
    return success_response(**payload)


@router.post('/chat')
async def chat(
    request_body: UserChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await chat_service.build_chat_stream(request_body=request_body, user_id=user.id, db=db)


@router.post('/upload', response_model=UploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    """上传文件，解析文本内容后返回，不存盘，供对话上下文注入。"""
    return await chat_service.parse_upload_file(user_id=user.id, file=file)


@router.post('/rag-upload', response_model=RagUploadResponse)
async def upload_rag_file(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    """解析文件、切分并写入当前用户的知识库。"""
    return await chat_service.parse_and_store_rag_file(user_id=user.id, file=file)


@router.get('/conversations')
async def get_user_conversations(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1, description="第几页"),
    limit: int = Query(20, ge=1, le=100, description="一页多少个会话"),
):
    data = await chat_service.get_user_conversations(user_id=user.id, db=db, page=page, limit=limit)
    return success_response(message="获取成功", data=data)


@router.post('/aicreate/conversations')
async def create_conversations(
    title: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    data = await chat_service.create_conversation(user_id=user.id, db=db, title=title)
    return success_response(message="success", data=data)


@router.get('/conversations/{id}/messages')
async def get_messages(
    id: str = FastAPIPath(..., description="会话id"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    data = await chat_service.get_conversation_messages(conversation_id=id, user_id=user.id, db=db)
    return success_response(message="success", data=data)


@router.delete('/conversations/{id}')
async def delete_conversation(
    id: str = FastAPIPath(..., description="线程id"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    deleted = await chat_service.delete_conversation_for_user(conversation_id=id, user_id=user.id, db=db)
    if not deleted:
        raise HTTPException(status_code=404, detail="该会话不存在")
    return success_response(message="success", data=None)
