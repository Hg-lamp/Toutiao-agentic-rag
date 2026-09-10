"""统一日志配置：本地文件轮转 + 控制台输出 + 标准库日志接管。"""

import logging
import os
import sys
from pathlib import Path

from loguru import logger


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "y"}


def _log_level() -> str:
    value = os.getenv("LOG_LEVEL", "INFO").strip().upper()
    try:
        logger.level(value)
        return value
    except ValueError:
        return "INFO"


def _log_dir() -> Path:
    configured = Path(os.getenv("LOG_DIR", "logs")).expanduser()
    return configured if configured.is_absolute() else PROJECT_ROOT / configured


class InterceptHandler(logging.Handler):
    """把 uvicorn、SQLAlchemy 等标准库日志转发给 loguru。"""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame = logging.currentframe()
        depth = 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(
            level,
            record.getMessage(),
        )


def setup_logging() -> None:
    """初始化日志，重复调用不会产生重复 sink。"""
    level = _log_level()
    log_dir = _log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)

    logger.remove()
    common = {
        "level": level,
        "backtrace": False,
        "diagnose": False,
        "enqueue": True,
    }
    logger.add(
        sys.stderr,
        colorize=sys.stderr.isatty(),
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | {message}"
        ),
        **common,
    )

    if _env_bool("LOG_TO_FILE", True):
        logger.add(
            log_dir / "backend_{time:YYYY-MM-DD}.log",
            rotation=os.getenv("LOG_ROTATION", "20 MB"),
            retention=os.getenv("LOG_RETENTION", "14 days"),
            compression=os.getenv("LOG_COMPRESSION", "zip"),
            encoding="utf-8",
            format=(
                "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
                "{name}:{function}:{line} | {message}"
            ),
            **common,
        )

    intercept = InterceptHandler()
    logging.basicConfig(handlers=[intercept], level=0, force=True)
    for name in (
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "sqlalchemy",
        "sqlalchemy.engine",
        "aiomysql",
    ):
        std_logger = logging.getLogger(name)
        std_logger.handlers = [intercept]
        std_logger.propagate = False
        std_logger.setLevel(logging.NOTSET)
