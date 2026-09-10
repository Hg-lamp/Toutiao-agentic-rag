<template>
  <div class="detail-page">
    <van-nav-bar title="新闻详情" left-text="返回" left-arrow @click-left="onClickLeft" fixed />
    <div class="detail-content" v-if="newsStore.newsDetail.id">
      <div class="article-header">
        <h1 class="article-title">{{ newsStore.newsDetail.title }}</h1>
        <div class="article-meta">
          <span class="article-badge" v-if="newsStore.newsDetail.isLive">实时</span>
          <span class="article-author">{{ newsStore.newsDetail.source || newsStore.newsDetail.author }}</span>
          <span class="meta-sep">/</span>
          <span :title="absoluteTime">{{ relativeTime }}</span>
          <span class="meta-sep">/</span>
          <span class="article-views">{{ newsStore.newsDetail.views }} 阅读</span>
        </div>
        <van-button class="favorite-btn" :icon="isFavorite ? 'star' : 'star-o'"
          :class="{ 'is-favorite': isFavorite }" @click="toggleFavorite" round plain size="small">
          {{ isFavorite ? '已收藏' : '收藏' }}
        </van-button>
      </div>
      <div class="article-cover" v-if="newsStore.newsDetail.image">
        <img :src="newsStore.newsDetail.image" :alt="newsStore.newsDetail.title" @error="onImageError" />
      </div>
      <div class="article-body">
        <p v-for="(paragraph, index) in contentParagraphs" :key="index">{{ paragraph }}</p>
      </div>
      <a class="article-source-link" v-if="newsStore.newsDetail.sourceUrl"
         :href="newsStore.newsDetail.sourceUrl" target="_blank" rel="noopener noreferrer">
        查看原文 · {{ newsStore.newsDetail.source || '来源' }}
        <van-icon name="arrow" />
      </a>
      <div class="article-divider"></div>
      <div class="related-news" v-if="newsStore.newsDetail.relatedNews?.length">
        <h3 class="related-title">相关推荐</h3>
        <div class="related-list">
          <div class="related-item" v-for="item in newsStore.newsDetail.relatedNews" :key="item.id" @click="goToRelatedNews(item.id)">
            <div class="related-image"><img :src="item.image" :alt="item.title" loading="lazy" /></div>
            <div class="related-text"><span class="related-news-title">{{ item.title }}</span></div>
          </div>
        </div>
      </div>
    </div>
    <van-empty v-else description="加载中..." />
  </div>
