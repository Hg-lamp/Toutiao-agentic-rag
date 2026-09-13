# 新闻资讯 AI 平台

**FastAPI + LangGraph + LangChain** 构建的 Agentic RAG 新闻资讯 AI 平台。

> 项目需求与验收标准见 [REQUIREMENTS.md](REQUIREMENTS.md)。
> 实时新闻采集的完整方案（问题定位、架构、配置、验收记录）见 [docs/NEWS_REALTIME.md](docs/NEWS_REALTIME.md)。
> Personal Mission Agent 的产品边界、协议、开发定稿和双 Agent 安排见 [docs/01-product-boundary.md](docs/01-product-boundary.md) 至 [docs/11-work-allocation.md](docs/11-work-allocation.md)。

## 功能特性

- **新闻浏览** — 分类、列表、详情
- **实时新闻** — 后台自动采集当日新闻，无需人工灌数据
  - 内置 21 个来源（央视新闻、中新网、IT之家、雷锋网、开源中国、少数派、华尔街见闻、界面新闻），默认启用 20 个
  - 启动即抓 + 每 30 分钟增量更新 + 每天 07:00 全量刷新
  - URL 指纹去重、标题指纹跨来源去重、超期新闻自动过滤与清理
  - 自动归类到原有 9 个频道，并补全正文、封面图、来源与原文链接
  - 列表按发布时间倒序，前端显示「刚刚 / 12分钟前」相对时间与「实时」角标
- **用户系统** — 注册、登录、个人信息、头像上传
- **收藏/历史记录** — 收藏新闻、浏览历史
- **AI Agentic RAG 聊天** — 基于 LangGraph 的智能问答系统
  - RAG 知识库检索（自定义）
  - 互联网搜索工具（SearXNG）
  - 子 Agent 任务分发
  - ReAct 循环（recursion_limit 100）
- **文件上传分析** — 支持 TXT/MD/PDF/DOCX/XLSX/CSV，自动解析文本内容注入对话上下文
- **图片对话理解** — 使用本地 Qwen3-VL 提取场景、对象、关系、文字和图表信息，再交给主模型回答
- **个人知识库** — 文本文件或图片解析后切分并写入用户专属 Redis 向量索引
- **对话持久化** — 基于 MySQL 保存会话、消息和记忆，PostgreSQL/LangGraph Checkpoint 保存图状态
- **会话管理** — 会话列表、历史消息查看、删除会话
- **对话记忆** — 提取并持久化用户长期偏好，辅助后续回答
- **统一日志** — loguru 接管 uvicorn/SQLAlchemy 标准库日志，本地按天轮转写入 `logs/`，容器内直接输出到 `docker logs`
- **工具安全网关** — 父/子 Agent 共用 `ToolRegistry + ToolGateway`，官方 `ToolNode` 的
  `awrap_tool_call` 负责参数校验、权限、超时、并发和按工具配置的重试；MCP 工具只能经
  `SandboxBroker` 进入一次性 Docker 沙箱（默认无网络、非 root、只读根文件系统）。

工具治理配置集中在 `backend/config/tool_config.py` 和 `.env`。第一阶段使用 Docker Desktop
的 WSL2 后端；本地开发使用构建出的镜像标签，生产环境必须替换为不可变 digest。
MCP 路径失败时不会回退到宿主机执行。

## 实时新闻是怎么工作的

```
FastAPI lifespan 启动
   │
   ├── 启动即抓一次（NEWS_REFRESH_ON_STARTUP=true）
   └── 后台协程循环（不占用请求线程，无需 Celery / APScheduler）
         ├── 每 NEWS_REFRESH_INTERVAL_MINUTES（30）分钟增量刷新
         └── 每天 NEWS_DAILY_REFRESH_HOUR（07:00）全量刷新
              │
              ▼
   多源并发抓取   20 个来源并发请求（NEWS_FETCH_CONCURRENCY=6）
              │   单个来源失败只跳过该源，不影响其它源和主服务
              ▼
   解析          RSS 2.0 / Atom / RDF / JSONP / JSON
              │   编码嗅探（HTTP charset → XML 声明 → utf-8 → gb18030/big5）
              │   发布时间解析（RFC822 / ISO / 「3分钟前」等中文相对时间）
              ▼
   清洗与归类    HTML 去标签 → URL 指纹 + 标题指纹去重
              │    超期过滤（早于 NEWS_MAX_AGE_HOURS=72 小时直接丢弃）
              │    关键词打分归类到 9 个频道（标题命中 3 分，摘要命中 1 分）
              ▼
   增量入库 MySQL  url_hash 唯一索引兜底，重复记录冲突即跳过
              ▼
   正文补全（可选）零依赖 HTMLParser 提取正文 + og:image 封面
              ▼
   失效 Redis 列表缓存 → 前端下一次刷新即可见
```

