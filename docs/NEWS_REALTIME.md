# 实时新闻改造方案

> 目标：**App 里看到的新闻不再是陈年旧闻，而是每天自动更新、分钟级新鲜的当日新闻。**
>
> 本文说明「原来为什么旧」「改了什么」「怎么用」「怎么调」。

---

## 一、问题定位：为什么原来的新闻很老

排查后确认是三个原因叠加，缺一不可：

### 1. 数据源本身是「假可达」的死源

原项目数据库里的新闻是早期手工灌进去的静态数据，没有任何自动更新机制。
即使换成 RSS，下面这些常见源也**不能**用（实测于 2026-09）：

| 来源 | HTTP 状态 | 看起来 | 实际最新一条 |
|---|---|---|---|
| 人民网 RSS ×8 个频道 | `200` + 合法 XML | ✅ 正常 | **2025-06-05**（冻结） |
| 新华网 RSS ×3 个频道 | `200` + 合法 XML | ✅ 正常 | **2022-12-14**（冻结） |
| 新浪 RSS ×9 个频道 | `200` + 合法 XML | ✅ 正常 | **2018-09-23**（冻结） |
| 澎湃 news `/rss` | `200`，60 KB | ✅ 正常 | 其实是**首页 HTML** |
| 36氪 `/feed` | `200`，17 KB | ✅ 正常 | 其实是**反爬验证页** |
| 网易 / 观察者网 RSS | `200`，275 KB | ✅ 正常 | 其实是**首页 HTML** |

**这就是坑所在**：它们全都返回 200，请求不报错，只有去解析
`pubDate` 才会发现内容已经是几年前的了。光看日志会以为一切正常。

### 2. 列表查询没有排序

```python
# 改造前 backend/crud/cache_news.py
stmt = select(News).where(News.category_id == category_id).offset(skip).limit(limit)
```

没有 `ORDER BY`，MySQL 返回的是**主键/插入顺序**，于是最早入库的老新闻
永远排在最前面 —— 分页翻到底也翻不到新内容。

### 3. 时间字段前后端对不上，界面上根本不显示时间

后端返回 ORM 对象，FastAPI 序列化出来是 snake_case：

```json
{ "publish_time": "2026-09-10T19:21:25" }
```

而前端四个页面读的都是 `publishTime`：

```vue
<span>{{ news.publishTime }}</span>   <!-- 永远是 undefined，渲染成空白 -->
```

所以用户既看不到时间，也感知不到"新"。

---

## 二、改造后的架构

```
┌──────────────────────────────────────────────────────────────────┐
│  news_scheduler（asyncio 常驻任务，挂在 FastAPI lifespan 上）      │
│   ├── 启动时立刻抓一轮（部署完就有当日新闻）                        │
│   ├── 每 NEWS_REFRESH_INTERVAL_MINUTES 分钟增量抓（默认 30 分钟）  │
│   └── 每天 NEWS_DAILY_REFRESH_HOUR 点全量抓（默认 07:00）          │
└───────────────────────────┬──────────────────────────────────────┘
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│  news_fetcher  多源并发抓取（故障隔离 + 编码安全 + 假可达检测）      │
│   ├── rss    中新网 8 个频道 RSS                                   │
│   ├── jsonp  央视网 6 个频道接口（5 分钟级，带图带摘要）             │
│   ├── json   今日头条实时热榜                                      │
│   └── rss    科技/财经垂直媒体（IT之家、少数派、华尔街见闻…）        │
└───────────────────────────┬──────────────────────────────────────┘
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│  news_fetcher.enrich_articles  正文补全                            │
│   └── RSS 只给摘要，这里再抓一次原文页，用零依赖 HTML 解析器提正文   │
└───────────────────────────┬──────────────────────────────────────┘
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│  news_classifier  频道归类                                        │
│   └── 来源频道保底 + 关键词打分纠偏 → 头条/社会/国内/国际/娱乐/      │
│       体育/军事/科技/财经（沿用原有 9 个频道，前端不用改）           │
└───────────────────────────┬──────────────────────────────────────┘
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│  news_pipeline  去重入库                                          │
│   ├── url_hash 唯一索引（sha1 归一化 URL）                        │
│   ├── 标题指纹跨来源去重（同一事件多家转载只留一条）                 │
│   ├── 超期过滤（NEWS_MAX_AGE_HOURS，默认只收 72 小时内）           │
│   ├── 超期清理（NEWS_RETENTION_DAYS，默认保留 30 天）              │
│   └── 入库后失效 Redis 列表缓存                                    │
└───────────────────────────┬──────────────────────────────────────┘
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│  MySQL news 表                                                    │
│   + source / source_url / url_hash / is_live / fetched_at         │
└───────────────────────────┬──────────────────────────────────────┘
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│  API（新增实时字段，列表按发布时间倒序）                            │
│   GET  /api/news/list    加 ORDER BY publish_time DESC            │
│   GET  /api/news/latest  首屏「最新」                             │
│   GET  /api/news/status  采集运行状态（排障入口）                  │
│   POST /api/news/refresh 手动触发一次抓取                          │
│   GET  /api/news/sources  当前启用的来源清单                       │
└───────────────────────────┬──────────────────────────────────────┘
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│  前端                                                             │
│   ├── utils/news.js：字段归一化（三种时间写法 → publishTime）       │
│   ├── 相对时间：「刚刚 / 12分钟前 / 3小时前 / 昨天 08:12」          │
│   ├── 「实时」角标 + 来源媒体名                                    │
│   ├── 每分钟静默拉最新，插到列表头部（不打断滚动）                  │
│   └── 详情页「查看原文」跳转溯源                                   │
└──────────────────────────────────────────────────────────────────┘
```

