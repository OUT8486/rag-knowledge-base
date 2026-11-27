<script setup>
import { onMounted, ref } from 'vue'
const props = defineProps({ call: { type: Function, required: true } })
const tab = ref('open'),
  rows = ref([]),
  offset = ref(0),
  busy = ref(false),
  error = ref(''),
  notice = ref('')
const drafts = ref({}),
  pageSize = 20
async function load(next = 0) {
  busy.value = true
  error.value = ''
  try {
    rows.value = await props.call(
      'get',
      `desk/${tab.value === 'materials' ? 'materials' : 'tickets'}`,
      {
        params: {
          limit: pageSize,
          offset: next,
          ...(tab.value === 'materials' ? {} : { state: tab.value }),
        },
      },
    )
    offset.value = next
  } catch (e) {
    rows.value = []
    error.value = e.response?.data?.detail || '无法加载坐席台。'
  } finally {
    busy.value = false
  }
}
function change(t) {
  if (busy.value) return
  tab.value = t
  rows.value = []
  drafts.value = {}
  notice.value = ''
  load(0)
}
async function publish(row, title) {
  if (title !== null && !title?.trim()) return
  if (
    !window.confirm(
      title === null
        ? '撤下这份资料，不再用于新的客户回答？'
        : `对所有客户公开「${title}」第 ${row.version} 版的内容？请确认已审核且不含内部信息。`,
    )
  )
    return
  busy.value = true
  error.value = ''
  try {
    await props.call('put', `desk/materials/${row.document_id}`, {
      data: { version_id: row.version_id, public_title: title?.trim() ?? null },
    })
    delete drafts.value[row.document_id]
    notice.value = title === null ? '已撤下资料。' : '此版本已对客发布。'
    await load(offset.value)
  } catch (e) {
    error.value = e.response?.data?.detail || '操作未成功。'
  } finally {
    busy.value = false
  }
}
async function reply(row) {
  const text = drafts.value[row.id]?.trim()
  if (!text || busy.value) return
  busy.value = true
  error.value = ''
  try {
    await props.call('post', `desk/tickets/${row.id}/reply`, {
      data: { reply: text },
    })
    delete drafts.value[row.id]
    notice.value = '已回复并结单，客户可凭查询凭证查看。'
    await load(0)
  } catch (e) {
    error.value = e.response?.data?.detail || '回复失败。'
  } finally {
    busy.value = false
  }
}
onMounted(() => load(0))
</script>
<template>
  <section class="desk" aria-label="客服坐席台">
    <header>
      <p>SUPPORT DESK</p>
      <h2>客服坐席台</h2>
      <a href="/support/" target="_blank" rel="noopener">打开客户页面 ↗</a>
    </header>
    <nav aria-label="坐席工作区">
      <button
        v-for="[key, label] in [
          ['open', '待回复'],
          ['resolved', '已结单'],
          ['materials', '对客资料'],
        ]"
        :key="key"
        :disabled="busy"
        :class="{ current: tab === key }"
        @click="change(key)"
      >
        {{ label }}</button
      ><button :disabled="busy" @click="load(offset)">刷新</button>
    </nav>
    <p v-if="tab === 'materials'" class="hint">
      上传入库不等于对外发布。请先审核原文，再为当前版本设置客户可见的标题。文档换版后需重新发布。
    </p>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="notice" role="status">{{ notice }}</p>
    <p v-if="busy" class="hint">正在处理…</p>
    <p v-else-if="!rows.length" class="empty">
      {{
        tab === 'materials'
          ? '暂无可发布资料。请先从左侧上传客服 PDF。'
          : tab === 'open'
            ? '目前没有待回复工单。'
            : '目前没有已结单工单。'
      }}
    </p>
    <article v-for="r in rows" :key="r.document_id || r.id">
      <template v-if="tab === 'materials'"
        ><h3>{{ r.filename }}</h3>
        <small
          >版本 {{ r.version }} ·
          {{
            r.public_title ? '对客可见：' + r.public_title : '尚未对客发布'
          }}</small
        >
        <template v-if="!r.public_title"
          ><label :for="'pub-' + r.document_id">客户可见标题</label
          ><input
            :id="'pub-' + r.document_id"
            v-model="drafts[r.document_id]"
            maxlength="100"
            placeholder="例如：售后服务指南"
          /><button
            :disabled="busy || !drafts[r.document_id]?.trim()"
            @click="publish(r, drafts[r.document_id])"
          >
            审核并对客发布
          </button></template
        >
        <button v-else :disabled="busy" @click="publish(r, null)">
          撤下公开版本
        </button>
      </template>
      <template v-else
        ><h3>{{ r.id }}</h3>
        <small>{{ new Date(r.created * 1000).toLocaleString('zh-CN') }}</small>
        <p class="body">{{ r.issue }}</p>
        <template v-if="r.status === 'open'"
          ><label :for="'reply-' + r.id">给客户的回复</label
          ><textarea
            :id="'reply-' + r.id"
            v-model="drafts[r.id]"
            maxlength="1200"
            rows="3"
          ></textarea
          ><button :disabled="busy || !drafts[r.id]?.trim()" @click="reply(r)">
            回复并结单
          </button></template
        >
        <div v-else class="body">
          <strong>坐席回复</strong>
          <p>{{ r.reply }}</p>
        </div>
      </template>
    </article>
    <footer v-if="offset || rows.length === pageSize">
      <button :disabled="busy || !offset" @click="load(offset - pageSize)">
        上一页</button
      ><button
        :disabled="busy || rows.length < pageSize"
        @click="load(offset + pageSize)"
      >
        下一页
      </button>
    </footer>
  </section>
</template>
<style scoped>
.desk {
  background: white;
  min-width: 0;
  padding: 26px;
  border: 1px solid #e1e7ec;
  border-radius: 16px;
  color: #203244;
}
.desk header {
  position: relative;
}
.desk header p {
  font-size: 11px;
  letter-spacing: 0.15em;
  color: #536c80;
  font-weight: 700;
  margin: 0;
}
.desk h2 {
  margin: 4px 0 16px;
}
.desk header a {
  color: #3452ac;
  font-size: 13px;
}
.desk nav {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 18px 0;
}
.desk button {
  cursor: pointer;
  border: 1px solid #cbd7de;
  border-radius: 7px;
  background: white;
  color: #2a4657;
  padding: 7px 12px;
}
.desk button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.desk button.current,
.desk article button {
  background: #244b54;
  color: white;
}
.desk article {
  border: 1px solid #dce5e6;
  border-radius: 10px;
  padding: 15px;
  margin: 12px 0;
}
.desk article h3 {
  font-size: 15px;
  margin: 0;
  overflow-wrap: anywhere;
}
.desk small,
.hint,
.empty {
  color: #596e79;
}
.desk label {
  display: block;
  font-size: 13px;
  margin: 12px 0 5px;
}
.desk input,
.desk textarea {
  display: block;
  width: 100%;
  font: inherit;
  border: 1px solid #b4c6cb;
  border-radius: 7px;
  padding: 8px;
  margin-bottom: 8px;
}
.desk .body {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.desk article button {
  display: block;
  margin-top: 8px;
}
.empty {
  background: #f3f7f6;
  padding: 25px;
  border-radius: 9px;
}
.desk [role='alert'] {
  color: #a73535;
}
.desk [role='status'] {
  color: #286345;
}
</style>
