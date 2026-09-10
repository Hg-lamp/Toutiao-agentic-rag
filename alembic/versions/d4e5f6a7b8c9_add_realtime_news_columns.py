"""add realtime news source columns

为实时新闻采集补充字段：
- source      来源媒体名称
- source_url  原文链接
- url_hash    原文链接指纹（唯一索引，用于采集去重）
- is_live     是否来自实时采集
- fetched_at  采集时间

老数据这些字段为 NULL / 0，不影响原有新闻的展示与收藏。

Revision ID: d4e5f6a7b8c9
Revises: b2c3d4e5f6a7
Create Date: 2026-09-10 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('news', sa.Column('source', sa.String(length=50), nullable=True, comment='来源媒体，例如 人民网 / 新华网'))
    op.add_column('news', sa.Column('source_url', sa.String(length=500), nullable=True, comment='原文链接'))
    op.add_column('news', sa.Column('url_hash', sa.String(length=40), nullable=True, comment='原文链接指纹，用于采集去重'))
    op.add_column('news', sa.Column('is_live', sa.Boolean(), nullable=False, server_default='0', comment='是否实时采集入库'))
    op.add_column('news', sa.Column('fetched_at', sa.DateTime(), nullable=True, comment='采集时间'))

    # 采集去重依赖这个唯一索引；MySQL 唯一索引允许多个 NULL，
    # 所以历史数据（url_hash 为 NULL）不会被影响。
    op.create_index('idx_news_url_hash', 'news', ['url_hash'], unique=True)

    # 列表页按发布时间倒序分页，加一个复合索引让查询走索引
    op.create_index('idx_news_category_publish', 'news', ['category_id', 'publish_time'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_news_category_publish', table_name='news')
    op.drop_index('idx_news_url_hash', table_name='news')
    op.drop_column('news', 'fetched_at')
    op.drop_column('news', 'is_live')
    op.drop_column('news', 'url_hash')
    op.drop_column('news', 'source_url')
    op.drop_column('news', 'source')
