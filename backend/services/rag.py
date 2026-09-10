import json
from loguru import logger
from backend.config.cache_config import get_cache, set_cache
from backend.utils.retriever import Retriever


class Rag:
    #缓存的命名前缀
    RAG_CACHE_NS_PREFIX="rag:retries"

    def __init__(self, search_count: int, user_id: int | None = None):
        self.retriever = Retriever(count=search_count, user_id=user_id)
       

    async def arun(self,topic:str):
        scope = self.retriever.user_id or "global"
        cache_key = f'{self.RAG_CACHE_NS_PREFIX}:{scope}:{topic}'
        cache_value=await get_cache(cache_key)
        #判断是否命中缓存
        if cache_value:
            logger.info("RAG 缓存命中: {}", topic)
            #由于返回结果是str，而存入的是检索到的列表，需要反序列化
            return json.loads(cache_value)

        try:
            result_docs=await self.retriever.ainvoke(topic)
        except Exception as e:
            logger.exception("RAG 检索出错")
            raise
        result = [
            {
                "content": doc.page_content,
                "metadata": doc.metadata,
            }
            for doc in result_docs
        ]

        #写入缓存
        await set_cache(cache_key,result)
        return result
    def __repr__(self):
        return f'<{self.retriever.config_schema()}>'