---

## 三、改造清单

### 新增文件

| 文件 | 作用 |
|---|---|
| `backend/config/news_config.py` | 实时新闻全部开关（环境变量驱动） |
| `backend/services/news_sources.py` | 新闻来源清单（实测筛选过） |
| `backend/services/news_fetcher.py` | 多源抓取 + 编码安全解码 + RSS/JSONP 解析 + 正文提纯 |
| `backend/services/news_classifier.py` | 频道归类（来源保底 + 关键词纠偏） |
| `backend/services/news_pipeline.py` | 去重、入库、缓存失效、超期清理、状态统计 |
| `backend/services/news_scheduler.py` | asyncio 定时调度 + schema 自检 |
| `backend/utils/html_text.py` | 零依赖 HTML 正文提取（标准库 `html.parser`） |
| `fronted/src/utils/news.js` | 前端新闻工具（字段归一化 + 时间格式化） |
| `alembic/versions/d4e5f6a7b8c9_add_realtime_news_columns.py` | 新增 5 个实时字段 + 2 个索引 |

### 修改文件

| 文件 | 改动 |
|---|---|
| `backend/models/news.py` | 新增 `source` / `source_url` / `url_hash` / `is_live` / `fetched_at` |
| `backend/crud/news.py`、`crud/cache_news.py` | **列表加 `ORDER BY publish_time DESC`**（关键修复） |
| `backend/routers/news.py` | 显式 camelCase 返回；新增 `/latest` `/status` `/refresh` `/sources` |
| `backend/main.py` | 加 `lifespan`，启停实时新闻调度器 |
| `backend/schemas/news_base.py` | 列表项 / 详情 / 相关推荐结构化 |
| `backend/cache/news_cache.py` | 新增 `invalidate_news_list_cache()` |
| `alembic/env.py` | `DATABASE_URL` 优先于 `alembic.ini`（容器里才能连对库） |
| `fronted/src/store/modules/news.js` | 重写（原文件 actions 结构是坏的，且字段没归一化） |
| `fronted/src/components/NewsItem.vue` | 相对时间 + 「实时」角标 + 来源名 + 破图兜底 |
| `fronted/src/views/Home.vue` | 顶部「x分钟前更新」+ 定时静默刷新 |
| `fronted/src/views/NewsDetail.vue` | 相对时间 + 来源 + 「查看原文」 |
| `fronted/src/views/Favorite.vue`、`History.vue` | 时间显示修复 |
| `fronted/src/config/api.js` | 新增 news 接口配置段 |
| `requirements.txt` | **钉住 `langgraph-prebuilt==1.0.7`**（见下方说明） |

### 顺带修掉的一个阻断性 Bug

`requirements.txt` 里 `langgraph==1.0.7` 没有钉住 `langgraph-prebuilt`，
全新 `pip install` 会装到 `langgraph-prebuilt>=1.0.8`，而它要从
`langgraph.runtime` 导入 `ExecutionInfo` —— 这个符号 langgraph 1.0.7 里没有：

```
ImportError: cannot import name 'ExecutionInfo' from 'langgraph.runtime'
```

结果是**后端根本起不来**。已在 `requirements.txt` 里钉死
`langgraph-prebuilt==1.0.7` 修复。

---

## 四、怎么用

### 1. 执行数据库迁移（必须）

```bash
alembic upgrade head
```

调度器启动时会自检 `news` 表有没有实时字段，没迁移会在日志里明确报：

