"""实时新闻后台调度器。

不引入 APScheduler / Celery 等新依赖，直接用 asyncio 常驻任务，
由 FastAPI 的 lifespan 启停，做到「启动即更新、运行期定时更新」。

调度策略：
* **启动时**立刻刷新一次 —— 保证刚 ``docker compose up`` 就有当日新闻；
* **运行期**每 ``NEWS_REFRESH_INTERVAL_MINUTES`` 分钟增量刷新一次（默认 30 分钟）；
* **每天** ``NEWS_DAILY_REFRESH_HOUR`` 点（默认 07:00）做一次全量刷新。
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional

from loguru import logger
from sqlalchemy import text

from backend.config import news_config
from backend.config.mysql_config import AsyncSessionLocal
from backend.services.news_pipeline import refresh_news

_task: Optional[asyncio.Task] = None
_stop_event: Optional[asyncio.Event] = None

# 运行状态，供 /api/news/status 查询
_state: dict = {
    "running": False,
    "last_run_at": None,
    "last_trigger": None,
    "last_result": None,
    "next_run_at": None,
    "last_error": None,
    "started_at": None,
}


async def check_schema() -> bool:
    """确认 news 表已经有实时采集字段。

    没跑迁移时给出明确提示，而不是抛一堆 SQL 错误。
    """
    async with AsyncSessionLocal() as db:
        try:
            await db.execute(
                text("SELECT source, source_url, url_hash, is_live, fetched_at FROM news LIMIT 1")
            )
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "[news] news 表缺少实时采集字段，实时新闻功能不可用。"
                "请先执行 `alembic upgrade head` 完成迁移。原始错误: {}",
                exc,
            )
            return False


async def _run_once(trigger: str) -> None:
    if _state["running"]:
        return
    _state["running"] = True
    _state["last_trigger"] = trigger
    try:
        result = await refresh_news(trigger=trigger)
        _state["last_result"] = result
        _state["last_error"] = None
    except Exception as exc:  # noqa: BLE001 - 后台任务绝不能把进程带崩
        _state["last_error"] = f"{type(exc).__name__}: {exc}"
        logger.exception("[news] 刷新失败({}): {}", trigger, exc)
    finally:
        _state["running"] = False
        _state["last_run_at"] = datetime.now().isoformat(timespec="seconds")


def _next_daily_at(now: datetime) -> datetime:
    """下一次每日全量刷新时刻。"""
    hour = min(max(news_config.NEWS_DAILY_REFRESH_HOUR, 0), 23)
    today = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    return today if today > now else today + timedelta(days=1)


def _seconds_until_next(now: datetime, next_daily: datetime) -> float:
    """下一次唤醒要等多久：取「间隔刷新」和「每日刷新」里更早的那个。"""
    interval_minutes = max(0, news_config.NEWS_REFRESH_INTERVAL_MINUTES)
    candidates = [(next_daily - now).total_seconds()]
    if interval_minutes > 0:
        candidates.append(interval_minutes * 60)
    return max(30.0, min(candidates))


async def _loop(stop: asyncio.Event) -> None:
    _state["started_at"] = datetime.now().isoformat(timespec="seconds")
    try:
        from backend.services.news_sources import get_active_sources

        source_count = len(get_active_sources())
    except Exception:  # noqa: BLE001
        source_count = 0
    logger.info(
        "[news] 实时新闻调度器已启动（间隔 {} 分钟，每日 {} 点，启用来源 {} 个）",
        news_config.NEWS_REFRESH_INTERVAL_MINUTES,
        news_config.NEWS_DAILY_REFRESH_HOUR,
        source_count,
    )

    schema_ok = await check_schema()
    if not schema_ok:
        _state["last_error"] = "news 表缺少实时采集字段，请执行 alembic upgrade head"

    if schema_ok and news_config.NEWS_REFRESH_ON_STARTUP:
        await _run_once("startup")

    next_daily = _next_daily_at(datetime.now())

    while not stop.is_set():
        now = datetime.now()
        delay = _seconds_until_next(now, next_daily)
        _state["next_run_at"] = (now + timedelta(seconds=delay)).isoformat(timespec="seconds")
        try:
            await asyncio.wait_for(stop.wait(), timeout=delay)
            break  # 收到停止信号
        except asyncio.TimeoutError:
            pass

        now = datetime.now()
        if now >= next_daily:
            await _run_once("daily")
            next_daily = _next_daily_at(now)
        else:
            await _run_once("interval")

    logger.info("[news] 实时新闻调度器已停止")


async def start_scheduler() -> None:
    """在 FastAPI lifespan 启动阶段调用。"""
    global _task, _stop_event

    if not news_config.NEWS_REALTIME_ENABLED:
        logger.info("[news] NEWS_REALTIME_ENABLED=false，实时新闻采集已关闭")
        return
    if _task and not _task.done():
        return

    _stop_event = asyncio.Event()
    _task = asyncio.create_task(_loop(_stop_event), name="news-realtime-scheduler")


async def stop_scheduler() -> None:
    """在 FastAPI lifespan 关闭阶段调用。"""
    global _task, _stop_event

    if _stop_event is not None:
        _stop_event.set()
    if _task is not None:
        _task.cancel()
        try:
            await _task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
    _task = None
    _stop_event = None


def scheduler_state() -> dict:
    """调度器可观测状态。"""
    return {
        **_state,
        "enabled": news_config.NEWS_REALTIME_ENABLED,
        "interval_minutes": news_config.NEWS_REFRESH_INTERVAL_MINUTES,
        "daily_hour": news_config.NEWS_DAILY_REFRESH_HOUR,
        "task_alive": bool(_task and not _task.done()),
    }
