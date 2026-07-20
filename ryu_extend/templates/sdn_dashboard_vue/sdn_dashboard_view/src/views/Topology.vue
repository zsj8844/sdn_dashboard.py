<script setup>
import { ref, onMounted } from 'vue'
import { fetchTopology } from '../api'

const topo = ref({ switches: [], links: [], hosts: [] })
const loading = ref(true)

onMounted(() => {
  fetchTopology()
    .then(d => topo.value = d || { switches: [], links: [], hosts: [] })
    .catch(console.error)
    .finally(() => loading.value = false)
})
</script>

<template>
  <div class="page">
    <div v-if="loading" class="page-loading">加载中...</div>
    <template v-else>
      <h2>网络拓扑</h2>
      <div v-if="topo.timestamp" class="topo-time">
        更新时间: {{ new Date(topo.timestamp * 1000).toLocaleString() }}
      </div>

      <div class="topo-grid">
        <div>
          <h3>交换机 ({{ topo.switches.length }})</h3>
          <div v-if="topo.switches.length === 0" class="empty-hint">等待拓扑发现...</div>
          <table v-else class="data-table">
            <thead>
              <tr><th>DPID</th><th>端口数</th></tr>
            </thead>
            <tbody>
              <tr v-for="sw in topo.switches" :key="sw.dpid">
                <td><code>{{ sw.dpid }}</code></td>
                <td>{{ sw.ports?.length || 0 }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div>
          <h3>链路 ({{ topo.links.length }})</h3>
          <div v-if="topo.links.length === 0" class="empty-hint">等待拓扑发现...</div>
          <table v-else class="data-table">
            <thead>
              <tr><th>源 DPID:Port</th><th>目的 DPID:Port</th></tr>
            </thead>
            <tbody>
              <tr v-for="(link, i) in topo.links" :key="i">
                <td><code>{{ link.src.dpid }}:{{ link.src.port }}</code></td>
                <td><code>{{ link.dst.dpid }}:{{ link.dst.port }}</code></td>
              </tr>
            </tbody>
          </table>
        </div>

        <div>
          <h3>主机 ({{ topo.hosts.length }})</h3>
          <div v-if="topo.hosts.length === 0" class="empty-hint">等待拓扑发现...</div>
          <table v-else class="data-table">
            <thead>
              <tr><th>MAC</th><th>IPv4</th><th>接入位置</th></tr>
            </thead>
            <tbody>
              <tr v-for="(host, i) in topo.hosts" :key="i">
                <td><code>{{ host.mac }}</code></td>
                <td>{{ host.ipv4?.join(', ') || 'N/A' }}</td>
                <td>{{ host.port ? `${host.port.dpid}:${host.port.port}` : 'N/A' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>
  </div>
</template>
