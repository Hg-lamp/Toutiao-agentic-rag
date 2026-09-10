from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.cache.news_cache import get_cached_categories, set_cache_categories, get_cache_news_list, \
    set_cache_news_list
from backend.models.news import Category, News
from backend.schemas.news_base import NewsItemResponse


async def get_categories(db:AsyncSession,skip:int=0,limit:int=100):
    #先尝试从缓存中获取数据
    cached_categories=await get_cached_categories()
    if cached_categories:
        return cached_categories

    stmt = select(Category).order_by(Category.sort_order,Category.id).offset(skip).limit(limit)
    result = await db.execute(stmt)
    categories =  result.scalars().all()
    #写入缓存
    if result:
        categories=jsonable_encoder(categories)#给orm对象转类型
        await set_cache_categories(categories)
    #返回数据
    return categories


async def get_news_list(db:AsyncSession,category_id:int=0,limit:int=10,skip:int=0):
    page = skip//limit +1
    #先尝试从缓存指定分类过获取新闻列表
    cached_list =await get_cache_news_list(category_id,page,limit)
    #查询指定分类下的所有新闻
    if cached_list:
        return [News(**item) for item in cached_list]
    # 必须按发布时间倒序：没有 ORDER BY 时数据库返回的是插入顺序，
    # 老数据会一直排在前面，用户看到的就是「很久以前的新闻」。
    stmt = select(News)
    if category_id:
        stmt = stmt.where(News.category_id == category_id)
    stmt = (
        stmt.order_by(News.publish_time.desc(), News.id.desc())
        .offset(skip)
        .limit(limit)
    )
    result=await db.execute(stmt)
    news_list= result.scalars().all()
    if news_list:
        #先把orm数据转换成字典才能写入缓存
        #orm转成pydantic 再转为字典
        #by_alias = False 不适应别名，保存python风格，因为redis数据是给后端用的
        news_data=[NewsItemResponse.model_validate(item).model_dump(mode="json",by_alias = False) for item in news_list]
        await set_cache_news_list(category_id,page,limit,news_data)
    return news_list


async def get_new_count(db:AsyncSession,category_id:int):
    stmt =select(func.count(News.id)).where(News.category_id==category_id)
    result  = await db.execute(stmt)
    return result.scalar_one()

async def get_news_detail(db:AsyncSession,news_id:int):
    stmt=select(News).where(News.id==news_id)
    result =await db.execute(stmt)
    return result.scalar_one_or_none()


#实现新闻浏览量的更新
async def increase_news_views(db:AsyncSession,news_id:int):
    stmt=update(News).where(News.id==news_id).values(views=News.views+1)
    res = await db.execute(stmt)
    await db.commit()
#虽然在路由层判断过了，但是一个方法可能被多个业务使用，写入数据库判断，来避免其他业务的缺判断
#更新，检查数据库是否真的命中数据
    return res.rowcount >0


#获取新闻页的同类新闻
async def get_related_news(db:AsyncSession,news_id:int,category_id:int):
    stmt=(select(News).
          where(News.id!=news_id,News.category_id==category_id).
          order_by(News.publish_time.desc(),News.id.desc()).
          limit(5))
    result = await db.execute(stmt)
    related_news = result.scalars().all()
    return[
        {"id":news_detail.id,
            "title":news_detail.title,
            "image":news_detail.image,
            "author":news_detail.author,
            "publish_time":news_detail.publish_time,
            "category_id":news_detail.category_id,
            "views":news_detail.views,
            "source":news_detail.source,
         } for news_detail in related_news]
