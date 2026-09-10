"""实时新闻来源清单。

**这份清单是实测出来的，不是拍脑袋写的。** 2026-09 对 40+ 个中文新闻源做过
可达性与新鲜度实测，结论如下（这也是原项目「新闻很老」的根因）：

* 原项目很可能用过的人民网 RSS / 新华网 RSS / 新浪 RSS —— 全部是「假可达」：
  返回 HTTP 200 和合法 XML，但 ``pubDate`` 分别冻结在 2025-06、2022-12、2018-09。
  只要不检查发布时间就发现不了，页面自然全是旧闻。
* 澎湃 / 36氪 / 网易 / 观察者网 —— 返回 200 但实际是首页 HTML 或反爬闸门页。
* 真正持续更新的，是下面这些「接口型」来源。

每个来源都带 ``category``（保底频道）和 ``allow_override``（是否允许关键词纠偏）：

* 综合/要闻类来源（央视要闻、中新要闻、头条热榜）``allow_override=True``，
  军事、娱乐这类没有独立实时源的频道就靠它们的关键词分流来填充；
* 频道类来源（中新财经、中新体育……）``allow_override=False``，
  因为频道本身就是最可靠的人工分类，不要被关键词带跑偏。
"""

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class NewsSource:
    key: str
    name: str                 # 展示给用户看的来源名
    url: str
    category: str             # 保底频道（必须是 news_category 里的名字）
    kind: str = "rss"         # rss | json | jsonp
    author_name: str = ""     # 入库时的 author 字段，留空则用 name
    allow_override: bool = False
    enabled: bool = True
    # JSON/JSONP 来源的取值路径
    json_items_path: str = ""
    json_fields: dict = field(default_factory=dict)


def _create_timeout_env() -> float:
    try:
        return float(os.getenv("NEWS_SOURCE_TIMEOUT", "0") or 0)
    except ValueError:
        return 0.0


# ==================== 央视网（JSONP 接口，最新 5 分钟，带图带摘要）====================
# 实测：news_1 = 5min / china_1 = 6min / world_1 = 89min / tech_1 = 90min / ent_1 = 273min
_CCTV_FIELDS = {
    "title": "title",
    "url": "url",
    "summary": "brief",
    "published_at": "focus_date",
    "image": "image",
}
_CCTV_BASE = "https://news.cctv.com/2019/07/gaiban/cmsdatainterface/page/{name}_1.jsonp?cb={name}"


def _cctv(key: str, name: str, channel: str, category: str, override: bool = False) -> NewsSource:
    return NewsSource(
        key=f"cctv-{key}",
        name=name,
        url=_CCTV_BASE.format(name=channel),
        category=category,
        kind="jsonp",
        author_name=name,
        allow_override=override,
        json_items_path="data.list",
        json_fields=dict(_CCTV_FIELDS),
    )


CCTV_SOURCES = [
    _cctv("news", "央视新闻", "news", "头条", override=True),
    _cctv("china", "央视新闻", "china", "国内"),
    _cctv("society", "央视新闻", "society", "社会"),
    # 国际频道允许纠偏：军事类稿件（叙利亚武器库爆炸、胡塞武装打击……）
    # 各大媒体都归在国际频道里，不纠偏的话「军事」永远空着
    _cctv("world", "央视新闻", "world", "国际", override=True),
    _cctv("tech", "央视新闻", "tech", "科技"),
    _cctv("ent", "央视新闻", "ent", "娱乐"),
]

# ==================== 中新网（RSS，最新 0.1~1.2 小时）====================
_CHINANEWS = "https://www.chinanews.com.cn/rss/{name}.xml"
CHINANEWS_SOURCES = [
    NewsSource("chinanews-importnews", "中新网", _CHINANEWS.format(name="importnews"),
               "头条", allow_override=True),
    NewsSource("chinanews-scroll", "中新网", _CHINANEWS.format(name="scroll-news"),
               "头条", allow_override=True),
    NewsSource("chinanews-china", "中新网", _CHINANEWS.format(name="china"), "国内"),
    NewsSource("chinanews-society", "中新网", _CHINANEWS.format(name="society"), "社会"),
    # 同上：国际频道允许纠偏，让军事类稿件能被分流到「军事」频道
    NewsSource("chinanews-world", "中新网", _CHINANEWS.format(name="world"), "国际",
               allow_override=True),
    NewsSource("chinanews-finance", "中新网", _CHINANEWS.format(name="finance"), "财经"),
    NewsSource("chinanews-sports", "中新网", _CHINANEWS.format(name="sports"), "体育"),
    # 中新网没有娱乐频道 RSS（ent.xml 是空壳），文化频道内容最接近娱乐
    NewsSource("chinanews-culture", "中新网", _CHINANEWS.format(name="culture"), "娱乐"),
]