### 内置来源

| 来源 | 类型 | 落点频道 | 说明 |
|---|---|---|---|
| 央视新闻 | JSONP × 6 | 头条 / 国内 / 社会 / 国际 / 科技 / 娱乐 | 更新最快（5 分钟内），自带摘要和封面图 |
| 中新网 | RSS × 8 | 头条 / 国内 / 社会 / 国际 / 财经 / 体育 / 娱乐 | 条目多，正文需要二次抓取 |
| IT之家 / 雷锋网 / 开源中国 / 少数派 | RSS × 4 | 科技 | 垂直科技资讯 |
| 华尔街见闻 / 界面新闻 | RSS × 2 | 财经 | 财经资讯 |
| 今日头条热榜 | JSONP × 1 | 头条 | **默认关闭**：只有标题，没有正文和图片 |

来源清单定义在 `backend/services/news_sources.py`，运行时可通过
`GET /api/news/sources` 查看当前实际启用的来源。

## 技术栈

| 类别 | 技术 | 用途 |
|---|---|---|
| Web 框架 | FastAPI | 后端 API 框架 |
| AI 引擎 | LangGraph | 智能体编排 |
| LLM | DeepSeek | 大语言模型 |
| 视觉模型 | Ollama (qwen3-vl:4b-instruct-q4_K_M) | 图片场景理解、OCR 与视觉上下文提取 |
| 嵌入模型 | Ollama (qwen3-embedding:0.6b) | 文本向量化 |
| 向量存储 | Redis (RediSearch) | 向量索引与检索 |
| 缓存 | Redis | 数据缓存 |
| 数据库 | MySQL + aiomysql | 持久化数据存储 |
| 会话存储 | PostgreSQL + LangGraph Checkpoint | 对话状态持久化 |
| ORM | SQLAlchemy 2.0 | 异步 ORM |
| 迁移 | Alembic | 数据库版本管理 |
| 搜索引擎 | SearXNG | 互联网搜索 |
| 新闻采集 | httpx + 标准库 xml/html 解析 | 实时新闻抓取（无额外依赖） |
| 日志 | loguru | 分级、按天轮转、接管标准库日志 |
| 前端 | Vue 3 + Vant + Vite | 移动端 Web 界面 |

## 环境要求

- Python 3.12+
- Node.js 20.19+ 或 22.12+（Vite 7 的要求，Node 18 跑不起来前端）
- Docker Desktop（推荐，包含 MySQL、Redis、Redis Stack、PostgreSQL、SearXNG）
- Ollama（本地模型，按需拉取）：
  - `qwen3-embedding:0.6b` — 文本向量化（必需）
  - `qwen3-vl:4b-instruct-q4_K_M` — 图片理解（可选，不用图片对话可以不拉）
- DeepSeek API Key

## 快速开始

### 1. 克隆项目

```bash
git clone https://github.com/Hg-lamp/Toutiao-agentic-rag.git
cd Toutiao-agentic-rag
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，至少填写 DEEPSEEK_API_KEY
```

### 3. 安装依赖

```bash
# 后端
pip install -r requirements.txt

# 前端
cd fronted && npm install && cd ..
```

> `langgraph-prebuilt` 已经在 `requirements.txt` 里钉死在 `1.0.7`。
> 不要手动升级到 `>=1.0.8`：那个版本会从 `langgraph.runtime` 导入
> `ExecutionInfo`，而 `langgraph` 1.0.7 没有这个符号，会导致
> `from langgraph.prebuilt import ToolNode` 直接 ImportError。

### 4. 启动基础设施

```bash
# 用 Docker 一键起依赖服务最省事
docker compose up -d mysql redis-cache redis-vector postgres searxng

# 再在宿主机拉起 Ollama 模型
ollama pull qwen3-embedding:0.6b
ollama pull qwen3-vl:4b-instruct-q4_K_M   # 可选，图片对话需要
```

