/**
 * API配置文件
 * 包含API基础URL和AI问答功能所需的API参数
 */

// API基础URL配置
export const apiConfig = {
  // 后端API基础URL
  baseURL: 'http://127.0.0.1:8000',
}

// AI 聊天后端接口配置
export const aiChatConfig = {
  // 后端 AI 聊天 SSE 接口地址
  apiEndpoint: `${apiConfig.baseURL}/api/ai/chat`,
  // 文件上传接口地址
  uploadEndpoint: `${apiConfig.baseURL}/api/ai/upload`,
  ragUploadEndpoint: `${apiConfig.baseURL}/api/ai/rag-upload`,
  // 会话列表接口（按当前用户）
  conversationsEndpoint: `${apiConfig.baseURL}/api/ai/conversations`,
  // 单个会话的消息历史接口
  messagesEndpoint: (threadId) => `${apiConfig.baseURL}/api/ai/conversations/${threadId}/messages`,
  // 删除单个会话
  deleteConversationEndpoint: (threadId) => `${apiConfig.baseURL}/api/ai/conversations/${threadId}`,
}

// 新闻接口配置（实时新闻）
export const newsConfig = {
  categoriesEndpoint: `${apiConfig.baseURL}/api/news/categories`,
  listEndpoint: `${apiConfig.baseURL}/api/news/list`,
  latestEndpoint: `${apiConfig.baseURL}/api/news/latest`,
  detailEndpoint: `${apiConfig.baseURL}/api/news/detail`,
  // 手动触发一次实时抓取
  refreshEndpoint: `${apiConfig.baseURL}/api/news/refresh`,
  // 采集运行状态（最近更新时间、各频道条数）
  statusEndpoint: `${apiConfig.baseURL}/api/news/status`,
  // 当前启用的新闻来源
  sourcesEndpoint: `${apiConfig.baseURL}/api/news/sources`,
}
