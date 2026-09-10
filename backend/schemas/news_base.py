from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict


class NewsItemResponse(BaseModel):
    """新闻列表项。

    ``publish_time`` 的别名历史上叫 ``publishedTime``，模块内部（Redis 缓存）
    用 ``by_alias=False`` 存 snake_case，对外接口则由路由层显式转成
    ``publishTime``（与前端约定一致）。
    """

    id:int
    title:str
    description:Optional[str]=None
    image:Optional[str]=None
    author:Optional[str]=None
    category_id:int =Field(...,alias="categoryId")
    views:int
    publish_time:Optional[datetime]=Field(...,alias="publishedTime")
    # ===== 实时采集字段 =====
    source:Optional[str]=None
    source_url:Optional[str]=Field(default=None,alias="sourceUrl")
    is_live:bool=Field(default=False,alias="isLive")
    fetched_at:Optional[datetime]=Field(default=None,alias="fetchedAt")
    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True
    )


class RelatedNewsItem(BaseModel):
    """详情页的「相关推荐」，只带渲染需要的字段，不返回正文。"""

    id:int
    title:str
    image:Optional[str]=None
    author:Optional[str]=None
    category_id:int=Field(...,alias="categoryId")
    views:int=0
    publish_time:Optional[datetime]=Field(default=None,alias="publishedTime")
    source:Optional[str]=None
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class NewsDetailResponse(NewsItemResponse):
    content:str
    related_news:list[RelatedNewsItem]=Field(default_factory=list,alias="relatedNews")
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