各服务的连接信息：

| 服务 | 地址 |
|---|---|
| MySQL | `root:root@localhost:3306/news_app`（utf8mb4） |
| Redis 缓存 | `localhost:6379` |
| Redis 向量 | `localhost:6380`（需带 RediSearch 模块） |
| PostgreSQL | `postgres:postgres@localhost:5432/langgraph_db` |
| SearXNG | `localhost:8080` |
| Ollama | `localhost:11434` |

### 5. 执行数据库迁移（必须）

```bash
alembic upgrade head
```

> **这一步不能跳过。** 实时新闻给 `news` 表新增了
> `source` / `source_url` / `url_hash` / `is_live` / `fetched_at` 五个字段，
> 不迁移的话 `/api/news/list`、`/latest`、`/detail` 会全部报
> `OperationalError: no such column: news.source`（HTTP 500）。

### 6. 启动服务

如果要用 `sandbox_echo` 验证 MCP 沙箱链路，先构建最小沙箱镜像：

```bash
docker build -f sandbox/Dockerfile -t toutiao-agentic-rag-sandbox:dev .
```

当前可用两个沙箱验证工具：

- `sandbox_echo`：回显文本，用于验证 MCP stdio 链路。
- `sandbox_run_command`：仅允许 `pwd`、`id`、`python_version`，用于验证沙箱内子进程执行。

第一阶段需要让后端和 `SandboxBroker` 运行在 WSL 或宿主机进程中，因为
Broker 需要调用 Docker CLI 创建临时容器。当前后端 Docker 镜像内部没有
Docker CLI 和 Docker Socket，所以暂不支持在 `backend` 容器内创建沙箱。

```bash
# 后端
uvicorn backend.main:app --reload --host localhost --port 8000
# 也可以直接 python 启动（backend/main.py 已处理 sys.path 与 .env 路径）
# python backend/main.py

# 前端（另开一个终端）
cd fronted
npm run dev
```

后端起来之后**不需要任何手工操作**，后台会自动开始抓取当日新闻，
日志里会看到 `[news]` 开头的采集记录。

### 7. 确认采集正常

```bash
curl http://localhost:8000/api/news/status
# 关注 today_news（当天入库条数，应为正数）与 latest_publish_time（应为当天）
```

### Docker 部署

```bash
# 配置 API Key 和 SearXNG 密钥
cp .env.example .env
# 编辑 .env，至少填写 DEEPSEEK_API_KEY

# 构建后端镜像并启动基础设施和 API
docker compose up -d --build

# 首次启动后执行数据库迁移（env.py 已支持读容器内的 DATABASE_URL）
docker compose exec backend alembic upgrade head

# 查看服务状态和日志
docker compose ps
docker compose logs -f backend

# 停止服务（保留数据卷）
docker compose down
```

Docker Compose 会启动 MySQL、Redis 缓存、Redis Stack 向量库、PostgreSQL
Checkpoint、SearXNG 和后端 API。首次启动后仍需在宿主机启动 Ollama，并执行：

```bash
ollama pull qwen3-embedding:0.6b
ollama pull qwen3-vl:4b-instruct-q4_K_M   # 可选
```

> 容器内的代码是 `COPY . .` 打进镜像的，改完代码要
> `docker compose up -d --build` 才会生效，单纯 `restart` 不会带上新代码。

### 访问地址

| 地址 | 说明 |
|---|---|
| http://localhost:5173 | 前端页面（`npm run dev` 默认端口） |
| http://localhost:8000 | API 服务 |
| http://localhost:8000/docs | Swagger 文档 |
| http://localhost:8000/redoc | ReDoc 文档 |
| http://localhost:8080 | SearXNG 搜索服务 |

> 前端后端地址写在 `fronted/src/config/api.js`（默认 `http://127.0.0.1:8000`），
> 后端不在本机时改这个文件即可。

## 智能体流程

