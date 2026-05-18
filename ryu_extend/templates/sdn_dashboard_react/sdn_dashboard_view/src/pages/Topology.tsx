import { useEffect, useState } from 'react';
import { fetchTopology } from '../api';

interface Switch {
  dpid: string;
  ports?: number[];
}

interface Link {
  src: { dpid: string; port: number };
  dst: { dpid: string; port: number };
}

interface Host {
  mac: string;
  ipv4?: string[];
  port?: { dpid: string; port: number };
}

interface TopologyData {
  switches: Switch[];
  links: Link[];
  hosts: Host[];
  timestamp?: number;
}

export default function Topology() {
  const [topo, setTopo] = useState<TopologyData>({ switches: [], links: [], hosts: [] });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchTopology()
      .then((d) => setTopo(d || { switches: [], links: [], hosts: [] }))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="page-loading">加载中...</div>;

  return (
    <div className="page">
      <h2>网络拓扑</h2>
      {topo.timestamp && (
        <div className="topo-time">
          更新时间: {new Date(topo.timestamp * 1000).toLocaleString()}
        </div>
      )}

      <div className="topo-grid">
        <div>
          <h3>交换机 ({topo.switches.length})</h3>
          {topo.switches.length === 0 ? (
            <div className="empty-hint">等待拓扑发现...</div>
          ) : (
            <table className="data-table">
              <thead>
                <tr><th>DPID</th><th>端口数</th></tr>
              </thead>
              <tbody>
                {topo.switches.map((sw) => (
                  <tr key={sw.dpid}>
                    <td><code>{sw.dpid}</code></td>
                    <td>{sw.ports?.length || 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div>
          <h3>链路 ({topo.links.length})</h3>
          {topo.links.length === 0 ? (
            <div className="empty-hint">等待拓扑发现...</div>
          ) : (
            <table className="data-table">
              <thead>
                <tr><th>源 DPID:Port</th><th>目的 DPID:Port</th></tr>
              </thead>
              <tbody>
                {topo.links.map((link, i) => (
                  <tr key={i}>
                    <td><code>{link.src.dpid}:{link.src.port}</code></td>
                    <td><code>{link.dst.dpid}:{link.dst.port}</code></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div>
          <h3>主机 ({topo.hosts.length})</h3>
          {topo.hosts.length === 0 ? (
            <div className="empty-hint">等待拓扑发现...</div>
          ) : (
            <table className="data-table">
              <thead>
                <tr><th>MAC</th><th>IPv4</th><th>接入位置</th></tr>
              </thead>
              <tbody>
                {topo.hosts.map((host, i) => (
                  <tr key={i}>
                    <td><code>{host.mac}</code></td>
                    <td>{host.ipv4?.join(', ') || 'N/A'}</td>
                    <td>{host.port ? `${host.port.dpid}:${host.port.port}` : 'N/A'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
