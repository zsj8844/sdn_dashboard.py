<script setup>
const links = [
  { to: '/', label: '总览', icon: '◉' },
  { to: '/topology', label: '拓扑', icon: '⬡' },
  { to: '/flows', label: '流表', icon: '⇄' },
  { to: '/apps', label: '应用', icon: '⬢' },
]
</script>

<template>
  <aside class="sidebar">
    <div class="sidebar-brand">
      <h1>SDN Panel</h1>
      <span class="sidebar-sub">IoT 控制系统</span>
    </div>
    <nav class="sidebar-nav">
      <router-link v-for="link in links" :key="link.to" :to="link.to">
        <span class="nav-icon">{{ link.icon }}</span>
        {{ link.label }}
      </router-link>
    </nav>
  </aside>
</template>
