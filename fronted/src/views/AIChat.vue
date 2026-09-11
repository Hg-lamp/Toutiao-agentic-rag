<template>
  <div class="chat-page">
    <van-nav-bar title="小助手" fixed>
      <template #left>
        <van-icon name="wap-nav" size="22" class="conv-toggle" @click="sidebarVisible = true" />
      </template>
    </van-nav-bar>

    <!-- 左侧会话栏（可折叠抽屉） -->
    <van-popup v-model:show="sidebarVisible" position="left" :style="{ width: '78%', height: '100%' }">
      <div class="conv-sidebar">
        <div class="conv-header">
          <span class="conv-header-title">会话列表</span>
          <van-button size="small" type="primary" round @click="handleNewChat">新建会话</van-button>
        </div>
        <div class="conv-list">
          <div
            v-for="conv in chatStore.conversations"
            :key="conv.threadId"
            :class="['conv-item', { active: conv.threadId === chatStore.activeThreadId }]"
            @click="handleSelectConversation(conv)"
          >
            <div class="conv-title">{{ conv.title || '新会话' }}</div>
            <div class="conv-meta">{{ conv.messageCount }} 条 · {{ formatTime(conv.updatedAt) }}</div>
            <van-button
              class="conv-del-btn"
              type="danger"
              size="mini"
              icon="cross"
              @click.stop="confirmDeleteConversation(conv)"
            />
          </div>
          <van-empty v-if="!chatStore.conversations.length" description="暂无会话" />
        </div>
      </div>
    </van-popup>

    <div class="chat-content">
      <div class="messages" ref="messagesContainer">
        <template v-for="(msg, index) in messages" :key="index">
          <!-- 图片附件与文件气泡优先于普通消息渲染 -->
          <div v-if="msg.role === 'image'" class="msg image" @click="removeImageMsg(index)">
            <div class="msg-label">你</div>
            <div class="msg-bubble image-bubble">
              <img class="pending-image" :src="msg.previewUrl" :alt="msg.name">
              <div class="image-caption">{{ msg.name }} · 点击移除</div>
            </div>
          </div>
          <div v-else-if="msg.role === 'file'" class="msg file" @click="openFilePreview(msg)">
            <div class="msg-label">你</div>
            <div class="msg-bubble file-bubble">
              <van-icon name="description" class="file-icon" />
              <div class="file-info">
                <div class="file-name">{{ msg.name }}</div>
                <div class="file-meta">{{ formatSize(msg.size) }} · {{ msg.sent ? '已发送，点击查看内容' : '待发送，点击查看内容' }}</div>
              </div>
              <van-icon
                v-if="!msg.sent"
                name="cross"
                class="file-remove"
                @click.stop="removeFileMsg(index)"
              />
            </div>
          </div>
          <div v-else :class="['msg', msg.role === 'user' ? 'user' : 'ai']">
            <div class="msg-label">{{ msg.role === 'user' ? '你' : 'AI' }}</div>
            <div class="msg-bubble" @click="handleMessageClick">
              <!-- 工具轨迹卡片 -->
              <div v-if="msg.traces && msg.traces.length" class="tool-traces">
                <div v-for="trace in msg.traces" :key="trace.tool_id" class="trace-card">
                  <div class="trace-header" @click="trace.expanded = !trace.expanded">
                    <span class="trace-icon">{{ trace.done ? '✅' : '⏳' }}</span>
                    <span class="trace-label">{{ trace.tool_label }}</span>
                    <span class="trace-args" v-if="trace.tool_args && trace.tool_args.query">"{{ trace.tool_args.query }}"</span>
                    <span class="trace-status" :class="{ running: !trace.done }">{{ trace.done ? '完成' : '执行中...' }}</span>
                  </div>
                  <div v-if="trace.expanded" class="trace-detail">
                    <pre class="trace-result">{{ trace.result }}</pre>
                  </div>
                </div>
              </div>
              <!-- 正文 -->
              <div v-if="msg.role === 'assistant' && msg.content === '' && (!msg.traces || !msg.traces.length)" class="typing"><span></span><span></span><span></span></div>
              <div
                v-else
                class="msg-text"
                :class="{ 'is-collapsed': isMessageCollapsed(msg) }"
                v-html="formatMessage(msg.content)"
              ></div>
              <div
                v-for="(chart, chartIndex) in (msg.charts || [])"
                :key="chartIndex"
                class="chart-container"
                :data-chart-key="chartKey(index, chartIndex)"
                :ref="(el) => setChartRef(el, index, chartIndex)"
              ></div>
              <button
                v-if="canCollapseMessage(msg)"
                type="button"
                class="message-collapse-btn"
                @click.stop="toggleMessageCollapse(msg)"
              >
                <van-icon :name="isMessageCollapsed(msg) ? 'arrow-down' : 'arrow-up'" />
                {{ isMessageCollapsed(msg) ? '展开完整消息' : '收起长消息' }}
              </button>
            </div>
            <van-button
              v-if="msg.role === 'assistant' && index === messages.length - 1 && msg.status === 'generating'"
              class="stop-generation-btn"
              type="warning"
              size="small"
              round
              icon="stop"
              @click.stop="stopGeneration"
            >
              停止
            </van-button>
          </div>
        </template>
      </div>
      <div class="input-area">
        <input type="file" ref="fileInput" @change="handleFileSelect" accept=".txt,.md,.csv,.pdf,.docx,.xlsx" style="display:none">
        <input type="file" ref="imageInput" @change="handleImageSelect" accept=".jpg,.jpeg,.png,.webp,.bmp" style="display:none">
        <input type="file" ref="ragFileInput" @change="handleRagFileSelect" accept=".txt,.md,.csv,.pdf,.docx,.xlsx,.jpg,.jpeg,.png,.webp,.bmp" style="display:none">
        <div class="upload-bar">
          <van-button class="upload-btn" :disabled="isUploading" @click="triggerUpload">{{ isUploading ? '⏳' : 'file' }}</van-button>
          <van-button class="upload-btn image-upload-btn" :disabled="isImageUploading" @click="triggerImageUpload">{{ isImageUploading ? '⏳' : 'IMG' }}</van-button>
          <van-button class="upload-btn rag-upload-btn" :disabled="isRagUploading" @click="triggerRagUpload">
            {{ isRagUploading ? '⏳' : 'RAG' }}
          </van-button>
        </div>
        <div class="input-row">
          <van-field v-model="userInput" rows="1" autosize type="textarea" placeholder="请输入问题..." class="chat-input" @keypress.enter.prevent="sendMessage" />
          <van-button type="primary" class="send-btn" :disabled="isLoading || (!userInput.trim() && !hasPendingImage && !hasPendingFile)" @click="sendMessage">发送</van-button>
        </div>
      </div>
    </div>

    <van-popup
      v-model:show="filePreviewVisible"
      position="bottom"
      round
      :style="{ height: '72%' }"
      class="file-preview-popup"
    >
      <div class="file-preview">
        <div class="file-preview-header">
          <div class="file-preview-heading">
            <div class="file-preview-title">{{ filePreview?.name || '文件内容' }}</div>
            <div class="file-preview-meta">{{ filePreview ? formatSize(filePreview.size) : '' }}</div>
          </div>
          <van-icon name="cross" class="file-preview-close" @click="closeFilePreview" />
        </div>
        <pre class="file-preview-content">{{ filePreview?.text || '文件内容为空' }}</pre>
        <div v-if="filePreview && !filePreview.sent" class="file-preview-footer">
          <van-button type="danger" block @click="removePreviewFile">移除文件</van-button>
        </div>
      </div>
    </van-popup>
    <tab-bar />
  </div>
