<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'

import SupportDesk from './components/SupportDesk.vue'
const showDesk = ref(false)
const props = defineProps({ api: Function, kb: Object, session: Object })
const emit = defineEmits(['switch', 'logout', 'expired'])
const controller = new AbortController()
onBeforeUnmount(() => controller.abort())
const { signal } = controller
const prefix = `kbs/${encodeURIComponent(props.kb.id)}/`
async function call(method, path, options = {}) {
  try {
    return (await props.api({ method, url: prefix + path, signal, ...options })).data
  } catch (err) {
    if (!signal.aborted && err.response?.status === 401) emit('expired')
    throw err
  }
}
const documents = ref([]), total = ref(0), offset = ref(0), limit = 50
const selectedDocumentId = ref(''), question = ref(''), fileInput = ref(null)
const loadingDocs = ref(false), uploading = ref(false), deletingId = ref(''), chatting = ref(false)
const notice = ref(''), errorMessage = ref(''), failedJob = ref(null)
const messages = ref([{role: 'assistant', content: `你正在查询「${props.kb.name}」。回答中的引用仅来自这个知识库。`, sources: []}])
const detail = e => e.response?.data?.detail || e.message || '请求失败'

async function loadDocuments(next = offset.value) {
  loadingDocs.value = true
  try {
    const data = await call('get', 'documents', {params: {limit, offset: next}})
    offset.value = next; documents.value = data.documents; total.value = data.document_count
  } catch (e) { errorMessage.value = `加载文档失败：${detail(e)}` }
  finally { loadingDocs.value = false }
}
async function track(job) {
  while (!signal.aborted && ['queued', 'running'].includes(job.status)) {
    notice.value = `${job.filename}：${job.status === 'queued' ? '已保存，等待入库' : '正在解析并建立索引'}…`
    await new Promise(resolve => setTimeout(resolve, 1200))
    if (signal.aborted) return
    job = await call('get', `jobs/${job.job_id}`)
  }
  if (signal.aborted) return
  if (job.status === 'failed') {
    failedJob.value = job; notice.value = ''; errorMessage.value = `${job.filename}：${job.error}`
  } else {
    notice.value = job.is_active ? `${job.filename}：已发布版本 ${job.version}，${job.indexed_count} 个文本块。` : `${job.filename}：相同内容已在历史版本 ${job.version} 中，不会替换当前版本。`
    await loadDocuments(0)
  }
}
async function uploadDocument(event) {
  const file = event.target.files?.[0]; event.target.value = ''
  if (!file || !props.kb.can_write) return
  if (!file.name.toLowerCase().endsWith('.pdf') || file.size > 10 * 1024 * 1024) {
    errorMessage.value = '请上传 10 MB 以内的 PDF 文件。'; return
  }
  uploading.value = true; failedJob.value = null; errorMessage.value = ''; notice.value = '正在上传…'
  const data = new FormData(); data.append('file', file)
  try { await track(await call('post', 'documents/upload', {data})) }
  catch (e) { errorMessage.value = `上传或查询进度失败：${detail(e)}。可重传同一文件恢复进度。`; notice.value = '' }
  finally { uploading.value = false }
}
async function retryJob() {
  const job = failedJob.value
  if (!job || uploading.value) return
  uploading.value = true; errorMessage.value = ''; failedJob.value = null
  try { await track(await call('post', `jobs/${job.job_id}/retry`)) }
  catch (e) { errorMessage.value = `重试失败：${detail(e)}`; failedJob.value = job }
  finally { uploading.value = false }
}
async function deleteDocument(doc) {
  if (!props.kb.can_write || !window.confirm(`确定删除「${doc.filename}」及其所有版本吗？`)) return
  deletingId.value = doc.document_id; errorMessage.value = ''
  try {
    await call('delete', `documents/${doc.document_id}`)
    if (selectedDocumentId.value === doc.document_id) selectedDocumentId.value = ''
    notice.value = `已下线 ${doc.filename}。`; await loadDocuments(0)
  } catch (e) { errorMessage.value = `删除失败：${detail(e)}` }
  finally { deletingId.value = '' }
}
async function sendQuestion() {
  const text = question.value.trim()
  if (!text || chatting.value) return
  messages.value.push({role: 'user', content: text, sources: []})
  question.value = ''; chatting.value = true; errorMessage.value = ''
  try {
    const data = {question: text, require_local: props.kb.policy === 'local_only'}
    if (selectedDocumentId.value) data.document_id = selectedDocumentId.value
    const result = await call('post', 'chat', {data})
    messages.value.push({role: 'assistant', content: result.answer, sources: result.sources})
  } catch (e) { messages.value.push({role: 'assistant', content: `请求失败：${detail(e)}`, sources: []}) }
  finally { chatting.value = false }
}
function handleEnter(e) { if (!e.shiftKey && !e.isComposing) { e.preventDefault(); sendQuestion() } }
const formatDistance = distance => typeof distance === 'number' ? distance.toFixed(3) : '未知'
onMounted(() => loadDocuments(0))
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <div class="brand">
        <div class="brand-icon">K</div>
        <div>
          <h1>KnowledgeFlow</h1>
          <p>智能文档知识库</p>
        </div>
      </div>

      <div class="connection-status">
        <span class="status-dot"></span>
        {{ session.subject }} · {{ kb.can_write ? '可管理' : '只读' }}
      </div>
    </header>

    <main class="workspace">
      <aside class="sidebar">
        <div class="section-heading">
          <div>
            <p class="eyebrow">KNOWLEDGE BASE</p>
            <h2>{{ kb.name }}</h2>
          </div>

          <span class="count-badge">
            {{ total }}
          </span>
        </div>

        <p class="subtle-text">
          {{ kb.policy === 'local_only' ? '仅本地模型 · 问题与原文不送往云端' : '允许发送至管理员指定的云模型' }}
        </p>
        <label class="field-label" for="kb-select">当前知识库</label>
        <select id="kb-select" class="document-select" :value="kb.id" @change="emit('switch', $event.target.value)">
          <option v-for="item in session.knowledge_bases" :key="item.id" :value="item.id">{{ item.name }}</option>
        </select>
        <p v-if="kb.customer_desk"><button class="text-button" @click="showDesk = !showDesk">{{ showDesk ? '返回知识库问答' : '进入客服坐席台' }}</button></p>
        <p><button class="text-button" @click="emit('logout')">退出当前账号</button></p>

        <button
          v-if="kb.can_write" class="primary-button upload-button"
          :disabled="uploading"
          @click="fileInput?.click()"
        >
          {{ uploading ? '正在解析并建立索引…' : '+ 上传 PDF' }}
        </button>

        <input
          ref="fileInput"
          class="hidden-input"
          type="file"
          accept=".pdf,application/pdf"
          @change="uploadDocument"
        />

        <p class="field-label">检索范围</p>

        <select
          v-model="selectedDocumentId"
          class="document-select"
        >
          <option value="">全部文档</option>
          <option
            v-for="doc in documents"
            :key="doc.document_id"
            :value="doc.document_id"
          >
            {{ doc.filename }}
          </option>
        </select>

        <div class="list-heading">
          <span>已入库文档</span>

          <button
            class="text-button"
            :disabled="loadingDocs"
            @click="loadDocuments()"
          >
            {{ loadingDocs ? '刷新中…' : '刷新' }}
          </button>
        </div>

        <div v-if="documents.length === 0 && !loadingDocs" class="empty-state">
          <div class="empty-icon">▤</div>
          <p>知识库还是空的</p>
          <span>{{ kb.can_write ? '上传 PDF 后即可提问。' : '请联系知识库管理员上传文档。' }}</span>
        </div>

        <article
          v-for="doc in documents"
          :key="doc.document_id"
          class="document-card"
          :class="{
            selected: selectedDocumentId === doc.document_id,
          }"
          @click="selectedDocumentId = doc.document_id"
        >
          <div class="file-icon">PDF</div>

          <div class="document-info">
            <h3 :title="doc.filename">
              {{ doc.filename }}
            </h3>
            <p>{{ doc.chunk_count }} 个文本块</p>
          </div>

          <button
            v-if="kb.can_write" class="delete-button"
            title="删除文档"
            :disabled="deletingId === doc.document_id"
            @click.stop="deleteDocument(doc)"
          >
            {{ deletingId === doc.document_id ? '…' : '×' }}
          </button>
        </article>

        <nav v-if="total > limit" class="pager" aria-label="文档分页">
          <button class="text-button" :disabled="loadingDocs || offset === 0" @click="loadDocuments(offset-limit)">上一页</button>
          <span>{{ offset + 1 }}–{{ offset + documents.length }} / {{ total }}</span>
          <button class="text-button" :disabled="loadingDocs || offset + limit >= total" @click="loadDocuments(offset+limit)">下一页</button>
        </nav>
        <div class="sidebar-footer">
          <span class="status-dot"></span>
          <span>仅显示当前知识库的已发布版本</span>
        </div>
      </aside>

      <SupportDesk v-if="showDesk && kb.customer_desk" :call="call" />
      <section v-else class="chat-panel">
        <div class="chat-header">
          <div>
            <p class="eyebrow">AI ASSISTANT</p>
            <h2>知识库问答</h2>
            <p class="subtle-text">
              基于检索到的文档内容回答，并显示来源。
            </p>
          </div>

          <div class="scope-label">
            {{ selectedDocumentId ? '指定文档' : '全部文档' }}
          </div>
        </div>

        <div class="notice-area" aria-live="polite"><button v-if="failedJob && kb.can_write" class="text-button" @click="retryJob">重试入库任务</button>
          <div v-if="notice" class="notice success-notice">
            {{ notice }}
            <button @click="notice = ''">×</button>
          </div>

          <div v-if="errorMessage" class="notice error-notice">
            {{ errorMessage }}
            <button @click="errorMessage = ''">×</button>
          </div>
        </div>

        <div class="message-list">
          <div
            v-for="(message, index) in messages"
            :key="index"
            class="message-row"
            :class="message.role"
          >
            <div class="avatar">
              {{ message.role === 'assistant' ? 'AI' : '我' }}
            </div>

            <div class="message-content">
              <div class="message-name">
                {{ message.role === 'assistant' ? 'KnowledgeFlow' : '你' }}
              </div>

              <div class="message-bubble">
                {{ message.content }}
              </div>

              <div
                v-if="message.sources.length"
                class="sources-panel"
              >
                <h4>检索来源 · {{ message.sources.length }}</h4>

                <article
                  v-for="source in message.sources"
                  :key="source.chunk_id"
                  class="source-card"
                >
                  <div class="source-heading">
                    <span class="source-tag">
                      {{ source.source_id }}
                    </span>

                    <span class="source-location">
                      {{ source.filename }} · 第 {{ source.page }} 页
                    </span>
                  </div>

                  <p class="source-text">{{ source.text }}</p>

                  <div class="source-meta">
                    <span>片段 #{{ source.chunk_index }}</span>
                    <span>距离 {{ formatDistance(source.distance) }}</span>
                  </div>
                </article>
              </div>
            </div>
          </div>

          <div v-if="chatting" class="loading-answer">
            <span class="typing-dot"></span>
            <span class="typing-dot"></span>
            <span class="typing-dot"></span>
            正在检索资料并生成回答…
          </div>
        </div>

        <div class="composer-area">
          <div class="suggestion-row">
            <button
              @click="question = '这份文档主要讲了什么？'"
            >
              总结文档
            </button>

            <button
              @click="question = '请列出文档中的关键知识点。'"
            >
              提取知识点
            </button>
          </div>

          <div class="composer">
            <textarea
              v-model="question"
              placeholder="输入问题，例如：输入半径 5 时，圆面积是多少？"
              rows="2"
              :disabled="chatting"
              @keydown.enter="handleEnter"
            ></textarea>

            <button
              class="send-button"
              :disabled="chatting || !question.trim()"
              @click="sendQuestion"
            >
              {{ chatting ? '思考中…' : '发送 ↗' }}
            </button>
          </div>

          <p class="composer-hint">
            Enter 发送 · Shift + Enter 换行
          </p>
        </div>
      </section>
    </main>
  </div>
