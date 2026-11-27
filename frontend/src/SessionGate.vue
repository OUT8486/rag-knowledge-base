<script setup>
import { computed, onMounted, ref, shallowRef } from 'vue'
import axios from 'axios'
import Workspace from './App.vue'

const session = ref(null), api = shallowRef(null), selected = ref(''), token = ref('')
const busy = ref(false), message = ref(''), customerOpen = ref(false)
const kb = computed(() => session.value?.knowledge_bases.find(item => item.id === selected.value))
async function login(automatic = false) {
  if (busy.value) return
  busy.value = true; message.value = ''
  const headers = {'X-RAG-Request': '1'}
  if (!automatic && token.value.trim()) headers.Authorization = `Bearer ${token.value.trim()}`
  const client = axios.create({baseURL: '/api/', timeout: 120000, headers})
  try {
    const {data} = await client.get('session')
    session.value = data; api.value = client; selected.value = data.knowledge_bases[0]?.id || ''; token.value = ''
  } catch (e) {
    if (!automatic || e.response?.status !== 401) message.value = e.response?.data?.detail || '无法连接知识库服务。'
  } finally { busy.value = false }
}
function logout(expired = false) {
  const sso = session.value?.auth_mode === 'proxy'
  session.value = null; api.value = null; token.value = ''; selected.value = ''
  message.value = expired ? '登录已失效，请重新登录。' : ''
  if (!expired && sso) window.location.assign('/oauth2/sign_out')
}
onMounted(() => {
  login(true)
  axios.get('/api/customer/info', {timeout: 4000}).then(() => { customerOpen.value = true }).catch(() => {})
})
</script>

<template>
  <Workspace v-if="kb" :key="`${session.subject}:${kb.id}`" :api="api" :kb="kb" :session="session"
    @switch="selected = $event" @logout="logout()" @expired="logout(true)" />
  <main v-else class="gate">
    <section><p class="brand">KNOWLEDGEFLOW</p><h1>企业知识库</h1>
      <template v-if="session"><p>当前账号尚未分配知识库。请联系管理员。</p><button @click="logout()">退出</button></template>
      <form v-else @submit.prevent="login()">
        <label for="access-token">试点访问令牌</label>
        <input id="access-token" v-model="token" type="password" autocomplete="off" placeholder="输入管理员分发的令牌" required />
        <button :disabled="busy">{{ busy ? '正在验证…' : '进入知识库' }}</button>
        <p>令牌只保存在本页内存中，刷新后需要重新输入。使用企业单点登录的站点，请<a href="/oauth2/start?rd=/">通过企业账号登录</a>。</p>
      </form>
      <p v-if="customerOpen"><a href="/support/">我是客户，前往在线咨询 →</a></p>
      <p v-if="message" role="alert">{{ message }}</p>
    </section>
  </main>
</template>
<style scoped>
.gate { min-height:100vh; display:grid; place-items:center; background:#f4f6fa; color:#172033; padding:20px; }
.gate section { width:min(100%,410px); box-sizing:border-box; background:white; padding:36px; border:1px solid #dfe5ef; border-radius:18px; }
.brand { color:#435be7; font-weight:750; letter-spacing:.12em; font-size:.8rem; }
.gate h1 { margin:.5em 0 1em; } .gate label { display:block; font-weight:650; }
.gate input,.gate button { box-sizing:border-box; width:100%; margin-top:10px; padding:12px; border-radius:8px; }
.gate input { border:1px solid #aab5c8; } .gate button { border:0; color:white; background:#4057ce; cursor:pointer; }
.gate form p { font-size:.85rem; line-height:1.6; color:#58657b; } [role=alert] {color:#a92b32;}
</style>
