"""多源新闻抓取器。

设计要点
--------
* **零新增依赖**：用标准库 ``xml.etree`` 解析 RSS/Atom，用 stdlib ``html.parser``
  提取正文；HTTP 用 ``httpx``（项目依赖里已存在）。
* **编码安全**：国内不少站点仍用 GB2312/GBK，这里按
  「HTTP 头 → XML/HTML 声明 → UTF-8 → GB18030」的顺序依次尝试解码。
* **故障隔离**：单个来源超时/404/改版只影响它自己，不会拖垮整轮刷新。
"""

import asyncio
import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any, Iterable, Optional
from urllib.parse import urlsplit, urlunsplit

import httpx
from loguru import logger

from backend.config import news_config
from backend.services.news_classifier import classify, clean_title
from backend.utils.html_text import (
    absolutize_url,
    extract_article,
    strip_html,
)

# 编码尝试顺序（UTF-8 优先，失败再退化到中文常见编码）
_FALLBACK_ENCODINGS = ("utf-8", "utf-8-sig", "gb18030", "gbk", "big5", "latin-1")

_XML_ENCODING_RE = re.compile(rb"<\?xml[^>]*encoding=[\"']([\w\-]+)[\"']", re.I)
_HTML_CHARSET_RE = re.compile(
    rb"<meta[^>]+charset=[\"']?\s*([\w\-]+)", re.I
)


@dataclass
class RawArticle:
    """抓取阶段的中间结构，字段名与 News 模型对齐。"""

    title: str
    url: str
    source: str
    category: str = "头条"
    summary: str = ""
    content: str = ""
    image: Optional[str] = None
    author: Optional[str] = None
    published_at: Optional[datetime] = None
    # 该来源是否允许关键词纠偏（综合频道 = True）
    allow_override: bool = True
    extra: dict = field(default_factory=dict)

    @property
    def url_hash(self) -> str:
        return url_fingerprint(self.url)

    @property
    def title_key(self) -> str:
        return clean_title(self.title).lower()

    def is_valid(self) -> bool:
        return bool(self.title and self.url and len(self.title) >= 6)


# ==================== 工具 ====================


def decode_bytes(content: bytes, http_charset: Optional[str] = None) -> str:
    """把响应体解码成字符串，尽力避免中文乱码。"""
    candidates: list[str] = []
    if http_charset:
        candidates.append(http_charset)

    head = content[:2048]
    match = _XML_ENCODING_RE.search(head)
    if match:
        candidates.append(match.group(1).decode("ascii", "ignore"))
    match = _HTML_CHARSET_RE.search(head)
    if match:
        candidates.append(match.group(1).decode("ascii", "ignore"))

    candidates.extend(_FALLBACK_ENCODINGS)

    tried: set[str] = set()
    for encoding in candidates:
        encoding = (encoding or "").strip().lower()
        # Python 里 gb2312 其实就是 gb18030 的子集，统一按 gb18030 解更稳
        if encoding in {"gb2312", "gbk", "gb18030"}:
            encoding = "gb18030"
        if not encoding or encoding in tried:
            continue
        tried.add(encoding)
        try:
            return content.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return content.decode("utf-8", errors="replace")


def _http_charset(response: httpx.Response) -> Optional[str]:
    try:
        return response.charset_encoding
    except Exception:  # pragma: no cover - httpx 版本差异
        content_type = response.headers.get("content-type", "")
        match = re.search(r"charset=([\w\-]+)", content_type, re.I)
        return match.group(1) if match else None


