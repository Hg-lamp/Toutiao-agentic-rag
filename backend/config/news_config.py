"""实时新闻采集相关配置。

所有开关都走环境变量，默认值保证「开箱即用」：容器/本地启动后端后
会自动开始拉取当日新闻，无需额外的定时任务或外部服务。
"""

import os


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "y"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


# ==================== 总开关 ====================
# 关闭后后端不会做任何联网采集，行为与改造前一致（便于排查问题）。
NEWS_REALTIME_ENABLED = _env_bool("NEWS_REALTIME_ENABLED", True)
# 进程启动时立即拉一次（保证刚部署完就有当日新闻）
NEWS_REFRESH_ON_STARTUP = _env_bool("NEWS_REFRESH_ON_STARTUP", True)
# 增量刷新间隔（分钟）——新闻不是秒级产品，30 分钟足够“实时”
NEWS_REFRESH_INTERVAL_MINUTES = _env_int("NEWS_REFRESH_INTERVAL_MINUTES", 30)
# 每天固定时刻做一次全量刷新（本地时区），默认早 7 点
NEWS_DAILY_REFRESH_HOUR = _env_int("NEWS_DAILY_REFRESH_HOUR", 7)

# ==================== 抓取参数 ====================
# 单个请求超时（秒）
NEWS_FETCH_TIMEOUT = _env_int("NEWS_FETCH_TIMEOUT", 12)
# 每个来源单次最多取多少条
NEWS_MAX_ITEMS_PER_SOURCE = _env_int("NEWS_MAX_ITEMS_PER_SOURCE", 30)
# 只入库最近 N 小时的新闻，避免把陈年旧闻灌进库里
NEWS_MAX_AGE_HOURS = _env_int("NEWS_MAX_AGE_HOURS", 72)
# 采集数据的保留天数，超期自动清理（不清理会无限增长）
NEWS_RETENTION_DAYS = _env_int("NEWS_RETENTION_DAYS", 30)
# 采集并发数
NEWS_FETCH_CONCURRENCY = _env_int("NEWS_FETCH_CONCURRENCY", 6)

# ==================== 正文补全 ====================
# RSS 只给摘要，这里再去抓一次原文页，把详情页正文补全
NEWS_ENRICH_ENABLED = _env_bool("NEWS_ENRICH_ENABLED", True)
# 每轮最多补全多少篇正文（控制耗时）
NEWS_ENRICH_MAX_PER_RUN = _env_int("NEWS_ENRICH_MAX_PER_RUN", 30)
NEWS_ENRICH_TIMEOUT = _env_int("NEWS_ENRICH_TIMEOUT", 8)
# 摘要短于该长度才需要补全正文
NEWS_ENRICH_MIN_CONTENT = _env_int("NEWS_ENRICH_MIN_CONTENT", 200)

# ==================== 手工触发 ====================
# 设置后，POST /api/news/refresh 必须带 ?token=xxx 才能触发；
# 不设置则任何来源都可以触发（本地开发方便），但有最小触发间隔保护。
NEWS_REFRESH_TOKEN = os.getenv("NEWS_REFRESH_TOKEN", "")
# 手工触发的最小间隔（秒），防止被反复打
NEWS_REFRESH_COOLDOWN_SECONDS = _env_int("NEWS_REFRESH_COOLDOWN_SECONDS", 60)

# ==================== 网络 ====================
# 形如 http://127.0.0.1:7890 ，留空表示直连
NEWS_HTTP_PROXY = os.getenv("NEWS_HTTP_PROXY", "")
NEWS_USER_AGENT = os.getenv(
    "NEWS_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
)