# ==================== 科技 / 财经 垂直媒体 ====================
VERTICAL_SOURCES = [
    NewsSource("ithome", "IT之家", "https://www.ithome.com/rss/", "科技", author_name="IT之家"),
    NewsSource("leiphone", "雷锋网", "https://www.leiphone.com/feed", "科技", author_name="雷锋网"),
    NewsSource("oschina", "开源中国", "https://www.oschina.net/news/rss", "科技", author_name="开源中国"),
    NewsSource("sspai", "少数派", "https://sspai.com/feed", "科技", author_name="少数派"),
    NewsSource("wallstreetcn", "华尔街见闻", "https://dedicated.wallstreetcn.com/rss.xml",
               "财经", author_name="华尔街见闻"),
    NewsSource("jiemian", "界面新闻", "https://a.jiemian.com/index.php?m=article&a=rss",
               "财经", allow_override=True, author_name="界面新闻"),
]

# ==================== 实时热榜（默认关闭，见下方说明）====================
# 热榜接口只给「标题 + 热度」，没有正文也没有配图，而且 toutiao.com 的文章页是
# JS 渲染的，抓不到内容。它的条目更像「热搜词」而不是新闻稿，混进列表会把
# 首屏刷成一句话标题，反而拉低观感，所以默认不启用。
# 需要的话在 .env 里打开：NEWS_ENABLED_SOURCES=toutiao-hot
HOTBOARD_SOURCES = [
    NewsSource(
        "toutiao-hot",
        "今日头条热榜",
        "https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc",
        "头条",
        kind="json",
        author_name="今日头条",
        allow_override=True,
        enabled=False,
        json_items_path="data",
        json_fields={
            "title": "Title",
            "url": "Url",
            # 热榜只有标题没有正文，摘要留空由 pipeline 兜底
            "summary": "",
            "published_at": "",
            "image": "",
        },
    ),
]

# ==================== 军事频道补充（走 SearXNG 联网搜索）====================
# 实测结论：没有找到任何一个持续更新的军事专用源
# （中国军网 rss.xml 是归档式、人民网/新浪军事 RSS 已冻结）。
# 项目里已经跑着 SearXNG，所以这里用「按频道搜索」来补军事这类薄弱频道。
# 默认关闭：需要时在 .env 里设置 NEWS_SEARXNG_CHANNELS=军事 打开即可。
_SEARXNG_TEMPLATE = (
    "{host}/search?q={query}&categories=news&format=json&language=zh-CN&time_range=day"
)


def _searxng_sources() -> list[NewsSource]:
    raw = os.getenv("NEWS_SEARXNG_CHANNELS", "").strip()
    if not raw:
        return []
    host = os.getenv("SEARXNG_HOST", "http://localhost:8080").rstrip("/")
    sources: list[NewsSource] = []
    from urllib.parse import quote

    for channel in [c.strip() for c in raw.split(",") if c.strip()]:
        sources.append(
            NewsSource(
                key=f"searxng-{channel}",
                name="联网搜索",
                url=_SEARXNG_TEMPLATE.format(host=host, query=quote(f"{channel}新闻")),
                category=channel,
                kind="json",
                author_name="联网搜索",
                json_items_path="results",
                json_fields={
                    "title": "title",
                    "url": "url",
                    "summary": "content",
                    "published_at": "publishedDate",
                    "image": "thumbnail",
                },
            )
        )
    return sources


ALL_SOURCES: list[NewsSource] = (
    CCTV_SOURCES + CHINANEWS_SOURCES + VERTICAL_SOURCES + HOTBOARD_SOURCES
)


def get_active_sources() -> list[NewsSource]:
    """返回当前启用的来源。

    * ``NEWS_DISABLED_SOURCES``：临时停用某些来源（用 key，逗号分隔）
    * ``NEWS_ENABLED_SOURCES``：显式打开默认关闭的来源（如 ``toutiao-hot``）
    """
    disabled = {
        item.strip()
        for item in os.getenv("NEWS_DISABLED_SOURCES", "").split(",")
        if item.strip()
    }
    force_enabled = {
        item.strip()
        for item in os.getenv("NEWS_ENABLED_SOURCES", "").split(",")
        if item.strip()
    }
    sources = [
        source
        for source in ALL_SOURCES + _searxng_sources()
        if (source.enabled or source.key in force_enabled) and source.key not in disabled
    ]
    return sources


def describe_sources() -> list[dict]:
    """给 /api/news/sources 用的可读清单，方便排查某个源是不是挂了。"""
    return [
        {
            "key": source.key,
            "name": source.name,
            "url": source.url,
            "category": source.category,
            "kind": source.kind,
            "allow_override": source.allow_override,
        }
        for source in get_active_sources()
    ]