def url_fingerprint(url: str) -> str:
    """归一化 URL 后取 sha1，做去重指纹。"""
    if not url:
        return ""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return hashlib.sha1(url.strip().encode("utf-8")).hexdigest()
    # 去掉查询参数里的跟踪字段、去掉 fragment
    query_pairs = []
    for pair in parts.query.split("&"):
        if not pair:
            continue
        key = pair.split("=", 1)[0].lower()
        if key.startswith(("utm_", "spm", "from", "share", "ref", "fr", "src")):
            continue
        query_pairs.append(pair)
    normalized = urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path, "&".join(query_pairs), "")
    )
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def parse_datetime(value: Any) -> Optional[datetime]:
    """尽量把各种时间写法解析成本地 naive datetime。"""
    if not value:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    if isinstance(value, (int, float)):
        # 秒 / 毫秒时间戳
        seconds = value / 1000 if value > 1e11 else value
        try:
            return datetime.fromtimestamp(seconds)
        except (OverflowError, OSError, ValueError):
            return None

    text = str(value).strip()
    if not text:
        return None

    # RFC822: Wed, 10 Sep 2026 08:00:00 +0800
    if "," in text or re.match(r"^\d{1,2}\s+\w{3}\s+\d{4}", text):
        try:
            parsed = parsedate_to_datetime(text)
            if parsed.tzinfo:
                parsed = parsed.astimezone().replace(tzinfo=None)
            return parsed
        except (TypeError, ValueError, IndexError):
            pass

    # ISO8601 / "2026-09-10 08:00:00" / "2026/09/10 08:00"
    cleaned = text.replace("/", "-").replace("T", " ").replace("Z", "")
    cleaned = re.sub(r"([+-]\d{2}):?(\d{2})$", "", cleaned).strip()
    for fmt in (
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y年%m月%d日 %H:%M:%S",
        "%Y年%m月%d日 %H:%M",
        "%Y年%m月%d日",
        "%m-%d %H:%M",
    ):
        try:
            parsed = datetime.strptime(cleaned, fmt)
            if parsed.year == 1900:  # 只有 "09-10 08:00" 这种
                parsed = parsed.replace(year=datetime.now().year)
            return parsed
        except ValueError:
            continue

    # "3分钟前" / "2小时前"
    match = re.match(r"^(\d+)\s*(分钟|小时|天)前$", text)
    if match:
        amount = int(match.group(1))
        unit = match.group(2)
        delta = {
            "分钟": timedelta(minutes=amount),
            "小时": timedelta(hours=amount),
            "天": timedelta(days=amount),
        }[unit]
        return datetime.now() - delta
    return None


def _first(node, names: Iterable[str]) -> str:
    """取第一个命中的子节点文本（自动忽略命名空间）。"""
    for name in names:
        for child in node:
            tag = child.tag.rsplit("}", 1)[-1].lower()
            if tag == name:
                text = "".join(child.itertext()).strip()
                if text:
                    return text
    return ""


def _first_attr(node, names: Iterable[str], attr: str) -> str:
    for name in names:
        for child in node:
            tag = child.tag.rsplit("}", 1)[-1].lower()
            if tag == name:
                value = (child.get(attr) or "").strip()
                if value:
                    return value
    return ""


def _feed_link(node) -> str:
    """RSS 的 <link> 是文本，Atom 的 <link> 是 href 属性，两种都要兼容。"""
    for child in node:
        tag = child.tag.rsplit("}", 1)[-1].lower()
        if tag == "link":
            href = (child.get("href") or "").strip()
            rel = (child.get("rel") or "alternate").lower()
            if href and rel in {"alternate", ""}:
                return href
            text = "".join(child.itertext()).strip()
            if text:
                return text
    return ""


def _pick_image(node, base_url: str) -> Optional[str]:
    """从 RSS item 里找封面图。"""
    candidates: list[str] = []
    for child in node:
        tag = child.tag.rsplit("}", 1)[-1].lower()
        if tag in {"enclosure", "content", "thumbnail"}:
            for attr in ("url", "href"):
                value = child.get(attr)
                if value:
                    candidates.append(value)
        elif tag in {"image", "img"}:
            for attr in ("url", "src", "href"):
                value = child.get(attr)
                if value:
                    candidates.append(value)
            text = "".join(child.itertext()).strip()
            if text.startswith("http"):
                candidates.append(text)
        elif tag == "description":
            html = "".join(child.itertext())
            match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html or "", re.I)
            if match:
                candidates.append(match.group(1))

    for candidate in candidates:
        # 过滤掉 1x1 像素、图标之类的垃圾图
        lowered = candidate.lower()
        if any(bad in lowered for bad in ("logo", "icon", "blank.gif", "spacer", "pixel")):
            continue
        return absolutize_url(candidate, base_url)
    return None


# ==================== 解析 ====================


