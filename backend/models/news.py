from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Index, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.models import Base


class Category(Base):
    __tablename__ = "news_category"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False, comment="分类名称")
    description: Mapped[str] = mapped_column(String(200), comment="分类描述")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="排序")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间"
    )

    def __repr__(self):
        return f"<category(id={self.id},name={self.name},description={self.description})>"


class News(Base):
    __tablename__ = "news"

    __table_args__ = (
        Index('fk_news_category_idx', 'category_id'),
        Index('idx_publish_time', 'publish_time'),
        # 列表页「分类内按发布时间倒序分页」的复合索引
        Index('idx_news_category_publish', 'category_id', 'publish_time'),
        # 采集去重：同一条新闻只入库一次（老数据该字段为 NULL，不受影响，
        # MySQL 的唯一索引允许多个 NULL）
        Index('idx_news_url_hash', 'url_hash', unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="新闻id")
    title: Mapped[str] = mapped_column(String(255), nullable=False, comment="新闻标题")
    description: Mapped[Optional[str]] = mapped_column(String(500), comment="新闻简介")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="内容")
    image: Mapped[Optional[str]] = mapped_column(String(255), comment="封面图片URL")
    author: Mapped[Optional[str]] = mapped_column(String(50), comment="作者")
    category_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="分类id")
    views: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="浏览量")
    publish_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, comment="发布时间")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间"
    )

    # ==================== 实时采集相关字段 ====================
    source: Mapped[Optional[str]] = mapped_column(
        String(50), comment="来源媒体，例如 人民网 / 新华网"
    )
    source_url: Mapped[Optional[str]] = mapped_column(
        String(500), comment="原文链接"
    )
    url_hash: Mapped[Optional[str]] = mapped_column(
        String(40), comment="原文链接指纹，用于采集去重"
    )
    is_live: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="0", comment="是否实时采集入库"
    )
    fetched_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, comment="采集时间"
    )

    def __repr__(self):
        return f"<news(id={self.id},title={self.title},description={self.description})>"