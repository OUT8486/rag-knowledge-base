<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import axios from 'axios'

const abort = new AbortController()
onBeforeUnmount(() => abort.abort())
const api = axios.create({
  baseURL: '/api/customer/',
  timeout: 90000,
  signal: abort.signal,
})
const mode = ref('chat'),
  policy = ref(null),
  starting = ref(true),
  unavailable = ref('')
const messages = ref([]),
  question = ref(''),
  sending = ref(false),
  cloud = ref(false),
  logEnd = ref(null)
const issue = ref(''),
  consent = ref(false),
  saving = ref(false),
  checking = ref(false)
const ticket = ref(null),
  receipt = ref(''),
  lookupKey = ref(''),
  ticketError = ref('')
const storageKey = 'knowledgeflow.customer.receipt.v1'
const choices = ['怎么申请售后服务？', '如何查看人工回复？']
const lastQuestion = computed(
  () => messages.value.filter((m) => m.role === 'user').at(-1)?.text || '',
)
const errorText = (err, fallback) =>
  typeof err.response?.data?.detail === 'string'
    ? err.response.data.detail
    : fallback
const date = (value) =>
  new Date(value * 1000).toLocaleString('zh-CN', { hour12: false })
async function loadInfo() {
  starting.value = true
  unavailable.value = ''
  cloud.value = false
  try {
    policy.value = (await api.get('info')).data.policy
  } catch {
    policy.value = null
    unavailable.value = '在线客服暂未开放，请稍后再来。'
  } finally {
    starting.value = false
  }
}
async function scrollLatest() {
  await nextTick()
  logEnd.value?.scrollIntoView({ block: 'nearest' })
}
async function ask(text = question.value) {
  text = text.trim()
  if (!text || sending.value || !policy.value) return
  if (policy.value === 'approved_cloud' && !cloud.value) return
  const previous = messages.value
    .filter((m) => m.role === 'user')
    .slice(-2)
    .map((m) => m.text.slice(0, 200))
  question.value = ''
  sending.value = true
  messages.value.push({ role: 'user', text })
  await scrollLatest()
  try {
    const { data } = await api.post('ask', {
      question: text,
      previous_questions: previous,
      allow_cloud: cloud.value,
    })
    messages.value.push({
      role: 'assistant',
      text: data.answer,
      sources: data.sources,
      handoff: ['no_evidence', 'handoff', 'unavailable'].includes(data.kind),
    })
  } catch (err) {
    if (err.response?.status === 409) await loadInfo()
    messages.value.push({
      role: 'assistant',
      text: errorText(err, '暂时无法连接客服。请稍后重试或转人工。'),
      handoff: true,
    })
  } finally {
    sending.value = false
    await scrollLatest()
  }
}
function enter(e) {
  if (!e.shiftKey && !e.isComposing) {
    e.preventDefault()
    ask()
  }
}
function handoff() {
  mode.value = 'new'
  issue.value = question.value.trim() || lastQuestion.value
  consent.value = false
  ticketError.value = ''
}
function keepReceipt(key) {
  receipt.value = key
  lookupKey.value = key
  try {
    if (key) sessionStorage.setItem(storageKey, key)
    else sessionStorage.removeItem(storageKey)
  } catch {
    /* still usable in memory */
  }
}
async function submitTicket() {
  if (!issue.value.trim() || !consent.value || saving.value) return
  saving.value = true
  ticketError.value = ''
  try {
    const { data } = await api.post('tickets', {
      issue: issue.value.trim(),
      share_with_agent: true,
    })
    keepReceipt(data.receipt)
    ticket.value = data
    mode.value = 'track'
    issue.value = ''
    consent.value = false
  } catch (err) {
    ticketError.value = errorText(err, '工单未提交成功，请重试。')
  } finally {
    saving.value = false
  }
}
async function lookup() {
  const key = lookupKey.value.trim()
  if (!key || checking.value) return
  checking.value = true
  ticketError.value = ''
  ticket.value = null
  try {
    const { data } = await api.get('ticket', {
      headers: { 'X-Ticket-Receipt': key },
    })
    keepReceipt(key)
    ticket.value = data
  } catch (err) {
    ticketError.value = errorText(err, '无法查询工单，请稍后再试。')
  } finally {
    checking.value = false
  }
}
function progress() {
  mode.value = 'track'
  ticketError.value = ''
  lookupKey.value = receipt.value
  if (receipt.value) lookup()
}
function forget() {
  keepReceipt('')
  ticket.value = null
  ticketError.value = ''
}
onMounted(async () => {
  try {
    receipt.value = sessionStorage.getItem(storageKey) || ''
    lookupKey.value = receipt.value
  } catch {
    /* private browser */
  }
  await loadInfo()
})
</script>

