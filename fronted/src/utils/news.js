/**
 * 新闻工具函数：字段归一化 + 时间格式化。
 *
 * 为什么需要它：
 * 后端的新闻接口历史上返回的是 ORM 的 snake_case（`publish_time`），
 * 而卡片上读的是 `publishTime`，两边对不上，导致界面上发布时间一直是空白。
 * 收藏/历史接口又走的是 Pydantic 别名（`publishedTime`）。
 * 这里统一把三种写法都收敛成 `publishTime`，前端任何地方拿到的新闻对象
 * 结构都是一致的。
 */

/** 把后端返回的新闻对象归一化成前端统一结构（camelCase）。 */
export function normalizeNews(raw) {
  if (!raw || typeof raw !== 'object') return raw

  const publishTime =
    raw.publishTime ?? raw.publish_time ?? raw.publishedTime ?? raw.published_time ?? null

  return {
    ...raw,
    id: raw.id ?? raw.news_id ?? raw.newsId,
    categoryId: raw.categoryId ?? raw.category_id,
    categoryName: raw.categoryName ?? raw.category_name ?? null,
    publishTime: normalizeTimeString(publishTime),
    source: raw.source ?? null,
    sourceUrl: raw.sourceUrl ?? raw.source_url ?? null,
    isLive: Boolean(raw.isLive ?? raw.is_live),
  }
}

/** 列表/详情批量归一化。 */
export function normalizeNewsList(list) {
  return Array.isArray(list) ? list.map(normalizeNews) : []
}

/**
 * 把后端的时间字符串转成 JS 一定能解析的格式。
 * 后端返回 "2026-09-10T19:21:25" 或 "2026-09-10 19:21:25"，
 * Safari 对后者解析不稳定，统一改成 ISO 风格。
 */
export function normalizeTimeString(value) {
  if (!value) return null
  if (typeof value !== 'string') {
    const date = new Date(value)
    return Number.isNaN(date.getTime()) ? null : date.toISOString()
  }
  return value.includes('T') ? value : value.replace(' ', 'T')
}

/**
 * 「刚刚 / 12分钟前 / 3小时前 / 昨天 08:12 / 09-08 14:30」。
 * 新闻类产品的核心是「看起来有多新」，所以相对时间比绝对时间更重要。
 */
export function formatRelativeTime(value, now = Date.now()) {
  const iso = normalizeTimeString(value)
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''

  const diffMs = now - date.getTime()
  const diffSec = Math.floor(diffMs / 1000)

  // 后端和本地时钟有偏差时，别显示「-3分钟前」
  if (diffSec < 60) return '刚刚'
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}分钟前`
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}小时前`

  const pad = (n) => String(n).padStart(2, '0')
  const clock = `${pad(date.getHours())}:${pad(date.getMinutes())}`
  const days = Math.floor(diffSec / 86400)
  if (days === 1) return `昨天 ${clock}`
  if (days < 7) return `${days}天前`
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${clock}`
}

/** 绝对时间，详情页用。 */
export function formatAbsoluteTime(value) {
  const iso = normalizeTimeString(value)
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  const pad = (n) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ` +
    `${pad(date.getHours())}:${pad(date.getMinutes())}`
}

/** 「2 分钟前更新」，用于首页顶部的新鲜度提示。 */
export function formatUpdatedAt(value) {
  const text = formatRelativeTime(value)
  return text ? `${text}更新` : ''
}
