<script setup>
import { computed, ref } from 'vue'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api'
const STORAGE_KEY = 'aligo-travel-workspace'
const input = ref('')
const isSending = ref(false)
const apiOnline = ref(false)
const activeView = ref('assistant')
const activeTab = ref('对话')
const sessionId = ref(createId())
const userId = 'travel-user'
const toolCalls = ref([])
const userPreferences = ref([])
const itinerary = ref(null)
const agentSteps = ref(makeWaitingSteps())
const messages = ref([welcomeMessage()])
const history = ref(loadWorkspace())
const suggestions = ['查北京下周天气', '差旅住宿标准是什么？', '我喜欢住安静的酒店']
const activeMessageCount = computed(() => messages.value.length)
const recentConversations = computed(() => history.value.slice(0, 6))
const savedTrips = computed(() => history.value.flatMap((item) => item.trip ? [{ ...item.trip, conversationId: item.id }] : []))

function createId() { return `session-${Date.now()}-${Math.random().toString(36).slice(2, 7)}` }
function welcomeMessage() { return { role: 'assistant', time: '刚刚', content: '你好，我是水精灵，您的差旅助手。告诉我出发地、目的地和出行时间，我可以帮您规划行程、查询差旅政策或记录出行偏好。' } }
function makeWaitingSteps() { return [
  { name: '意图识别', detail: '等待输入', state: 'waiting' }, { name: '事项收集', detail: '等待意图识别', state: 'waiting' },
  { name: '偏好管理', detail: '按需执行', state: 'waiting' }, { name: '知识查询', detail: '按需检索知识库', state: 'waiting' },
  { name: '实时工具', detail: '按需查询外部信息', state: 'waiting' }, { name: '行程规划', detail: '按需生成方案', state: 'waiting' },
] }
function loadWorkspace() { try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]') } catch { return [] } }
function persistWorkspace() { localStorage.setItem(STORAGE_KEY, JSON.stringify(history.value.slice(0, 20))) }
function saveCurrentConversation() {
  const userMessage = messages.value.find((item) => item.role === 'user')
  if (!userMessage) return
  const item = { id: sessionId.value, title: userMessage.content.slice(0, 24), messages: messages.value, trip: itinerary.value, updatedAt: Date.now() }
  history.value = [item, ...history.value.filter((old) => old.id !== item.id)].sort((a, b) => b.updatedAt - a.updatedAt)
  persistWorkspace()
}
function newConversation() { saveCurrentConversation(); sessionId.value = createId(); messages.value = [welcomeMessage()]; itinerary.value = null; toolCalls.value = []; userPreferences.value = []; agentSteps.value = makeWaitingSteps(); activeView.value = 'assistant' }
function openConversation(item) { if (!item) return; sessionId.value = item.id; messages.value = item.messages || [welcomeMessage()]; itinerary.value = item.trip || null; activeView.value = 'assistant' }
function removeConversation(id) { history.value = history.value.filter((item) => item.id !== id); persistWorkspace(); if (sessionId.value === id) newConversation() }
function selectSuggestion(text) { input.value = text; activeView.value = 'assistant' }
function setStep(index, detail, state = 'done') { if (agentSteps.value[index]) agentSteps.value[index] = { ...agentSteps.value[index], detail, state } }