```
用户输入
  │
  ├── 文件上传（可选）
  │   └── 前端上传 → 后端解析文本 → 注入到对话消息
  │
  └── 父图（Parent Graph）—— ReAct 循环
      │
      START → llm_node → router
                    │         │
                    │    ┌────┴────┐
                    │    ▼         ▼
                    │ tool_node  __end__
                    │    │
                    └────┘
      │
      ├── llm_node（DeepSeek 模型 + 系统提示词）
      │   ├── 判断是否需要调用工具
      │   │   ├── searxng_search_engine → 互联网搜索（SearXNG）
      │   │   ├── rag_search → 公考知识库检索（Redis 向量）
      │   │   ├── calculator → 数学表达式计算
      │   │   └── agent → 子任务分发 → 子图 ReAct 循环
      │   │
      │   └── 直接回答用户
      │
      └── ReAct 循环（recursion_limit 100）
          └── LLM 调用工具 → 工具返回结果 → LLM 推理 → ...
```

### 子图（Child Graph）

由 `agent` 工具触发的独立子图，拥有独立的 ReAct 循环：

```
START → llm_node → router → tool_node → llm_node → ...
                        ↓
                      __end__ → 返回结果给父图
```

### 流程说明

| 节点 | 说明 |
|---|---|
| `llm_node` | 调用 DeepSeek 模型，系统提示词定义角色（鼠鼠）、回答规范、工具使用方式 |
| `router` | 检查 LLM 输出是否包含 tool_calls，有则进入工具节点，无则结束 |
| `tool_node` | 执行 LLM 选择的工具，返回结果给 LLM 进行下一轮推理 |
| `child_graph` | 由 `agent` 工具触发的独立子图，处理复杂子任务后返回结果 |

## 目录结构

```
Toutiao-agentic-rag/
├── backend/
│   ├── agent/              # LangGraph 智能体
│   │   ├── agent_graph.py  # 主图（父图）
│   │   └── child_graph.py  # 子图
│   ├── cache/              # Redis 缓存
│   │   └── news_cache.py   # 新闻缓存 + 采集后失效列表/分类缓存
│   ├── config/             # 配置文件
│   │   ├── llm_config.py       # LLM 配置
│   │   ├── mysql_config.py     # MySQL / PostgreSQL 配置
│   │   ├── prompt_template.py  # 提示词模板
│   │   ├── embeddings.py       # 嵌入模型配置
│   │   ├── redis_vector.py     # 向量存储配置
│   │   ├── graph_config.py     # LangGraph 配置
│   │   ├── cache_config.py     # Redis 缓存配置
│   │   ├── upload_config.py    # 上传类型与大小限制
│   │   ├── vision_config.py    # 视觉模型配置与提示词
│   │   ├── logging_config.py   # 统一日志（轮转 + 接管标准库）
│   │   ├── news_config.py      # 实时新闻配置
│   │   └── search_engine.py    # SearXNG 搜索配置
│   ├── crud/               # 数据库 CRUD
│   ├── models/             # SQLAlchemy 模型
│   ├── routers/            # API 路由
│   │   ├── ai_chat.py      # AI 聊天、文件与图片附件、会话
│   │   ├── news.py         # 新闻（含实时采集的 status/refresh/sources）
│   │   ├── users.py        # 用户
│   │   ├── favorite.py     # 收藏
│   │   └── history.py      # 历史
│   ├── schemas/            # Pydantic 模型
│   ├── services/           # 业务服务
│   │   ├── rag.py                # RAG 检索
│   │   ├── tools.py              # 工具定义与执行
│   │   ├── file_parser.py        # 文档解析（TXT/MD/CSV/PDF/DOCX/XLSX）
│   │   ├── attachment_service.py # 聊天图片附件落盘与校验
│   │   ├── vision_service.py     # 调用 Ollama 视觉模型
│   │   ├── vision_context.py     # 视觉结果转对话上下文
│   │   ├── news_sources.py       # 实时新闻来源清单
│   │   ├── news_fetcher.py       # 多源抓取与解析
│   │   ├── news_classifier.py    # 频道归类
│   │   ├── news_pipeline.py      # 去重入库流水线
│   │   └── news_scheduler.py     # 定时调度
│   ├── uploads/            # 上传文件（avatars/ 头像、ai/ 聊天图片）
│   └── utils/              # 工具函数
│       ├── auth.py         # JWT 与密码校验
│       └── html_text.py    # 零依赖 HTML 正文提取
├── alembic/                # 数据库迁移
│   └── versions/           # 迁移脚本（head = d4e5f6a7b8c9）
├── docs/                   # 实时新闻等专题文档
├── searxng/                # SearXNG 配置
├── fronted/                # Vue 3 前端
│   ├── src/config/api.js   # 后端地址与各模块端点
│   └── src/utils/news.js   # 新闻字段归一化与时间格式化
├── docker-compose.yml      # Docker 编排
├── Dockerfile              # 镜像构建
├── requirements.txt        # Python 依赖
└── logs/                   # 运行日志（已 gitignore）
```