</template>
<script setup>
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useNewsStore } from '../store/modules/news'
import { useHistoryStore } from '../store/modules/history'
import { useFavoriteStore } from '../store/modules/favorite'
import { useUserStore } from '../store/user'
import { showToast } from 'vant'
import { formatAbsoluteTime, formatRelativeTime } from '../utils/news'
const route = useRoute(); const router = useRouter()
const newsStore = useNewsStore(); const historyStore = useHistoryStore()
const favoriteStore = useFavoriteStore(); const userStore = useUserStore()
const newsId = computed(() => Number(route.params.id))
const relativeTime = computed(() => formatRelativeTime(newsStore.newsDetail.publishTime))
const absoluteTime = computed(() => formatAbsoluteTime(newsStore.newsDetail.publishTime))
const contentParagraphs = computed(() => {
  if (!newsStore.newsDetail.content) return []
  return newsStore.newsDetail.content.split(/\n{2,}/).map(p => p.trim()).filter(Boolean)
})
const onImageError = (event) => { event.target.parentElement.style.display = 'none' }
const onClickLeft = () => router.back()
const goToRelatedNews = (id) => router.push(`/news/detail/${id}`)
const isFavorite = computed(() => favoriteStore.isFavorite(newsId.value))
const toggleFavorite = async () => {
  if (!userStore.getLoginStatus) { showToast({ message: '请先登录后再收藏', position: 'bottom' }); router.push('/login'); return }
  const status = await favoriteStore.toggleFavorite(newsStore.newsDetail)
  if (status === true) showToast({ message: '已添加到收藏', position: 'bottom' })
  else if (status === false) showToast({ message: '已取消收藏', position: 'bottom' })
  else showToast({ message: '操作失败，请稍后重试', position: 'bottom' })
}
onMounted(async () => {
  await newsStore.getNewsDetail(newsId.value)
  if (newsStore.newsDetail.id && userStore.getLoginStatus) {
    try { await historyStore.addHistoryApi(newsStore.newsDetail.id) } catch (e) { console.error(e) }
  }
  favoriteStore.loadFavorites()
  if (userStore.getLoginStatus && newsStore.newsDetail.id) {
    const result = await favoriteStore.checkFavoriteStatusApi(newsStore.newsDetail.id)
    if (result.success && !result.isLocal) {
      if (result.isFavorite && !favoriteStore.isFavorite(newsStore.newsDetail.id)) favoriteStore.addFavorite(newsStore.newsDetail)
      else if (!result.isFavorite && favoriteStore.isFavorite(newsStore.newsDetail.id)) favoriteStore.removeFavorite(newsStore.newsDetail.id)
    }
  }
})
</script>
<style scoped>
.detail-page { padding-top: 46px; min-height: 100vh; padding-bottom: 30px; }
.detail-content { max-width: 100%; }
.article-header { padding: 20px 16px 12px; position: relative; }
.article-title { font-size: 22px; font-weight: 700; line-height: 1.45; margin: 0 0 12px; color: var(--text-primary); letter-spacing: 0.01em; }
.article-meta { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-secondary); flex-wrap: wrap; }
.article-author { font-weight: 500; color: var(--accent-purple); }
.article-badge { display: inline-flex; align-items: center; height: 16px; padding: 0 6px; border-radius: 3px; font-size: 10px; font-weight: 600; color: #fff; background: linear-gradient(135deg, var(--accent-pink), var(--accent-purple)); }
.meta-sep { color: var(--border-light); }
.article-views { font-family: var(--font-mono); font-size: 11px; letter-spacing: -0.02em; }
/* 实时采集的新闻保留原文链接，方便溯源 */
.article-source-link { display: flex; align-items: center; justify-content: space-between; margin: 18px 16px 0; padding: 11px 14px; border-radius: 8px; font-size: 13px; color: var(--accent-purple); text-decoration: none; background: var(--bg-card); border: 1px solid var(--border-light); box-shadow: var(--shadow-card); }
.article-source-link:active { border-color: var(--border-hover); }
.favorite-btn { position: absolute; right: 16px; top: 20px; font-size: 12px; border-color: var(--border-light); color: var(--text-secondary) !important; }
.favorite-btn.is-favorite { color: var(--accent-pink) !important; border-color: var(--accent-pink) !important; }
.article-cover { margin: 0 16px 16px; border-radius: 10px; overflow: hidden; box-shadow: var(--shadow-card); }
.article-cover img { width: 100%; display: block; }
.article-body { padding: 0 16px; font-size: 16px; line-height: 1.85; color: var(--text-primary); }
.article-body p { margin-bottom: 18px; text-align: justify; }
.article-divider { height: 1px; margin: 24px 16px; background: linear-gradient(to right, transparent, var(--accent-blue), transparent); opacity: 0.3; }
.related-news { padding: 0 16px; }
.related-title { font-size: 17px; font-weight: 600; margin: 0 0 14px; color: var(--text-primary); }
.related-list { display: flex; flex-direction: column; gap: 10px; }
.related-item { display: flex; align-items: center; padding: 10px; background: var(--bg-card); backdrop-filter: blur(12px); border-radius: 8px; box-shadow: var(--shadow-card); border: 1px solid var(--border-light); cursor: pointer; }
.related-item:active { border-color: var(--border-hover); }
.related-image { width: 72px; height: 54px; flex-shrink: 0; margin-right: 12px; border-radius: 6px; overflow: hidden; background: var(--bg-mid); }
.related-image img { width: 100%; height: 100%; object-fit: cover; }
.related-text { flex: 1; min-width: 0; }
.related-news-title { font-size: 14px; line-height: 1.4; color: var(--text-primary); display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
</style>