</template>

<style scoped>
.pager { display:flex; justify-content:space-between; align-items:center; font-size:.8rem; margin:1em 0; }
.app-shell {
  min-height: 100vh;
  background: #f4f6fa;
  color: #172033;
}

.topbar {
  height: 76px;
  padding: 0 34px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #fff;
  border-bottom: 1px solid #e8ebf2;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
}

.brand-icon {
  width: 42px;
  height: 42px;
  border-radius: 13px;
  display: grid;
  place-items: center;
  color: white;
  background: #435be7;
  font-size: 23px;
  font-weight: 800;
}

.brand h1,
.brand p,
.section-heading h2,
.chat-header h2,
.chat-header p {
  margin: 0;
}

.brand h1 {
  font-size: 19px;
  letter-spacing: -0.4px;
}

.brand p {
  margin-top: 3px;
  color: #8490a5;
  font-size: 12px;
}

.connection-status {
  color: #55637a;
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.status-dot {
  width: 8px;
  height: 8px;
  display: inline-block;
  border-radius: 50%;
  background: #29b779;
}

.workspace {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 20px;
  max-width: 1500px;
  margin: auto;
  padding: 24px;
  min-height: calc(100vh - 76px);
}

.sidebar,
.chat-panel {
  background: #fff;
  border: 1px solid #e8ebf2;
  border-radius: 18px;
  min-width: 0;
}

.sidebar {
  padding: 24px 20px;
  display: flex;
  flex-direction: column;
}

.section-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.eyebrow {
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 1.4px;
  color: #6879e9;
  margin: 0 0 7px;
}

.section-heading h2,
.chat-header h2 {
  font-size: 21px;
}

.count-badge {
  background: #eef0ff;
  color: #435be7;
  padding: 5px 10px;
  border-radius: 20px;
  font-size: 12px;
}

.subtle-text {
  font-size: 12px;
  line-height: 1.7;
  color: #8791a3;
}

.upload-button {
  width: 100%;
  margin: 17px 0 23px;
}

.primary-button,
.send-button {
  border: 0;
  border-radius: 10px;
  background: #435be7;
  color: white;
  font-weight: 600;
  cursor: pointer;
  padding: 12px 16px;
}

.primary-button:hover,
.send-button:hover {
  background: #344bd0;
}

button:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.hidden-input {
  display: none;
}

.field-label,
.list-heading {
  font-size: 12px;
  color: #69768c;
  font-weight: 650;
}

.document-select {
  width: 100%;
  padding: 11px 10px;
  margin-top: 9px;
  border: 1px solid #e1e5ee;
  border-radius: 9px;
  background: white;
  color: #354158;
  font-size: 12px;
}

.list-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin: 27px 0 12px;
}

