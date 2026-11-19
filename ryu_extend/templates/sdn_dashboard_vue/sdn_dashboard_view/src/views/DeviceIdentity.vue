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

</script>

<template>
  <div class="page">
    <h2>设备身份配置</h2>
    <p class="page-hint">配置IP地址与设备身份的映射。控制器收到数据包时自动根据源IP识别设备。</p>

    <div v-if="msg" :class="['msg', msg.includes('失败') || msg.includes('错误') ? 'msg-err' : 'msg-ok']">{{ msg }}</div>

    <!-- 添加设备 -->
    <div class="form-panel">
      <h3>添加设备身份</h3>
      <div class="form-row">
        <label>IP地址:
          <input v-model="form.ip" placeholder="192.168.1.10" />
        </label>
        <label>设备ID:
          <input v-model="form.device_id" placeholder="iot1" />
        </label>
        <label>设备名称:
          <input v-model="form.device_name" placeholder="温度传感器" />
        </label>
        <label>类型:
          <select v-model="form.device_type">
            <option v-for="t in deviceTypes" :key="t.value" :value="t.value">{{ t.label }}</option>
          </select>
        </label>
        <label>角色:
          <select v-model="form.role">
            <option v-for="r in roles" :key="r.value" :value="r.value">{{ r.label }}</option>
          </select>
        </label>
        <button class="btn-primary" @click="handleAdd">添加设备</button>
      </div>
      <div class="form-actions">
        <button class="btn-secondary" @click="handleReload">通知控制器重载配置</button>
      </div>
    </div>

    <!-- 已配置列表 -->
    <h3>已配置设备列表 ({{ Object.keys(config.devices || {}).length }})</h3>
    <div v-if="loading" class="page-loading">加载中...</div>
    <div v-else-if="Object.keys(config.devices || {}).length === 0" class="empty-hint">暂无设备配置</div>
    <table v-else class="data-table">
      <thead>
        <tr>
          <th>设备</th>
          <th>IP</th>
          <th>类型</th>
          <th>角色</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(info, ip) in config.devices" :key="ip">
          <td>
            <strong>{{ info.device_id }}</strong>
            <span v-if="info.device_name" style="color:#6b7280"> ({{ info.device_name }})</span>
          </td>
          <td><code>{{ ip }}</code></td>
          <td>{{ info.device_type || '-' }}</td>
          <td><span :class="['status-badge', info.role || 'host']">{{ info.role || 'host' }}</span></td>
          <td><button class="btn-danger" @click="handleDelete(ip)">删除</button></td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
