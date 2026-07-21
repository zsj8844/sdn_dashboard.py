const BASE = '/api'

export async function fetchData() {
  const res = await fetch(`${BASE}/data`)
  return res.json()
}

export async function fetchTopology() {
  const res = await fetch(`${BASE}/topology`)
  return res.json()
}

export async function fetchStats() {
  const res = await fetch(`${BASE}/stats`)
  return res.json()
}

export async function fetchFlows() {
  const res = await fetch(`${BASE}/flows`)
  return res.json()
}

export async function addFlow(flow) {
  const res = await fetch(`${BASE}/flows`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(flow),
  })
  return res.json()
}

export async function deleteFlow(flow) {
  const res = await fetch(`${BASE}/flows`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(flow),
  })
  return res.json()
}

export async function fetchApps() {
  const res = await fetch(`${BASE}/apps`)
  return res.json()
}

export async function createApp(app) {
  const res = await fetch(`${BASE}/apps`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(app),
  })
  return res.json()
}

export async function deleteApp(appId) {
  const res = await fetch(`${BASE}/apps/${appId}`, { method: 'DELETE' })
  return res.json()
}

export async function deployApp(appId, deviceId) {
  const res = await fetch(`${BASE}/apps/${appId}/deploy`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ device_id: deviceId }),
  })
  return res.json()
}

export async function undeployApp(appId, deviceId) {
  const res = await fetch(`${BASE}/apps/${appId}/undeploy`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ device_id: deviceId }),
  })
  return res.json()
}

// 设备身份配置
export async function fetchDeviceIdentityConfig() {
  const res = await fetch(`${BASE}/device-identity/config`)
  return res.json()
}

export async function addDeviceIdentity(device) {
  const res = await fetch(`${BASE}/device-identity/device`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(device),
  })
  return res.json()
}

export async function deleteDeviceIdentity(ip) {
  const res = await fetch(`${BASE}/device-identity/device/${ip}`, { method: 'DELETE' })
  return res.json()
}

export async function reloadControllerConfig() {
  const res = await fetch(`${BASE}/device-identity/reload`, { method: 'POST' })
  return res.json()
}
