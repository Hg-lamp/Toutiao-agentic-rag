import asyncio
import os
from logging.config import fileConfig

from dotenv import load_dotenv
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# 加载 .env 文件（如果在项目根目录运行）
load_dotenv()

# Alembic Config 对象
config = context.config

# 设置日志
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ========== 关键：导入所有模型，让 Alembic 检测到表结构 ==========
from backend.models import Base                     # 统一的 Base
from backend.models import news, users, favorite, history, memory  # 加载所有模型文件
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """离线模式：只生成 SQL 脚本，不连接数据库"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    """在线模式：执行迁移到数据库"""
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """异步在线模式（适配项目使用的 aiomysql）"""
    configuration = config.get_section(config.config_ini_section, {})
    # 环境变量优先：容器里 DATABASE_URL 指向 mysql 服务名，
    # 而 alembic.ini 里写死的是 localhost，直接读 ini 会连错库。
    configuration["sqlalchemy.url"] = os.getenv(
        "DATABASE_URL", config.get_main_option("sqlalchemy.url")
    )
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """入口：使用异步方式运行迁移"""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()