.text-button {
  border: 0;
  background: none;
  color: #435be7;
  cursor: pointer;
  font-size: 12px;
}

.document-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 8px;
  border: 1px solid transparent;
  border-radius: 11px;
  cursor: pointer;
  margin-bottom: 5px;
}

.document-card:hover,
.document-card.selected {
  background: #f4f5ff;
  border-color: #e2e5ff;
}

.file-icon {
  flex-shrink: 0;
  width: 37px;
  height: 42px;
  display: grid;
  place-items: center;
  border-radius: 8px;
  color: #d75969;
  background: #fff0f1;
  font-size: 10px;
  font-weight: 800;
}

.document-info {
  flex: 1;
  min-width: 0;
}

.document-info h3 {
  font-size: 12px;
  line-height: 1.6;
  font-weight: 650;
  margin: 0;
  overflow-wrap: anywhere;
}

.document-info p {
  font-size: 11px;
  color: #8993a4;
  margin: 4px 0 0;
}

.delete-button {
  border: 0;
  background: transparent;
  color: #a0a8b7;
  font-size: 21px;
  cursor: pointer;
  padding: 4px;
}

.delete-button:hover {
  color: #df4657;
}

.empty-state {
  text-align: center;
  color: #8a94a5;
  padding: 32px 10px;
}