## API 接口

### 新闻

| 端点 | 参数 | 说明 |
|---|---|---|
| `GET /api/news/categories` | —— | 获取分类列表 |
| `GET /api/news/list` | `categoryId`（0=全部）、`page`、`pageSize` | 分页列表，按发布时间倒序 |
| `GET /api/news/latest` | `categoryId`、`limit`(1–50) | 最新新闻，用于「实时」首屏 |
| `GET /api/news/detail` | `id` | 详情（浏览量 +1，附相关新闻） |
| `GET /api/news/status` | —— | 采集运行状态：当天条数、各频道条数、调度器、最近一轮结果 |
| `POST /api/news/refresh` | `wait`、`token` | 手动触发一次抓取；`wait=false` 转后台执行 |
| `GET /api/news/sources` | —— | 当前启用的来源清单（排查某个源是否失效） |

### 其它模块

| 模块 | 端点 | 说明 |
|---|---|---|
| 用户 | `POST /api/user/register` | 注册 |
| 用户 | `POST /api/user/login` | 登录 |
| 用户 | `GET /api/user/info` | 获取用户信息 |
| 用户 | `PUT /api/user/update` | 更新用户信息 |
| 用户 | `PUT /api/user/password` | 修改密码 |
| 用户 | `POST /api/user/avatar` | 上传头像 |
| 收藏 | `GET /api/favorite/check` | 检查收藏状态 |
| 收藏 | `POST /api/favorite/add` | 添加收藏 |
| 收藏 | `DELETE /api/favorite/remove` | 取消收藏 |
| 收藏 | `GET /api/favorite/list` | 收藏列表 |
| 收藏 | `DELETE /api/favorite/clear` | 清空收藏 |
| 历史 | `POST /api/history/add` | 添加历史记录 |
| 历史 | `GET /api/history/list` | 历史记录列表 |
| 历史 | `DELETE /api/history/delete/{history_id}` | 删除单条历史记录 |
| 历史 | `DELETE /api/history/clear` | 清空历史记录 |
| AI | `POST /api/ai/chat` | AI 聊天（SSE 流式） |
| AI | `GET /api/ai/conversations` | 当前用户的会话列表 |
| AI | `POST /api/ai/aicreate/conversations` | 创建会话 |
| AI | `GET /api/ai/conversations/{id}/messages` | 获取会话消息 |
| AI | `DELETE /api/ai/conversations/{id}` | 删除会话 |
| 文件 | `POST /api/ai/upload` | 解析文件并返回文本（5MB 限制） |
| 文件 | `POST /api/ai/attachments` | 上传聊天图片附件，发送消息时调用视觉模型 |
| 文件 | `DELETE /api/ai/attachments/{attachment_id}` | 删除当前用户的待发送图片附件 |
| 文件 | `POST /api/ai/rag-upload` | 上传文件并写入当前用户知识库 |

## 环境变量

### 核心服务

| 变量 | 说明 | 默认值 |
|---|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek API Key | 必填 |
| `DATABASE_URL` | MySQL 数据库 URL | `mysql+aiomysql://root:root@localhost:3306/news_app?charset=utf8mb4` |
| `CHECKPOINTER_DATABASE_URL` | PostgreSQL 连接 URL（LangGraph 会话存储） | `postgresql://postgres:postgres@localhost:5432/langgraph_db` |
| `REDIS_HOST` | Redis 缓存主机 | `localhost` |
| `REDIS_PORT` | Redis 缓存端口 | `6379` |
| `REDIS_DB` | Redis 缓存数据库编号 | `0` |
| `REDIS_VECTOR_URL` | 向量存储 Redis URL | `redis://localhost:6380` |
| `SEARXNG_HOST` | SearXNG 搜索引擎地址 | `http://localhost:8080` |
| `SEARXNG_SECRET_KEY` | SearXNG 密钥 | 可选 |
| `DB_ECHO` | 打印 SQL 日志（排查用） | `false` |

### 视觉模型