</template>
<script setup>
import { showDialog, showImagePreview } from 'vant';
import { ref, computed, onMounted, onActivated, onBeforeUnmount, nextTick, watch } from 'vue'; import TabBar from '../components/TabBar.vue'; import * as marked from 'marked'; import DOMPurify from 'dompurify'; import * as echarts from 'echarts'; import { aiChatConfig } from '../config/api'; import { useChatStore } from '../store/modules/chat'; import { useUserStore } from '../store/user';
import { handleUnauthorizedResponse } from '../utils/auth';
const messages = ref([{ role: 'assistant', content: '你好，我是鼠鼠小助手，有什么需要我帮忙的吗？' }]);
const userInput = ref(''); const messagesContainer = ref(null); const isLoading = ref(false);
const activeRequest = ref(null);
const filePreviewVisible = ref(false);
const filePreview = ref(null);
const isUploading = ref(false); const fileInput = ref(null);
const isImageUploading = ref(false); const imageInput = ref(null);
const isRagUploading = ref(false); const ragFileInput = ref(null);
const chatStore = useChatStore(); const userStore = useUserStore(); const sidebarVisible = ref(false);
const chartInstances = new Map();
const chartKey = (messageIndex, chartIndex) => `${messageIndex}-${chartIndex}`;
const disposeCharts = () => {
  chartInstances.forEach((chart) => chart.dispose());
  chartInstances.clear();
};
const renderChart = (el, messageIndex, chartIndex) => {
  const chart = messages.value[messageIndex]?.charts?.[chartIndex];
  if (!el?.isConnected || !chart || el.clientWidth === 0 || el.clientHeight === 0) return false;
  const key = chartKey(messageIndex, chartIndex);
  const instance = echarts.getInstanceByDom(el) || echarts.init(el);
  instance.setOption(chart.option, true);
  instance.resize();
  chartInstances.set(key, instance);
  return true;
};
const setChartRef = (el, messageIndex, chartIndex) => {
  if (!el) return;
  requestAnimationFrame(() => {
    if (!renderChart(el, messageIndex, chartIndex)) {
      requestAnimationFrame(() => renderChart(el, messageIndex, chartIndex));
    }
  });
};
const renderAllCharts = () => {
  nextTick(() => {
    requestAnimationFrame(() => {
      if (!messagesContainer.value) return;
      messagesContainer.value.querySelectorAll('.chart-container[data-chart-key]').forEach((el) => {
        const [messageIndex, chartIndex] = el.dataset.chartKey.split('-').map(Number);
        renderChart(el, messageIndex, chartIndex);
      });
    });
  });
};
const LONG_MESSAGE_CHAR_LIMIT = 420;
const LONG_MESSAGE_LINE_LIMIT = 12;
const formatMessage = (c) => c ? DOMPurify.sanitize(marked.parse(c)) : '';
const isLongMessage = (message) => {
  const content = message?.content || '';
  return content.length > LONG_MESSAGE_CHAR_LIMIT
    || content.split('\n').length > LONG_MESSAGE_LINE_LIMIT;
};
const canCollapseMessage = (message) => (
  isLongMessage(message)
  && message.status !== 'generating'
  && message.status !== 'pending'
);
const isMessageCollapsed = (message) => (
  canCollapseMessage(message) && (message.collapsed ?? true)
);
const toggleMessageCollapse = (message) => {
  message.collapsed = !isMessageCollapsed(message);
  renderAllCharts();
};
const handleMessageClick = (event) => {
  const image = event.target;
  if (!(image instanceof HTMLImageElement)) return;
  const src = image.currentSrc || image.src;
  if (!src) return;
  showImagePreview({
    images: [src],
    startPosition: 0,
    closeable: true,
    loop: false,
  });
};
const parseStoredFileMessages = (content) => {
  const source = content || '';
  const matches = [...source.matchAll(/用户上传了文件 ([\s\S]+?)，内容如下：\n```\n([\s\S]*?)\n```(?=\n\n|$)/g)];
  if (!matches.length) return null;

  const files = matches.map((match) => {
    const text = match[2];
    return {
      role: 'file',
      name: match[1].trim(),
      text,
      size: new TextEncoder().encode(text).length,
      sent: true,
    };
  });
  const lastMatch = matches[matches.length - 1];
  return {
    files,
    question: source.slice(lastMatch.index + lastMatch[0].length).replace(/^\n+/, '').trim(),
  };
};
const parseStoredMessage = (content) => {
  const charts = [];
  const parsedFiles = parseStoredFileMessages(content);
  const visibleContent = parsedFiles ? parsedFiles.question : content;
  const cleanContent = (visibleContent || '').replace(/<!-- AI_CHART:(.*?) -->/gs, (_, raw) => {
    try {
      const payload = JSON.parse(raw);
      if (payload?.type === 'chart' && payload.option) charts.push(payload);
    } catch (e) {
      console.warn('忽略无效的历史图表数据', e);
    }
    return '';
  }).trim();
  return { content: cleanContent, charts, files: parsedFiles?.files || [] };
};
const buildFileContext = (file) => (
  `用户上传了文件 ${file.name}，内容如下：\n\`\`\`\n${file.text}\n\`\`\`\n\n`
);
const formatSize = (bytes) => { if (bytes < 1024) return bytes + 'B'; if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + 'KB'; return (bytes / 1024 / 1024).toFixed(1) + 'MB'; };
const hasPendingImage = computed(() => messages.value.some((msg) => msg.role === 'image'));
const hasPendingFile = computed(() => messages.value.some((msg) => msg.role === 'file' && !msg.sent));
const scrollToBottom = () => { if (messagesContainer.value) messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight };
const triggerUpload = () => { if (!isUploading.value) fileInput.value.click() };
const triggerImageUpload = () => { if (!isImageUploading.value) imageInput.value.click() };
const triggerRagUpload = () => { if (!isRagUploading.value) ragFileInput.value.click() };
const handleFileSelect = async (e) => {
  const file = e.target.files[0]; if (!file) return;
  isUploading.value = true;
  try {
    const fd = new FormData(); fd.append('file', file);
    const headers = {};
    if (userStore.token) headers.Authorization = userStore.token;
    const res = await fetch(aiChatConfig.uploadEndpoint, { method: 'POST', headers, body: fd });
    if (await handleUnauthorizedResponse(res)) return;
    if (!res.ok) { const err = await res.json(); throw new Error(err.detail || `上传失败: ${res.status}`); }
    const data = await res.json();
    // 在消息列表末尾插入文件气泡（用户侧）
    messages.value.push({ role: 'file', name: data.filename, text: data.text, size: data.size, sent: false });
    await nextTick(); scrollToBottom();
  } catch (e) { messages.value.push({ role: 'assistant', content: `⚠️ 文件上传失败: ${e.message}` }); await nextTick(); scrollToBottom(); }
  finally { isUploading.value = false; e.target.value = ''; }
};
const handleImageSelect = async (e) => {
  const file = e.target.files[0]; if (!file) return;
  if (messages.value.filter((msg) => msg.role === 'image').length >= 2) {
    messages.value.push({ role: 'assistant', content: '⚠️ 单次最多上传 2 张图片' });
    e.target.value = '';
    return;
  }

  isImageUploading.value = true;
  try {
    const fd = new FormData(); fd.append('file', file);
    const headers = {};
    if (userStore.token) headers.Authorization = userStore.token;
    const res = await fetch(aiChatConfig.attachmentEndpoint, { method: 'POST', headers, body: fd });
    if (await handleUnauthorizedResponse(res)) return;
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || data.message || `图片上传失败: ${res.status}`);

    const attachment = data.data || data;
    messages.value.push({
      role: 'image',
      attachmentId: attachment.attachment_id,
      name: attachment.filename,
      size: attachment.size,
      previewUrl: attachment.preview_url,
    });
    await nextTick(); scrollToBottom();
  } catch (error) {
    messages.value.push({ role: 'assistant', content: `⚠️ 图片上传失败: ${error.message}` });
    await nextTick(); scrollToBottom();
  } finally {
    isImageUploading.value = false;
    e.target.value = '';
  }
};
const handleRagFileSelect = async (e) => {
  const file = e.target.files[0]; if (!file) return;
  isRagUploading.value = true;
  try {
    const fd = new FormData(); fd.append('file', file);
    const headers = {};
    if (userStore.token) headers.Authorization = userStore.token;
    const res = await fetch(aiChatConfig.ragUploadEndpoint, { method: 'POST', headers, body: fd });
    if (await handleUnauthorizedResponse(res)) return;
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || `知识库上传失败: ${res.status}`);
    }
    const data = await res.json();
    messages.value.push({
      role: 'assistant',
      content: `✅ 文件「${data.filename}」已加入知识库，共切分 ${data.chunks} 个片段。后续提问时会自动检索。`,
    });
    await nextTick(); scrollToBottom();
  } catch (error) {
    messages.value.push({ role: 'assistant', content: `⚠️ 知识库上传失败: ${error.message}` });
    await nextTick(); scrollToBottom();
  } finally {
    isRagUploading.value = false;
    e.target.value = '';
  }
};
const openFilePreview = (fileMessage) => {
  filePreview.value = fileMessage;
  filePreviewVisible.value = true;
};
const closeFilePreview = () => {
  filePreviewVisible.value = false;
};
const removeFileMsg = (index) => {
  if (filePreview.value === messages.value[index]) closeFilePreview();
  messages.value.splice(index, 1);
};
const removePreviewFile = () => {
  const index = messages.value.indexOf(filePreview.value);
  if (index !== -1) removeFileMsg(index);
};
const removeImageMsg = async (index) => {
  const imageMessage = messages.value[index];
  if (!imageMessage || imageMessage.role !== 'image') return;
  messages.value.splice(index, 1);
  if (!imageMessage.attachmentId) return;

  try {
    const headers = {};
    if (userStore.token) headers.Authorization = userStore.token;
    const res = await fetch(aiChatConfig.deleteAttachmentEndpoint(imageMessage.attachmentId), {
      method: 'DELETE',
      headers,
    });
    await handleUnauthorizedResponse(res);
  } catch (error) {
    console.warn('删除图片附件失败:', error);
  }
};
const formatTime = (iso) => {
  if (!iso) return '';
  const d = new Date(iso);
  const now = new Date();
  const pad = (n) => (n < 10 ? '0' + n : n);
  const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  return d.toDateString() === now.toDateString() ? hm : `${d.getMonth() + 1}-${d.getDate()} ${hm}`;
};
const handleNewChat = () => {
  chatStore.newConversation();
  messages.value = [{ role: 'assistant', content: '你好，我是鼠鼠小助手，有什么需要我帮忙的吗？' }];
  disposeCharts();
  closeFilePreview();
  sidebarVisible.value = false;
  nextTick(scrollToBottom);
};
const handleSelectConversation = async (conv) => {
  chatStore.selectConversation(conv.threadId);
  disposeCharts();
  closeFilePreview();
  sidebarVisible.value = false;
  messages.value = [{ role: 'assistant', content: '' }];
  const res = await chatStore.fetchMessages(conv.threadId);
  if (res.success) {
    messages.value = res.data.flatMap((m) => {
      const parsed = parseStoredMessage(m.content);
      const historyMessages = [];
      if (m.role === 'user' && parsed.files.length) historyMessages.push(...parsed.files);
      if (parsed.content || !parsed.files.length) {
        historyMessages.push({
          role: m.role,
          content: parsed.content,
          charts: parsed.charts,
        });
      }
      return historyMessages;
    });
    if (!messages.value.length) messages.value = [{ role: 'assistant', content: '（空会话）' }];
  } else {
    messages.value = [{ role: 'assistant', content: `加载失败：${res.message}` }];
  }
  await nextTick();
  renderAllCharts();
  scrollToBottom();
};
const confirmDeleteConversation = async (conv) => {
  if (isLoading.value) {
    showDialog({ title: '提示', message: 'AI 正在回复中，请稍后再删除该会话' });
    return;
  }
  try {
    const action = await showDialog({
      title: '提示',
      message: `确定删除会话「${conv.title || '新会话'}」吗？删除后不可恢复。`,
      showCancelButton: true,
    });
    if (action !== 'confirm') return;
    const res = await chatStore.deleteConversation(conv.threadId);
    if (!res.success) {
      showDialog({ title: '提示', message: res.message || '删除会话失败' });
      return;
    }
    if (chatStore.activeThreadId === conv.threadId) {
      chatStore.activeThreadId = null;
      messages.value = [{ role: 'assistant', content: '会话已删除，可以开始新对话～' }];
    }
  } catch (e) {
    console.error('删除会话失败:', e);
  }
};
const sendMessage = async () => {
  if (isLoading.value) return;
  const typedMessage = userInput.value.trim();
  const pendingFiles = messages.value.filter((message) => message.role === 'file' && !message.sent);
  const fileContext = pendingFiles.map(buildFileContext).join('');
  const modelMessage = [fileContext.trim(), typedMessage].filter(Boolean).join('\n\n');
  const imageMessages = messages.value
    .map((message, index) => ({ message, index }))
    .filter(({ message }) => message.role === 'image');
  const attachmentIds = imageMessages.map(({ message }) => message.attachmentId).filter(Boolean);
  const imageMarkdown = imageMessages
    .map(({ message }) => `![${message.name.replace(/[\[\]]/g, '')}](${message.previewUrl})`)
    .join('\n');
  const requestContent = [imageMarkdown, modelMessage].filter(Boolean).join('\n\n');
  const userContent = [imageMarkdown, typedMessage].filter(Boolean).join('\n\n');
  if (!requestContent) return;

  for (const { index } of imageMessages.sort((a, b) => b.index - a.index)) {
    messages.value.splice(index, 1);
  }
  pendingFiles.forEach((file) => { file.sent = true; });
  if (userContent) messages.value.push({ role: 'user', content: userContent });
  userInput.value = '';
  messages.value.push({
    role: 'assistant',
    content: '',
    charts: [],
    traces: [],
    done: false,
    status: 'pending',
  }); await nextTick(); scrollToBottom();
  isLoading.value = true;
  const request = { controller: new AbortController(), reader: null, message: messages.value[messages.value.length - 1], stopped: false };
  activeRequest.value = request;
  try {
    const threadId = chatStore.activeThreadId;
    const headers = { 'Content-Type': 'application/json' };
    if (userStore.token) headers.Authorization = userStore.token;
    const res = await fetch(aiChatConfig.apiEndpoint, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        messages: [{ role: 'user', content: requestContent }],
        thread_id: threadId,
        attachment_ids: attachmentIds,
      }),
      signal: request.controller.signal,
    });
    if (await handleUnauthorizedResponse(res)) return;
    if (!res.ok) throw new Error(`请求失败，状态码: ${res.status}`);
    const reader = res.body.getReader(); request.reader = reader;
    const decoder = new TextDecoder(); let buf = '', ai = '';
    const lastIdx = () => messages.value.length - 1;
    let streamFinished = false;
    readStream:
    while (true) {
      const { done, value } = await reader.read(); if (done) break;
      if (request.stopped) break;
      buf += decoder.decode(value, { stream: true }); const lines = buf.split('\n'); buf = lines.pop() || '';
      for (const line of lines) {
        if (request.stopped) break;
        if (!line.startsWith('data: ')) continue;
        const raw = line.slice(6);
        if (raw === '[DONE]') {
          streamFinished = true;
          break readStream;
        }
        try {
          const j = JSON.parse(raw);
          switch (j.type) {
            case 'session_start':
              chatStore.activeThreadId = j.thread_id;
              chatStore.upsertConversation({
                threadId: j.thread_id,
                title: j.title || (typedMessage || pendingFiles[0]?.name || '文件对话').slice(0, 30),
                messageCount: 1,
                updatedAt: new Date().toISOString(),
              });
              break;
            case 'tool_start':
              messages.value[lastIdx()].traces.push({ tool_id: j.tool_id, tool_name: j.tool_name, tool_label: j.tool_label || j.tool_name, tool_args: j.tool_args, result: '', expanded: false, done: false });
              await nextTick(); scrollToBottom();
              break;
            case 'tool_end':
              { const trace = messages.value[lastIdx()].traces.find(t => t.tool_id === j.tool_id);
                if (trace) { trace.result = j.result; trace.done = true; } }
              await nextTick(); scrollToBottom();
              break;
            case 'chart':
              messages.value[lastIdx()].charts.push(j.chart);
              await nextTick();
              renderAllCharts();
              scrollToBottom();
              break;
            case 'text_delta':
              messages.value[lastIdx()].status = 'generating';
              ai += j.content; messages.value[lastIdx()].content = ai; await nextTick(); scrollToBottom();
              break;
            case 'done':
              messages.value[lastIdx()].done = true;
              messages.value[lastIdx()].status = 'done';
              streamFinished = true;
              break readStream;
            case 'error':
              messages.value[lastIdx()].content = j.message || 'AI 服务暂时不可用，请稍后重试。';
              messages.value[lastIdx()].done = true;
              messages.value[lastIdx()].status = 'error';
              break;
          }
        } catch (e) { console.error(e) }
      }
    }
    if (streamFinished && request.reader) {
      await request.reader.cancel().catch(() => {});
    }
    if (!ai && !request.stopped && request.message.status !== 'error') {
      messages.value[lastIdx()].content = '抱歉，AI 暂时无法生成回复，请稍后再试。';
      messages.value[lastIdx()].status = 'error';
    }
  } catch (e) {
    if (!request.stopped && e.name !== 'AbortError') {
      request.message.content = `发生错误: ${e.message}`;
      request.message.status = 'error';
    }
  } finally {
    if (activeRequest.value === request) {
      activeRequest.value = null;
      isLoading.value = false;
    }
    request.message.done = true;
    if (request.message.status === 'pending' || request.message.status === 'generating') {
      request.message.status = request.stopped ? 'stopped' : 'done';
    }
    await nextTick(); scrollToBottom();
  }
};
const stopGeneration = async () => {
  const request = activeRequest.value;
  if (!request || request.stopped) return;
  request.stopped = true;
  request.message.done = true;
  request.message.status = 'stopped';
  request.message.content = request.message.content
    ? `${request.message.content}\n\n> 已停止生成。`
    : '已停止生成。';
  request.controller.abort();
  if (request.reader) await request.reader.cancel();
  await nextTick(); scrollToBottom();
};
const resizeCharts = () => {
  chartInstances.forEach((chart) => chart.resize());
};
watch(messages, () => nextTick(scrollToBottom), { deep: true });
onMounted(async () => {
  window.addEventListener('resize', resizeCharts);
  scrollToBottom();
  await chatStore.fetchConversations();
});
onActivated(() => renderAllCharts());
onBeforeUnmount(() => {
  window.removeEventListener('resize', resizeCharts);
  if (activeRequest.value) {
    activeRequest.value.stopped = true;
    activeRequest.value.controller.abort();
    activeRequest.value.reader?.cancel();
  }
  disposeCharts();
});
</script>
<style scoped>
.chat-page {
  display: flex;
  flex-direction: column;
  height: 100vh;
  padding-top: 46px;
  padding-bottom: 50px;
  box-sizing: border-box;
  font-family: "Ma Shan Zheng", "ZCOOL KuaiLe", "PingFang SC", cursive;
}
:deep(.van-nav-bar) { background: transparent !important; border-bottom: none !important; }
:deep(.van-nav-bar__title) {
  color: var(--text-primary);
  font-family: "Ma Shan Zheng", "ZCOOL KuaiLe", cursive;
  font-size: 20px;
}
.chat-content { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.messages {
  flex: 1; overflow-y: auto; padding: 16px 14px; background: transparent;
  scroll-behavior: smooth;
}

/* ----- 云朵气泡通用 ----- */
.msg {
  margin-bottom: 20px;
  max-width: 80%;
  animation: cloudFloat 0.5s var(--ease-smooth) both;
  position: relative;
}
.user { margin-left: auto; }
.ai { margin-right: auto; }

/* 文件气泡：用户侧，右对齐，可点击删除 */
.file {
  width: fit-content;
  margin-left: auto;
  cursor: pointer;
  transition: opacity 0.2s;
}
.file:hover { opacity: 0.7; }

.image {
  margin-left: auto;
  cursor: pointer;
  transition: opacity 0.2s;
}
.image:hover { opacity: 0.82; }

.msg-label {
  font-size: 12px;
  font-weight: 400;
  color: var(--text-tertiary);
  margin-bottom: 6px;
  padding-left: 4px;
  letter-spacing: 0.08em;
  font-family: "Ma Shan Zheng", cursive;
}
.user .msg-label, .file .msg-label { text-align: right; padding-right: 4px; }

/* ----- 云朵气泡本体 ----- */
.msg-bubble {
  position: relative;
  padding: 14px 18px;
  word-break: break-word;
  font-size: 16px;
  line-height: 1.8;
  letter-spacing: 0.03em;
  transition: transform 0.2s var(--ease-smooth);
}
.msg-text.is-collapsed {
  position: relative;
  max-height: 300px;
  overflow: hidden;
}
.msg-text.is-collapsed::after {
  content: '';
  position: absolute;
  right: 0;
  bottom: 0;
  left: 0;
  height: 72px;
  pointer-events: none;
}
.ai .msg-text.is-collapsed::after {
  background: linear-gradient(180deg, rgba(255, 248, 231, 0), #fff8e7 82%);
}
.user .msg-text.is-collapsed::after {
  background: linear-gradient(180deg, rgba(232, 244, 253, 0), #e8f4fd 82%);
}
.message-collapse-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  margin: 10px auto 0;
  padding: 4px 10px;
  border: 1px solid rgba(120, 140, 170, 0.18);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.42);
  color: #5a6f8f;
  font: inherit;
  font-size: 12px;
  line-height: 1.4;
  cursor: pointer;
}
.message-collapse-btn:hover {
  background: rgba(255, 255, 255, 0.65);
}

/* AI 云朵（左侧）—— 暖白蓬松云 */
.ai .msg-bubble {
  background: linear-gradient(145deg, #fff8e7, #fffdf5);
  color: #5a4a3a;
  border-radius: 28px 28px 28px 6px;
  box-shadow:
    0 6px 20px rgba(255, 200, 100, 0.15),
    0 2px 6px rgba(0, 0, 0, 0.04);
  border: 1px solid rgba(255, 220, 150, 0.25);
}
.ai .msg-bubble::before {
  content: '';
  position: absolute;
  left: -8px;
  bottom: 10px;
  width: 16px;
  height: 14px;
  background: radial-gradient(circle at 6px 8px, #fff8e7 60%, transparent 61%);
  filter: drop-shadow(-1px 1px 2px rgba(255, 200, 100, 0.1));
}
.stop-generation-btn {
  display: block;
  margin-top: 8px;
  margin-left: 4px;
  box-shadow: 0 3px 10px rgba(255, 152, 0, 0.2);
}

/* 用户云朵（右侧）—— 蓝天白云 */
.user .msg-bubble {
  background: linear-gradient(145deg, #e8f4fd, #d4eaf7);
  color: #2a3a5a;
  border-radius: 28px 28px 6px 28px;
  box-shadow:
    0 6px 20px rgba(100, 180, 255, 0.15),
    0 2px 6px rgba(0, 0, 0, 0.04);
  border: 1px solid rgba(150, 200, 255, 0.25);
}
.user .msg-bubble::before {
  content: '';
  position: absolute;
  right: -8px;
  bottom: 10px;
  width: 16px;
  height: 14px;
  background: radial-gradient(circle at 10px 8px, #e8f4fd 60%, transparent 61%);
  filter: drop-shadow(1px 1px 2px rgba(100, 180, 255, 0.1));
}

/* 文件云朵气泡 —— 浅绿，用户侧右对齐 */
.file .msg-bubble {
  background: linear-gradient(145deg, #e8fae8, #d4f0d4);
  color: #2a5a3a;
  border-radius: 28px 28px 6px 28px;
  box-shadow:
    0 6px 20px rgba(100, 200, 100, 0.12),
    0 2px 6px rgba(0, 0, 0, 0.04);
  border: 1px solid rgba(100, 200, 100, 0.2);
  padding: 10px 16px;
  font-size: 14px;
}
.file-bubble {
  display: flex;
  align-items: center;
  gap: 10px;
  width: min(300px, 70vw);
  max-width: 100%;
}
.file-icon {
  flex-shrink: 0;
  color: #3a8a5a;
  font-size: 22px;
}
.file-info {
  flex: 1;
  min-width: 0;
}
.file-name {
  overflow: hidden;
  color: #245a38;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.file-meta {
  margin-top: 2px;
  color: #5f876c;
  font-size: 12px;
}
.file-remove {
  flex-shrink: 0;
  padding: 6px;
  color: #6b8f78;
  font-size: 16px;
}
.file .msg-bubble::before {
  content: '';
  position: absolute;
  right: -8px;
  bottom: 10px;
  width: 16px;
  height: 14px;
  background: radial-gradient(circle at 10px 8px, #e8fae8 60%, transparent 61%);
  filter: drop-shadow(1px 1px 2px rgba(100, 200, 100, 0.08));
}

.image-bubble {
  padding: 8px !important;
  background: linear-gradient(145deg, #edf7ff, #dfeffb) !important;
  border: 1px solid rgba(100, 180, 255, 0.28) !important;
}
.image-bubble::before { display: none; }
.pending-image {
  display: block;
  width: min(220px, 58vw);
  max-height: 240px;
  object-fit: cover;
  border-radius: 18px;
}
.image-caption {
  margin-top: 6px;
  padding: 0 4px 2px;
  color: #5a5a7a;
  font-size: 12px;
  text-align: center;
}

.file-preview {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: linear-gradient(180deg, #fffdf6, #fff8ea);
}
.file-preview-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 16px 18px;
  border-bottom: 1px solid rgba(255, 200, 150, 0.25);
}
.file-preview-heading {
  flex: 1;
  min-width: 0;
}
.file-preview-title {
  overflow: hidden;
  color: var(--text-primary);
  font-size: 16px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.file-preview-meta {
  margin-top: 3px;
  color: var(--text-tertiary);
  font-size: 12px;
}
.file-preview-close {
  flex-shrink: 0;
  padding: 6px;
  color: var(--text-secondary);
  font-size: 20px;
}
.file-preview-content {
  flex: 1;
  overflow: auto;
  margin: 0;
  padding: 18px;
  color: var(--text-primary);
  font-family: "JetBrains Mono", "Fira Code", "Consolas", monospace;
  font-size: 13px;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
}
.file-preview-footer {
  padding: 12px 18px 18px;
  border-top: 1px solid rgba(255, 200, 150, 0.2);
}

/* 云朵悬停效果 */
.msg-bubble:hover {
  transform: translateY(-2px) scale(1.01);
}

/* 输入区域 */
.input-area {
  padding: 4px 12px 10px;
  background: transparent;
  border-top: 1px solid rgba(255, 200, 150, 0.2);
}
/* 上传按钮栏 */
.upload-bar {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-bottom: 4px;
}
.upload-btn {
  height: 32px;
  padding: 0 10px;
  border-radius: 16px;
  background: rgba(255, 248, 235, 0.4);
  border: 1px solid rgba(255, 200, 150, 0.2);
  font-size: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-secondary);
}
.rag-upload-btn {
  color: #5b6ee1;
  font-weight: 600;
}
.image-upload-btn {
  color: #2f855a;
  font-weight: 600;
}
.input-row {
  display: flex;
  gap: 6px;
  align-items: flex-end;
}
.chat-input { flex: 1; }
.chat-input :deep(.van-field__body) {
  background: rgba(255, 248, 235, 0.4);
  border-radius: 24px;
  border: 1px solid rgba(255, 200, 150, 0.2);
  backdrop-filter: blur(4px);
}
.send-btn { align-self: flex-end; flex-shrink: 0; }

.chart-container {
  width: 100%;
  min-height: 300px;
  margin-top: 12px;
}

/* Markdown 样式适配云朵 */
.msg-bubble pre {
  background: rgba(255, 255, 255, 0.5);
  backdrop-filter: blur(4px);
  padding: 12px;
  border-radius: 16px;
  overflow-x: auto;
  margin: 10px 0;
  border: 1px solid rgba(255, 220, 150, 0.15);
  font-family: "JetBrains Mono", "Fira Code", "Consolas", monospace;
  font-size: 14px;
}
.msg-bubble code {
  background: rgba(255, 220, 150, 0.2);
  padding: 2px 8px;
  border-radius: 6px;
  font-family: "JetBrains Mono", "Fira Code", "Consolas", monospace;
  font-size: 14px;
}
.user .msg-bubble code { background: rgba(255, 255, 255, 0.3); }
.msg-bubble :deep(img) {
  display: block !important;
  width: auto !important;
  max-width: min(230px, 56vw) !important;
  max-height: 280px !important;
  height: auto !important;
  object-fit: contain;
  margin: 4px auto;
  border-radius: 16px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.06);
  cursor: zoom-in;
}
.user .msg-bubble :deep(img) {
  max-width: min(210px, 52vw) !important;
  max-height: 260px !important;
}
.msg-bubble :deep(p) { margin: 6px 0; }
.msg-bubble :deep(ul), .msg-bubble :deep(ol) { padding-left: 20px; margin: 6px 0; }
.msg-bubble :deep(a) {
  color: #4060d0;
  text-decoration: underline;
  text-underline-offset: 2px;
}

/* 打字动画 */
.typing { display: flex; gap: 6px; padding: 6px 0; align-items: center; }
.typing span {
  height: 10px; width: 10px;
  background: #ffd54f;
  border-radius: 50%;
  display: inline-block;
  animation: cloudBounce 1.4s infinite ease-in-out;
  box-shadow: 0 2px 6px rgba(255, 200, 100, 0.3);
}
.typing span:nth-child(2) { animation-delay: 0.2s; }
.typing span:nth-child(3) { animation-delay: 0.4s; }

/* 云朵飘入动画 */
@keyframes cloudFloat {
  from {
    opacity: 0;
    transform: translateY(12px) scale(0.95);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

@keyframes cloudBounce {
  0%, 60%, 100% { transform: translateY(0); }
  30% { transform: translateY(-8px); }
}

/* ----- 左侧会话栏 ----- */
.conv-toggle { cursor: pointer; color: var(--text-primary); }
.conv-sidebar {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: linear-gradient(180deg, #fffdf6, #fff8ea);
}
.conv-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-bottom: 1px solid rgba(255, 200, 150, 0.2);
}
.conv-header-title {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
  font-family: "Ma Shan Zheng", "ZCOOL KuaiLe", cursive;
  letter-spacing: 0.06em;
}
.conv-list {
  flex: 1;
  overflow-y: auto;
  padding: 10px 8px;
}
.conv-item {
  position: relative;
  padding: 12px 14px;
  padding-right: 40px;
  border-radius: 16px;
  margin-bottom: 6px;
  cursor: pointer;
  border: 1px solid transparent;
  transition: background 0.2s var(--ease-smooth), transform 0.2s var(--ease-smooth);
}
.conv-item:hover { background: rgba(255, 220, 150, 0.15); }
.conv-item.active {
  background: linear-gradient(145deg, #fff3d6, #ffe9bd);
  border-color: rgba(255, 200, 100, 0.35);
}
.conv-title {
  font-size: 15px;
  color: var(--text-primary);
  font-family: "Ma Shan Zheng", "ZCOOL KuaiLe", cursive;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  margin-bottom: 4px;
}
.conv-meta { font-size: 12px; color: var(--text-tertiary); }

.conv-del-btn {
  position: absolute;
  top: 50%;
  right: 10px;
  transform: translateY(-50%);
  width: 22px;
  height: 22px;
  padding: 0;
  border-radius: 50%;
  opacity: 0.65;
  border: none;
}

/* ── 工具轨迹卡片 ── */
.tool-traces { margin-bottom: 8px; }
.trace-card {
  background: rgba(255, 248, 235, 0.6);
  border: 1px solid rgba(255, 200, 100, 0.2);
  border-radius: 12px;
  margin-bottom: 6px;
  overflow: hidden;
  backdrop-filter: blur(4px);
}
.trace-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  cursor: pointer;
  font-size: 13px;
  user-select: none;
}
.trace-icon { font-size: 14px; }
.trace-label { font-weight: 600; color: var(--text-primary); }
.trace-args { color: var(--text-secondary); font-size: 12px; }
.trace-status { margin-left: auto; font-size: 12px; }
.trace-status.running { color: #ff9800; }
.trace-status:not(.running) { color: #4caf50; }
.trace-detail { padding: 0 12px 8px; }
.trace-result {
  font-size: 12px;
  color: var(--text-secondary);
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 200px;
  overflow-y: auto;
  margin: 0;
}
</style>