def parse_feed(text: str, source) -> list[RawArticle]:
    """解析 RSS 2.0 / Atom / RDF。"""
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(text.strip())
    except ET.ParseError as exc:
        logger.warning("[news] 来源 {} XML 解析失败: {}", source.name, exc)
        return []

    # 兼容 RDF（rss 1.0）：item 不在 channel 里面
    root_tag = root.tag.rsplit("}", 1)[-1].lower()
    if root_tag == "rss":
        channel = root.find("channel")
        nodes = list(channel) if channel is not None else list(root)
        items = [n for n in nodes if n.tag.rsplit("}", 1)[-1].lower() == "item"]
    elif root_tag == "feed":  # Atom
        items = [n for n in root if n.tag.rsplit("}", 1)[-1].lower() == "entry"]
    elif root_tag == "rdf":
        items = [n for n in root if n.tag.rsplit("}", 1)[-1].lower() == "item"]
    else:
        items = [n for n in root.iter() if n.tag.rsplit("}", 1)[-1].lower() in {"item", "entry"}]

    articles: list[RawArticle] = []
    for node in items[: max(news_config.NEWS_MAX_ITEMS_PER_SOURCE * 2, 30)]:
        raw_title = _first(node, ("title",))
        link = _feed_link(node)
        description = _first(node, ("description", "summary", "content", "encoded"))
        published = _first(
            node,
            ("pubdate", "published", "updated", "date", "dc:date", "lastbuilddate"),
        )
        author = _first(node, ("author", "creator", "dc:creator", "source"))
        clean = clean_title(strip_html(raw_title, 200))
        summary = strip_html(description, 500)
        article = RawArticle(
            title=clean,
            url=absolutize_url(link, source.url),
            source=source.author_name or source.name,
            category=_resolve_category(clean, summary, source),
            summary=summary,
            content="",
            image=_pick_image(node, source.url),
            author=strip_html(author, 40) or (source.author_name or source.name),
            published_at=parse_datetime(published),
            allow_override=bool(getattr(source, "allow_override", False)),
        )
        if article.is_valid():
            articles.append(article)
    return articles


def _resolve_category(title: str, summary: str, source) -> str:
    """来源频道保底 + 关键词纠偏，得到最终频道名。"""
    return classify(
        title=title,
        summary=summary,
        source_category=getattr(source, "category", None),
        allow_override=bool(getattr(source, "allow_override", False)),
    )


def parse_json_source(payload: Any, source) -> list[RawArticle]:
    """解析 JSON 接口来源。

    通过 ``source.json_fields`` 配置字段映射，支持 ``a.b.c`` 形式的嵌套取值；
    ``json_items_path`` 指向列表节点，留空表示顶层就是列表。
    """
    items_node = _json_get(payload, getattr(source, "json_items_path", "") or "")
    if items_node is None:
        # 有些接口直接返回数组
        items_node = payload if isinstance(payload, list) else []
    if isinstance(items_node, dict):
        items_node = [items_node]
    if not isinstance(items_node, list):
        return []

    fields = getattr(source, "json_fields", {}) or {}
    articles: list[RawArticle] = []
    for item in items_node[: max(news_config.NEWS_MAX_ITEMS_PER_SOURCE * 2, 30)]:
        if not isinstance(item, dict):
            continue
        title = clean_title(strip_html(str(_json_get(item, fields.get("title", "title")) or ""), 200))
        url = str(_json_get(item, fields.get("url", "url")) or "")
        summary = strip_html(str(_json_get(item, fields.get("summary", "summary")) or ""), 500)
        published = _json_get(item, fields.get("published_at", "published_at"))
        author = _json_get(item, fields.get("author", "author"))
        image = _json_get(item, fields.get("image", "image"))

        article = RawArticle(
            title=title,
            url=absolutize_url(url, source.url),
            source=source.author_name or source.name,
            category=_resolve_category(title, summary, source),
            summary=summary,
            content="",
            image=absolutize_url(str(image), source.url) if image else None,
            author=str(author) if author else (source.author_name or source.name),
            published_at=parse_datetime(published),
            allow_override=bool(getattr(source, "allow_override", False)),
        )
        if article.is_valid():
            articles.append(article)
    return articles


def strip_jsonp(text: str) -> str:
    """剥掉 JSONP 外壳：``news({...})`` → ``{...}``。"""
    stripped = text.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        return stripped
    match = re.match(r"^[\w$.]+\s*\(\s*(.*?)\s*\)\s*;?\s*$", stripped, re.S)
    return match.group(1) if match else stripped


def _json_get(data: Any, path: str) -> Any:
    if not path:
        # 空路径表示「该来源没有这个字段」，返回 None 而不是整个节点，
        # 否则 str(dict) 会被当成摘要写进库
        return None
    current = data
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
        if current is None:
            return None
    return current


# ==================== 抓取 ====================


def build_client() -> httpx.AsyncClient:
    kwargs: dict[str, Any] = {
        "timeout": httpx.Timeout(news_config.NEWS_FETCH_TIMEOUT),
        "follow_redirects": True,
        "headers": {
            "User-Agent": news_config.NEWS_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
        },
        "limits": httpx.Limits(max_connections=20, max_keepalive_connections=10),
    }
    if news_config.NEWS_HTTP_PROXY:
        kwargs["proxy"] = news_config.NEWS_HTTP_PROXY
    return httpx.AsyncClient(**kwargs)


