import { defineStore } from 'pinia'
import axios from 'axios'
import { apiConfig, newsConfig } from '../../config/api'
import { normalizeNews, normalizeNewsList } from '../../utils/news'

const PAGE_SIZE = 10
// 列表页自动刷新间隔：新闻是分钟级产品，3 分钟足够「实时」
const AUTO_REFRESH_MS = 3 * 60 * 1000

export const useNewsStore = defineStore('news', {
  state: () => ({
    newsList: [],
    newsDetail: {},
    categories: [],
    currentCategory: 1,
    page: 0,
    total: 0,
    loading: false,
    refreshing: false,
    finished: false,
    categoriesLoading: false,
    // 最近一次成功拿到数据的时间，用于「x分钟前更新」提示
    lastUpdatedAt: null,
    // 后端采集状态（/api/news/status），失败时为 null
    liveStatus: null,
    autoRefreshTimer: null
  }),

  getters: {
    hasData: (state) => state.newsList.length > 0,
    getCategoryName: (state) => (categoryId) => {
      const category = state.categories.find(item => item.id === categoryId)
      return category ? category.name : '未知'
    }
  },

  actions: {
    // 获取新闻分类
    async getCategories() {
      if (this.categoriesLoading) return

      this.categoriesLoading = true

      try {
        const response = await axios.get(newsConfig.categoriesEndpoint)

        if (response.data && response.data.code === 200) {
          this.categories = [...response.data.data, { id: 10, name: '更多' }]

          // 如果没有设置当前分类，则设置为第一个分类
          if (!this.currentCategory && this.categories.length > 0) {
            this.currentCategory = this.categories[0].id
          }
        }
      } catch (error) {
        console.error('获取新闻分类失败:', error)
        // 设置默认分类，以防API请求失败
        this.categories = [
          { id: 1, name: '头条' },
          { id: 2, name: '社会' },
          { id: 3, name: '国内' },
          { id: 4, name: '国际' },
          { id: 5, name: '娱乐' },
          { id: 6, name: '体育' },
          { id: 7, name: '科技' },
          { id: 10, name: '更多' }
        ]
      } finally {
        this.categoriesLoading = false
      }
    },

    // 切换新闻分类
    changeCategory(categoryId) {
      if (this.currentCategory === categoryId) return
      this.currentCategory = categoryId
      this.newsList = []
      this.page = 0
      this.total = 0
      this.finished = false
      this.getNewsList(true)
    },

    // 获取新闻列表（分页加载）
    async getNewsList(isRefresh = false) {
      if (isRefresh) {
        this.refreshing = true
        this.newsList = []
        this.page = 0
        this.finished = false
      }

      // 已经加载完就不重复请求
      if (!isRefresh && this.finished) {
        this.loading = false
        return
      }

      this.loading = true

      const nextPage = isRefresh ? 1 : this.page + 1

      try {
        const params = {
          categoryId: this.currentCategory,
          page: nextPage,
          pageSize: PAGE_SIZE
        }

        const response = await axios.get(newsConfig.listEndpoint, { params })

        if (response.data && response.data.code === 200) {
          const payload = response.data.data || {}
          const newsData = normalizeNewsList(payload.list || [])

          // 按 id 去重，避免自动刷新和分页交叉时出现重复卡片
          const existingIds = new Set(this.newsList.map(item => item.id))
          const fresh = newsData.filter(item => !existingIds.has(item.id))

          this.newsList = isRefresh ? newsData : [...this.newsList, ...fresh]
          this.page = nextPage
          this.total = payload.total || 0
          this.lastUpdatedAt = new Date().toISOString()

          // 后端会直接告诉我们还有没有更多，比按条数猜更可靠
          if (typeof payload.has_more === 'boolean') {
            this.finished = !payload.has_more
          } else {
            this.finished = newsData.length < PAGE_SIZE
          }
        }
      } catch (error) {
        console.error('获取新闻列表失败:', error)
        // 请求失败时不要卡在 loading，允许用户下拉重试
        this.finished = true
      } finally {
        this.loading = false
        this.refreshing = false
      }
    },

    // 获取新闻详情
    async getNewsDetail(id) {
      try {
        const response = await axios.get(`${newsConfig.detailEndpoint}?id=${id}`)

        if (response.data && response.data.code === 200) {
          const detail = normalizeNews(response.data.data)
          detail.relatedNews = normalizeNewsList(detail.relatedNews || [])
          this.newsDetail = detail
          return detail
        }
        console.error('获取新闻详情失败: 接口返回错误')
      } catch (error) {
        console.error('获取新闻详情失败:', error)
      }
      return null
    },

    /**
     * 静默拉取当前分类的最新几条，把新出现的新闻插到列表最前面。
     * 只插入不替换，所以不会打断用户的滚动位置。
     */
    async fetchLatest() {
      try {
        // 直接按当前分类取，避免"最新 10 条"全被别的频道占了
        const response = await axios.get(newsConfig.latestEndpoint, {
          params: { limit: PAGE_SIZE, categoryId: this.currentCategory }
        })
        if (response.data?.code !== 200) return 0

        const latest = normalizeNewsList(response.data.data?.list || [])
        this.lastUpdatedAt = new Date().toISOString()
        if (!latest.length) return 0

        const existingIds = new Set(this.newsList.map(item => item.id))
        const incoming = latest.filter(item => !existingIds.has(item.id))
        if (!incoming.length) return 0

        this.newsList = [...incoming, ...this.newsList]
        this.total += incoming.length
        return incoming.length
      } catch (error) {
        console.error('获取最新新闻失败:', error)
        return 0
      }
    },

    // 拉取后端采集状态，首页用来显示「实时更新中」
    async fetchLiveStatus() {
      try {
        const response = await axios.get(newsConfig.statusEndpoint)
        if (response.data?.code === 200) {
          this.liveStatus = response.data.data
        }
      } catch (error) {
        // 状态接口不可用不影响新闻浏览，静默失败
        this.liveStatus = null
      }
    },

    // 手动触发后端抓取（下拉刷新时如果数据太旧会调用）
    async triggerRefresh() {
      try {
        const response = await axios.post(newsConfig.refreshEndpoint, null, {
          params: { wait: false }
        })
        return response.data?.code === 200
      } catch (error) {
        console.error('触发新闻刷新失败:', error)
        return false
      }
    },

    startAutoRefresh() {
      this.stopAutoRefresh()
      this.autoRefreshTimer = setInterval(() => {
        // 页面不可见时不打扰后端
        if (typeof document !== 'undefined' && document.hidden) return
        this.fetchLatest()
      }, AUTO_REFRESH_MS)
    },

    stopAutoRefresh() {
      if (this.autoRefreshTimer) {
        clearInterval(this.autoRefreshTimer)
        this.autoRefreshTimer = null
      }
    }
  }
})
