<script setup>
import { ref, onMounted } from 'vue'
import { fetchApps, createApp, deleteApp, deployApp, undeployApp } from '../api'

const apps = ref([])
const loading = ref(true)
const msg = ref('')
const showForm = ref(false)
const form = ref({
  app_id: '',
  app_name: '',
  app_type: 'edge',
  app_code: '',
  version: '1.0.0',
  description: '',
})

function loadApps() {
  loading.value = true
  fetchApps()
    .then(d => apps.value = d.apps || [])
    .catch(console.error)
    .finally(() => loading.value = false)
}

onMounted(loadApps)

async function handleCreate() {
  if (!form.value.app_id || !form.value.app_name) return
  msg.value = ''
  try {
    const res = await createApp(form.value)
    if (res.status === 'success') {
      msg.value = '应用创建成功'
      showForm.value = false
      form.value = { app_id: '', app_name: '', app_type: 'edge', app_code: '', version: '1.0.0', description: '' }
      loadApps()
    } else {
      msg.value = `错误: ${res.message}`
    }
  } catch {
    msg.value = '请求失败'
  }
}

async function handleDelete(appId) {
  msg.value = ''
  try {
    const res = await deleteApp(appId)
    if (res.status === 'success') { msg.value = '删除成功'; loadApps() }
    else msg.value = `错误: ${res.message}`
  } catch { msg.value = '请求失败' }
}

async function handleDeploy(appId) {
  msg.value = ''
  try {
    const res = await deployApp(appId)
    if (res.status === 'success') { msg.value = `${appId} 部署成功`; loadApps() }
    else msg.value = `错误: ${res.message}`
  } catch { msg.value = '请求失败' }
}

async function handleUndeploy(appId) {
  msg.value = ''
  try {
    const res = await undeployApp(appId)
    if (res.status === 'success') { msg.value = `${appId} 取消部署`; loadApps() }
    else msg.value = `错误: ${res.message}`
  } catch { msg.value = '请求失败' }
}
</script>

<template>
  <div class="page">
    <div v-if="loading" class="page-loading">加载中...</div>
    <template v-else>
      <div class="page-header">
        <h2>应用部署</h2>
        <button class="btn-primary" @click="showForm = !showForm">
          {{ showForm ? '取消' : '+ 新建应用' }}
        </button>
      </div>

      <div v-if="msg" :class="['msg', msg.includes('成功') ? 'msg-ok' : 'msg-err']">{{ msg }}</div>

      <div v-if="showForm" class="form-panel">
        <h3>新建应用</h3>
        <div class="form-grid">
          <label>应用 ID: <input v-model="form.app_id" placeholder="temperature_monitor" /></label>
          <label>应用名称: <input v-model="form.app_name" placeholder="温度监测" /></label>
          <label>类型:
            <select v-model="form.app_type">
              <option value="edge">edge</option>
              <option value="cloud">cloud</option>
              <option value="hybrid">hybrid</option>
            </select>
          </label>
          <label>版本: <input v-model="form.version" /></label>
          <label class="form-full">代码:
            <textarea v-model="form.app_code" placeholder="# Python 应用代码..." rows="4" />
          </label>
          <label class="form-full">描述:
            <input v-model="form.description" placeholder="应用描述..." />
          </label>
        </div>
        <button class="btn-primary" @click="handleCreate">创建</button>
      </div>

      <div v-if="apps.length === 0" class="empty-hint">暂无应用，点击"+ 新建应用"创建</div>
      <table v-else class="data-table">
        <thead>
          <tr>
            <th>应用 ID</th>
            <th>名称</th>
            <th>类型</th>
            <th>版本</th>
            <th>状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="app in apps" :key="app.app_id">
            <td><code>{{ app.app_id }}</code></td>
            <td>{{ app.app_name }}</td>
            <td><span class="status-badge info">{{ app.app_type }}</span></td>
            <td>{{ app.version }}</td>
            <td>
              <span :class="['status-badge', app.status === 'deployed' ? 'online' : 'offline']">
                {{ app.status }}
              </span>
            </td>
            <td class="actions-cell">
              <button v-if="app.status === 'deployed'" class="btn-warn" @click="handleUndeploy(app.app_id)">卸载</button>
              <button v-else class="btn-primary" @click="handleDeploy(app.app_id)">部署</button>
              <button class="btn-danger" @click="handleDelete(app.app_id)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
    </template>
  </div>
</template>
