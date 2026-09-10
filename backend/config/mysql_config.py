import os
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# 数据库 URL——优先从环境变量读取，否则用默认值（本地开发）
ASYNC_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "mysql+aiomysql://root:root@localhost:3306/news_app?charset=utf8mb4"
)
CHECKPOINTER_DATABASE_URL = os.getenv(
    "CHECKPOINTER_DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/langgraph_db"
)

DB_ECHO = os.getenv("DB_ECHO", "false").strip().lower() in {
    "1", "true", "yes", "on", "y",
}

async_engine = create_async_engine(
    ASYNC_DATABASE_URL,
    echo=DB_ECHO,
    pool_size=10,
    max_overflow=20,
)
# 创建异步会话工厂
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)
# 依赖项，用于获取数据库会话
async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
