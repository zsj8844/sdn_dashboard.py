<script setup>
import { ref, onMounted, computed } from 'vue'
import { fetchFlows, addFlow, deleteFlow } from '../api'

const data = ref(null)
const loading = ref(true)
const form = ref({ dpid: 1, priority: 10, table_id: 0, match: '', actions: 'output:2' })
const msg = ref('')

const flows = computed(() => data.value?.flows || {})
const switchKeys = computed(() => Object.keys(flows.value).sort())

function loadFlows() {
  loading.value = true
  fetchFlows()
    .then(d => data.value = d)
    .catch(console.error)
    .finally(() => loading.value = false)
}

onMounted(loadFlows)

async function handleAdd() {
  if (!form.value.match.trim()) return
  msg.value = ''
  try {
    const res = await addFlow(form.value)
    if (res.status === 'success') {
      msg.value = '流表添加成功'
      form.value.match = ''
      loadFlows()
    } else {
      msg.value = `错误: ${res.message}`
    }
  } catch {
    msg.value = '请求失败'
  }
}

async function handleDelete(match) {
  msg.value = ''
  try {
    const res = await deleteFlow({ dpid: form.value.dpid, match })
    if (res.status === 'success') {
      msg.value = '流表删除成功'
      loadFlows()
    } else {
      msg.value = `错误: ${res.message}`
    }
  } catch {
    msg.value = '请求失败'
  }
}

function selectSwitch(sw) {
  form.value.dpid = sw === 's1' ? 1 : 2
}
</script>

<template>
  <div class="page">
    <div v-if="loading" class="page-loading">加载中...</div>
    <template v-else>
      <h2>流表管理</h2>

      <div class="switch-tabs">
        <button
          v-for="sw in (switchKeys.length ? switchKeys : ['s1', 's2'])"
          :key="sw"
          :class="['tab-btn', { active: form.dpid === (sw === 's1' ? 1 : 2) }]"
          @click="selectSwitch(sw)"
        >
          {{ sw }}
        </button>
      </div>

      <div v-if="msg" :class="['msg', msg.includes('成功') ? 'msg-ok' : 'msg-err']">{{ msg }}</div>

      <div class="flow-form">
        <h3>添加流表</h3>
        <div class="form-row">
          <label>Match:
            <input v-model="form.match" placeholder="in_port=1" />
          </label>
          <label>Actions:
            <input v-model="form.actions" />
          </label>
          <label>Priority:
            <input v-model.number="form.priority" type="number" style="width: 70px" />
          </label>
          <button @click="handleAdd">添加</button>
        </div>
      </div>

      <h3>当前流表 — s{{ form.dpid }}</h3>

      <div v-if="Object.keys(flows).length === 0" class="empty-hint">
        无流表数据，请确认控制器已连接交换机
      </div>
      <table v-else class="data-table">
        <thead>
          <tr>
            <th>交换机</th>
            <th>流表项</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="(entries, sw) in flows" :key="sw">
            <tr v-for="(entry, i) in entries" :key="`${sw}-${i}`">
              <td><span class="status-badge online">{{ sw }}</span></td>
              <td><code class="flow-code">{{ entry }}</code></td>
              <td>
                <button class="btn-danger" @click="handleDelete(entry)">删除</button>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </template>
  </div>
</template>
