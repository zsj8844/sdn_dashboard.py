import { useEffect, useState } from 'react';
import { fetchApps, createApp, deleteApp, deployApp, undeployApp } from '../api';

interface AppInfo {
  app_id: string;
  app_name: string;
  app_type: string;
  version: string;
  description: string;
  status: string;
  created_at?: string;
  updated_at?: string;
}

export default function Apps() {
  const [apps, setApps] = useState<AppInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [msg, setMsg] = useState('');
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({
    app_id: '',
    app_name: '',
    app_type: 'edge',
    app_code: '',
    version: '1.0.0',
    description: '',
  });

  const loadApps = () => {
    setLoading(true);
    fetchApps()
      .then((d) => setApps(d.apps || []))
      .catch(console.error)
      .finally(() => setLoading(false));
  };

  useEffect(() => { loadApps(); }, []);

  const handleCreate = async () => {
    if (!form.app_id || !form.app_name) return;
    setMsg('');
    try {
      const res = await createApp(form);
      if (res.status === 'success') {
        setMsg('应用创建成功');
        setShowForm(false);
        setForm({ app_id: '', app_name: '', app_type: 'edge', app_code: '', version: '1.0.0', description: '' });
        loadApps();
      } else {
        setMsg(`错误: ${res.message}`);
      }
    } catch {
      setMsg('请求失败');
    }
  };

  const handleDelete = async (appId: string) => {
    setMsg('');
    try {
      const res = await deleteApp(appId);
      if (res.status === 'success') { setMsg('删除成功'); loadApps(); }
      else setMsg(`错误: ${res.message}`);
    } catch { setMsg('请求失败'); }
  };

  const handleDeploy = async (appId: string) => {
    setMsg('');
    try {
      const res = await deployApp(appId);
      if (res.status === 'success') { setMsg(`${appId} 部署成功`); loadApps(); }
      else setMsg(`错误: ${res.message}`);
    } catch { setMsg('请求失败'); }
  };

  const handleUndeploy = async (appId: string) => {
    setMsg('');
    try {
      const res = await undeployApp(appId);
      if (res.status === 'success') { setMsg(`${appId} 取消部署`); loadApps(); }
      else setMsg(`错误: ${res.message}`);
    } catch { setMsg('请求失败'); }
  };

  if (loading) return <div className="page-loading">加载中...</div>;

  return (
    <div className="page">
      <div className="page-header">
        <h2>应用部署</h2>
        <button className="btn-primary" onClick={() => setShowForm(!showForm)}>
          {showForm ? '取消' : '+ 新建应用'}
        </button>
      </div>

      {msg && <div className={`msg ${msg.includes('成功') ? 'msg-ok' : 'msg-err'}`}>{msg}</div>}

      {showForm && (
        <div className="form-panel">
          <h3>新建应用</h3>
          <div className="form-grid">
            <label>应用 ID: <input value={form.app_id} onChange={(e) => setForm({ ...form, app_id: e.target.value })} placeholder="temperature_monitor" /></label>
            <label>应用名称: <input value={form.app_name} onChange={(e) => setForm({ ...form, app_name: e.target.value })} placeholder="温度监测" /></label>
            <label>类型:
              <select value={form.app_type} onChange={(e) => setForm({ ...form, app_type: e.target.value })}>
                <option value="edge">edge</option>
                <option value="cloud">cloud</option>
                <option value="hybrid">hybrid</option>
              </select>
            </label>
            <label>版本: <input value={form.version} onChange={(e) => setForm({ ...form, version: e.target.value })} /></label>
            <label className="form-full">代码:
              <textarea value={form.app_code} onChange={(e) => setForm({ ...form, app_code: e.target.value })} placeholder="# Python 应用代码..." rows={4} />
            </label>
            <label className="form-full">描述:
              <input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder="应用描述..." />
            </label>
          </div>
          <button className="btn-primary" onClick={handleCreate}>创建</button>
        </div>
      )}

      {apps.length === 0 ? (
        <div className="empty-hint">暂无应用，点击"+ 新建应用"创建</div>
      ) : (
        <table className="data-table">
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
            {apps.map((app) => (
              <tr key={app.app_id}>
                <td><code>{app.app_id}</code></td>
                <td>{app.app_name}</td>
                <td><span className="status-badge info">{app.app_type}</span></td>
                <td>{app.version}</td>
                <td>
                  <span className={`status-badge ${app.status === 'deployed' ? 'online' : 'offline'}`}>
                    {app.status}
                  </span>
                </td>
                <td className="actions-cell">
                  {app.status === 'deployed' ? (
                    <button className="btn-warn" onClick={() => handleUndeploy(app.app_id)}>卸载</button>
                  ) : (
                    <button className="btn-primary" onClick={() => handleDeploy(app.app_id)}>部署</button>
                  )}
                  <button className="btn-danger" onClick={() => handleDelete(app.app_id)}>删除</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
