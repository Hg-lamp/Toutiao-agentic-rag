import json
import os
from typing import Any

import redis.asyncio as aioredis

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
redis = aioredis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    db=REDIS_DB,
    decode_responses=True
)

# 设置 和 对读取 （字符串 和1列表或字典） "[{}]"
# 读取字符串
async def get_cache(key:str):
    try:
        return await redis.get(key)
    except Exception as e:
        print(f"获取缓存失败{e}")
        return None
# 读取列表或者字典
async def get_json_cache(key:str):
    try:
       data= await redis.get(key)
       if data:
           return json.loads(data)
       return None
    except Exception as e:
        print(f"获取json缓存失败{e}")

# 设置缓存
async def set_cache(key:str,value:Any,expire:int=3600):
    try:
        if isinstance(value,(dict,list)):
            value = json.dumps(value,ensure_ascii=False)#中文正常保存
        await redis.setex(key,expire,value)
        return True
    except Exception as e:
        print(f"设置缓存失败了{e}")
        return False


async def delete_cache_by_prefix(prefix: str):
    """删除指定前缀的缓存，供知识库更新后失效旧检索结果。"""
    try:
        keys = [key async for key in redis.scan_iter(match=f"{prefix}*")]
        if keys:
            await redis.delete(*keys)
        return len(keys)
    except Exception as e:
        print(f"删除缓存失败{e}")
        return 0