from typing import Literal

from langchain_core.tools import tool

from backend.config.search_engine import SearXNG
from backend.services.tool_gateway import TOOL_REGISTRY, ToolSpec


@tool
async def searxng_search_engine(query: str):
    """
    互联网搜索工具，用于查询新闻、资讯、实时信息、天气、网络信息等。

    重要：query 必须是精炼的核心关键词，越简短越好（如 "郑州天气"、"佛山天气预报"、"今日股市"）。
    严禁把用户的完整问句原样传进来（如 "帮我查询今天郑州的天气" ），
    也不要添加 "今日"、"今天" 等时间词（会干扰搜索）。请先从用户问题中提取核心名词作为 query。
    """
    try:
        results = await SearXNG.aresults(query, num_results=3, engines=["bing", "360search"])
        if not results:
            return "未搜索到结果"
        formatted = []
        for r in results:
            if "Result" in r:
                continue
            formatted.append(f"标题：{r.get('title','')}\n摘要：{r.get('snippet','')}\n链接：{r.get('link','')}")
        return "\n\n".join(formatted) if formatted else "未搜索到结果"
    except Exception as exc:
        return f"搜索失败: {exc}"


@tool
async def sandbox_echo(text: str) -> str:
    """Test tool that returns text from inside the isolated sandbox."""
    raise RuntimeError("sandbox_echo must execute through MCP")


@tool
async def sandbox_run_command(command: Literal["pwd", "id", "python_version"]) -> str:
    """Run a fixed, allowlisted command inside the isolated sandbox."""
    raise RuntimeError("sandbox_run_command must execute through MCP")


TOOL_SPECS = [
    (searxng_search_engine, ToolSpec(
        name="searxng_search_engine", description="Search public web results through the configured search proxy.",
        risk_level="R2", idempotent=True,
    )),
    (sandbox_echo, ToolSpec(
        name="sandbox_echo", description="Return text from the isolated sandbox.",
        executor="mcp", risk_level="R1", idempotent=True,
        timeout_seconds=10, sandbox_profile="default",
    )),
    (sandbox_run_command, ToolSpec(
        name="sandbox_run_command", description="Run an allowlisted process in the sandbox.",
        executor="mcp", risk_level="R4", idempotent=True,
        timeout_seconds=10, sandbox_profile="default",
        required_scopes=("sandbox.command.execute",),
    )),
]

for _tool, _spec in TOOL_SPECS:
    TOOL_REGISTRY.register(_tool, _spec)

PARENT_TOOLS = [searxng_search_engine, sandbox_echo, sandbox_run_command]
CHILD_TOOLS = [searxng_search_engine]