<template>
  <header class="top">
    <div class="brand">
      <span class="logo" aria-hidden="true">K</span
      ><strong>KnowledgeFlow</strong><i></i><span>客户服务中心</span>
    </div>
    <span class="channel">网页服务</span>
  </header>
  <main class="layout">
    <aside class="rail">
      <p class="overline">SERVICE DESK</p>
      <h1>客户服务中心</h1>
      <p class="intro">先问 AI，需要时交给人工。</p>
      <nav aria-label="客服导航">
        <button :class="{ active: mode === 'chat' }" @click="mode = 'chat'">
          <b>01</b> AI 咨询
        </button>
        <button :class="{ active: mode === 'new' }" @click="handoff">
          <b>02</b> 转人工
        </button>
        <button :class="{ active: mode === 'track' }" @click="progress">
          <b>03</b> 工单进度
        </button>
      </nav>
      <div class="note">
        <strong>隐私提醒</strong>
        <p>
          请勿发送密码、验证码、身份证号或支付信息。本客服不能代查订单或执行退款。
        </p>
      </div>
    </aside>
    <section class="panel">
      <div v-if="starting || !policy" class="state" role="status">
        <h2>{{ starting ? '正在连接客服…' : unavailable }}</h2>
        <button v-if="!starting" class="outline" @click="loadInfo">
          重新连接
        </button>
      </div>
      <template v-else-if="mode === 'chat'">
        <header class="section-head">
          <div>
            <p class="overline">AI ASSISTANT</p>
            <h2>在线咨询</h2>
          </div>
          <span class="badge">AI 助手</span>
        </header>
        <div
          class="chatlog"
          role="log"
          aria-label="咨询对话"
          aria-live="polite"
        >
          <div v-if="!messages.length" class="hello">
            <span class="monogram" aria-hidden="true">K<span>·</span></span>
            <h3>你好，有什么可以帮你？</h3>
            <p>
              我会根据已发布的帮助资料回答，并标明出处。你也可以直接转人工。
            </p>
            <div class="chips">
              <button v-for="q in choices" :key="q" @click="question = q">
                {{ q }} ↗
              </button>
            </div>
          </div>
          <article
            v-for="(m, i) in messages"
            :key="i"
            class="msg"
            :class="m.role"
          >
            <small>{{ m.role === 'user' ? '你' : 'AI 客服' }}</small>
            <div class="bubble">{{ m.text }}</div>
            <details v-if="m.sources?.length">
              <summary>查看依据 · {{ m.sources.length }}</summary>
              <blockquote v-for="s in m.sources" :key="s.source_id">
                <strong
                  >[{{ s.source_id }}] {{ s.title }} · 第
                  {{ s.page }} 页</strong
                >
                <p>{{ s.excerpt }}</p>
              </blockquote>
            </details>
            <button v-if="m.handoff" class="link" @click="handoff">
              把问题交给人工 →
            </button>
          </article>
          <p v-if="sending" class="muted" role="status">正在查找公开资料…</p>
          <div ref="logEnd"></div>
        </div>
        <form class="composer" @submit.prevent="ask()">
          <label v-if="policy === 'approved_cloud'" class="check"
            ><input
              v-model="cloud"
              type="checkbox"
            />同意将本次问题、最近两条提问及相关公开资料发给指定云模型。不同意也可转人工。</label
          >
          <label class="sr" for="customer-question">咨询问题</label
          ><textarea
            id="customer-question"
            v-model="question"
            rows="2"
            maxlength="1000"
            placeholder="描述你的问题，请勿输入密码或验证码…"
            @keydown.enter="enter"
          ></textarea>
          <div class="actions">
            <span>Enter 发送 · Shift + Enter 换行</span
            ><button
              class="primary"
              :disabled="
                sending ||
                !question.trim() ||
                (policy === 'approved_cloud' && !cloud)
              "
            >
              发送问题 ↗
            </button>
          </div>
        </form>
      </template>
      <template v-else-if="mode === 'new'">
        <header class="section-head">
          <div>
            <p class="overline">HUMAN SUPPORT</p>
            <h2>转交人工客服</h2>
          </div>
          <span class="badge">留言工单</span>
        </header>
        <form class="sheet" @submit.prevent="submitTicket">
          <h3>希望坐席帮你处理什么？</h3>
          <p class="muted">
            请勿填写密码、验证码或支付信息。只会提交下方确认的描述，不附整段对话。工作人员回复后，可在「工单进度」查看。
          </p>
          <label for="ticket-issue">问题描述</label
          ><textarea
            id="ticket-issue"
            v-model="issue"
            rows="5"
            maxlength="1200"
            required
            placeholder="请简述问题和已经尝试过的操作。"
          ></textarea>
          <label class="check"
            ><input
              v-model="consent"
              type="checkbox"
            />我同意将这段描述交给人工坐席处理。</label
          >
          <p v-if="receipt" class="muted">
            新工单会替换本标签页记住的凭证，请先保存旧凭证。
          </p>
          <p v-if="ticketError" role="alert">{{ ticketError }}</p>
          <button
            class="primary"
            :disabled="!consent || !issue.trim() || saving"
          >
            {{ saving ? '正在提交…' : '提交人工工单' }}
          </button>
        </form>
      </template>
      <template v-else>
        <header class="section-head">
          <div>
            <p class="overline">TICKET TRACKING</p>
            <h2>工单进度</h2>
          </div>
        </header>
        <div class="sheet">
          <form @submit.prevent="lookup">
            <label for="receipt">私密查询凭证</label>
            <p class="muted">
              凭证不是工单号。持有者可查看问题和回复，请单独保存，不要分享。凭证在工单创建后
              30 天内有效。
            </p>
            <input
              id="receipt"
              v-model="lookupKey"
              type="password"
              autocomplete="off"
              spellcheck="false"
              maxlength="64"
              required
            />
            <div class="buttons">
              <button class="primary" :disabled="checking || !lookupKey.trim()">
                {{ checking ? '查询中…' : '查询进度' }}</button
              ><button
                v-if="receipt"
                class="outline"
                type="button"
                :disabled="checking"
                @click="forget"
              >
                本机忘记凭证
              </button>
            </div>
          </form>
          <p v-if="ticketError" role="alert">{{ ticketError }}</p>
          <article v-if="ticket" class="ticket">
            <span class="badge">{{
              ticket.status === 'open' ? '待人工回复' : '人工已回复'
            }}</span>
            <h3>工单 {{ ticket.id }}</h3>
            <small>{{ date(ticket.created) }}</small>
            <p>{{ ticket.issue }}</p>
            <div v-if="ticket.reply" class="reply">
              <strong>坐席回复</strong>
              <p>{{ ticket.reply }}</p>
            </div>
            <details>
              <summary>显示查询凭证，供复制保存</summary>
              <code>{{ receipt }}</code>
            </details>
          </article>
        </div>
      </template>
    </section>
  </main>
