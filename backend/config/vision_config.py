"""视觉模型与聊天图片附件配置。"""
import os


OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
VISION_MODEL = os.getenv("VISION_MODEL", "qwen3-vl:4b-instruct-q4_K_M")
VISION_TIMEOUT = int(os.getenv("VISION_TIMEOUT", "180"))
VISION_CONNECT_TIMEOUT = int(os.getenv("VISION_CONNECT_TIMEOUT", "10"))
VISION_MAX_CONCURRENCY = int(os.getenv("VISION_MAX_CONCURRENCY", "1"))
VISION_MAX_IMAGE_SIDE = int(os.getenv("VISION_MAX_IMAGE_SIDE", "1024"))
VISION_NUM_CTX = int(os.getenv("VISION_NUM_CTX", "4096"))
VISION_NUM_PREDICT = int(os.getenv("VISION_NUM_PREDICT", "768"))
VISION_KEEP_ALIVE = os.getenv("VISION_KEEP_ALIVE", "30m")

VISION_PROMPT = """你是知识库和对话系统的视觉信息提取器，不负责给出最终结论。
请忠实提取图片中真实可见的信息，使用简洁 Markdown 输出，包含：
1. 场景概述；
2. 可见文字，原样提取；
3. 主要建筑、草木、物体及其颜色、材质和状态；
4. 对象之间的主要空间关系；
5. 表格、图表或界面信息（如存在）；
6. 不确定项。

无法确认的植物品种、品牌、地标、建筑年代或人物身份必须填写“不确定”，禁止猜测。
不要回答用户的最终问题，只提供支持回答的视觉事实和文字证据。"""
