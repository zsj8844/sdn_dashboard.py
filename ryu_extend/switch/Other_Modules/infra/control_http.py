"""
内部控制 HTTP 服务
提供前端调用的控制接口（如触发 LLDP 拓扑刷新等）。
也提供 /install-path 让网关主动请求下发流表。
在控制器进程内运行，端口 16634，仅监听 127.0.0.1。
"""

import json
import logging
from wsgiref.simple_server import make_server
from urllib.parse import parse_qs

logger = logging.getLogger(__name__)

# ── 拓扑端口映射（Mininet 确定性分配） ──
# s1(dpid=1): port1→iot3, port2→s2
# s2(dpid=2): port1→s1, port2→h1, port3→h2

S1_FORWARD_FLOWS = [
    # (ipv4_dst, out_port, description)
    ('192.168.1.20', 2, '→ h1 via s2'),
    ('192.168.1.21', 2, '→ h2 via s2'),
    ('192.168.2.10', 1, '← iot1 via iot3'),
    ('192.168.3.11', 1, '← iot2 via iot3'),
    ('192.168.4.13', 1, '← iot4 via iot3'),
]

S2_FORWARD_FLOWS = [
    ('192.168.1.20', 2, '→ h1'),
    ('192.168.1.21', 3, '→ h2'),
    ('192.168.2.10', 1, '← iot1 via s1'),
    ('192.168.3.11', 1, '← iot2 via s1'),
    ('192.168.4.13', 1, '← iot4 via s1'),
]


class ControlHTTPServer:
    """
    内部控制 HTTP 服务

    路由：
      GET /refresh       — 手动触发一轮 LLDP 拓扑发现
      GET /install-path  — 网关请求预装转发流表，参数: src_ip, dst_ip（可选，不传则装全部）
      GET /install-all   — 预装所有 IoT↔host 双向流表
    """

    HOST = '127.0.0.1'
    PORT = 16634

    def __init__(self, lldp_manager, flow_manager=None, topology=None):
        self.lldp_manager = lldp_manager
        self.flow_manager = flow_manager
        self.topology = topology or {'switches': {}}
        self._flows_installed = False

    def start(self):
        """启动服务（阻塞），建议用 hub.spawn 运行在协程中"""
        try:
            server = make_server(self.HOST, self.PORT, _ControlApp(self))
            logger.info("内部控制服务已启动: http://%s:%d/", self.HOST, self.PORT)
            server.serve_forever()
        except Exception as e:
            logger.warning("内部控制服务启动失败: %s", e)

    def install_default_flows(self):
        """预装所有交换机上的默认转发流表（主动模式）"""
        switches = self.topology.get('switches', {})
        if not self.flow_manager:
            logger.warning("flow_manager 未注入，跳过流表预装")
            return 0, 0

        total = 0
        for dpid, datapath in switches.items():
            flows = S1_FORWARD_FLOWS if dpid == 1 else S2_FORWARD_FLOWS
            parser = datapath.ofproto_parser
            for ip_dst, out_port, desc in flows:
                match = parser.OFPMatch(eth_type=0x0800, ipv4_dst=ip_dst)
                actions = [parser.OFPActionOutput(out_port)]
                try:
                    self.flow_manager.add_flow(datapath, priority=100, match=match,
                                               actions=actions, idle_timeout=0)
                    logger.info("s%d 主动流表: %s → port%d (%s)", dpid, ip_dst, out_port, desc)
                    total += 1
                except Exception as e:
                    logger.error("s%d 流表安装失败(%s): %s", dpid, ip_dst, e)

        self._flows_installed = True
        s1_count = len(S1_FORWARD_FLOWS) if 1 in switches else 0
        s2_count = len(S2_FORWARD_FLOWS) if 2 in switches else 0
        return s1_count, s2_count


class _ControlApp:
    """WSGI 应用，路由分发"""

    def __init__(self, server: ControlHTTPServer):
        self.server = server

    def __call__(self, environ, start_response):
        path = environ.get('PATH_INFO', '')
        qs = environ.get('QUERY_STRING', '')
        params = parse_qs(qs)

        if path == '/refresh':
            return self._handle_refresh(start_response)
        elif path == '/install-all':
            return self._handle_install_all(start_response)
        elif path == '/install-path':
            return self._handle_install_path(start_response, params)

        start_response('404 Not Found', [('Content-Type', 'application/json')])
        return [json.dumps({"error": "not found"}).encode()]

    def _handle_refresh(self, start_response):
        """触发 LLDP 拓扑刷新"""
        self.server.lldp_manager.force_send()
        start_response('200 OK', [('Content-Type', 'application/json')])
        return [json.dumps({"status": "ok", "message": "LLDP refresh triggered"}).encode()]

    def _handle_install_all(self, start_response):
        """预装所有默认转发流表"""
        s1_count, s2_count = self.server.install_default_flows()
        start_response('200 OK', [('Content-Type', 'application/json')])
        return [json.dumps({
            "status": "ok",
            "message": f"Flows installed: s1={s1_count}, s2={s2_count}",
            "s1_flows": s1_count,
            "s2_flows": s2_count,
        }).encode()]

    def _handle_install_path(self, start_response, params):
        """按需安装单条路径（兼容网关的精确请求）"""
        src_ip = params.get('src_ip', [None])[0]
        dst_ip = params.get('dst_ip', [None])[0]

        if not src_ip or not dst_ip:
            # 参数不全就装全部
            s1_count, s2_count = self.server.install_default_flows()
            start_response('200 OK', [('Content-Type', 'application/json')])
            return [json.dumps({
                "status": "ok",
                "fallback": "install_all",
                "s1_flows": s1_count,
                "s2_flows": s2_count,
            }).encode()]

        # 单路径安装：只装涉及 src_ip 和 dst_ip 的流表
        switches = self.server.topology.get('switches', {})
        installed = 0
        for dpid, datapath in switches.items():
            flows = S1_FORWARD_FLOWS if dpid == 1 else S2_FORWARD_FLOWS
            parser = datapath.ofproto_parser
            target_ips = {src_ip, dst_ip}
            for ip_dst, out_port, _desc in flows:
                if ip_dst in target_ips:
                    match = parser.OFPMatch(eth_type=0x0800, ipv4_dst=ip_dst)
                    actions = [parser.OFPActionOutput(out_port)]
                    try:
                        self.server.flow_manager.add_flow(
                            datapath, priority=100, match=match,
                            actions=actions, idle_timeout=0)
                        installed += 1
                    except Exception as e:
                        logger.error("s%d 流表安装失败(%s): %s", dpid, ip_dst, e)

        start_response('200 OK', [('Content-Type', 'application/json')])
        return [json.dumps({
            "status": "ok",
            "src_ip": src_ip,
            "dst_ip": dst_ip,
            "flows_installed": installed,
        }).encode()]
