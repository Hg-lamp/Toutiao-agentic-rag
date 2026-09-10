"""零依赖的 HTML 正文提取工具。

只用标准库 ``html.parser``，不引入 bs4 / lxml / readability，
避免给项目增加合并成本。目标是从新闻详情页里捞出「像正文的那几段」，
不追求完美还原，够详情页展示即可。
"""

import html as html_lib
import re
from html.parser import HTMLParser
from typing import List, Optional

# 这些标签里的内容一律丢弃
_DROP_TAGS = {
    "script", "style", "noscript", "iframe", "svg", "canvas", "form",
    "nav", "footer", "header", "aside", "button", "select", "input",
    "video", "audio", "map", "template",
}

# 遇到这些块级标签的结束标签就断段
_BLOCK_TAGS = {
    "p", "div", "br", "li", "tr", "section", "article", "blockquote",
    "h1", "h2", "h3", "h4", "h5", "h6", "dd", "dt", "figcaption",
    "td", "th", "pre", "hr", "table", "ul", "ol", "main",
}

# 门户网站正文区常见的噪声行
_NOISE_PATTERNS = [
    re.compile(r"^(责任编辑|编辑|来源|作者|记者|编辑：|来源：)[:：]?\s*\S{0,20}$"),
    re.compile(r"^(分享到|分享|扫一扫|扫码|点击查看|查看全文|阅读全文|更多精彩|相关阅读|推荐阅读|热点推荐|猜你喜欢)[:：]?$"),
    re.compile(r"^(上一篇|下一篇|返回顶部|回到顶部|关闭|广告|登录|注册|评论|点赞|收藏)$"),
    re.compile(r"(版权所有|版权声明|免责声明|京ICP备|沪ICP备|粤ICP备|互联网新闻信息服务许可证|违法和不良信息举报)"),
    re.compile(r"^(微信|微博|QQ|QQ空间|抖音|快手|客户端|APP|下载)"),
    re.compile(r"^[\s\d\W]{0,6}$"),
    # 导航条：一长串栏目名，几乎不含句子标点
    re.compile(r"^[^。，、！？；：]{20,}$"),
    # 文章页头部元信息：「2026-09-10 19:24:17来源：央视新闻客户端作者：刘阳禾责任编辑：刘阳禾」
    re.compile(r"^\d{4}[-年]\d{1,2}[-月]\d{1,2}.*(来源|作者|责任编辑|大字体|小字体)"),
    re.compile(r"^(首页|当前位置|您现在的位置)\s*[→>》]"),
    re.compile(r"^(更多精彩内容请进入|发表评论|【编辑[:：]|换一批|推荐阅读|相关新闻|最新报道)"),
]

# 中文句子标点——用来区分「正文段落」和「导航/栏目名罗列」
_SENTENCE_PUNCT_RE = re.compile(r"[。，、！？；：“”‘’（）《》]")
# 分隔符密度高 = 导航条
_NAV_MARKERS = ("|", "｜", "·", "•", "/", ">", "》")

# 标题属性可能在 meta 里的候选键
_META_DESC_KEYS = ("description", "og:description", "twitter:description")
_META_IMAGE_KEYS = ("og:image", "twitter:image", "twitter:image:src")
_META_SITE_KEYS = ("og:site_name", "application-name", "mediaid")


