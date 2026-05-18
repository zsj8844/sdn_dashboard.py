import { useEffect, useState } from 'react';
import { fetchFlows, addFlow, deleteFlow } from '../api';

interface FlowEntry {
  dpid: number;
  flows: Record<string, string[]>;
}

interface FlowForm {
  dpid: number;
  priority: number;
  table_id: number;
  match: string;
  actions: string;
}

const defaultForm: FlowForm = {
  dpid: 1,
  priority: 10,
  table_id: 0,
  match: '',
  actions: 'output:2',
};

export default function Flows() {
  const [data, setData] = useState<FlowEntry | null>(null);
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState<FlowForm>(defaultForm);
  const [msg, setMsg] = useState('');

  const loadFlows = () => {
    setLoading(true);
    fetchFlows()
      .then(setData)
      .catch(console.error)
      .finally(() => setLoading(false));
  };

  useEffect(() => { loadFlows(); }, []);

  const handleAdd = async () => {
    if (!form.match.trim()) return;
    setMsg('');
    try {
      const res = await addFlow(form);
      if (res.status === 'success') {
        setMsg('流表添加成功');
        setForm({ ...form, match: '' });
        loadFlows();
      } else {
        setMsg(`错误: ${res.message}`);
      }
    } catch {
      setMsg('请求失败');
    }
  };

  const handleDelete = async (match: string) => {
    setMsg('');
    try {
      const res = await deleteFlow({ dpid: form.dpid, match });
      if (res.status === 'success') {
        setMsg('流表删除成功');
        loadFlows();
      } else {
        setMsg(`错误: ${res.message}`);
      }
    } catch {
      setMsg('请求失败');
    }
  };

  if (loading) return <div className="page-loading">加载中...</div>;

  const flows = data?.flows || {};
  const switchKeys = Object.keys(flows).sort();

  return (
    <div className="page">
      <h2>流表管理</h2>

      <div className="switch-tabs">
        {(switchKeys.length ? switchKeys : ['s1', 's2']).map((sw) => (
          <button
            key={sw}
            className={`tab-btn ${form.dpid === (sw === 's1' ? 1 : 2) ? 'active' : ''}`}
            onClick={() => setForm({ ...form, dpid: sw === 's1' ? 1 : 2 })}
          >
            {sw}
          </button>
        ))}
      </div>

      {msg && <div className={`msg ${msg.includes('成功') ? 'msg-ok' : 'msg-err'}`}>{msg}</div>}

      <div className="flow-form">
        <h3>添加流表</h3>
        <div className="form-row">
          <label>Match:
            <input
              value={form.match}
              onChange={(e) => setForm({ ...form, match: e.target.value })}
              placeholder="in_port=1"
            />
          </label>
          <label>Actions:
            <input
              value={form.actions}
              onChange={(e) => setForm({ ...form, actions: e.target.value })}
            />
          </label>
          <label>Priority:
            <input
              type="number"
              value={form.priority}
              onChange={(e) => setForm({ ...form, priority: +e.target.value })}
              style={{ width: 70 }}
            />
          </label>
          <button onClick={handleAdd}>添加</button>
        </div>
      </div>

      <h3>
        当前流表 — s{form.dpid}
      </h3>

      {Object.keys(flows).length === 0 ? (
        <div className="empty-hint">无流表数据，请确认控制器已连接交换机</div>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>交换机</th>
              <th>流表项</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(flows).map(([sw, entries]) =>
              entries.map((entry, i) => (
                <tr key={`${sw}-${i}`}>
                  <td><span className="status-badge online">{sw}</span></td>
                  <td><code className="flow-code">{entry}</code></td>
                  <td>
                    <button
                      className="btn-danger"
                      onClick={() => handleDelete(entry)}
                    >
                      删除
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}
