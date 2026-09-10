#新闻相关的缓存方法，新闻分类的读取和写入
#key value
from typing import List, Dict, Any, Optional

from backend.config.cache_config import delete_cache_by_prefix, get_json_cache, set_cache

CATEGORIES_KEY='news:categories'
NEWS_LIST_PREFIX='news:list'
#获取新闻分类缓存
async def get_cached_categories():
    return await get_json_cache(CATEGORIES_KEY)

#写入新闻分类缓存：缓存的数据，过期时间
#分类，配置7200，列表：600  详情：1800 验证码：120 数据越稳定：缓存越久
#避免所有key同时过期，引起缓存雪崩
async def set_cache_categories(data:List[Dict[str,Any]],expire:int = 7200):
    return await set_cache(CATEGORIES_KEY,data,expire)

#写入缓存-新闻列表 key=news_list:分类id:页码：每页数量+列表数据+过期时间
async def set_cache_news_list(category_id:Optional[int],page:int,size:int,news_list:list[Dict[str,Any]],expire:int = 1800):
    #调用封装的Redis的设置方法，存新闻列表到缓存
    category_part =category_id if category_id is not None else "all"

    key=f"{NEWS_LIST_PREFIX}:{category_part}:{page}:{size}"
    await set_cache(key,news_list,expire)

async def get_cache_news_list(category_id:Optional[int],page:int,size:int):
    category_part = category_id if category_id is not None else "all"
    key=f"{NEWS_LIST_PREFIX}:{category_part}:{page}:{size}"
    return await get_json_cache(key)


#实时新闻入库后必须让列表缓存失效，否则前端下拉刷新还是拿到旧数据
async def invalidate_news_list_cache():
    deleted = await delete_cache_by_prefix(f"{NEWS_LIST_PREFIX}:")
    return deleted