.empty-icon {
  font-size: 28px;
  color: #a0a9bb;
}

.empty-state p {
  margin-bottom: 4px;
  color: #4b566c;
  font-size: 13px;
}

.empty-state span {
  font-size: 11px;
}

.sidebar-footer {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-top: 19px;
  margin-top: auto;
  color: #8a94a5;
  font-size: 10px;
}

.chat-panel {
  display: flex;
  flex-direction: column;
  min-height: 760px;
  overflow: hidden;
}

.chat-header {
  padding: 25px 30px 20px;
  border-bottom: 1px solid #eff1f5;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 15px;
}

.chat-header .subtle-text {
  margin-bottom: 0;
}

.scope-label {
  font-size: 11px;
  color: #435be7;
  background: #f0f1ff;
  padding: 8px 11px;
  border-radius: 9px;
  white-space: nowrap;
}

.notice-area {
  padding: 0 26px;
}

.notice {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 12px;
  margin-top: 12px;
  border-radius: 8px;
  font-size: 12px;
  overflow-wrap: anywhere;
}

.notice button {
  border: 0;
  background: none;
  cursor: pointer;
}

.success-notice {
  background: #edf9f2;
  color: #20764c;
}

.error-notice {
  background: #fff0f0;
  color: #b32b37;
}

