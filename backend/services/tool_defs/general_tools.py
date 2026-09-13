import json
import statistics
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from langchain_core.tools import tool

from backend.services.tool_gateway import TOOL_REGISTRY, ToolSpec


@tool
async def calculator(expression: str):
    """
    计算数学表达式
    :param expression: 数学表达式，如 "3 + 5 * 2", "sqrt(16)", "2 ** 10"
    """
    import numexpr as ne

    return ne.evaluate(expression).item()


@tool
async def get_current_time(timezone: str = "Asia/Shanghai") -> str:
    """
    获取指定时区的当前日期和时间。

    :param timezone: IANA 时区名称，默认为 Asia/Shanghai。
    :return: ISO 8601 格式的当前时间。
    """
    try:
        zone = ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"不支持的时区: {timezone}") from exc
    return datetime.now(zone).isoformat(timespec="seconds")


@tool
async def analyze_numeric_data(values: list[float]) -> str:
    """
    对一组数值做基础统计分析，适合在生成图表前确认数据特征。

    :param values: 数值列表，至少包含一个数字。
    :return: JSON 字符串，包含数量、总和、均值、中位数、最小值、最大值和标准差。
    """
    if not values:
        raise ValueError("values 不能为空")
    if not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in values):
        raise ValueError("values 必须全部为数字")

    result = {
        "count": len(values),
        "sum": sum(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
        "stdev": statistics.stdev(values) if len(values) > 1 else 0,
    }
    return json.dumps(result, ensure_ascii=False)


@tool
async def generate_chart(
    chart_type: Literal["bar", "line", "pie", "scatter", "radar", "funnel"],
    title: str,
    categories: list[str],
    series: list[dict],
) -> str:
    """
    生成前端可渲染的图表配置。

    仅当用户明确要求图表、趋势图、柱状图、折线图、饼图、散点图、
    雷达图或漏斗图时调用。
    工具不返回图片，而是返回 ECharts option 配置。调用后应根据配置
    向用户简要说明图表展示的内容，不要把完整 JSON 原样复制到回答中。
    """
    supported_types = {"bar", "line", "pie", "scatter", "radar", "funnel"}
    if chart_type not in supported_types:
        raise ValueError(f"不支持的图表类型: {chart_type}")
    if chart_type not in ("scatter", "funnel") and not categories:
        raise ValueError("categories 不能为空")
    if not series:
        raise ValueError("series 不能为空")

    if chart_type in ("bar", "line"):
        for item in series:
            data = item.get("data")
            if not isinstance(data, list) or len(data) != len(categories):
                raise ValueError("bar/line 图表的每个 series.data 长度必须等于 categories 长度")
    elif chart_type in ("pie", "funnel"):
        for item in series:
            data = item.get("data")
            if not isinstance(data, list):
                raise ValueError(f"{chart_type} 图表的 series.data 必须是列表")
            if any(not isinstance(point, dict) or "name" not in point or "value" not in point for point in data):
                raise ValueError(f"{chart_type} 图表数据必须包含 name 和 value")
    elif chart_type == "scatter":
        for item in series:
            data = item.get("data")
            if not isinstance(data, list) or any(
                not isinstance(point, list) or len(point) != 2
                or not all(isinstance(value, (int, float)) for value in point)
                for point in data
            ):
                raise ValueError("scatter 图表的 data 必须是 [[x, y], ...] 数值列表")
    elif chart_type == "radar":
        for item in series:
            data = item.get("data")
            if not isinstance(data, list) or len(data) != len(categories) or not all(
                isinstance(value, (int, float)) for value in data
            ):
                raise ValueError("radar 图表的每个 series.data 必须与 categories 等长且为数值")

    option = {
        "title": {"text": title},
        "tooltip": {"trigger": "item" if chart_type in ("pie", "scatter", "funnel") else "axis"},
        "legend": {},
        "xAxis": {"type": "category", "data": categories} if chart_type in ("bar", "line") else None,
        "yAxis": {"type": "value"} if chart_type in ("bar", "line", "scatter") else None,
        "radar": {
            "indicator": [
                {"name": category, "max": max(
                    [value for item in series for value in item["data"]] or [1]
                ) * 1.2}
                for category in categories
            ]
        } if chart_type == "radar" else None,
        "series": [
            {
                "name": item.get("name", ""),
                "type": chart_type,
                "data": item["data"],
                **({"coordinateSystem": "cartesian2d"} if chart_type == "scatter" else {}),
            }
            for item in series
        ],
    }
    option = {key: value for key, value in option.items() if value is not None}
    return json.dumps({"type": "chart", "chart_type": chart_type, "option": option}, ensure_ascii=False)


TOOL_SPECS = [
    (calculator, ToolSpec(
        name="calculator", description="Evaluate a bounded numeric expression without external I/O.",
        risk_level="R0", idempotent=True, retry_max_attempts=1, timeout_seconds=5,
    )),
    (get_current_time, ToolSpec(
        name="get_current_time", description="Read the current time for an explicitly selected timezone.",
        risk_level="R0", idempotent=True, retry_max_attempts=1, timeout_seconds=5,
    )),
    (analyze_numeric_data, ToolSpec(
        name="analyze_numeric_data", description="Calculate descriptive statistics for a supplied numeric list.",
        risk_level="R0", idempotent=True, retry_max_attempts=1, timeout_seconds=5,
    )),
    (generate_chart, ToolSpec(
        name="generate_chart", description="Build a validated chart configuration for the frontend.",
        risk_level="R0", idempotent=True, timeout_seconds=5,
    )),
]

for _tool, _spec in TOOL_SPECS:
    TOOL_REGISTRY.register(_tool, _spec)

PARENT_TOOLS = [calculator, get_current_time, analyze_numeric_data, generate_chart]
CHILD_TOOLS = [calculator, get_current_time, analyze_numeric_data]
