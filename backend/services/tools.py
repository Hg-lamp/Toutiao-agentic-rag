import numexpr as ne
from langchain_core.tools import tool
from backend.config.search_engine import SearXNG
from backend.crud.memory import get_user_memory
from backend.services.rag import Rag

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
async def rag_search(topic:str,count:int=2)->list[str]:
    """
    检索公务员考试（公考）知识库的专用工具。
    当用户的问题明确涉及公务员考试、行测、申论、公考知识点时使用。
    不要在无关话题（如日常聊天、写诗、讲笑话、天气查询等）使用此工具。

    :param topic: 需要检索的内容关键词
    :param count:需要检索返回的结果数量，默认为2
    :return: 返回检索到的结果（列表形式）
    """
    rag= Rag(search_count=count)
    return await rag.arun(topic)



@tool
async def agent(task:str)->str:
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
        result = await child_output(task)
        return f"任务的结果为:\n{result}\n"
    except Exception as e:
        return f"任务执行失败: {str(e)}"


@tool
async def get_memory(config):
    """
    获取保存的与当前用户的关键记忆
    :return:记忆信息
    """
    result = await get_user_memory(config["configurable"]["user_id"])
    return result



PARENT_TOOLS=[calculator,searxng_search_engine,agent,rag_search]
CHILD_TOOLS=[calculator,searxng_search_engine,rag_search]
