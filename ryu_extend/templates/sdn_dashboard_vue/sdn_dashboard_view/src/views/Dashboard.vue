<script setup>
import { ref, onMounted } from 'vue'
import { fetchData } from '../api'

const data = ref(null)
const loading = ref(true)

onMounted(() => {
  fetchData()
    .then(setData)
    .catch(console.error)
    .finally(() => loading.value = false)
})

function setData(d) { data.value = d }

const switches = () => data.value?.switches_status || {}
const bleNodes = () => data.value?.ble_mesh?.nodes || []
const onlineBle = () => bleNodes().filter(n => n.status === '在线').length
const onlineSw = () => Object.values(switches()).filter(s => s.connected).length
</script>

<template>
  <div class="page">
    <div v-if="loading" class="page-loading">加载中...</div>
    <div v-else-if="!data" class="page-error">无法连接到控制器</div>
    <template v-else>
      <h2>设备总览</h2>

      <div class="stats-grid">
        <div class="stat-card">
          <span class="stat-value">{{ Object.keys(switches()).length }}</span>
          <span class="stat-label">交换机</span>
          <span class="stat-sub">{{ onlineSw() }} 在线</span>
        </div>
        <div class="stat-card">
          <span class="stat-value">{{ bleNodes().length }}</span>
          <span class="stat-label">BLE 节点</span>
          <span class="stat-sub">{{ onlineBle() }} 在线</span>
        </div>
        <div class="stat-card">
          <span class="stat-value">{{ (data.s1_flows?.length || 0) + (data.s2_flows?.length || 0) }}</span>
          <span class="stat-label">流表项</span>
          <span class="stat-sub">s1 + s2</span>
        </div>
        <div class="stat-card">
          <span class="stat-value">{{ data.gateway_logs?.length || 0 }}</span>
          <span class="stat-label">网关日志</span>
          <span class="stat-sub">条</span>
        </div>
      </div>

      <h3>交换机状态</h3>
      <div class="switch-cards">
        <div v-for="(sw, name) in switches()" :key="name" :class="['switch-card', sw.connected ? 'online' : 'offline']">
          <div class="switch-card-header">
            <span class="switch-name">{{ name }}</span>
            <span :class="['status-badge', sw.connected ? 'online' : 'offline']">
              {{ sw.connected ? '在线' : '离线' }}
            </span>
          </div>
          <div class="switch-card-body">
            <div>DPID: <code>{{ sw.dpid || 'N/A' }}</code></div>
            <div>最后在线: {{ sw.last_seen || 'N/A' }}</div>
            <div>流表项: {{ name === 's1' ? data.s1_flows?.length : data.s2_flows?.length }}</div>
          </div>
        </div>
      </div>

      <h3>BLE Mesh 节点</h3>
      <table class="data-table">
        <thead>
          <tr>
            <th>设备 ID</th>
            <th>类型</th>
            <th>状态</th>
            <th>信号 (RSSI)</th>
            <th>电量</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="node in bleNodes()" :key="node.id">
            <td><code>{{ node.id }}</code></td>
            <td>{{ node.type }}</td>
            <td>
              <span :class="['status-badge', node.status === '在线' ? 'online' : 'offline']">
                {{ node.status }}
              </span>
            </td>
            <td>{{ node.rssi }} dBm</td>
            <td>
              <div class="battery-bar">
                <div class="battery-fill" :style="{ width: node.battery + '%' }" />
                <span>{{ node.battery }}%</span>
              </div>
            </td>
          </tr>
        </tbody>
      </table>

      <h3>网关日志</h3>
      <div class="log-panel">
        <div v-for="(log, i) in data.gateway_logs?.slice(-20)" :key="i" class="log-line">{{ log }}</div>
        <div v-if="!data.gateway_logs?.length" class="log-empty">暂无日志</div>
      </div>
    </template>
  </div>
</template>
