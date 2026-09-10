"""文件上传相关配置常量。"""
import os
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent.parent

# 聊天图片附件存储目录（与 /uploads 静态目录保持一致）
AI_UPLOAD_DIR = Path(os.getenv("AI_UPLOAD_DIR", BACKEND_DIR / "uploads" / "ai"))

# 支持的文件扩展名
IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".bmp",
}

ALLOWED_EXTENSIONS = {
    ".txt", ".md", ".csv",
    ".pdf", ".docx", ".xlsx",
} | IMAGE_EXTENSIONS

AI_IMAGE_EXTENSIONS = IMAGE_EXTENSIONS

# 文件大小上限：5MB
MAX_FILE_SIZE = 5 * 1024 * 1024
# 图片单文件上限：10MB
MAX_IMAGE_FILE_SIZE = 10 * 1024 * 1024

# 单次聊天最多附加图片数量
MAX_CHAT_ATTACHMENTS = 2

# 解析后文本长度上限（约 10 万字），防止前端渲染爆炸
MAX_CHARS = 100000
