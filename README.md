# 新闻资讯 AI 平台

**FastAPI + LangGraph + LangChain** 构建的 Agentic RAG 新闻资讯 AI 平台。

> 项目需求与验收标准见 [REQUIREMENTS.md](REQUIREMENTS.md)。
> 实时新闻采集的完整方案见 [docs/NEWS_REALTIME.md](docs/NEWS_REALTIME.md)。

## 功能特性

- **新闻浏览** — 分类、列表、详情
- **实时新闻** — 后台自动采集当日新闻，无需人工灌数据
  - 21 个实测可用的新闻源（央视新闻、中新网、IT之家、华尔街见闻等）
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
| 前端 | Vue.js (Vant UI) | 移动端 Web 界面 |

## 环境要求

- Python 3.12+
- Docker Desktop（推荐，包含 MySQL、Redis、Redis Stack、PostgreSQL、SearXNG）
- Ollama（本地嵌入模型 `qwen3-embedding:0.6b`）
- DeepSeek API Key

## 快速开始

### 本地运行

```bash
# 1. 克隆项目
git clone https://github.com/Hg-lamp/Toutiao_Test.git
cd Toutiao_Test

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env 填入 API Key

# 3. 安装依赖
pip install -r requirements.txt

# 4. 确保 MySQL、Redis、PostgreSQL、Ollama、SearXNG 就绪
#    MySQL: root:root@localhost:3306/news_app (utf8mb4)
#    Redis: localhost:6379（缓存）+ localhost:6380（向量）
#    PostgreSQL: postgres:postgres@localhost:5432/langgraph_db

# 5. 执行数据库迁移（实时新闻需要这一步新增字段，必须先执行）
alembic upgrade head

# 6. 启动服务
uvicorn backend.main:app --reload --host localhost --port 8000

# 启动后无需其它操作：后台会自动开始抓取当日新闻，
# 日志里会看到 [news] 开头的采集记录。想立刻确认可以去：
#   curl http://localhost:8000/api/news/status
```

### Docker 部署

```bash
# 配置 API Key 和 SearXNG 密钥
cp .env.example .env
# 编辑 .env，至少填写 DEEPSEEK_API_KEY

# 构建后端镜像并启动基础设施和 API
docker compose up -d --build

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
```

### 访问地址