```
[news] news 表缺少实时采集字段，实时新闻功能不可用。请先执行 `alembic upgrade head` 完成迁移。
```

### 2. 启动后端

```bash
uvicorn backend.main:app --reload --host localhost --port 8000
# 或
docker compose up -d --build
```

启动后**无需任何额外操作**，后台会自动开始抓取。日志形如：

```
[news] 实时新闻调度器已启动（间隔 30 分钟，每日 7 点）
[news] 来源 央视新闻 抓到 30 条
[news] 来源 中新网 抓到 30 条
[news] 正文补全成功 5/6
[news] 刷新完成(startup): 抓取 600 / 入库 483 / 去重 78 / 过期 39 / 耗时 25s
```

### 3. 验证

```bash
# 采集状态：today_news 应该是个不小的数字，latest_publish_time 应该是当天
curl http://localhost:8000/api/news/status

# 手动触发一次抓取
curl -X POST "http://localhost:8000/api/news/refresh?wait=true"

# 来源清单
curl http://localhost:8000/api/news/sources

# 最新新闻
curl "http://localhost:8000/api/news/latest?limit=5"
```

前端打开首页应该能看到：
- 顶部导航右侧有红点 + 「刚刚更新 / 12分钟前更新」
- 卡片上有「实时」角标、来源媒体名、相对时间
- 下拉刷新的内容会变

---

## 五、配置项

全部走环境变量，加在 `.env` 里即可（默认值已经能正常工作）：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `NEWS_REALTIME_ENABLED` | `true` | 总开关，设 `false` 完全回到改造前行为 |
| `NEWS_REFRESH_ON_STARTUP` | `true` | 启动时是否立刻抓一次 |
| `NEWS_REFRESH_INTERVAL_MINUTES` | `30` | 增量刷新间隔 |
| `NEWS_DAILY_REFRESH_HOUR` | `7` | 每天几点做一次全量刷新 |
| `NEWS_MAX_AGE_HOURS` | `72` | 只收最近 N 小时的新闻 |
| `NEWS_RETENTION_DAYS` | `30` | 采集数据保留天数，超期自动删 |
| `NEWS_MAX_ITEMS_PER_SOURCE` | `30` | 每个来源单次最多取多少条 |
| `NEWS_ENRICH_ENABLED` | `true` | 是否再去抓原文页补全正文 |
| `NEWS_ENRICH_MAX_PER_RUN` | `30` | 每轮最多补全多少篇正文 |
| `NEWS_FETCH_TIMEOUT` | `12` | 单请求超时（秒） |
| `NEWS_FETCH_CONCURRENCY` | `6` | 并发抓取数 |
| `NEWS_REFRESH_TOKEN` | 空 | 设置后 `/api/news/refresh` 必须带 `?token=` |
| `NEWS_DISABLED_SOURCES` | 空 | 临时停用某些来源，如 `sspai,oschina` |
| `NEWS_ENABLED_SOURCES` | 空 | 打开默认关闭的来源，如 `toutiao-hot` |
| `NEWS_SEARXNG_CHANNELS` | 空 | 用 SearXNG 补薄弱频道，见下 |
| `NEWS_HTTP_PROXY` | 空 | 需要代理时填 `http://127.0.0.1:7890` |

### 默认启用的 20 个来源

| 来源 | 类型 | 频道 | 实测新鲜度 |
|---|---|---|---|
| 央视新闻 ×6 | JSONP | 头条/国内/社会/国际/科技/娱乐 | **5～90 分钟**（带图带摘要） |
| 中新网 ×8 | RSS | 头条×2/国内/社会/国际/财经/体育/娱乐 | **0.1～1.2 小时** |
| IT之家 | RSS | 科技 | 0.2 小时，60 条 |
| 雷锋网 | RSS | 科技 | 2 小时 |
| 开源中国 | RSS | 科技 | 0.9 小时 |
| 少数派 | RSS | 科技 | 4.6 小时 |
| 华尔街见闻 | RSS | 财经 | 0.8 小时，61 条 |
| 界面新闻 | RSS | 财经 | 0.4 小时 |

其中**央视新闻**是质量最好的源：5 分钟级更新、一次 80 条、
每条都带封面图和摘要，详情页正文也能抓到。

---

## 六、已知限制与后续可选项

### 今日头条热榜默认关闭

头条热榜接口只给「标题 + 热度」，没有正文也没有配图，而且 `toutiao.com`
的文章页是 JS 渲染的，抓不到内容 —— 它的条目更像「热搜词」而不是新闻稿，
混进列表会把首屏刷成一串没有正文的一句话标题，反而拉低观感。
所以它**默认关闭**，需要的话打开：