async function sendMessage() {
  const query = input.value.trim()
  if (!query || isSending.value) return
  messages.value.push({ role: 'user', time: '刚刚', content: query }); input.value = ''; isSending.value = true; agentSteps.value = makeWaitingSteps(); setStep(0, '正在分析你的需求', 'running')
  try {
    const response = await fetch(`${API_BASE_URL}/chat`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: query, user_id: userId, session_id: sessionId.value }) })
    if (!response.ok) throw new Error(`API 请求失败（${response.status}）`)
    const data = await response.json(); apiOnline.value = true
    const intentLabel = data.intent?.intents?.map((item) => item.type).join(' + ') || data.intent?.intent || '已处理'; const result = data.skill_result || {}; const realtime = result.realtime
    if (realtime) { toolCalls.value.unshift({ agent: 'RealTimeQueryAgent', server: realtime.mcp_server || 'travel-tools', tool: realtime.tool || '实时工具', status: realtime.success ? '调用成功' : '调用失败', detail: realtime.error || realtime.text || '已返回结果', source: realtime.data_source || realtime.source || '' }); setStep(4, `${realtime.tool || '实时工具'} · ${realtime.success ? '调用成功' : '参数待补充'}`) }
    if (result.trip?.itinerary?.itinerary) { itinerary.value = result.trip.itinerary.itinerary; setStep(5, '已生成行程方案') }
    if (result.preference?.current_preferences) userPreferences.value = Object.entries(result.preference.current_preferences).map(([key, value]) => `${key}：${Array.isArray(value) ? value.join('、') : value}`)
    setStep(0, `已识别：${intentLabel}`); if (result.trip) setStep(1, '已提取出行事项'); if (result.preference) setStep(2, '已更新用户偏好'); if (result.policy) setStep(3, '已检索差旅知识库')
    messages.value.push({ role: 'assistant', time: '刚刚', content: data.answer, meta: `意图：${intentLabel} · DeepSeek API 返回` }); saveCurrentConversation()
  } catch (error) { apiOnline.value = false; messages.value.push({ role: 'assistant', time: '刚刚', content: `暂时无法完成请求：${error.message}。请检查后端服务和服务器端 API Key。`, meta: 'API 请求失败' }); setStep(0, '请求失败，请检查服务状态', 'waiting') }
  finally { isSending.value = false }
}
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand"><span class="brand-mark">水</span><span>水精灵</span></div><div class="brand-subtitle">智能差旅工作台</div>
      <button class="new-chat" @click="newConversation"><span>＋</span> 新建对话</button>
      <div class="side-section"><div class="side-label">工作台</div><button class="side-item" :class="{ active: activeView === 'assistant' }" @click="activeView = 'assistant'"><span class="side-icon">◌</span> 差旅助手</button><button class="side-item" :class="{ active: activeView === 'trips' }" @click="activeView = 'trips'"><span class="side-icon">▤</span> 我的行程 <span class="side-count">{{ savedTrips.length }}</span></button><button class="side-item" :class="{ active: activeView === 'knowledge' }" @click="activeView = 'knowledge'"><span class="side-icon">⌁</span> 知识中心</button></div>
      <div class="side-section history-section"><div class="side-label">最近对话</div><button v-if="!recentConversations.length" class="history-empty">暂无对话记录</button><button v-for="item in recentConversations" :key="item.id" class="history-item" @click="openConversation(item)"><span>{{ item.title }}</span><i title="删除对话" @click.stop="removeConversation(item.id)">×</i></button></div>
      <div class="sidebar-footer"><div class="profile"><div class="avatar">周</div><div><strong>周涛</strong><span>个人工作区</span></div><span class="more">···</span></div></div>
    </aside>
    <main class="main-content">
      <header class="topbar"><div><span class="eyebrow">PERSONAL TRAVEL COPILOT</span><h1>{{ activeView === 'assistant' ? '差旅助手' : activeView === 'trips' ? '我的行程' : '知识中心' }}</h1></div><div class="top-actions"><button class="avatar small">周</button></div></header>
      <div v-if="activeView === 'assistant'" class="workspace">
        <section class="chat-column"><div class="tabbar"><button :class="{ selected: activeTab === '对话' }" @click="activeTab = '对话'">对话</button><button :class="{ selected: activeTab === '执行记录' }" @click="activeTab = '执行记录'">执行记录 <span class="tab-badge">{{ activeMessageCount }}</span></button></div>
          <div v-if="activeTab === '对话'" class="chat-list"><article v-for="(message, index) in messages" :key="index" class="message" :class="message.role"><div v-if="message.role === 'assistant'" class="message-avatar">水</div><div class="message-body"><div class="message-meta"><span>{{ message.role === 'assistant' ? '水精灵' : '你' }}</span><span>{{ message.time }}</span></div><div class="message-text">{{ message.content }}</div><div v-if="message.meta" class="message-tag">{{ message.meta }}</div></div></article></div>
          <div v-else class="execution-log"><div v-for="step in agentSteps" :key="step.name"><strong>{{ step.name }}</strong><span>{{ step.detail }}</span></div></div>
          <div class="suggestions"><button v-for="suggestion in suggestions" :key="suggestion" @click="selectSuggestion(suggestion)">{{ suggestion }}</button></div><div class="composer"><textarea v-model="input" placeholder="描述你的出行需求，或询问差旅政策..." @keydown.enter.exact.prevent="sendMessage"></textarea><div class="composer-bottom"><span class="composer-hint">Enter 发送 · Shift + Enter 换行</span><button class="send-btn" :disabled="isSending" @click="sendMessage">{{ isSending ? '处理中' : '发送' }} <span>↑</span></button></div></div>
        </section>
        <aside class="insight-column"><div class="panel-heading"><div><span class="eyebrow">LIVE WORKFLOW</span><h2>执行状态</h2></div><span class="live-pill"><i></i> LIVE</span></div><div class="agent-list"><div v-for="(step, index) in agentSteps" :key="step.name" class="agent-step"><div class="step-line"><span class="step-number" :class="step.state">{{ step.state === 'done' ? '✓' : index + 1 }}</span><span v-if="index < agentSteps.length - 1" class="connector"></span></div><div><strong>{{ step.name }}</strong><p>{{ step.detail }}</p></div></div></div>
          <div v-if="toolCalls.length" class="tool-call-panel"><div class="tool-call-heading"><span>最近工具调用</span><small>{{ toolCalls.length }} 次</small></div><div v-for="(call, index) in toolCalls.slice(0, 4)" :key="`${call.tool}-${index}`" class="tool-call-card"><div class="tool-call-top"><strong>{{ call.tool }}</strong><span :class="{ failed: !call.status.includes('成功') }">{{ call.status }}</span></div><p>{{ call.agent }} → {{ call.server }}</p><small>{{ call.detail }}</small><small v-if="call.source">来源：{{ call.source }}</small></div></div>
          <div class="panel-divider"></div><div class="panel-heading compact"><div><span class="eyebrow">GENERATED PLAN</span><h2>行程方案</h2></div><button class="text-button" @click="activeView = 'trips'">查看详情 ↗</button></div><div v-if="itinerary" class="plan-card"><div class="plan-top"><div><h3>{{ itinerary.title || '未命名行程' }}</h3><p>{{ itinerary.route || itinerary.duration || '已由行程规划 Agent 生成' }}</p></div><span class="plan-icon">✦</span></div><div v-for="(day, index) in itinerary.daily_plans || []" :key="index" class="day-card"><div class="day-label"><span>DAY {{ index + 1 }}</span><small>{{ day.date || '' }}</small></div><strong>{{ day.title || day.summary || `第 ${index + 1} 天` }}</strong><ul><li v-for="(item, itemIndex) in (day.items || day.activities || [day])" :key="itemIndex">{{ typeof item === 'string' ? item : JSON.stringify(item) }}</li></ul></div></div><div v-else class="empty-card">完成一次行程规划后，生成的方案会显示在这里。</div>
          <div class="panel-divider"></div><div class="panel-heading compact"><div><span class="eyebrow">MEMORY</span><h2>我的偏好</h2></div><span class="text-button">{{ userPreferences.length }} 条</span></div><div class="preference-list"><span v-if="!userPreferences.length" class="empty-inline">暂无已加载偏好</span><span v-for="preference in userPreferences" :key="preference" class="preference-chip">{{ preference }}</span></div><div class="source-note"><span>⌁</span><div><strong>知识来源已接入</strong><p>差旅政策 · 城市攻略 · FAQ</p></div></div>
        </aside>
      </div>
      <section v-else-if="activeView === 'trips'" class="content-page"><div class="page-heading"><span class="eyebrow">TRIP LIBRARY</span><h2>我的行程</h2><p>由真实对话生成的行程会自动保存在这里。</p></div><div v-if="!savedTrips.length" class="empty-page">还没有已生成的行程。去差旅助手描述一次出差需求吧。</div><div v-for="trip in savedTrips" :key="trip.conversationId" class="trip-library-card"><div><span class="eyebrow">SAVED ITINERARY</span><h3>{{ trip.title || '未命名行程' }}</h3><p>{{ trip.route || trip.duration || '已生成方案' }}</p></div><button class="text-button" @click="openConversation(history.find((item) => item.id === trip.conversationId))">打开对话 ↗</button></div></section>
      <section v-else class="content-page"><div class="page-heading"><span class="eyebrow">KNOWLEDGE CENTER</span><h2>知识中心</h2><p>差旅助手会在相关问题中自动检索这些资料。</p></div><div class="knowledge-grid"><article><span>01</span><h3>企业差旅政策</h3><p>住宿、交通、报销和审批相关规则。</p></article><article><span>02</span><h3>城市出行攻略</h3><p>城市交通、机场车站和商务区信息。</p></article><article><span>03</span><h3>常见问题 FAQ</h3><p>企业差旅流程与使用说明。</p></article></div></section>
    </main>
  </div>
</template>
