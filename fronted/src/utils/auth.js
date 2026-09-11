import axios from 'axios';
import { showToast } from 'vant';
import { useUserStore } from '../store/user';

const AUTH_ENDPOINTS = ['/api/user/login', '/api/user/register'];

let routerInstance = null;
let piniaInstance = null;

const isAuthEndpoint = (url = '') => AUTH_ENDPOINTS.some((endpoint) => url.includes(endpoint));

const clearExpiredSession = async () => {
  if (!routerInstance || !piniaInstance) return false;

  const userStore = useUserStore(piniaInstance);
  const hadSession = Boolean(userStore.token || userStore.isLogin || userStore.userInfo);

  userStore.logout();

  if (!hadSession) return false;

  showToast('登录已过期，请重新登录');

  const currentRoute = routerInstance.currentRoute.value;
  if (currentRoute.meta?.requiresAuth) {
    await routerInstance.replace({
      name: 'Login',
      query: { redirect: currentRoute.fullPath },
    }).catch(() => {});
  }

  return true;
};

export const handleUnauthorizedResponse = async (response) => {
  if (response?.status !== 401) return false;
  await clearExpiredSession();
  return true;
};

export const setupAuthInterceptor = ({ router, pinia }) => {
  routerInstance = router;
  piniaInstance = pinia;

  axios.interceptors.response.use(
    (response) => response,
    async (error) => {
      if (error.response?.status === 401 && !isAuthEndpoint(error.config?.url)) {
        await clearExpiredSession();
      }
      return Promise.reject(error);
    }
  );
};