| 地址 | 说明 |
|---|---|
| http://localhost:8000 | API 服务 |
| http://localhost:8000/docs | Swagger 文档 |
| http://localhost:8000/redoc | ReDoc 文档 |
| http://localhost:8080 | SearXNG 搜索服务 |

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
Toutiao_course/
├── backend/
│   ├── agent/              # LangGraph 智能体
│   │   ├── agent_graph.py  # 主图（父图）
│   │   └── child_graph.py  # 子图
│   ├── cache/              # Redis 缓存
│   │   └── news_cache.py   # 新闻缓存 + 采集后失效
│   ├── config/             # 配置文件
│   │   ├── llm_config.py   # LLM 配置
│   │   ├── mysql_config.py # MySQL 数据库配置
│   │   ├── prompt_template.py  # 提示词模板
│   │   ├── embeddings.py   # 嵌入模型配置
│   │   ├── redis_vector.py # 向量存储配置
│   │   ├── graph_config.py # LangGraph 配置
│   │   ├── cache_config.py # Redis 缓存配置
│   │   ├── news_config.py  # 实时新闻配置
│   │   └── search_engine.py # SearXNG 搜索配置
│   ├── crud/               # 数据库 CRUD
│   ├── models/             # SQLAlchemy 模型
│   ├── routers/            # API 路由
│   │   ├── ai_chat.py      # AI 聊天、文件与会话
│   │   ├── news.py         # 新闻（含实时采集的 status/refresh/sources）
│   │   ├── users.py        # 用户
│   │   ├── favorite.py     # 收藏
│   │   └── history.py      # 历史
│   ├── schemas/            # Pydantic 模型
│   ├── services/           # 业务服务
│   │   ├── rag.py          # RAG 检索
│   │   ├── tools.py        # 工具定义与执行
│   │   ├── news_sources.py     # 实时新闻来源清单
│   │   ├── news_fetcher.py     # 多源抓取与解析
│   │   ├── news_classifier.py  # 频道归类
│   │   ├── news_pipeline.py    # 去重入库流水线
│   │   └── news_scheduler.py   # 定时调度
│   └── utils/              # 工具函数
│       └── html_text.py    # 零依赖 HTML 正文提取
├── alembic/                # 数据库迁移
├── docs/                   # 实时新闻等专题文档
├── searxng/                # SearXNG 配置
├── fronted/                # Vue.js 前端
│   └── src/utils/news.js   # 新闻字段归一化与时间格式化
├── docker-compose.yml      # Docker 编排
├── Dockerfile              # 镜像构建
└── requirements.txt        # Python 依赖
```

## API 接口

| 模块 | 端点 | 说明 |
|---|---|---|
| 新闻 | `GET /api/news/categories` | 获取分类列表 |
| 新闻 | `GET /api/news/list` | 获取新闻列表（分页，按发布时间倒序） |
| 新闻 | `GET /api/news/latest` | 获取最新新闻（首屏「实时」） |
| 新闻 | `GET /api/news/detail` | 获取新闻详情 |
| 新闻 | `GET /api/news/status` | 实时采集运行状态（最近更新时间、各频道条数） |
| 新闻 | `POST /api/news/refresh` | 手动触发一次实时抓取 |
| 新闻 | `GET /api/news/sources` | 当前启用的新闻来源清单 |
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

| 变量 | 说明 | 默认值 |
|---|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek API Key | 必填 |
| `DATABASE_URL` | MySQL 数据库 URL | `mysql+aiomysql://root:root@localhost:3306/news_app` |
| `CHECKPOINTER_DATABASE_URL` | PostgreSQL 连接 URL（LangGraph 会话存储） | `postgresql://postgres:postgres@localhost:5432/langgraph_db` |
| `REDIS_HOST` | Redis 缓存主机 | `localhost` |
| `REDIS_PORT` | Redis 缓存端口 | `6379` |
| `REDIS_DB` | Redis 缓存数据库编号 | `0` |
| `REDIS_VECTOR_URL` | 向量存储 Redis URL | `redis://localhost:6380` |
| `OLLAMA_BASE_URL` | Ollama 服务地址 | `http://localhost:11434` |
| `VISION_MODEL` | Ollama 视觉模型 | `qwen3-vl:4b-instruct-q4_K_M` |
| `VISION_MAX_CONCURRENCY` | 视觉模型并发数（6GB 显存建议为 1） | `1` |
| `VISION_MAX_IMAGE_SIDE` | 图片送入模型前的最长边 | `1024` |
| `SEARXNG_HOST` | SearXNG 搜索引擎地址 | `http://localhost:8080` |
| `SEARXNG_SECRET_KEY` | SearXNG 密钥 | 可选 |
| `NEWS_REALTIME_ENABLED` | 实时新闻总开关 | `true` |
| `NEWS_REFRESH_INTERVAL_MINUTES` | 增量刷新间隔（分钟） | `30` |
| `NEWS_DAILY_REFRESH_HOUR` | 每日全量刷新时刻 | `7` |
| `NEWS_MAX_AGE_HOURS` | 只收录最近 N 小时的新闻 | `72` |
| `NEWS_RETENTION_DAYS` | 采集数据保留天数 | `30` |
| `NEWS_REFRESH_TOKEN` | 手动触发采集的令牌 | 可选 |

> 完整配置项（正文补全、并发、代理、来源开关等）见
> [docs/NEWS_REALTIME.md](docs/NEWS_REALTIME.md#五配置项)。

## 数据库架构

### MySQL（业务数据）
- `user` — 用户表
- `news` — 新闻表（含 `source` / `source_url` / `url_hash` / `is_live` / `fetched_at` 实时采集字段）
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

## 文件上传功能

支持上传文件类型：
- `.txt` / `.md` — 纯文本
- `.csv` — CSV 表格（自动格式化对齐）
- `.pdf` — PDF 文档（自动提取文本）
- `.docx` — Word 文档（自动提取文本）
- `.xlsx` — Excel 表格（自动提取所有工作表）
- `.jpg` / `.jpeg` / `.png` / `.webp` / `.bmp` — 图片场景理解与 OCR

限制：
- 单文件最大 5MB
- 解析文本最大 10 万字（超出截断）
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
- [x] 为工具节点添加缓存机制
- [x] 会话管理（列表/删除/消息历史）
- [ ] Skill 路由系统（向量匹配）
- [x] 用户档案提炼（Memory 系统）
- [ ] 上下文超限检测与提示
- [ ] 单元测试 / 集成测试
- [ ] 更多工具函数
- [ ] 优化‘我的’界面的效果

## 许可证

MIT
