<template>
  <div class="my-container">
    <van-nav-bar :title="$t('my.title')" />
    <div class="user-info" @click="goToProfile" v-if="isLogin && sessionVerified">
      <div class="avatar">
        <van-image round width="72" height="72"
          :src="userInfo?.avatar || 'https://fastly.jsdelivr.net/npm/@vant/assets/cat.jpeg'" />
      </div>
      <div class="info">
        <div class="username">{{ isLogin && userInfo ? (userInfo.nickname || userInfo.username) : $t('my.notLoggedIn') }}</div>
        <div class="desc" v-if="isLogin && userInfo">{{ userInfo.bio || $t('profile.bio') }}</div>
      </div>
      <van-icon name="arrow" class="arrow-icon" />
    </div>
    <div class="user-info" v-else>
      <div class="avatar">
        <van-image round width="72" height="72"
          src="https://fastly.jsdelivr.net/npm/@vant/assets/cat.jpeg" />
      </div>
      <div class="info">
        <div class="username">{{ $t('my.notLoggedIn') }}</div>
        <div class="desc">
          <van-button type="primary" size="small" @click="goToLogin" style="margin-right: 10px">{{ $t('my.goToLogin') }}</van-button>
          <van-button type="default" size="small" @click="goToRegister">{{ $t('my.goToRegister') }}</van-button>
        </div>
      </div>
    </div>

    <div class="menu-list">
      <van-cell-group inset>
        <van-cell :title="$t('my.myFavorite')" is-link @click="goToFavorite" icon="star-o" />
        <van-cell :title="$t('my.browsingHistory')" is-link @click="goToHistory" icon="clock-o" />
        <van-cell :title="'AI问答'" is-link @click="goToAIChat" icon="chat-o" />
        <van-cell :title="$t('my.settings')" is-link @click="goToSettings" icon="setting-o" />
        <van-cell v-if="isLogin" :title="$t('my.logout')" @click="handleLogout" icon="logout" />
      </van-cell-group>
    </div>
    <tab-bar />
  </div>
</template>

<script setup>
import { onActivated, ref } from 'vue';
import { useUserStore } from '../store/user';
import { useRouter } from 'vue-router';
import { computed } from 'vue';
import { showDialog, showToast } from 'vant';
import TabBar from '../components/TabBar.vue';
import { useI18n } from 'vue-i18n';

const userStore = useUserStore();
const router = useRouter();
const { t } = useI18n();

const userInfo = computed(() => userStore.userInfo);
const isLogin = computed(() => userStore.getLoginStatus);
const sessionVerified = ref(false);

const goToLogin = () => router.push('/login');
const goToRegister = () => router.push('/register');
const goToProfile = () => { if (isLogin.value) router.push('/profile') };
const goToHistory = () => { isLogin.value ? router.push('/history') : (showToast(t('common.login')), router.push('/login')) };
const goToFavorite = () => { isLogin.value ? router.push('/favorite') : (showToast(t('common.login')), router.push('/login')) };
const goToAIChat = () => router.push('/aichat');
const goToSettings = () => router.push('/settings');

const handleLogout = () => {
  showDialog({ title: t('common.confirm'), message: t('my.logout') + '?', showCancelButton: true })
    .then((action) => { if (action === 'confirm') { userStore.logout(); router.push('/login') } });
};

onActivated(async () => {
  if (!userStore.getLoginStatus || !userStore.token) {
    sessionVerified.value = false;
    return;
  }

  try {
    const result = await userStore.getUserInfoDetail();
    sessionVerified.value = result.success;
  } catch (e) {
    sessionVerified.value = false;
    console.error(e);
  }
});
</script>

<style scoped>
.my-container { padding-top: 46px; padding-bottom: 50px; min-height: 100vh; }

:deep(.van-nav-bar) { background: transparent !important; border-bottom: none !important; }
:deep(.van-nav-bar__title) { color: var(--text-primary); }

.user-info {
  display: flex; align-items: center; padding: 16px 16px; margin: 0;
  background: transparent;
  position: relative; cursor: pointer;
}
.user-info:active { background: rgba(255, 255, 255, 0.1); }

.arrow-icon { position: absolute; right: 16px; color: var(--text-tertiary); }
.avatar { margin-right: 14px; flex-shrink: 0; }
.info { flex: 1; min-width: 0; }
.username { font-size: 18px; font-weight: 600; margin-bottom: 4px; color: var(--text-primary); }
.desc { font-size: 13px; color: var(--text-secondary); }

.menu-list { margin: 0; }
.menu-list :deep(.van-cell-group) { background: transparent !important; }
.menu-list :deep(.van-cell) {
  background: transparent !important;
  margin-bottom: 1px; border-left: none; border-right: none;
}
.menu-list :deep(.van-cell:first-child) { border-radius: 0; }
.menu-list :deep(.van-cell:last-child) { border-radius: 0; margin-bottom: 0; }
.menu-list :deep(.van-cell-group) { border-radius: 0; overflow: hidden; box-shadow: none; border: none; border-top: 1px solid var(--border-light); }
.menu-list :deep(.van-cell__left-icon) { color: var(--accent-purple); font-size: 18px; }
</style>
