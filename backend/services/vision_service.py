"""共享视觉模型服务：聊天图片理解与 RAG 图片解析共用。"""
import asyncio
import base64
import io

import requests
from PIL import Image, ImageOps, UnidentifiedImageError

from backend.config.vision_config import (
    OLLAMA_BASE_URL,
    VISION_CONNECT_TIMEOUT,
    VISION_KEEP_ALIVE,
    VISION_MAX_CONCURRENCY,
    VISION_MAX_IMAGE_SIDE,
    VISION_MODEL,
    VISION_NUM_CTX,
    VISION_NUM_PREDICT,
    VISION_PROMPT,
    VISION_TIMEOUT,
)


class VisionServiceError(RuntimeError):
    """视觉模型调用失败。"""


class VisionTimeoutError(VisionServiceError):
    """视觉模型处理超时。"""


class VisionUnavailableError(VisionServiceError):
    """视觉模型服务不可用。"""


class VisionService:
    """封装图片标准化、Ollama Chat API 调用和并发限制。"""

    def __init__(self) -> None:
        self._semaphore = asyncio.Semaphore(max(1, VISION_MAX_CONCURRENCY))

    async def analyze_image(
        self,
        content: bytes,
        *,
        filename: str = "image",
        question: str = "",
    ) -> str:
        async with self._semaphore:
            return await asyncio.to_thread(
                self._analyze_sync,
                content,
                filename,
                question,
            )

    def _analyze_sync(self, content: bytes, filename: str, question: str) -> str:
        image_b64 = self._prepare_image(content)
        prompt = self._build_prompt(filename=filename, question=question)

        try:
            response = requests.post(
                f"{OLLAMA_BASE_URL}/api/chat",
                json={
                    "model": VISION_MODEL,
                    "stream": False,
                    "keep_alive": VISION_KEEP_ALIVE,
                    "messages": [
                        {
                            "role": "user",
                            "content": prompt,
                            "images": [image_b64],
                        }
                    ],
                    "options": {
                        "temperature": 0,
                        "num_ctx": VISION_NUM_CTX,
                        "num_predict": VISION_NUM_PREDICT,
                    },
                },
                timeout=(VISION_CONNECT_TIMEOUT, VISION_TIMEOUT),
            )
            response.raise_for_status()
        except requests.Timeout as exc:
            raise VisionTimeoutError("图片理解超时，请稍后重试") from exc
        except requests.ConnectionError as exc:
            raise VisionUnavailableError("无法连接 Ollama 视觉模型服务") from exc
        except requests.HTTPError as exc:
            detail = exc.response.text[:300] if exc.response is not None else str(exc)
            raise VisionServiceError(f"视觉模型调用失败: {detail}") from exc
        except requests.RequestException as exc:
            raise VisionServiceError(f"视觉模型请求失败: {exc}") from exc

        try:
            result = response.json()
            text = str(result["message"]["content"]).strip()
        except (ValueError, KeyError, TypeError) as exc:
            raise VisionServiceError("视觉模型返回了无效结果") from exc

        if not text:
            raise VisionServiceError("视觉模型没有提取到有效内容")
        return text

    @staticmethod
    def _prepare_image(content: bytes) -> str:
        if not content:
            raise VisionServiceError("图片内容为空")

        try:
            with Image.open(io.BytesIO(content)) as source:
                image = ImageOps.exif_transpose(source).convert("RGB")
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise VisionServiceError("图片文件无效或已损坏") from exc

        image.thumbnail(
            (VISION_MAX_IMAGE_SIDE, VISION_MAX_IMAGE_SIDE),
            Image.Resampling.LANCZOS,
        )
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=88, optimize=True)
        return base64.b64encode(buffer.getvalue()).decode("ascii")

    @staticmethod
    def _build_prompt(*, filename: str, question: str) -> str:
        question_text = question.strip() or "请完整理解图片内容。"
        return (
            f"{VISION_PROMPT}\n\n"
            f"原始文件名：{filename}\n"
            f"用户问题：{question_text}\n\n"
            "请优先提取回答该问题所需的视觉事实，但仍需保留图片中的关键全局信息。"
        )


vision_service = VisionService()
