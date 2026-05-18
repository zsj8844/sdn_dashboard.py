import { useEffect, useState } from 'react';
import { fetchData } from '../api';

interface BLENode {
  id: string;
  type: string;
  status: string;
  rssi: number;
  battery: number;
}

interface SwitchStatus {
  connected: boolean;
  last_seen: string | null;
  dpid: string | null;
}

interface DashboardData {
  ble_mesh: { nodes: BLENode[] };
  gateway_logs: string[];
  s1_logs: string[];
  s2_logs: string[];
  s1_flows: string[];
  s2_flows: string[];
  switches_status: Record<string, SwitchStatus>;
}

export default function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchData()
      .then(setData)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="page-loading">加载中...</div>;
  if (!data) return <div className="page-error">无法连接到控制器</div>;

  const switches = data.switches_status || {};
  const bleNodes = data.ble_mesh?.nodes || [];
  const onlineBle = bleNodes.filter((n) => n.status === '在线').length;
  const onlineSw = Object.values(switches).filter((s) => s.connected).length;

  return (
    <div className="page">
      <h2>设备总览</h2>

      <div className="stats-grid">
        <div className="stat-card">
          <span className="stat-value">{Object.keys(switches).length}</span>
          <span className="stat-label">交换机</span>
          <span className="stat-sub">{onlineSw} 在线</span>
        </div>
        <div className="stat-card">
          <span className="stat-value">{bleNodes.length}</span>
          <span className="stat-label">BLE 节点</span>
          <span className="stat-sub">{onlineBle} 在线</span>
        </div>
        <div className="stat-card">
          <span className="stat-value">
            {(data.s1_flows?.length || 0) + (data.s2_flows?.length || 0)}
          </span>
          <span className="stat-label">流表项</span>
          <span className="stat-sub">s1 + s2</span>
        </div>
        <div className="stat-card">
          <span className="stat-value">{data.gateway_logs?.length || 0}</span>
          <span className="stat-label">网关日志</span>
          <span className="stat-sub">条</span>
        </div>
      </div>

      <h3>交换机状态</h3>
      <div className="switch-cards">
        {Object.entries(switches).map(([name, sw]) => (
          <div key={name} className={`switch-card ${sw.connected ? 'online' : 'offline'}`}>
            <div className="switch-card-header">
              <span className="switch-name">{name}</span>
              <span className={`status-badge ${sw.connected ? 'online' : 'offline'}`}>
                {sw.connected ? '在线' : '离线'}
              </span>
            </div>
            <div className="switch-card-body">
              <div>DPID: <code>{sw.dpid || 'N/A'}</code></div>
              <div>最后在线: {sw.last_seen || 'N/A'}</div>
              <div>流表项: {name === 's1' ? data.s1_flows?.length : data.s2_flows?.length}</div>
            </div>
          </div>
        ))}
      </div>

      <h3>BLE Mesh 节点</h3>
      <table className="data-table">
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
          {bleNodes.map((node) => (
            <tr key={node.id}>
              <td><code>{node.id}</code></td>
              <td>{node.type}</td>
              <td>
                <span className={`status-badge ${node.status === '在线' ? 'online' : 'offline'}`}>
                  {node.status}
                </span>
              </td>
              <td>{node.rssi} dBm</td>
              <td>
                <div className="battery-bar">
                  <div className="battery-fill" style={{ width: `${node.battery}%` }} />
                  <span>{node.battery}%</span>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3>网关日志</h3>
      <div className="log-panel">
        {data.gateway_logs?.slice(-20).map((log, i) => (
          <div key={i} className="log-line">{log}</div>
        ))}
        {!data.gateway_logs?.length && <div className="log-empty">暂无日志</div>}
      </div>
    </div>
  );
}
