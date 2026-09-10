import json
import numexpr as ne
import statistics
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from backend.config.search_engine import SearXNG
from backend.crud.memory import get_user_memory, save_user_memory
from backend.services.rag import Rag
from backend.schemas.agent_response import AgentResult

#搜索工具

#由于tavily使用需要另外配置apikey，所以使用SearXNG
@tool
async def searxng_search_engine(query:str):
    """
    互联网搜索工具，用于查询新闻、资讯、实时信息、天气、网络信息等。

    重要：query 必须是精炼的核心关键词，越简短越好（如 "郑州天气"、"佛山天气预报"、"今日股市"）。
    严禁把用户的完整问句原样传进来（如 "帮我查询今天郑州的天气" ），
    也不要添加 "今日"、"今天" 等时间词（会干扰搜索）。请先从用户问题中提取核心名词作为 query。

    :param query: 精炼的搜索关键词/短语
    :return: 返回搜索到的结果（标题 + 摘要 + 链接）
    """
    try:
        results = await SearXNG.aresults(query, num_results=3, engines=["bing", "360search"])
        if not results:
            return "未搜索到结果"
        formatted = []
        for r in results:
            if "Result" in r:  # 无结果时的占位
                continue
            formatted.append(f"标题：{r.get('title','')}\n摘要：{r.get('snippet','')}\n链接：{r.get('link','')}")
        return "\n\n".join(formatted) if formatted else "未搜索到结果"
    except Exception as e:
        return f"搜索失败: {str(e)}"

#测试的一个工具
@tool
async def calculator(expression: str):
    """
    计算数学表达式
    :param expression: 数学表达式，如 "3 + 5 * 2", "sqrt(16)", "2 ** 10"
    """
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

    :param chart_type: 图表类型，支持 bar、line、pie、scatter、radar、funnel。
    :param title: 图表标题。
    :param categories: 分类名称。bar/line 为横轴分类，radar 为指标名称；
        scatter 可传空列表，funnel 可传空列表。
    :param series: 数据系列。bar/line 格式为
        [{"name": "销量", "data": [10, 20, 30]}]；
        pie/funnel 格式为 [{"name": "数据", "data": [{"name": "A", "value": 10}]}]；
        scatter 格式为 [{"name": "身高体重", "data": [[170, 65], [180, 75]]}]；
        radar 格式为 [{"name": "产品A", "data": [80, 90, 70]}]。
    :return: JSON 字符串，外层 type 固定为 chart，供 SSE/前端识别。
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


@tool
async def rag_search(
    topic: str,
    config: RunnableConfig,
    count: int = 2,
) -> list[dict]:
    """
    检索当前用户知识库的工具。
    当用户的问题涉及公务员考试、行测、申论、公考知识点，或用户此前上传到 RAG
    知识库的文件内容时使用。
    不要在无关话题（如日常聊天、写诗、讲笑话、天气查询等）使用此工具。

    :param topic: 需要检索的内容关键词
    :param count:需要检索返回的结果数量，默认为2
    :return: 返回检索到的结果（列表形式）
    """
    user_id = (config or {}).get("configurable", {}).get("user_id")
    rag = Rag(search_count=count, user_id=user_id)
    return await rag.arun(topic)



@tool
async def agent(task: str, config: RunnableConfig) -> str:
    """
    任务下发工具（一个任务对应一个agent）
    一般在长难任务时候调用，用于下发单个任务给子agent。
    子agent是一个独立ReAct的agent，能够独立完成任务，最后将结果返回给主agent。
    如果需要处理多个任务，主agent可以多次调用此工具，每次传入一个任务。

    :param task: 需要处理的单个任务描述
    :return: 返回处理结果
    """
    from backend.agent.child_graph import child_output
    try:
        result = await child_output(task, config=config)
        return result
    except Exception as e:
        return json.dumps(
            AgentResult(
                status="failed",
                task=task,
                summary="子 Agent 执行失败",
                error=str(e),
            ).model_dump(),
            ensure_ascii=False,
        )


@tool
async def get_memory(
    config: RunnableConfig,
    memory_key: str = "",
) -> list[dict]:
    """
    读取当前用户保存的长期记忆。需要查找特定记忆时传入 memory_key，
    否则返回当前用户全部有效记忆。
    """
    user_id = (config or {}).get("configurable", {}).get("user_id")
    if not user_id:
        raise ValueError("缺少当前用户信息")
    return await get_user_memory(user_id, memory_key or None)


@tool
async def save_memory(
    config: RunnableConfig,
    memory_key: str,
    memory_value: str,
    memory_type: str = "fact",
) -> dict:
    """
    保存当前用户的长期记忆。
    只保存用户明确表达、稳定且未来有帮助的信息，不要保存密码、令牌、
    身份证号等敏感信息。相同 memory_key 会覆盖旧值。
    """
    user_id = (config or {}).get("configurable", {}).get("user_id")
    if not user_id:
        raise ValueError("缺少当前用户信息")
    return await save_user_memory(
        user_id=user_id,
        memory_key=memory_key,
        memory_value=memory_value,
        memory_type=memory_type,
    )


PARENT_TOOLS=[
    calculator,
    get_current_time,
    analyze_numeric_data,
    searxng_search_engine,
    agent,
    rag_search,
    generate_chart,
    get_memory,
    save_memory,
]
CHILD_TOOLS=[
    calculator,
    get_current_time,
    analyze_numeric_data,
    searxng_search_engine,
    rag_search,
]