| 变量 | 说明 | 默认值 |
|---|---|---|
| `OLLAMA_BASE_URL` | Ollama 服务地址 | `http://localhost:11434` |
| `VISION_MODEL` | Ollama 视觉模型 | `qwen3-vl:4b-instruct-q4_K_M` |
| `VISION_TIMEOUT` | 单张图推理超时（秒） | `180` |
| `VISION_MAX_CONCURRENCY` | 视觉模型并发数（6GB 显存建议为 1） | `1` |
| `VISION_MAX_IMAGE_SIDE` | 图片送入模型前的最长边 | `1024` |
| `VISION_NUM_CTX` | 视觉模型上下文长度 | `4096` |
| `VISION_NUM_PREDICT` | 视觉模型最大输出长度 | `768` |
| `VISION_KEEP_ALIVE` | 模型在显存中的保活时长 | `30m` |
| `AI_UPLOAD_DIR` | 聊天图片落盘目录 | `backend/uploads/ai` |

### 实时新闻

| 变量 | 说明 | 默认值 |
|---|---|---|
| `NEWS_REALTIME_ENABLED` | 实时新闻总开关（`false` 完全关闭采集） | `true` |
| `NEWS_REFRESH_ON_STARTUP` | 后端启动时立刻抓一次 | `true` |
| `NEWS_REFRESH_INTERVAL_MINUTES` | 增量刷新间隔（分钟） | `30` |
| `NEWS_DAILY_REFRESH_HOUR` | 每日全量刷新时刻（0–23） | `7` |
| `NEWS_MAX_AGE_HOURS` | 只收录最近 N 小时的新闻 | `72` |
| `NEWS_RETENTION_DAYS` | 采集数据保留天数，超期自动清理 | `30` |
| `NEWS_MAX_ITEMS_PER_SOURCE` | 每个来源单次最多取多少条 | `30` |
| `NEWS_ENRICH_ENABLED` | 是否抓原文页补全正文与封面 | `true` |
| `NEWS_ENRICH_MAX_PER_RUN` | 每轮最多补全多少篇正文 | `30` |
| `NEWS_FETCH_TIMEOUT` | 单请求超时（秒） | `12` |
| `NEWS_FETCH_CONCURRENCY` | 抓取并发数 | `6` |
| `NEWS_REFRESH_TOKEN` | `POST /api/news/refresh` 的令牌，留空不校验 | 空 |
| `NEWS_REFRESH_COOLDOWN_SECONDS` | 两次手动刷新的最小间隔（秒） | `60` |
| `NEWS_DISABLED_SOURCES` | 临时停用某些来源（用 key，逗号分隔） | 空 |
| `NEWS_ENABLED_SOURCES` | 打开默认关闭的来源，如 `toutiao-hot` | 空 |
| `NEWS_SEARXNG_CHANNELS` | 用 SearXNG 搜频道补薄弱频道，如 `军事` | 空 |
| `NEWS_HTTP_PROXY` | 访问新闻源需要的代理，如 `http://127.0.0.1:7890` | 空 |
| `NEWS_USER_AGENT` | 抓取时使用的 User-Agent | 内置浏览器 UA |

### 日志

| 变量 | 说明 | 默认值 |
|---|---|---|
| `LOG_TO_FILE` | 是否写本地日志文件（Docker 里建议 `false`） | `true` |
| `LOG_DIR` | 日志目录（相对路径以项目根为基准） | `logs` |
| `LOG_LEVEL` | 日志级别 | `INFO` |
| `LOG_ROTATION` | 单文件轮转阈值 | `20 MB` |
| `LOG_RETENTION` | 历史文件保留时长 | `14 days` |
| `LOG_COMPRESSION` | 轮转后压缩格式 | `zip` |

