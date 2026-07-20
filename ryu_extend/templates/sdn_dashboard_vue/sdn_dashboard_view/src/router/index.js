import { createRouter, createWebHistory } from 'vue-router'
import Dashboard from '../views/Dashboard.vue'
import Topology from '../views/Topology.vue'
import Flows from '../views/Flows.vue'
import Apps from '../views/Apps.vue'

const routes = [
  { path: '/', name: 'Dashboard', component: Dashboard },
  { path: '/topology', name: 'Topology', component: Topology },
  { path: '/flows', name: 'Flows', component: Flows },
  { path: '/apps', name: 'Apps', component: Apps },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
