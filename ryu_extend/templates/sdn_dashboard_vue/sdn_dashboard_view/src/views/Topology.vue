<script setup>
import { ref, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { fetchTopology } from '../api'

const topo = ref({ switches: [], links: [], hosts: [] })
const loading = ref(true)
const refreshing = ref(false)
const msg = ref('')

let svg = null
let topoGroup = null
let zoom = null
let simulation = null

function buildGraph() {
  const nodes = []
  const links = []

  // 交换机节点
  for (const dpid of (topo.value.switches || [])) {
    nodes.push({ id: `switch-${dpid}`, label: `s${dpid}`, type: 'switch' })
  }

  // 主机节点
  const hostIds = new Set()
  for (const host of (topo.value.hosts || [])) {
    const hid = host.mac || host.ip
    if (hostIds.has(hid)) continue
    hostIds.add(hid)
    const role = host.role || 'host'
    const isPending = host.pending || host.mac?.startsWith('pending_')
    nodes.push({
      id: hid,
      label: isPending ? (host.device_id || host.ip || '?') : (host.device_id || host.ip || '?'),
      fullLabel: host.device_name || host.device_id || host.ip || '',
      type: role === 'gateway' ? 'gateway' : role === 'iot' ? 'iot' : 'host',
      isPending,
    })
    // 主机 → 交换机（占位设备不连线）
    if (!isPending && host.switch_dpid > 0) {
      links.push({ source: hid, target: `switch-${host.switch_dpid}` })
    } else if (isPending) {
      // 占位设备：连到最近的交换机或游离显示
    }
  }

  // 交换机间链路
  for (const l of (topo.value.links || [])) {
    links.push({ source: l.src_switch, target: l.dst_switch, isSwitchLink: true })
  }

  return { nodes, links }
}

function nodeColor(d) {
  if (d.type === 'switch') return '#667eea'
  if (d.type === 'gateway') return '#ecc94b'
  if (d.type === 'iot') return '#48bb78'
  return '#a0aec0' // host
}

function nodeRadius(d) {
  if (d.type === 'switch') return 28
  if (d.type === 'gateway') return 22
  return 18
}

function renderGraph() {
  const graph = buildGraph()
  if (graph.nodes.length === 0) return

  const el = document.getElementById('topo-graph')
  if (!el) return
  el.innerHTML = ''

  const width = el.clientWidth || 800
  const height = 480

  svg = d3.select('#topo-graph')
    .append('svg')
    .attr('width', width)
    .attr('height', height)
    .attr('viewBox', `0 0 ${width} ${height}`)

  // 缩放
  zoom = d3.zoom()
    .scaleExtent([0.3, 4])
    .on('zoom', (event) => { topoGroup.attr('transform', event.transform) })

  svg.call(zoom)
  topoGroup = svg.append('g')

  // 箭头定义
  svg.append('defs').append('marker')
    .attr('id', 'arrowhead')
    .attr('viewBox', '0 -5 10 10')
    .attr('refX', 30)
    .attr('refY', 0)
    .attr('markerWidth', 6)
    .attr('markerHeight', 6)
    .attr('orient', 'auto')
    .append('path')
    .attr('d', 'M0,-5L10,0L0,5')
    .attr('fill', '#4a5568')

  // 链路
  const link = topoGroup.append('g')
    .selectAll('line')
    .data(graph.links)
    .enter()
    .append('line')
    .attr('stroke', d => d.isSwitchLink ? '#667eea' : '#4a5568')
    .attr('stroke-width', d => d.isSwitchLink ? 3 : 1.5)
    .attr('stroke-dasharray', d => d.isSwitchLink ? '' : '5,3')
    .attr('marker-end', d => d.isSwitchLink ? 'url(#arrowhead)' : '')

  // 节点组
  const node = topoGroup.append('g')
    .selectAll('g')
    .data(graph.nodes)
    .enter()
    .append('g')
    .call(d3.drag()
      .on('start', (event, d) => {
        if (!event.active) simulation.alphaTarget(0.3).restart()
        d.fx = d.x; d.fy = d.y
      })
      .on('drag', (event, d) => { d.fx = event.x; d.fy = event.y })
      .on('end', (event, d) => {
        if (!event.active) simulation.alphaTarget(0)
        d.fx = null; d.fy = null
      }))

  // 圆圈
  node.append('circle')
    .attr('r', d => nodeRadius(d))
    .attr('fill', d => nodeColor(d))
    .attr('stroke', '#fff')
    .attr('stroke-width', 2)
    .attr('stroke-dasharray', d => d.isPending ? '4,2' : '')

  // 占位标记：圆圈内加 ? 号
  node.filter(d => d.isPending).append('text')
    .attr('text-anchor', 'middle')
    .attr('dy', -16)
    .attr('fill', '#fbbf24')
    .attr('font-size', 12)
    .attr('font-weight', 'bold')
    .text('?')

  // 主标签
  node.append('text')
    .attr('text-anchor', 'middle')
    .attr('dy', 4)
    .attr('fill', '#fff')
    .attr('font-size', d => d.type === 'switch' ? 13 : 11)
    .attr('font-weight', 'bold')
    .text(d => d.label)

  // IP 副标签（小字，圆圈下方）
  node.filter(d => d.ip)
    .append('text')
    .attr('text-anchor', 'middle')
    .attr('dy', d => nodeRadius(d) + 12)
    .attr('fill', '#a0aec0')
    .attr('font-size', 9)
    .text(d => d.ip)

  // 力模拟
  simulation = d3.forceSimulation(graph.nodes)
    .force('link', d3.forceLink(graph.links).id(d => d.id).distance(d => d.isSwitchLink ? 180 : 100))
    .force('charge', d3.forceManyBody().strength(-400))
    .force('center', d3.forceCenter(width / 2, height / 2))
    .force('collide', d3.forceCollide(40))
    .on('tick', () => {
      link
        .attr('x1', d => d.source.x)
        .attr('y1', d => d.source.y)
        .attr('x2', d => d.target.x)
        .attr('y2', d => d.target.y)
      node.attr('transform', d => `translate(${d.x}, ${d.y})`)
    })

  // 双击重置
  svg.on('dblclick', () => {
    svg.transition().duration(500).call(zoom.transform, d3.zoomIdentity)
  })
}

function loadTopology() {
  loading.value = true
  fetchTopology()
    .then(d => {
      topo.value = d || { switches: [], links: [], hosts: [] }
    })
    .catch(e => { console.error(e); msg.value = '加载拓扑失败' })
    .finally(() => {
      loading.value = false
      nextTick(renderGraph)
    })
}

async function refreshTopology() {
  refreshing.value = true
  msg.value = ''
  try {
    await fetch('/api/topology/refresh', { method: 'POST' })
    await new Promise(r => setTimeout(r, 3000))
    await fetchTopology().then(d => {
      topo.value = d || { switches: [], links: [], hosts: [] }
    })
    nextTick(renderGraph)
  } catch (e) {
    console.error('拓扑刷新失败:', e)
    msg.value = '刷新失败'
  } finally {
    refreshing.value = false
  }
}

onMounted(loadTopology)

onUnmounted(() => {
  if (simulation) simulation.stop()
})
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h2>网络拓扑</h2>
      <div style="display:flex;gap:10px;align-items:center;">
        <span v-if="msg" style="color:#ecc94b;font-size:13px;">{{ msg }}</span>
        <button class="btn-primary" :disabled="refreshing" @click="refreshTopology">
          {{ refreshing ? '刷新中...' : '🔄 刷新拓扑' }}
        </button>
      </div>
    </div>

    <div v-if="topo.timestamp" class="topo-time">
      更新时间: {{ new Date(topo.timestamp * 1000).toLocaleString() }}
    </div>

    <!-- 拓扑图 -->
    <div class="topo-graph-container">
      <div v-if="loading" class="page-loading">加载中...</div>
      <div v-else-if="topo.switches.length === 0 && topo.hosts.length === 0" class="empty-hint">
        暂无拓扑数据，点击刷新
      </div>
      <div id="topo-graph" class="topo-graph-svg"></div>
    </div>

    <!-- 图例 -->
    <div class="legend">
      <span class="legend-item"><span class="dot" style="background:#667eea;"></span> 交换机</span>
      <span class="legend-item"><span class="dot" style="background:#ecc94b;"></span> 网关</span>
      <span class="legend-item"><span class="dot" style="background:#48bb78;"></span> IoT设备</span>
      <span class="legend-item"><span class="dot" style="background:#a0aec0;"></span> 主机</span>
      <span class="legend-item" style="margin-left:20px;">━ 交换机链路</span>
      <span class="legend-item">┅ 主机连接</span>
    </div>

    <!-- 数据明细 -->
    <div class="topo-grid">
      <div>
        <h3>交换机 ({{ topo.switches.length }})</h3>
        <table v-if="topo.switches.length" class="data-table">
          <thead><tr><th>DPID</th></tr></thead>
          <tbody>
            <tr v-for="(dpid, i) in topo.switches" :key="i">
              <td><code>switch-{{ dpid }}</code></td>
            </tr>
          </tbody>
        </table>
      </div>
      <div>
        <h3>链路 ({{ topo.links.length }})</h3>
        <table v-if="topo.links.length" class="data-table">
          <thead><tr><th>源</th><th>目的</th></tr></thead>
          <tbody>
            <tr v-for="(l, i) in topo.links" :key="i">
              <td><code>{{ l.src_switch }}:{{ l.src_port }}</code></td>
              <td><code>{{ l.dst_switch }}:{{ l.dst_port }}</code></td>
            </tr>
          </tbody>
        </table>
      </div>
      <div>
        <h3>主机 ({{ topo.hosts.length }})</h3>
        <table v-if="topo.hosts.length" class="data-table">
          <thead><tr><th>设备</th><th>IP</th><th>位置</th></tr></thead>
          <tbody>
            <tr v-for="(h, i) in topo.hosts" :key="i">
              <td><strong>{{ h.device_id || '?' }}</strong></td>
              <td>{{ h.ip }}</td>
              <td><code>s{{ h.switch_dpid }}:{{ h.port }}</code></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page { max-width: 1100px; margin: 0 auto; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.page-header h2 { margin: 0; }
.btn-primary {
  padding: 8px 18px; border: none; border-radius: 8px;
  background: linear-gradient(135deg, #667eea, #764ba2); color: #fff;
  cursor: pointer; font-weight: 600; font-size: 14px;
}
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.topo-time { color: #a0aec0; font-size: 13px; margin-bottom: 10px; }
.page-loading { text-align: center; padding: 60px; color: #a0aec0; }
.empty-hint { text-align: center; padding: 60px; color: #64748b; }
.topo-graph-container { margin-bottom: 15px; }
.topo-graph-svg {
  width: 100%; min-height: 480px;
  background: #1e293b; border-radius: 12px;
  overflow: hidden; cursor: grab;
}
.topo-graph-svg:active { cursor: grabbing; }
.topo-graph-svg :deep(svg) { display: block; }
.legend {
  display: flex; flex-wrap: wrap; gap: 16px; margin-bottom: 20px;
  padding: 10px 16px; background: #1e293b; border-radius: 8px;
  font-size: 13px; color: #a0aec0;
}
.legend-item { display: flex; align-items: center; gap: 6px; }
.dot { width: 12px; height: 12px; border-radius: 50%; display: inline-block; }
.topo-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
.topo-grid h3 { margin: 0 0 8px 0; color: #e2e8f0; font-size: 15px; }
.data-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.data-table th { text-align: left; padding: 6px 10px; background: #0f172a; color: #a0aec0; }
.data-table td { padding: 6px 10px; border-bottom: 1px solid #1e293b; color: #e2e8f0; }
.data-table code { color: #667eea; font-size: 12px; }
@media (max-width: 768px) {
  .topo-grid { grid-template-columns: 1fr; }
}
</style>
