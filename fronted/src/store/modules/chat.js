import { defineStore } from 'pinia';
import axios from 'axios';
import { useUserStore } from '../user';
import { aiChatConfig } from '../../config/api';

export const useChatStore = defineStore('chat', {
  state: () => ({
    conversations: [],
    activeThreadId: null, // null 表示新会话
    loading: false,
  }),

  getters: {
    getConversations: (state) => state.conversations,
    getActiveThreadId: (state) => state.activeThreadId,
  },

  actions: {
    // 拉取当前用户的会话列表
    async fetchConversations() {
      const userStore = useUserStore();
      if (!userStore.getLoginStatus) {
        return { success: false, message: '请先登录' };
      }
      try {
        this.loading = true;
        const response = await axios.get(aiChatConfig.conversationsEndpoint, {
          headers: { Authorization: userStore.token },
        });
        if (response.data.code === 200) {
          this.conversations = response.data.data.list || [];
          return { success: true, data: this.conversations };
        }
        return { success: false, message: response.data.message || '获取会话列表失败' };
      } catch (error) {
        console.error('获取会话列表失败:', error);
        return { success: false, message: '网络请求失败' };
      } finally {
        this.loading = false;
      }
    },

    // 拉取某个会话的消息历史
    async fetchMessages(threadId) {
      const userStore = useUserStore();
      if (!userStore.getLoginStatus) {
        return { success: false, message: '请先登录' };
      }
      try {
        const response = await axios.get(aiChatConfig.messagesEndpoint(threadId), {
          headers: { Authorization: userStore.token },
        });
        if (response.data.code === 200) {
          return { success: true, data: response.data.data.list || [] };
        }
        return { success: false, message: response.data.message || '获取消息失败' };
      } catch (error) {
        console.error('获取消息失败:', error);
        return { success: false, message: '网络请求失败' };
      }
    },

    // 新建会话：清空 activeThreadId
    newConversation() {
      this.activeThreadId = null;
    },

    // 选中某个会话
    selectConversation(threadId) {
      this.activeThreadId = threadId;
    },

    // 发完第一条消息后，把新会话插入列表顶部（去重）
    upsertConversation(conv) {
      const idx = this.conversations.findIndex((c) => c.threadId === conv.threadId);
      if (idx !== -1) this.conversations.splice(idx, 1);
      this.conversations.unshift(conv);
    },

    // 删除某个会话（同时清理后端 conversation/message/checkpoint）
    async deleteConversation(threadId) {
      const userStore = useUserStore();
      if (!userStore.getLoginStatus) {
        return { success: false, message: '请先登录' };
      }
      try {
        const response = await axios.delete(aiChatConfig.deleteConversationEndpoint(threadId), {
          headers: { Authorization: userStore.token },
        });
        if (response.data.code === 200) {
          this.conversations = this.conversations.filter((c) => c.threadId !== threadId);
          if (this.activeThreadId === threadId) {
            this.activeThreadId = null;
          }
          return { success: true };
        }
        return { success: false, message: response.data.message || '删除会话失败' };
      } catch (error) {
        console.error('删除会话失败:', error);
        return { success: false, message: error.response?.data?.detail || '网络请求失败' };
      }
    },
  },
});
