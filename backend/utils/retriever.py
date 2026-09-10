import asyncio

from backend.config.redis_vector import retriever_database
from redisvl.query.filter import Tag


class Retriever:
    def __init__(self,count:int=2, user_id: int | None = None):
        if count < 1 or count > 10:
            raise ValueError("检索数量必须在 1 到 10 之间")
        self.count = count
        self.user_id = user_id

    async def ainvoke(self,query:str):
        filter_expression = Tag("user_id") == str(self.user_id) if self.user_id is not None else None
        return await asyncio.to_thread(
            retriever_database.similarity_search,
            query,
            self.count,
            filter_expression,
        )

    def config_schema(self):
        return retriever_database.config_schema()