class _TextExtractor(HTMLParser):
    """把 HTML 拆成候选段落 / 顺手收集 meta 信息。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._drop_depth = 0
        self._buffer: List[str] = []
        self._paragraphs: List[str] = []
        self.meta: dict = {}
        self.title = ""
        self._in_title = False

    # ---------- 标签 ----------
    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag in _DROP_TAGS:
            self._drop_depth += 1
            return
        if tag == "title":
            self._in_title = True
        if tag == "meta":
            attr = {k.lower(): (v or "") for k, v in attrs}
            key = (attr.get("property") or attr.get("name") or attr.get("itemprop") or "").lower()
            content = attr.get("content", "").strip()
            if key and content and key not in self.meta:
                self.meta[key] = content
        if tag == "img" and self._drop_depth == 0:
            # 保留正文里的图片线索（用占位符标记，避免被当成文字）
            pass

    def handle_startendtag(self, tag: str, attrs) -> None:
        if tag.lower() == "br":
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _DROP_TAGS:
            if self._drop_depth:
                self._drop_depth -= 1
            return
        if tag == "title":
            self._in_title = False
        if tag in _BLOCK_TAGS:
            self._flush()

    # ---------- 文本 ----------
    def handle_data(self, data: str) -> None:
        if self._drop_depth:
            return
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self.title = (self.title + " " + text).strip()
            return
        self._buffer.append(text)

    # ---------- 内部 ----------
    def _flush(self) -> None:
        if not self._buffer:
            return
        line = re.sub(r"\s+", " ", "".join(self._buffer)).strip()
        self._buffer.clear()
        if line:
            self._paragraphs.append(line)

    def close(self) -> None:  # noqa: D102
        super().close()
        self._flush()

    @property
    def paragraphs(self) -> List[str]:
        self._flush()
        return list(self._paragraphs)


def _is_noise(line: str) -> bool:
    if len(line) < 8:
        return True
    return any(pattern.search(line) for pattern in _NOISE_PATTERNS)


def _is_nav_line(line: str) -> bool:
    """判断一行是不是导航条 / 栏目罗列，而不是正文。"""
    markers = sum(line.count(marker) for marker in _NAV_MARKERS)
    # 有多个分隔符、几乎没有句子标点 → 基本可以断定是栏目罗列
    # （例如「大医生来了|医学的温度|医药新观察」）
    if markers >= 2 and len(_SENTENCE_PUNCT_RE.findall(line)) <= 1:
        return True
    if len(line) < 24:
        return False
    # 长行里一个句子标点都没有 → 导航
    return not _SENTENCE_PUNCT_RE.search(line)


def _strip_leading_nav(body: List[str]) -> List[str]:
    """去掉正文开头混进来的栏目名/面包屑（它们都没有句号、逗号）。"""
    start = 0
    while start < len(body) - 1 and not _SENTENCE_PUNCT_RE.search(body[start]):
        start += 1
    return body[start:] if start else body


def _pick_main_body(lines: List[str], min_len: int = 24, max_paragraphs: int = 60) -> List[str]:
    """从一堆候选段落里挑出最像「正文」的一段。

    中文门户页面的结构是：导航/栏目名 → 正文若干长段 → 相关推荐/页脚。
    导航和页脚经过 ``_is_noise`` / ``_is_nav_line`` 之后基本只剩短行，
    所以「长度 >= min_len 的最长连续段」通常正好就是正文。
    """
    if not lines:
        return []

    runs: List[List[str]] = []
    current: List[str] = []
    for line in lines:
        if len(line) >= min_len:
            current.append(line)
        else:
            if current:
                runs.append(current)
                current = []
    if current:
        runs.append(current)

    if not runs:
        return lines[:max_paragraphs]

    best = max(runs, key=lambda run: sum(len(x) for x in run))
    # 挑出来的正文太少，说明页面结构不典型（比如正文本身就是短句），退回全部
    if sum(len(x) for x in best) < 200:
        return lines[:max_paragraphs]
    return best[:max_paragraphs]


def extract_article(html_text: str) -> dict:
    """返回 ``{"paragraphs": [...], "text": str, "meta": {...}, "title": str}``。

    ``text`` 用 ``\\n\\n`` 连接（详情页前端就是按 ``\\n\\n`` 切段的）。
    """
    if not html_text:
        return {"paragraphs": [], "text": "", "meta": {}, "title": ""}

    parser = _TextExtractor()
    try:
        parser.feed(html_text)
        parser.close()
    except Exception:  # 页面畸形时不能把整条采集链路带崩
        pass

    raw = parser.paragraphs
    # 去掉重复行（门户页面经常正文重复渲染）与明显的噪声行
    seen: set = set()
    cleaned: List[str] = []
    for line in raw:
        if line in seen:
            continue
        seen.add(line)
        if _is_noise(line) or _is_nav_line(line):
            continue
        cleaned.append(line)

    body = _strip_leading_nav(_pick_main_body(cleaned))

    return {
        "paragraphs": body,
        "text": "\n\n".join(body),
        "meta": parser.meta,
        "title": html_lib.unescape(parser.title or "").strip(),
    }


def extract_article_text(html_text: str, max_chars: int = 20000) -> str:
    """只取正文文本，超长截断。"""
    text = extract_article(html_text)["text"]
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "…"
    return text


def extract_og_image(html_text: str) -> Optional[str]:
    """从 meta 里取封面图。"""
    if not html_text:
        return None
    meta = extract_article(html_text)["meta"]
    for key in _META_IMAGE_KEYS:
        value = meta.get(key)
        if value and value.startswith(("http://", "https://")):
            return value
    return None


def extract_meta_description(html_text: str) -> Optional[str]:
    if not html_text:
        return None
    meta = extract_article(html_text)["meta"]
    for key in _META_DESC_KEYS:
        value = meta.get(key)
        if value:
            return re.sub(r"\s+", " ", value).strip()
    return None


def strip_html(raw: str, max_chars: int = 500) -> str:
    """把 RSS 里的富文本摘要压成纯文本。"""
    if not raw:
        return ""
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    text = re.sub(r"(?i)<br\s*/?>|</p>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "…"
    return text


def absolutize_url(url: str, base: str) -> str:
    """把 RSS 里的相对链接补成绝对链接。"""
    if not url:
        return ""
    url = url.strip()
    if url.startswith("//"):
        return "https:" + url
    if url.startswith(("http://", "https://")):
        return url
    if not base:
        return url
    from urllib.parse import urljoin

    return urljoin(base, url)