```bash
# .env
NEWS_ENABLED_SOURCES=toutiao-hot
```

### 军事频道偏薄

实测**没有找到任何持续更新的军事专用源**：

- 中国军网 `81.cn/rss.xml` —— 归档式，item 没有 `pubDate`，日期跨度按月
- 人民网军事 / 新浪军事 RSS —— 已冻结
- 环球网军事 / 澎湃防务 / 中华网军事 —— 无可用 feed

现在的做法是**关键词分流**：中新网要闻/滚动、央视国际里
带 `军工 / 导弹 / 演习 / 航母 / 国防` 等词的稿件会被分到「军事」，
一轮大约 5～15 条，够填满一屏，但比不上其它频道的量。

**想补足的话**，项目里已经跑着 SearXNG，可以打开按频道搜索：

```bash
# .env
NEWS_SEARXNG_CHANNELS=军事,娱乐
```

它会用 `categories=news&time_range=day` 去搜「军事新闻」，把结果当来源。
默认关闭是因为这条链路依赖 SearXNG 容器和上游搜索引擎，稳定性不如直连源。

### 其它

- **中新网没有封面图**：其文章页不输出 `og:image`，站点内也没有可用的
  正文配图，所以中新网条目是纯文字卡片（央视新闻、华尔街见闻、IT之家、
  界面新闻、雷锋网的条目都带图，整体约 45% 有条目带封面）。
- **原文图片可能防盗链**：部分来源的图在浏览器里加载不出来，卡片做了破图隐藏兜底。
- **正文提纯是启发式的**：`backend/utils/html_text.py` 用标准库做正文提取，
  不引入 readability/bs4。实测 8/8 篇中新网稿件都能取到正文（268～2147 字），
  结构特别怪的页面可能只取到部分正文，这时会退化成 RSS 摘要（不会比改造前差）。
- **首次抓取耗时约 25～40 秒**（20 个来源并发 + 正文补全），
  跑在后台任务里不阻塞接口，但启动后前几十秒列表可能是空的。
  想让它更快可以先关掉正文补全：`NEWS_ENRICH_ENABLED=false`。

---

## 七、怎么加/换新闻源

只改 `backend/services/news_sources.py` 一个文件：

```python
NewsSource(
    key="my-source",              # 唯一标识，NEWS_DISABLED_SOURCES 用它
    name="某某新闻",               # 界面上显示的来源名
    url="https://example.com/rss", # feed 地址
    category="科技",               # 保底频道（必须是 9 个频道名之一）
    kind="rss",                   # rss | json | jsonp
    allow_override=False,          # 是否允许关键词纠偏
)
```

JSON / JSONP 接口再补上取值路径：

```python
NewsSource(
    key="my-api", name="某某API", url="https://example.com/api?...",
    category="头条", kind="jsonp",
    json_items_path="data.list",        # 列表节点路径，支持 a.b.c
    json_fields={
        "title": "title", "url": "url", "summary": "brief",
        "published_at": "focus_date", "image": "image",
    },
)
```

**加源前务必先验证新鲜度**，不要只看 HTTP 200：

```python
# 判断标准：Content-Type 是 xml/json、能解析出条目、且最新一条的 pubDate 在 24 小时内
```

---

## 八、验收自测记录

2026-09-10 实测（20 个来源，SQLite 环境跑通全链路）：

```
抓取 570 / 入库 451 / 去重 80 / 过期 39 / 耗时 29.2s

频道分布：头条 37  社会 61  国内 40  国际 53  娱乐 35
          体育 29  军事  5  科技 109  财经 82
当日新闻 today_news = 346

封面图覆盖 45%  正文平均 163 字（补全后中新网稿件 268～2147 字，8/8 成功）

GET /api/news/list?categoryId=1  ->  200
  {"id":139,"title":"青海发布冬虫夏草野生与人工鉴别技术攻关新成果",
   "description":"中新社西宁9月10日电 (祁增蓓)第四届中国质量万里行…",
   "publishTime":"2026-09-10T19:43:41","source":"中新网","isLive":true}

GET /api/news/detail?id=139      ->  200
  content 为真实正文  sourceUrl 指向中新网原文  relatedNews 5 条

GET /api/news/status             ->  200  today_news=346
POST /api/news/refresh?wait=true ->  200  刷新完成
GET /api/news/sources            ->  200  20 个来源
```

前端（`vite build` 因环境限制了 npm 远程拉包未能执行，
已用 `node --check` 校验全部改动的 JS 模块与各 `.vue` 的 `<script setup>` 语法）。
