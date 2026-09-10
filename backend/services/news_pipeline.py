"""实时新闻采集流水线：抓取 → 分类 → 去重 → 入库 → 失效缓存 → 清理。

对外只暴露 :func:`refresh_news`，返回本轮统计信息，方便接口/日志观测。
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional

from loguru import logger
from sqlalchemy import case, delete, func, select
from sqlalchemy.exc import IntegrityError

from backend.cache.news_cache import invalidate_news_list_cache
from backend.config import news_config
from backend.config.mysql_config import AsyncSessionLocal
from backend.models.news import Category, News
from backend.services.news_classifier import (
    DEFAULT_CATEGORIES,
    title_fingerprint,
)
from backend.services.news_fetcher import RawArticle, enrich_articles, fetch_all

# 同一时刻只允许一轮刷新在跑（定时任务 + 手工触发可能撞车）
_refresh_lock = asyncio.Lock()

# 最近一轮刷新的结果，供 /api/news/status 和 /api/news/refresh 的冷却判断使用
_last_result: Optional[dict] = None


def is_refreshing() -> bool:
    return _refresh_lock.locked()


def last_refresh() -> Optional[dict]:
    return _last_result


async def ensure_categories(db) -> dict[str, int]:
    """保证 9 个默认频道存在，返回 {频道名: id}。

    全新数据库也能直接跑：分类表为空时自动建好，不用手工插数据。
    """
    result = await db.execute(select(Category))
    existing = {row.name: row.id for row in result.scalars().all()}

    missing = [name for name in DEFAULT_CATEGORIES if name not in existing]
    if missing:
        for index, name in enumerate(missing):
            category = Category(
                name=name,
                description=f"{name}频道（实时采集自动创建）",
                sort_order=DEFAULT_CATEGORIES.index(name) + 1,
            )
            db.add(category)
        await db.commit()
        result = await db.execute(select(Category))
        existing = {row.name: row.id for row in result.scalars().all()}
        logger.info("[news] 自动创建缺失频道: {}", ", ".join(missing))

    return existing


def _filter_by_age(articles: list[RawArticle]) -> tuple[list[RawArticle], int]:
    """丢弃过期的新闻，避免把旧闻当新闻灌进库。"""
    now = datetime.now()
    cutoff = now - timedelta(hours=max(1, news_config.NEWS_MAX_AGE_HOURS))
    kept: list[RawArticle] = []
    dropped = 0
    for article in articles:
        if article.published_at is None:
            # 没有时间就以抓取时间作为发布时间
            article.published_at = now
        # 明显是未来时间的（时区解析错误）也拉回当前
        if article.published_at > now + timedelta(hours=12):
            article.published_at = now
        if article.published_at < cutoff:
            dropped += 1
            continue
        kept.append(article)
    return kept, dropped


def _dedupe_in_batch(articles: list[RawArticle]) -> tuple[list[RawArticle], int]:
    """同一批次内按 URL 指纹 + 标题指纹去重。"""
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    kept: list[RawArticle] = []
    dropped = 0
    for article in articles:
        url_hash = article.url_hash
        title_key = article.title_key
        if url_hash in seen_urls:
            dropped += 1
            continue
        # 标题完全一致的跨来源转载只保留第一条
        if title_key and len(title_key) >= 8 and title_key in seen_titles:
            dropped += 1
            continue
        seen_urls.add(url_hash)
        if title_key:
            seen_titles.add(title_key)
        kept.append(article)
    return kept, dropped


async def _load_recent_fingerprints(db, days: int = 3) -> tuple[set[str], set[str]]:
    """读出最近入库新闻的 URL 指纹与标题指纹，用于跨轮次去重。"""
    since = datetime.now() - timedelta(days=days)
    result = await db.execute(
        select(News.url_hash, News.title).where(News.publish_time >= since)
    )
    url_hashes: set[str] = set()
    title_keys: set[str] = set()
    for url_hash, title in result.all():
        if url_hash:
            url_hashes.add(url_hash)
        if title:
            title_keys.add(title_fingerprint(title))
    return url_hashes, title_keys


def _build_news(article: RawArticle, category_id: int, now: datetime) -> News:
    """把抓取结果转换成 ORM 对象。"""
    content = (article.content or "").strip()
    summary = (article.summary or "").strip()

    if not content:
        # 没抓到正文就用摘要兜底，保证详情页不是空的
        content = summary or article.title
    if not summary:
        summary = content[:200]

    return News(
        title=article.title[:255],
        description=summary[:500],
        content=content,
        image=(article.image or "")[:255] or None,
        author=(article.author or article.source or "新闻资讯")[:50],
        category_id=category_id,
        views=0,
        publish_time=article.published_at or now,
        source=article.source[:50] if article.source else None,
        source_url=article.url[:500] if article.url else None,
        url_hash=article.url_hash,
        is_live=True,
        fetched_at=now,
    )


async def _prune_old_live_news(db) -> int:
    """清理超期的采集数据，防止表无限增长。"""
    days = max(1, news_config.NEWS_RETENTION_DAYS)
    cutoff = datetime.now() - timedelta(days=days)
    result = await db.execute(
        delete(News).where(News.is_live.is_(True), News.publish_time < cutoff)
    )
    await db.commit()
    return result.rowcount or 0


async def refresh_news(trigger: str = "scheduler") -> dict:
    """执行一轮实时新闻刷新（对外入口，保证任何异常都不会冒泡到调度器/接口）。

    :param trigger: 触发来源（startup / interval / daily / manual），仅用于日志和返回。
    """
    global _last_result

    try:
        result = await _refresh_news(trigger)
    except Exception as exc:  # noqa: BLE001 - 采集失败不能影响业务接口
        logger.exception("[news] 刷新异常({})", trigger)
        result = {
            "trigger": trigger,
            "fetched": 0,
            "inserted": 0,
            "errors": [f"{type(exc).__name__}: {exc}"],
        }

    result["finished_at"] = datetime.now().isoformat(timespec="seconds")
    _last_result = result
    return result


async def _refresh_news(trigger: str) -> dict:
    if _refresh_lock.locked():
        logger.info("[news] 已有一轮刷新在执行，跳过本次触发（{}）", trigger)
        return {"skipped": True, "reason": "already_running", "trigger": trigger}

    async with _refresh_lock:
        started = datetime.now()
        stats = {
            "trigger": trigger,
            "fetched": 0,
            "accepted": 0,
            "inserted": 0,
            "duplicated": 0,
            "expired": 0,
            "enriched": 0,
            "pruned": 0,
            "errors": [],
            "started_at": started.isoformat(timespec="seconds"),
        }

        articles = await fetch_all()
        stats["fetched"] = len(articles)
        if not articles:
            stats["errors"].append("所有来源都没有抓到内容（检查网络或来源配置）")
            stats["duration_ms"] = int((datetime.now() - started).total_seconds() * 1000)
            return stats

        articles, expired = _filter_by_age(articles)
        stats["expired"] = expired
        articles, duplicated = _dedupe_in_batch(articles)
        stats["duplicated"] = duplicated

        # 正文补全放在去重之后，避免为重复内容浪费请求
        stats["enriched"] = await enrich_articles(articles)
        stats["accepted"] = len(articles)

        now = datetime.now()
        async with AsyncSessionLocal() as db:
            categories = await ensure_categories(db)
            if not categories:
                stats["errors"].append("news_category 表为空且自动创建失败，无法入库")
                stats["duration_ms"] = int((datetime.now() - started).total_seconds() * 1000)
                return stats
            fallback_category_id = next(iter(categories.values()))
            known_urls, known_titles = await _load_recent_fingerprints(db)

            pending: list[News] = []
            for article in articles:
                if article.url_hash in known_urls:
                    stats["duplicated"] += 1
                    continue
                title_key = article.title_key
                if title_key and len(title_key) >= 8 and title_key in known_titles:
                    stats["duplicated"] += 1
                    continue

                category_id = categories.get(article.category, fallback_category_id)
                pending.append(_build_news(article, category_id, now))
                known_urls.add(article.url_hash)
                if title_key:
                    known_titles.add(title_key)

            inserted = 0
            for item in pending:
                # 逐条插入：一条重复/超长不能把整批数据回滚掉
                db.add(item)
                try:
                    await db.commit()
                    inserted += 1
                except IntegrityError:
                    await db.rollback()
                    stats["duplicated"] += 1
                except Exception as exc:  # noqa: BLE001
                    await db.rollback()
                    logger.warning("[news] 入库失败《{}》: {}", item.title, exc)
                    stats["errors"].append(f"入库失败: {item.title[:30]}")
            stats["inserted"] = inserted

            try:
                stats["pruned"] = await _prune_old_live_news(db)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[news] 清理历史数据失败: {}", exc)

        if stats["inserted"]:
            # 有新数据就必须让列表缓存失效，否则前端还是看到旧的
            cleared = await invalidate_news_list_cache()
            stats["cache_cleared"] = cleared

        stats["duration_ms"] = int((datetime.now() - started).total_seconds() * 1000)
        logger.info(
            "[news] 刷新完成({}): 抓取 {} / 入库 {} / 去重 {} / 过期 {} / 耗时 {}ms",
            trigger,
            stats["fetched"],
            stats["inserted"],
            stats["duplicated"],
            stats["expired"],
            stats["duration_ms"],
        )
        return stats


async def news_stats() -> dict:
    """给 /api/news/status 用的运行状态。"""
    async with AsyncSessionLocal() as db:
        total_result = await db.execute(select(func.count(News.id)))
        live_result = await db.execute(
            select(func.count(News.id)).where(News.is_live.is_(True))
        )
        newest_result = await db.execute(select(func.max(News.publish_time)))
        last_fetch_result = await db.execute(select(func.max(News.fetched_at)))
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_result = await db.execute(
            select(func.count(News.id)).where(News.publish_time >= today_start)
        )

        per_category_rows = await db.execute(
            select(
                Category.id,
                Category.name,
                func.coalesce(
                    func.sum(case((News.is_live.is_(True), 1), else_=0)), 0
                ).label("live_count"),
            )
            .join(News, News.category_id == Category.id, isouter=True)
            .group_by(Category.id, Category.name)
            .order_by(Category.sort_order, Category.id)
        )

    per_category = [
        {"category_id": cid, "name": name, "live_count": count}
        for cid, name, count in per_category_rows.all()
    ]

    return {
        "enabled": news_config.NEWS_REALTIME_ENABLED,
        "refresh_interval_minutes": news_config.NEWS_REFRESH_INTERVAL_MINUTES,
        "total_news": total_result.scalar_one() or 0,
        "live_news": live_result.scalar_one() or 0,
        "today_news": today_result.scalar_one() or 0,
        "latest_publish_time": _iso(newest_result.scalar_one_or_none()),
        "last_fetched_at": _iso(last_fetch_result.scalar_one_or_none()),
        "categories": per_category,
    }


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat(sep=" ", timespec="seconds") if value else None
