<script setup>
import { ref, onMounted } from 'vue'
import { fetchDeviceIdentityConfig, addDeviceIdentity, deleteDeviceIdentity, reloadControllerConfig } from '../api'

const config = ref({ devices: {} })
const loading = ref(true)
const msg = ref('')

const form = ref({
  ip: '',
  device_id: '',
  device_name: '',
  device_type: 'temperature_sensor',
  role: 'iot',
})

const deviceTypes = [
  { value: 'temperature_sensor', label: '温度传感器' },
  { value: 'humidity_sensor', label: '湿度传感器' },
  { value: 'position_sensor', label: '位置传感器' },
  { value: 'light_sensor', label: '光照传感器' },
  { value: 'motion_sensor', label: '移动传感器' },
  { value: 'pressure_sensor', label: '压力传感器' },
  { value: 'gateway', label: '网关' },
  { value: 'host', label: '传统终端' },
]

const roles = [
  { value: 'iot', label: 'IoT设备' },
  { value: 'gateway', label: '网关' },
  { value: 'host', label: '传统主机' },
]

function loadConfig() {
  loading.value = true
  fetchDeviceIdentityConfig()
    .then(d => config.value = d)
    .catch(console.error)
    .finally(() => loading.value = false)
}

onMounted(loadConfig)

async function handleAdd() {
  if (!form.value.ip || !form.value.device_id) {
    msg.value = '请填写IP地址和设备ID'
    return
  }
  msg.value = ''
  try {
    const res = await addDeviceIdentity(form.value)
    if (res.status === 'success') {
      msg.value = '添加成功'
      form.value = { ip: '', device_id: '', device_name: '', device_type: 'temperature_sensor', role: 'iot' }
      loadConfig()
    } else {
      msg.value = `错误: ${res.message}`
    }
  } catch {
    msg.value = '请求失败'
  }
}

async function handleDelete(ip) {
  if (!confirm(`确定删除 ${ip} 的设备配置？`)) return
  msg.value = ''
  try {
    const res = await deleteDeviceIdentity(ip)
    if (res.status === 'success') { msg.value = '删除成功'; loadConfig() }
    else { msg.value = `错误: ${res.message}` }
  } catch {
    msg.value = '请求失败'
  }
}

async function handleReload() {
  msg.value = ''
  try {
    const res = await reloadControllerConfig()
    msg.value = res.message || '重载信号已发出'
  } catch {
    msg.value = '请求失败'
  }
}

function roleStyle(role) {
  if (role === 'gateway') return 'color:#ecc94b'
  if (role === 'iot') return 'color:#48bb78'
  return 'color:#a0aec0'
}
</script>

<template>
  <div class="page">
    <h2>设备身份配置</h2>
    <p class="hint">配置IP地址与设备身份的映射。控制器收到数据包时自动根据源IP识别设备。</p>

    <div v-if="msg" class="toast" :class="{ error: msg.includes('失败') || msg.includes('错误') }">{{ msg }}</div>

    <!-- 添加设备 -->
    <section class="card">
      <h3>添加设备身份</h3>
      <div class="form-row">
        <input v-model="form.ip" placeholder="IP地址 (如 192.168.1.10)" class="inp" />
        <input v-model="form.device_id" placeholder="设备ID (如 iot1)" class="inp" />
        <input v-model="form.device_name" placeholder="设备名称 (如 温度传感器)" class="inp" />
        <select v-model="form.device_type" class="inp">
          <option v-for="t in deviceTypes" :key="t.value" :value="t.value">{{ t.label }}</option>
        </select>
        <select v-model="form.role" class="inp">
          <option v-for="r in roles" :key="r.value" :value="r.value">{{ r.label }}</option>
        </select>
        <button class="btn" @click="handleAdd">添加设备</button>
      </div>
      <button class="btn" @click="handleReload" style="margin-top:10px">通知控制器重载配置</button>
    </section>

    <!-- 已配置列表 -->
    <section class="card">
      <h3>已配置设备列表 ({{ Object.keys(config.devices || {}).length }})</h3>
      <div v-if="loading">加载中...</div>
      <div v-else-if="Object.keys(config.devices || {}).length === 0" class="empty">暂无设备配置</div>
      <div v-else class="list">
        <div v-for="(info, ip) in config.devices" :key="ip" class="row">
          <div class="info">
            <strong>{{ info.device_id }}</strong>
            <span v-if="info.device_name">({{ info.device_name }})</span>
            <span class="tag">IP: {{ ip }}</span>
            <span class="tag">类型: {{ info.device_type || '' }}</span>
            <span :style="roleStyle(info.role)">[{{ info.role || 'host' }}]</span>
          </div>
          <button class="btn danger" @click="handleDelete(ip)">删除</button>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.page { max-width: 900px; margin: 0 auto; }
.hint { color: #a0aec0; margin-bottom: 20px; }
.card { background: #1e293b; border-radius: 12px; padding: 20px; margin-bottom: 20px; }
.card h3 { margin: 0 0 15px 0; color: #e2e8f0; }
.form-row { display: flex; flex-wrap: wrap; gap: 10px; }
.inp { padding: 8px 12px; border-radius: 6px; border: 1px solid #334155; background: #0f172a; color: #e2e8f0; }
.btn { padding: 8px 16px; border: none; border-radius: 6px; background: linear-gradient(135deg, #667eea, #764ba2); color: #fff; cursor: pointer; font-weight: 600; }
.btn.danger { background: #dc3545; }
.toast { padding: 10px 16px; background: #48bb78; color: #fff; border-radius: 6px; margin-bottom: 15px; }
.toast.error { background: #dc3545; }
.empty { color: #64748b; }
.list { display: flex; flex-direction: column; gap: 8px; }
.row { display: flex; justify-content: space-between; align-items: center; padding: 10px 14px; background: #0f172a; border-radius: 8px; }
.info { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.info strong { color: #667eea; }
.tag { color: #a0aec0; font-size: 13px; }
</style>
