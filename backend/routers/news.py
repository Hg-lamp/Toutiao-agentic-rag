from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import news_config
from backend.config.mysql_config import get_db
from backend.crud import news, cache_news
from backend.models.news import News
from backend.services.news_pipeline import (
    is_refreshing,
    last_refresh,
    news_stats,
    refresh_news,
)
from backend.services.news_scheduler import scheduler_state
from backend.services.news_sources import describe_sources

#创建apirouter实例
router = APIRouter(prefix='/api/news',tags=['news'])

#接口实现流程
#1.模块化路由
#2.定义模型类-数据库表
#3.在crud文件里面创建文件，封装操作数据库的方法
#4.在路由处理函数里面调用crud封装好的方法，响应结果


def _fmt_time(value: Optional[datetime]) -> Optional[str]:
    """统一时间格式：前端 new Date('2026-09-10T19:21:25') 可直接解析。"""
    return value.strftime("%Y-%m-%dT%H:%M:%S") if value else None


def serialize_news(item: News, category_names: Optional[dict] = None) -> dict:
    """把 ORM 新闻对象转成对外的 camelCase 结构。

    改造前这里直接返回 ORM 对象，FastAPI 序列化出来的是 ``publish_time``，
    而前端读的是 ``publishTime``，所以详情页/列表页的时间一直是空白。
    """
    return {
        "id": item.id,
        "title": item.title,
        "description": item.description,
        "image": item.image,
        "author": item.author,
        "categoryId": item.category_id,
        "categoryName": (category_names or {}).get(item.category_id),
        "views": item.views or 0,
        "publishTime": _fmt_time(item.publish_time),
        "source": item.source,
        "sourceUrl": item.source_url,
        "isLive": bool(item.is_live),
        "fetchedAt": _fmt_time(item.fetched_at),
    }


@router.get('/categories')
async def categories(skip:int=0,limit:int=100,db:AsyncSession=Depends(get_db)):
    #获取数据库里面新闻分类数据-先定义模型类-封装查询数据的方法
    categories =await cache_news.get_categories(db, skip, limit)
    return {
        "code":200,
        "message":"获取新闻分类成功",
        "data":categories

    }


@router.get('/list')
async def get_list(
        category_id:int=Query(default=0,alias="categoryId"),
        page:int=1,
        page_size:int=Query(default=10,alias="pageSize"),
        db:AsyncSession=Depends(get_db)
):
    #处理分页规则 查询新闻列表 计算总量 计算是否还有更多
    offset = (page-1)*page_size

    data=await cache_news.get_news_list(db, category_id, page_size, offset)
    total=await news.get_new_count(db, category_id)
    category_names = await news.get_category_map(db)
    news_list = [serialize_news(item, category_names) for item in data]
    has_more = (offset+len(news_list))<total
    return{
        "code":200,
        "message":"success",
        "data":{
            "list":news_list,
            "total":total,
            "has_more":has_more,
        }
    }


@router.get('/latest')
async def get_latest(
        limit:int=Query(default=10,ge=1,le=50),
        category_id:int=Query(default=0,alias="categoryId"),
        db:AsyncSession=Depends(get_db)
):
    """最新新闻：按发布时间倒序，用于「实时」首屏。"""
    data = await news.get_latest_news(db, limit=limit, category_id=category_id)
    category_names = await news.get_category_map(db)
    return {
        "code":200,
        "message":"success",
        "data":{
            "list":[serialize_news(item, category_names) for item in data],
            "server_time": _fmt_time(datetime.now()),
        }
    }


@router.get('/detail')
async def get_detail(news_id:int = Query(...,alias="id"),db:AsyncSession=Depends(get_db)):
    #获取新闻详情 + 浏览量+1 + 相关新闻
    news_detail = await news.get_news_detail(db, news_id)
    if not news_detail:
        raise HTTPException(status_code=404,detail="新闻不存在")
    views = news_detail.views
    if not await news.increase_news_views(db, news_detail.id):
        raise HTTPException(status_code=404,detail="新闻不存在")
    related_news= await news.get_related_news(db, news_detail.id, news_detail.category_id)
    category_names = await news.get_category_map(db)
    return{
        "code":200,
        "message":"success",
        "data":{
            **serialize_news(news_detail, category_names),
            "content":news_detail.content,
            "views":views,
            "relatedNews":[
                {
                    "id":item["id"],
                    "title":item["title"],
                    "image":item["image"],
                    "author":item["author"],
                    "categoryId":item["category_id"],
                    "views":item["views"],
                    "publishTime":_fmt_time(item["publish_time"]),
                    "source":item.get("source"),
                }
                for item in related_news
            ],
        }
    }


@router.post('/refresh')
async def refresh_now(
        background: BackgroundTasks,
        wait: bool = Query(default=True, description="true=同步等待结果（默认），false=后台执行立即返回"),
        token: str = Query(default="", description="配置了 NEWS_REFRESH_TOKEN 时必须带上"),
):
    """手动触发一次实时抓取。

    用途：部署后想立刻看到新闻、或者定时任务没跑起来时手动补一刀。
    """
    if news_config.NEWS_REFRESH_TOKEN and token != news_config.NEWS_REFRESH_TOKEN:
        raise HTTPException(status_code=403, detail="刷新令牌不正确")

    if is_refreshing():
        return {"code":200,"message":"已有刷新任务在执行，稍后查看 /api/news/status","data":last_refresh()}

    # 冷却时间，避免被反复触发
    previous = last_refresh()
    if previous and previous.get("finished_at"):
        try:
            elapsed = (datetime.now() - datetime.fromisoformat(previous["finished_at"])).total_seconds()
            if elapsed < news_config.NEWS_REFRESH_COOLDOWN_SECONDS:
                return {
                    "code":200,
                    "message":f"距上次刷新仅 {int(elapsed)} 秒，冷却中（{news_config.NEWS_REFRESH_COOLDOWN_SECONDS}s）",
                    "data":previous,
                }
        except ValueError:
            pass

    if wait:
        result = await refresh_news(trigger="manual")
        return {"code":200,"message":"刷新完成","data":result}

    background.add_task(refresh_news, "manual")
    return {"code":200,"message":"已在后台开始刷新","data":None}


@router.get('/status')
async def status():
    """实时新闻运行状态：查这个接口就能知道采集是不是正常。"""
    stats = await news_stats()
    return {
        "code":200,
        "message":"success",
        "data":{
            **stats,
            "scheduler": scheduler_state(),
            "last_refresh": last_refresh(),
            "refreshing": is_refreshing(),
            "server_time": _fmt_time(datetime.now()),
        }
    }


@router.get('/sources')
async def sources():
    """当前启用的新闻来源清单（排查某个源是否失效用）。"""
    return {"code":200,"message":"success","data":describe_sources()}
