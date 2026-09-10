"""聊天图片附件服务：负责文件校验、隔离存储和读取。"""
import asyncio
import io
import json
import uuid
from dataclasses import dataclass
from pathlib import Path

import aiofiles
from PIL import Image, UnidentifiedImageError

from backend.config.upload_config import AI_IMAGE_EXTENSIONS, AI_UPLOAD_DIR


class AttachmentError(ValueError):
    """聊天附件业务异常。"""


class AttachmentNotFoundError(AttachmentError):
    """附件不存在或不属于当前用户。"""


@dataclass(frozen=True)
class ChatAttachment:
    attachment_id: str
    user_id: int
    filename: str
    content_type: str
    size: int
    path: Path
    preview_url: str

    def to_response(self) -> dict:
        return {
            "attachment_id": self.attachment_id,
            "filename": self.filename,
            "content_type": self.content_type,
            "size": self.size,
            "preview_url": self.preview_url,
        }


class AttachmentService:
    """按 user_id 隔离存储聊天图片，并维护轻量元数据。"""

    def __init__(self, base_dir: Path = AI_UPLOAD_DIR):
        self.base_dir = base_dir

    @staticmethod
    def validate_image(content: bytes) -> None:
        try:
            with Image.open(io.BytesIO(content)) as image:
                # PIL 要求 verify() 紧跟在 open() 之后调用。
                image.verify()
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise AttachmentError("图片文件无效或已损坏") from exc

    async def save_image(
        self,
        *,
        user_id: int,
        filename: str,
        content_type: str,
        content: bytes,
    ) -> ChatAttachment:
        extension = Path(filename).suffix.lower()
        if extension not in AI_IMAGE_EXTENSIONS:
            raise AttachmentError(f"不支持的图片类型: {extension}")
        if not content:
            raise AttachmentError("图片内容为空")

        self.validate_image(content)
        attachment_id = uuid.uuid4().hex
        user_dir = self.base_dir / str(user_id)
        await asyncio.to_thread(user_dir.mkdir, parents=True, exist_ok=True)

        image_path = user_dir / f"{attachment_id}{extension}"
        meta_path = user_dir / f"{attachment_id}.json"
        preview_url = f"/uploads/ai/{user_id}/{image_path.name}"

        attachment = ChatAttachment(
            attachment_id=attachment_id,
            user_id=user_id,
            filename=filename,
            content_type=content_type,
            size=len(content),
            path=image_path,
            preview_url=preview_url,
        )

        async with aiofiles.open(image_path, "wb") as image_file:
            await image_file.write(content)
        async with aiofiles.open(meta_path, "w", encoding="utf-8") as meta_file:
            payload = attachment.to_response()
            payload["user_id"] = user_id
            await meta_file.write(json.dumps(payload, ensure_ascii=False))

        return attachment

    async def get(self, *, user_id: int, attachment_id: str) -> ChatAttachment:
        try:
            uuid.UUID(attachment_id)
        except (ValueError, AttributeError) as exc:
            raise AttachmentNotFoundError("附件不存在") from exc

        meta_path = self.base_dir / str(user_id) / f"{attachment_id}.json"
        if not await asyncio.to_thread(meta_path.is_file):
            raise AttachmentNotFoundError("附件不存在或已过期")

        try:
            raw = await asyncio.to_thread(meta_path.read_text, encoding="utf-8")
            payload = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            raise AttachmentNotFoundError("附件元数据无效") from exc

        try:
            owner_id = int(payload.get("user_id", 0))
        except (TypeError, ValueError) as exc:
            raise AttachmentNotFoundError("附件元数据无效") from exc
        if owner_id != int(user_id):
            raise AttachmentNotFoundError("无权访问该附件")

        image_path = self.base_dir / str(user_id) / Path(payload["preview_url"]).name
        if not await asyncio.to_thread(image_path.is_file):
            raise AttachmentNotFoundError("附件文件不存在")

        return ChatAttachment(
            attachment_id=attachment_id,
            user_id=user_id,
            filename=str(payload.get("filename", "image")),
            content_type=str(payload.get("content_type", "application/octet-stream")),
            size=int(payload.get("size", 0)),
            path=image_path,
            preview_url=str(payload["preview_url"]),
        )

    async def get_many(self, *, user_id: int, attachment_ids: list[str]) -> list[ChatAttachment]:
        attachments = []
        for attachment_id in attachment_ids:
            attachments.append(await self.get(user_id=user_id, attachment_id=attachment_id))
        return attachments

    async def read_bytes(self, attachment: ChatAttachment) -> bytes:
        try:
            return await asyncio.to_thread(attachment.path.read_bytes)
        except OSError as exc:
            raise AttachmentNotFoundError("附件文件读取失败") from exc

    async def delete(self, *, user_id: int, attachment_id: str) -> bool:
        try:
            attachment = await self.get(user_id=user_id, attachment_id=attachment_id)
        except AttachmentNotFoundError:
            return False

        meta_path = self.base_dir / str(user_id) / f"{attachment_id}.json"
        for path in (attachment.path, meta_path):
            await asyncio.to_thread(path.unlink, missing_ok=True)
        return True


attachment_service = AttachmentService()
