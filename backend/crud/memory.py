from datetime import datetime
from typing import Optional

from sqlalchemy import or_, select

from backend.config.mysql_config import AsyncSessionLocal
from backend.models.memory import Memory


def _normalize_key(memory_key: str) -> str:
    key = memory_key.strip().lower()
    if not key:
        raise ValueError("memory_key 不能为空")
    if len(key) > 100:
        raise ValueError("memory_key 不能超过 100 个字符")
    return key


async def get_user_memory(
    user_id: int,
    memory_key: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """读取当前用户未过期的有效记忆。"""
    if limit < 1 or limit > 100:
        raise ValueError("limit 必须在 1 到 100 之间")

    filters = [
        Memory.user_id == user_id,
        Memory.is_active == 1,
        or_(Memory.expires_at.is_(None), Memory.expires_at > datetime.now()),
    ]
    if memory_key:
        filters.append(Memory.memory_key == _normalize_key(memory_key))

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Memory)
            .where(*filters)
            .order_by(Memory.updated_at.desc())
            .limit(limit)
        )
        memories = result.scalars().all()
        now = datetime.now()
        for memory in memories:
            memory.last_accessed_at = now
        await db.commit()

        return [
            {
                "key": memory.memory_key,
                "value": memory.memory_value,
                "type": memory.memory_type,
                "source": memory.source,
                "confidence": memory.confidence,
            }
            for memory in memories
        ]


async def save_user_memory(
    user_id: int,
    memory_key: str,
    memory_value: str,
    memory_type: str = "fact",
    source: str = "assistant",
    confidence: float = 1.0,
) -> dict:
    """新增或覆盖用户的一条长期记忆。"""
    key = _normalize_key(memory_key)
    value = memory_value.strip()
    if not value:
        raise ValueError("memory_value 不能为空")
    if len(memory_type.strip()) > 30 or not memory_type.strip():
        raise ValueError("memory_type 必须是 1 到 30 个字符")
    if len(source.strip()) > 30 or not source.strip():
        raise ValueError("source 必须是 1 到 30 个字符")
    if not 0 <= confidence <= 1:
        raise ValueError("confidence 必须在 0 到 1 之间")

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Memory).where(
                Memory.user_id == user_id,
                Memory.memory_key == key,
            )
        )
        memory = result.scalar_one_or_none()
        if memory is None:
            memory = Memory(
                user_id=user_id,
                memory_key=key,
                memory_value=value,
                memory_type=memory_type.strip(),
                source=source.strip(),
                confidence=confidence,
                is_active=1,
            )
            db.add(memory)
        else:
            memory.memory_value = value
            memory.memory_type = memory_type.strip()
            memory.source = source.strip()
            memory.confidence = confidence
            memory.is_active = 1
            memory.expires_at = None

        await db.commit()
        return {
            "key": key,
            "value": value,
            "type": memory_type.strip(),
            "source": source.strip(),
            "confidence": confidence,
        }