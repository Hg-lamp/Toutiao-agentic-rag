import os

from langchain_deepseek import ChatDeepSeek
from langchain_ollama import ChatOllama

from backend.services.tools import CHILD_TOOLS, PARENT_TOOLS

# 聊天大模型
chat_model = ChatDeepSeek(
    model="deepseek-chat",
    temperature=0.5,
    max_tokens=1024,
    max_retries=2,
    timeout=300,
    stream_chunk_timeout=300,
    api_key=os.getenv("DEEPSEEK_API_KEY"),  # 从环境变量读取
    extra_body={
        "thinking": {
            "type": "disabled"
        }
    }
)
local_chat_model=ChatOllama(
    base_url="localhost:11434",
    model="deepseek-r1:7b"
)
# 绑定所有工具的父模型
tool_model = chat_model.bind_tools(PARENT_TOOLS)

#绑定除子agent之外的所有工具的子模型
child_model =chat_model.bind_tools(CHILD_TOOLS)