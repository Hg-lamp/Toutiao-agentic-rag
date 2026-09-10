<template>
  <div class="news-card" @click="goToDetail">
    <div class="news-card__content">
      <h3 class="news-card__title">{{ news.title }}</h3>
      <p class="news-card__desc" v-if="news.description">{{ news.description }}</p>
      <div class="news-card__meta">
        <span class="news-card__badge" v-if="news.isLive">实时</span>
        <span class="news-card__author">{{ news.source || news.author }}</span>
        <span class="meta-dot">·</span>
        <span class="news-card__time">{{ relativeTime }}</span>
        <span class="meta-dot">·</span>
        <span class="news-card__views">{{ news.views }} 阅读</span>
      </div>
    </div>
    <div class="news-card__image" v-if="news.image">
      <img :src="news.image" :alt="news.title" loading="lazy" @error="onImageError" />
    </div>
  </div>
</template>

<script setup>
import { computed, ref, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { formatRelativeTime } from '../utils/news'

const props = defineProps({
  news: { type: Object, required: true }
})

const router = useRouter()
const now = ref(Date.now())
let timer = null

// 相对时间会随时间变化，每分钟重算一次
onMounted(() => {
  timer = setInterval(() => { now.value = Date.now() }, 60 * 1000)
})
onBeforeUnmount(() => { if (timer) clearInterval(timer) })

const relativeTime = computed(() => formatRelativeTime(props.news.publishTime, now.value))

const goToDetail = () => {
  router.push(`/news/detail/${props.news.id}`)
}

// 部分来源的图片有防盗链，加载失败时直接隐藏，避免出现破图
const onImageError = (event) => {
  event.target.style.display = 'none'
}
</script>

<style scoped>
.news-card {
  display: flex;
  padding: 14px 16px;
  margin: 0 12px 8px;
  background: var(--bg-card);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border-radius: 10px;
  box-shadow: var(--shadow-card);
  border: 1px solid var(--border-light);
  cursor: pointer;
  animation: fadeInUp 0.35s var(--ease-smooth) both;
}

.news-card:active {
  box-shadow: var(--shadow-card-hover);
  border-color: var(--border-hover);
  transform: translateY(-1px);
}

.news-card__content {
  flex: 1;
  min-width: 0;
  margin-right: 12px;
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.news-card__title {
  font-size: 16px;
  font-weight: 600;
  line-height: 1.45;
  margin: 0 0 6px;
  color: var(--text-primary);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  text-overflow: ellipsis;
}

.news-card__desc {
  font-size: 13px;
  line-height: 1.5;
  color: var(--text-secondary);
  margin: 0 0 8px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  text-overflow: ellipsis;
}

.news-card__meta {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--text-tertiary);
  flex-wrap: wrap;
}

.news-card__author {
  color: var(--accent-purple);
  font-weight: 500;
}

/* 「实时」角标：来自自动采集的当日新闻 */
.news-card__badge {
  display: inline-flex;
  align-items: center;
  height: 15px;
  padding: 0 5px;
  border-radius: 3px;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: #fff;
  background: linear-gradient(135deg, var(--accent-pink), var(--accent-purple));
}

.meta-dot {
  color: var(--border-light);
  font-weight: 600;
}

.news-card__views {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: -0.02em;
  color: var(--text-tertiary);
}

.news-card__image {
  width: 100px;
  height: 76px;
  flex-shrink: 0;
  border-radius: 6px;
  overflow: hidden;
  background: var(--bg-mid);
}

.news-card__image img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: transform 0.3s var(--ease-smooth);
}

.news-card:active .news-card__image img {
  transform: scale(1.05);
}
</style>