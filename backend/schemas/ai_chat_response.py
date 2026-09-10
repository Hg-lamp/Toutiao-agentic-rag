from datetime import datetime
from typing import Optional, Annotated
from pydantic import BaseModel, Field, ConfigDict

from backend.config.upload_config import MAX_CHAT_ATTACHMENTS


class MessageItem(BaseModel):
    role:str
    content:str

class UserChatRequest(BaseModel):
    messages: list[MessageItem] = Field(..., min_length=1)
    thread_id:Optional[str]
    attachment_ids: list[str] = Field(default_factory=list, max_length=MAX_CHAT_ATTACHMENTS)


class ReflectionResponse(BaseModel):
    is_solved:bool = Field(...,description="对用户问题的回答判断是否得以解决用户的问题")
    reason:str =Field(max_length=25,description="对于这个问题的回答是否解决给出原因，简短一句话即可")


class UploadResponse(BaseModel):
    """文件上传解析结果，文本内容注入到对话上下文。"""
    filename: str
    text: str
    size: int


class AttachmentResponse(BaseModel):
    """聊天图片附件上传结果。"""
    attachment_id: str
    filename: str
    content_type: str
    size: int
    preview_url: str


class RagUploadResponse(BaseModel):
    """知识库文件入库结果。"""
    filename: str
    size: int
    chunks: int
    document_id: str


class ConversationResponse(BaseModel):
    """会话列表单项，字段以 camelCase 对齐前端。"""
    conversation_id: str = Field(serialization_alias="threadId")
    title: Optional[str] = None
    message_count: int = Field(serialization_alias="messageCount")
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")
    model_config = ConfigDict(
        from_attributes=True,  # 允许从 orm 对象属性中取值
    )


class ConversationListResponse(BaseModel):
    """会话列表，data 直接返回 { list, total }。"""
    total: int
    list: list[ConversationResponse]
    model_config = ConfigDict(
        from_attributes=True,
    )


class MessageResponse(BaseModel):
    """单条消息，字段以 camelCase 对齐前端。"""
    role: str
    content: str
    created_at: datetime = Field(serialization_alias="createdAt")
    model_config = ConfigDict(
        from_attributes=True,
    )


class MessageListResponse(BaseModel):
    """消息历史，data 直接返回 { list }。"""
    list: list[MessageResponse]
    model_config = ConfigDict(
        from_attributes=True,
    )
