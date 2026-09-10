from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.mysql import TINYINT
from sqlalchemy.dialects.mysql import INTEGER as MYSQL_INTEGER
from sqlalchemy.orm import Mapped, mapped_column

from backend.models import Base


class Memory(Base):
    __tablename__ = "memory"

    __table_args__ = (
        UniqueConstraint("user_id", "memory_key", name="uq_memory_user_key"),
        Index("idx_memory_user_active", "user_id", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="记忆主键")
    user_id: Mapped[int] = mapped_column(
        MYSQL_INTEGER(unsigned=True),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属用户",
    )
    memory_key: Mapped[str] = mapped_column(String(100), nullable=False, comment="记忆键")
    memory_value: Mapped[str] = mapped_column(Text, nullable=False, comment="记忆内容")
    memory_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default="fact", comment="记忆类型"
    )
    source: Mapped[str] = mapped_column(
        String(30), nullable=False, default="assistant", comment="记忆来源"
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0, comment="置信度")
    is_active: Mapped[int] = mapped_column(
        TINYINT, nullable=False, default=1, comment="是否有效"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间"
    )
    last_accessed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, comment="最后读取时间"
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, comment="过期时间"
    )