更多采集配置与排查方式见 [docs/NEWS_REALTIME.md](docs/NEWS_REALTIME.md#五配置项)。

> 本地运行（`uvicorn`）时上面所有变量都从 `.env` 直接生效；
> Docker 部署时 `docker-compose.yml` 只透传了
> `NEWS_REALTIME_ENABLED` / `NEWS_REFRESH_INTERVAL_MINUTES` /
> `NEWS_DAILY_REFRESH_HOUR` / `NEWS_REFRESH_TOKEN` / `NEWS_SEARXNG_CHANNELS`，
> 其余变量容器内用代码默认值（与 `.env.example` 一致）。
> 想在容器里改这些值，需要在 `docker-compose.yml` 的 `backend.environment` 里补一行。

## 数据库架构

### MySQL（业务数据）
- `user` — 用户表
- `user_token` — 登录令牌表
- `news` — 新闻表（含 `source` / `source_url` / `url_hash` / `is_live` / `fetched_at` 实时采集字段）
- `news_category` — 新闻频道表（9 个频道）
- `favorite` — 收藏表
- `history` — 浏览历史表
- `conversations` — AI 会话元信息表
- `messages` — AI 消息记录表
- `memory` — 用户长期记忆表

### PostgreSQL（LangGraph Checkpoint）
- `checkpoints` — 会话状态快照（自动管理，含完整消息历史）
- `checkpoint_writes` — 节点写入记录（自动管理）
- `checkpoint_blobs` — 大对象存储（自动管理）

> 图状态由 LangGraph Checkpoint 管理；消息列表同时写入 MySQL，便于会话历史分页读取。

### 迁移版本

```
cd7c3f3aeb52   (初始建表)
   └─ a1b2c3d4e5f6
        └─ b2c3d4e5f6a7
             └─ d4e5f6a7b8c9   ← head：实时新闻字段与索引
```

新增索引：`idx_news_url_hash`（唯一，去重兜底）、`idx_news_category_publish`（列表查询）。

## 日志

统一由 `backend/config/logging_config.py` 配置，在 `backend/main.py` 最早执行：

- 本地：控制台彩色输出 + `logs/backend_YYYY-MM-DD.log`，按 20 MB 轮转、保留 14 天、压缩为 zip
- Docker：`docker-compose.yml` 里 `LOG_TO_FILE` 兜底为 `false`，日志只走容器日志，
  用 `docker compose logs -f backend` 查看；如果 `.env` 里显式写了 `true`，
  容器内也会写 `/app/logs`，但该目录没有挂卷，重建容器就没了
- 已接管 `uvicorn` / `uvicorn.error` / `uvicorn.access` / `sqlalchemy` / `aiomysql` 的标准库日志

采集相关日志都带 `[news]` 前缀，几个关键行：

```
[news] 实时新闻调度器已启动（间隔 30 分钟，每日 7 点，启用来源 20 个）
[news] 来源 央视新闻 抓到 30 条
[news] 刷新完成(startup): 抓取 570 / 入库 451 / 去重 80 / 过期 39 / 耗时 29.2s
[news] news 表缺少实时采集字段，请先执行 alembic upgrade head   ← 出现这行说明没迁移
```

## 文件上传功能

支持上传文件类型：
- `.txt` / `.md` — 纯文本
- `.csv` — CSV 表格（自动格式化对齐）
- `.pdf` — PDF 文档（自动提取文本）
- `.docx` — Word 文档（自动提取文本）
- `.xlsx` — Excel 表格（自动提取所有工作表）
- `.jpg` / `.jpeg` / `.png` / `.webp` / `.bmp` — 图片场景理解与 OCR

限制：
- 文档单文件最大 5MB，图片单文件最大 10MB
- 解析文本最大 10 万字（超出截断）
- 单次聊天最多附带 2 张图片
- 聊天图片保存在 `backend/uploads/ai/{user_id}`，用于消息历史和预览
- 文本文件上传后不存盘，内容直接注入对话上下文

## 开发计划

- [x] 用户注册/登录
- [x] 新闻 CRUD
- [x] **实时新闻自动采集（多源聚合 + 定时更新 + 去重 + 自动归类）**
- [x] 收藏 / 历史记录
- [x] Agentic RAG 智能体
- [x] 异步高并发（async/await + ainvoke）
- [x] Docker 容器化部署
- [x] Alembic 数据库迁移
- [x] 文件上传与解析
- [x] 图片对话理解（本地视觉模型 + OCR）
- [x] 统一日志（文件轮转 + 容器日志）
- [x] 为工具节点添加缓存机制
- [x] 会话管理（列表/删除/消息历史）
- [x] 用户档案提炼（Memory 系统）
- [ ] Skill 路由系统（向量匹配）
- [ ] 上下文超限检测与提示
- [ ] 单元测试 / 集成测试
- [ ] 更多工具函数
- [ ] 优化「我的」界面的效果

## 许可证

MIT