async def fetch_source(client: httpx.AsyncClient, source) -> list[RawArticle]:
    """抓取并解析单个来源。任何异常都被吞掉并记日志，返回空列表。"""
    try:
        response = await client.get(source.url)
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001 - 单个来源失败不能影响整轮
        logger.warning("[news] 来源 {} 请求失败: {}", source.name, exc)
        return []

    try:
        text = decode_bytes(response.content, _http_charset(response))

        # 「假可达」防护：不少站点会返回 200 + 首页 HTML 或反爬页，
        # 看着成功其实一条数据都没有（实测：澎湃 60KB 首页、36氪 17KB 验证页）。
        head = text.lstrip()[:120].lower()
        if head.startswith("<!doctype html") or head.startswith("<html"):
            logger.warning("[news] 来源 {} 返回的是网页而不是数据接口，已跳过", source.name)
            return []

        if source.kind in {"json", "jsonp"}:
            import json

            payload = json.loads(strip_jsonp(text))
            articles = parse_json_source(payload, source)
        else:
            articles = parse_feed(text, source)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[news] 来源 {} 解析失败: {}", source.name, exc)
        return []

    # 每个来源单次最多取这么多条，避免某个源刷屏把其它源挤掉
    articles = articles[: max(1, news_config.NEWS_MAX_ITEMS_PER_SOURCE)]
    logger.info("[news] 来源 {} 抓到 {} 条", source.name, len(articles))
    return articles


async def fetch_all(sources: Optional[list] = None) -> list[RawArticle]:
    """并发抓取所有启用的来源。"""
    if sources is None:
        from backend.services.news_sources import get_active_sources

        sources = get_active_sources()
    if not sources:
        return []

    semaphore = asyncio.Semaphore(max(1, news_config.NEWS_FETCH_CONCURRENCY))

    async with build_client() as client:
        async def _guarded(src):
            async with semaphore:
                return await fetch_source(client, src)

        results = await asyncio.gather(
            *(_guarded(src) for src in sources), return_exceptions=True
        )

    articles: list[RawArticle] = []
    for result in results:
        if isinstance(result, Exception):
            logger.warning("[news] 来源抓取异常: {}", result)
            continue
        articles.extend(result)
    return articles


async def enrich_articles(articles: list[RawArticle]) -> int:
    """补全正文：再去抓一次原文页面，把详情页正文填上。

    只处理「正文还很短」的条目，并且有数量上限，避免刷新一轮耗时过长。
    失败时保留 RSS 摘要，不影响入库。
    """
    if not news_config.NEWS_ENRICH_ENABLED or not articles:
        return 0

    targets = [
        a for a in articles
        if len(a.content or a.summary or "") < news_config.NEWS_ENRICH_MIN_CONTENT
    ][: max(0, news_config.NEWS_ENRICH_MAX_PER_RUN)]
    if not targets:
        return 0

    semaphore = asyncio.Semaphore(max(1, news_config.NEWS_FETCH_CONCURRENCY))
    enriched = 0

    async with build_client() as client:
        async def _one(article: RawArticle) -> bool:
            async with semaphore:
                try:
                    response = await client.get(
                        article.url,
                        timeout=httpx.Timeout(news_config.NEWS_ENRICH_TIMEOUT),
                    )
                    response.raise_for_status()
                    text = decode_bytes(response.content, _http_charset(response))
                    parsed = extract_article(text)
                    body = parsed["text"]
                    # 正文太短说明没抓到（比如页面是 JS 渲染的），保持摘要
                    if len(body) < max(120, news_config.NEWS_ENRICH_MIN_CONTENT):
                        return False
                    article.content = body
                    if not article.image:
                        for key in ("og:image", "twitter:image"):
                            value = parsed["meta"].get(key)
                            if value and value.startswith("http"):
                                article.image = value
                                break
                    if not article.summary:
                        article.summary = body[:200]
                    return True
                except Exception as exc:  # noqa: BLE001
                    logger.debug("[news] 正文补全失败 {}: {}", article.url, exc)
                    return False

        results = await asyncio.gather(*(_one(a) for a in targets))
    enriched = sum(1 for ok in results if ok)
    logger.info("[news] 正文补全成功 {}/{}", enriched, len(targets))
    return enriched