</template>

<style>
:root {
  font-family: Inter, 'Microsoft YaHei', system-ui, sans-serif;
  color: #183632;
  background: #f3f6f3;
  font-synthesis: none;
}
* {
  box-sizing: border-box;
}
body {
  margin: 0;
}
button,
input,
textarea {
  font: inherit;
}
button {
  cursor: pointer;
}
button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
button:focus-visible,
summary:focus-visible,
a:focus-visible {
  outline: 3px solid #d38b3e;
  outline-offset: 3px;
}
.top {
  height: 68px;
  background: #143c37;
  color: white;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 max(5vw, 20px);
}
.brand {
  display: flex;
  align-items: center;
  gap: 13px;
}
.brand strong {
  letter-spacing: -0.04em;
  font-size: 19px;
}
.brand i {
  height: 17px;
  border-left: 1px solid #78958e;
}
.brand > span:last-child,
.channel {
  font-size: 13px;
  color: #ccded5;
}
.logo,
.monogram {
  display: grid;
  place-items: center;
  background: #c7e3bb;
  color: #173e35;
  font-weight: 800;
  border-radius: 9px;
}
.logo {
  width: 30px;
  height: 30px;
}
.layout {
  max-width: 1180px;
  margin: 38px auto;
  padding: 0 24px;
  display: grid;
  grid-template-columns: 240px minmax(0, 1fr);
  gap: 30px;
}
.rail {
  padding: 24px 4px;
}
.overline {
  font-size: 10px;
  letter-spacing: 0.18em;
  font-weight: 750;
  color: #538173;
  margin: 0 0 9px;
}
.rail h1,
.section-head h2,
.sheet h3,
.hello h3 {
  margin: 0;
  letter-spacing: -0.04em;
}
.rail h1 {
  font-size: 29px;
}
.intro,
.muted,
.note p,
.hello p {
  color: #526b63;
  line-height: 1.7;
}
.intro {
  font-size: 14px;
  margin: 8px 0 28px;
}
nav {
  display: grid;
  gap: 6px;
}
nav button {
  text-align: left;
  border: 0;
  background: transparent;
  color: #36544c;
  font-weight: 650;
  border-radius: 9px;
  padding: 12px;
}
nav b {
  font-size: 10px;
  letter-spacing: 0.1em;
  color: #658c79;
  margin-right: 12px;
}
nav .active {
  background: #dce9db;
  color: #163e31;
}
.note {
  border-top: 1px solid #d1ded4;
  margin-top: 34px;
  padding-top: 20px;
  font-size: 13px;
}
.note p {
  margin: 4px 0;
}
.panel {
  min-width: 0;
  height: min(740px, calc(100dvh - 135px));
  min-height: 440px;
  background: white;
  border: 1px solid #d4e0d7;
  border-radius: 19px;
  box-shadow: 0 12px 30px #18372b0b;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.section-head {
  padding: 23px 29px 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid #e5ece5;
}
.section-head h2 {
  font-size: 23px;
}
.badge {
  font-size: 12px;
  display: inline-block;
  padding: 5px 10px;
  border-radius: 20px;
  background: #e6efe4;
  color: #345b42;
}
.chatlog,
.sheet {
  padding: 22px 29px;
  overflow: auto;
  overflow-wrap: anywhere;
}
.chatlog {
  flex: 1;
}
.hello {
  max-width: 470px;
  padding: 20px 0;
}
.monogram {
  display: inline-flex;
  justify-content: center;
  width: 44px;
  height: 44px;
  font-size: 25px;
  margin: 0 0 15px;
}
.monogram span {
  color: #63945c;
}
.hello h3 {
  font-size: 25px;
}
.chips,
.buttons,
.actions {
  display: flex;
  align-items: center;
  gap: 9px;
  flex-wrap: wrap;
}
.chips button,
.outline {
  background: white;
  border: 1px solid #c3d4c6;
  border-radius: 8px;
  color: #315849;
  padding: 8px 12px;
  font-size: 13px;
}
.msg {
  margin: 14px 0;
  max-width: 88%;
}
.msg small,
.ticket small {
  color: #667a72;
  font-size: 12px;
}
.bubble,
.ticket p {
  white-space: pre-wrap;
  line-height: 1.65;
}
.bubble {
  background: #f2f6f1;
  border-radius: 2px 13px 13px;
  padding: 10px 14px;
  margin-top: 4px;
}
.user {
  margin-left: auto;
  text-align: right;
}
.user .bubble {
  display: inline-block;
  text-align: left;
  background: #dfeede;
  border-radius: 13px 2px 13px 13px;
}
.link {
  color: #25674e;
  background: none;
  border: 0;
  padding: 8px 0;
}
details {
  font-size: 13px;
  color: #426354;
  margin-top: 7px;
}
summary {
  cursor: pointer;
}
blockquote {
  border-left: 2px solid #b4cdb8;
  margin: 10px 0;
  padding-left: 11px;
}
blockquote p {
  margin: 3px 0;
}
.composer {
  padding: 16px 24px;
  border-top: 1px solid #e3eae4;
}
.sheet > form,
.sheet {
  line-height: 1.65;
}
.sheet label:not(.check) {
  display: block;
  font-weight: 650;
}
.sheet h3 {
  font-size: 19px;
  margin: 6px 0;
}
.sheet p {
  margin: 0.6em 0 1em;
}
.composer textarea,
.sheet textarea,
.sheet input:not([type='checkbox']) {
  width: 100%;
  border: 1px solid #afc6b6;
  border-radius: 9px;
  padding: 11px 12px;
  resize: vertical;
  background: #fcfdfb;
  color: #17362d;
}
.composer textarea:focus,
.sheet textarea:focus,
.sheet input:focus {
  outline: 2px solid #76a281;
}
.actions {
  justify-content: space-between;
  margin-top: 8px;
}
.actions span {
  font-size: 11px;
  color: #677b72;
}
.primary {
  border: 0;
  background: #245942;
  color: white;
  font-weight: 650;
  padding: 9px 16px;
  border-radius: 8px;
}
.check {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  font-size: 13px;
  color: #536358;
  margin: 10px 0;
}
.check input {
  accent-color: #245942;
}
.buttons {
  margin-top: 12px;
}
.ticket,
.reply {
  border: 1px solid #d5e3d6;
  background: #f6f9f4;
  border-radius: 10px;
  margin: 20px 0 0;
  padding: 16px;
}
.reply {
  background: white;
}
.ticket code {
  display: block;
  overflow-wrap: anywhere;
  user-select: all;
  margin: 8px 0;
}
.state {
  margin: auto;
  text-align: center;
  padding: 22px;
}
.state h2 {
  font-size: 19px;
}
[role='alert'] {
  color: #933e2c;
}
.sr {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip-path: inset(50%);
}
@media (max-width: 760px) {
  .top {
    height: 54px;
  }
  .layout {
    display: block;
    padding: 0 12px;
    margin: 12px auto;
  }
  .rail {
    padding: 0 0 11px;
  }
  .rail > h1,
  .rail > .intro,
  .rail > .overline,
  .rail > .note {
    display: none;
  }
  nav {
    grid-template-columns: repeat(3, 1fr);
  }
  nav button {
    text-align: center;
    padding: 9px 2px;
    font-size: 14px;
  }
  nav b {
    display: none;
  }
  .panel {
    height: calc(100dvh - 122px);
    min-height: 390px;
  }
  .section-head,
  .sheet,
  .chatlog {
    padding: 16px;
  }
  .composer {
    padding: 12px;
  }
  .hello h3 {
    font-size: 22px;
  }
  .brand {
    gap: 8px;
  }
  .channel {
    display: none;
  }
  .msg {
    max-width: 94%;
  }
}
</style>
