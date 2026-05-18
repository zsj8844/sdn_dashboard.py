const BASE = '/api';

export async function fetchData() {
  const res = await fetch(`${BASE}/data`);
  return res.json();
}

export async function fetchTopology() {
  const res = await fetch(`${BASE}/topology`);
  return res.json();
}

export async function fetchStats() {
  const res = await fetch(`${BASE}/stats`);
  return res.json();
}

export async function fetchFlows() {
  const res = await fetch(`${BASE}/flows`);
  return res.json();
}

export async function addFlow(flow: {
  dpid: number;
  priority?: number;
  table_id?: number;
  match: string;
  actions: string;
}) {
  const res = await fetch(`${BASE}/flows`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(flow),
  });
  return res.json();
}

export async function deleteFlow(flow: {
  dpid: number;
  priority?: number;
  table_id?: number;
  match: string;
}) {
  const res = await fetch(`${BASE}/flows`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(flow),
  });
  return res.json();
}

export async function fetchApps() {
  const res = await fetch(`${BASE}/apps`);
  return res.json();
}

export async function createApp(app: {
  app_id: string;
  app_name: string;
  app_type: string;
  app_code: string;
  version?: string;
  description?: string;
}) {
  const res = await fetch(`${BASE}/apps`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(app),
  });
  return res.json();
}

export async function deleteApp(appId: string) {
  const res = await fetch(`${BASE}/apps/${appId}`, { method: 'DELETE' });
  return res.json();
}

export async function deployApp(appId: string) {
  const res = await fetch(`${BASE}/apps/${appId}/deploy`, { method: 'POST' });
  return res.json();
}

export async function undeployApp(appId: string) {
  const res = await fetch(`${BASE}/apps/${appId}/undeploy`, { method: 'POST' });
  return res.json();
}