.message-list {
  flex: 1;
  padding: 28px 30px;
  display: flex;
  flex-direction: column;
  gap: 28px;
}

.message-row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  max-width: 940px;
}

.message-row.user {
  align-self: flex-end;
  flex-direction: row-reverse;
}

.avatar {
  flex-shrink: 0;
  width: 34px;
  height: 34px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  font-size: 11px;
  font-weight: 750;
  background: #eef0ff;
  color: #435be7;
}

.user .avatar {
  background: #e7f4ed;
  color: #26875b;
}

.message-content {
  flex: 1;
  min-width: 0;
}

.message-name {
  margin: 2px 0 8px;
  font-size: 12px;
  color: #67738a;
}

.message-bubble {
  padding: 14px 16px;
  border: 1px solid #edf0f5;
  background: #fafbfe;
  border-radius: 4px 14px 14px 14px;
  font-size: 13px;
  line-height: 1.9;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.user .message-bubble {
  border: 0;
  background: #435be7;
  color: white;
  border-radius: 14px 4px 14px 14px;
}

.sources-panel {
  margin-top: 14px;
}

.sources-panel h4 {
  font-size: 12px;
  margin: 0 0 10px;
  color: #47546b;
}

.source-card {
  padding: 12px;
  border: 1px solid #e6eaf2;
  background: white;
  border-radius: 10px;
  margin-top: 8px;
}

.source-heading {
  display: flex;
  gap: 9px;
  align-items: flex-start;
  flex-wrap: wrap;
}

.source-tag {
  background: #eef0ff;
  color: #435be7;
  padding: 3px 7px;
  font-size: 10px;
  border-radius: 5px;
  font-weight: 750;
}

.source-location {
  color: #56637a;
  font-size: 11px;
  overflow-wrap: anywhere;
  line-height: 1.7;
}

.source-text {
  font-size: 12px;
  line-height: 1.8;
  color: #525e73;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  max-height: 180px;
  overflow: auto;
}

.source-meta {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  color: #98a1b0;
  font-size: 10px;
}

.loading-answer {
  padding: 0 30px 25px;
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: #7f899b;
}

.typing-dot {
  width: 6px;
  height: 6px;
  background: #6879e9;
  border-radius: 50%;
  animation: pulse 1s infinite alternate;
}

.typing-dot:nth-child(2) {
  animation-delay: 0.2s;
}

.typing-dot:nth-child(3) {
  animation-delay: 0.4s;
  margin-right: 5px;
}

@keyframes pulse {
  from { opacity: 0.3; }
  to { opacity: 1; }
}

.composer-area {
  border-top: 1px solid #edf0f5;
  padding: 16px 26px 18px;
  background: #fff;
}

.suggestion-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 11px;
}

.suggestion-row button {
  border: 1px solid #e4e8f0;
  color: #637087;
  background: #fff;
  padding: 7px 10px;
  border-radius: 20px;
  cursor: pointer;
  font-size: 11px;
}

.suggestion-row button:hover {
  border-color: #aeb7fb;
  color: #435be7;
}

.composer {
  border: 1px solid #dfe4ee;
  border-radius: 13px;
  padding: 10px;
  display: flex;
  align-items: flex-end;
  gap: 10px;
  transition: border-color 0.2s;
}

.composer:focus-within {
  border-color: #8693f2;
}

.composer textarea {
  flex: 1;
  min-width: 0;
  resize: vertical;
  border: 0;
  outline: none;
  font: inherit;
  font-size: 13px;
  line-height: 1.7;
  color: #243047;
  background: transparent;
}

.send-button {
  flex-shrink: 0;
  font-size: 12px;
  padding: 10px 15px;
}

.composer-hint {
  margin: 8px 0 0;
  text-align: right;
  font-size: 10px;
  color: #a0a8b5;
}

@media (max-width: 850px) {
  .workspace {
    grid-template-columns: 1fr;
    padding: 12px;
  }

  .sidebar {
    padding: 18px;
  }

  .chat-panel {
    min-height: 620px;
  }

  .topbar {
    padding: 0 18px;
  }

  .chat-header,
  .message-list {
    padding-left: 18px;
    padding-right: 18px;
  }
}

@media (max-width: 480px) {
  .connection-status {
    font-size: 11px;
  }

  .chat-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .message-list {
    padding: 20px 12px;
  }

  .composer-area {
    padding: 12px;
  }

  .notice-area {
    padding: 0 12px;
  }
}
</style>
