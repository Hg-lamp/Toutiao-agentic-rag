<template>
  <div class="list-page">
    <van-nav-bar title="我的收藏" left-text="返回" left-arrow @click-left="onClickLeft" right-text="清空" @click-right="onClickClear" fixed />
    <div class="list-content" v-if="favoriteStore.getFavorites.length">
      <div class="list-item" v-for="item in favoriteStore.getFavorites" :key="item.id">
        <van-cell @click="goToNewsDetail(item.id)" :border="false">
          <template #title>
            <div class="item-card">
              <div class="item-image" v-if="item.image"><img :src="item.image" :alt="item.title" loading="lazy" /></div>
              <div class="item-info">
                <div class="item-title">{{ item.title }}</div>
                <div class="item-meta"><span>{{ item.source || item.author }}</span><span class="dot">·</span><span>{{ formatRelativeTime(item.publishTime) }}</span></div>
                <div class="item-time">收藏于 {{ item.favoriteTime }}</div>
              </div>
            </div>
          </template>
        </van-cell>
        <van-button class="del-btn" type="danger" size="mini" icon="cross" @click="confirmDelete(item.id)"></van-button>
      </div>
    </div>
    <van-empty v-else description="暂无收藏内容" />
  </div>
</template>
<script setup>
import { onMounted } from 'vue'; import { useRouter } from 'vue-router'; import { useFavoriteStore } from '../store/modules/favorite'; import { showDialog } from 'vant'; import { formatRelativeTime } from '../utils/news';
const router = useRouter(); const favoriteStore = useFavoriteStore();
const onClickLeft = () => router.back();
const goToNewsDetail = (id) => router.push(`/news/detail/${id}`);
const removeFavorite = async (id) => { const r = await favoriteStore.removeFavoriteApi(id); if (r.success) favoriteStore.removeFavorite(id) };
const confirmDelete = (id) => { showDialog({ title: '提示', message: '确定要删除吗？', showCancelButton: true }).then(a => { if (a === 'confirm') removeFavorite(id) }) };
const onClickClear = () => { showDialog({ title: '提示', message: '确定要清空所有收藏吗？', showCancelButton: true }).then(async a => { if (a === 'confirm') await favoriteStore.clearFavoritesApi() }) };
onMounted(async () => { try { const r = await favoriteStore.getFavoriteListApi(); if (!r || !r.success) favoriteStore.loadFavorites() } catch (e) { favoriteStore.loadFavorites() } });
</script>
<style scoped>
.list-page { padding-top: 46px; padding-bottom: 20px; min-height: 100vh; }
.list-content { padding: 8px 12px; }
.list-item { position: relative; margin-bottom: 8px; background: var(--bg-card); backdrop-filter: blur(12px); border-radius: 10px; box-shadow: var(--shadow-card); border: 1px solid var(--border-light); overflow: hidden; }
.list-item:active { border-color: var(--border-hover); }
.item-card { display: flex; padding: 4px 0; }
.item-image { width: 100px; height: 72px; margin-right: 12px; flex-shrink: 0; border-radius: 6px; overflow: hidden; background: var(--bg-mid); }
.item-image img { width: 100%; height: 100%; object-fit: cover; }
.item-info { flex: 1; display: flex; flex-direction: column; justify-content: space-between; min-width: 0; }
.item-title { font-size: 15px; font-weight: 600; line-height: 1.4; color: var(--text-primary); display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.item-meta { display: flex; align-items: center; gap: 4px; font-size: 12px; color: var(--text-secondary); margin-top: 4px; }
.dot { color: var(--border-light); }
.item-time { font-family: var(--font-mono); font-size: 11px; color: var(--text-tertiary); margin-top: 2px; }
.del-btn { position: absolute; top: 50%; right: 8px; transform: translateY(-50%); width: 22px; height: 22px; padding: 0; border-radius: 50%; opacity: 0.7; }
:deep(.van-cell) { padding-right: 36px; }
</style>