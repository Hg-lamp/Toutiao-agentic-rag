import os


from langchain_redis import RedisConfig, RedisVectorStore

from backend.config.embeddings import embed_model

#向量数据库配置
redis_vector_config = RedisConfig(
    index_name="index",
    redis_url=os.getenv("REDIS_VECTOR_URL", "redis://localhost:6380"),
    metadata_schema=[
        {"name": "category", "type": "tag"},
        {"name": "num", "type": "numeric"},
        {"name": "user_id", "type": "tag"},
        {"name": "document_id", "type": "tag"},
        {"name": "source", "type": "text"},
    ]
)
#检索存储器
retriever_database=RedisVectorStore(
    config=redis_vector_config,
    embeddings=embed_model
)