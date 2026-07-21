"""
Packet-In 处理器
负责：包解析 → MAC学习 → ARP主机发现 → BLE数据解析 → 路由决策 → 转发 + 流表下发
从 ble_switch_13.py 抽取而来，降低主控制器文件复杂度。
"""

import requests
import logging
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet as pkt_lib, ethernet, ipv4, udp, arp as arp_pkt


class PacketProcessor:
    """Packet-In 全流程处理器"""

    def __init__(self, shared_state, modules):
        """
        shared_state: dict，包含共享数据:
            - mac_to_port, ble_port_map, ip_port_map
            - topology
            - device_identity_config
        modules: dict，包含依赖的子模块:
            - lldp_manager, topo_mgr, flow_manager, iot_processor, reporter
            - resolve_out_port (function)
            - web_panel_url (str)
            - logger (logging.Logger)
        """
        self.mac_to_port = shared_state['mac_to_port']
        self.ble_port_map = shared_state['ble_port_map']
        self.ip_port_map = shared_state['ip_port_map']
        self.topology = shared_state['topology']
        self.device_identity_config = shared_state.get('device_identity_config', {})

        self.lldp_mgr = modules['lldp_manager']
        self.topo_mgr = modules['topo_mgr']
        self.flow_mgr = modules['flow_manager']
        self.iot_proc = modules['iot_processor']
        self.reporter = modules['reporter']
        self.resolve_route = modules['resolve_out_port']
        self.web_panel_url = modules.get('web_panel_url', 'http://localhost:5000')
        self.logger = modules.get('logger') or logging.getLogger(__name__)

    # ═══════════════════ 主入口 ═══════════════════

    def handle(self, msg):
        """Packet-In 事件处理入口，由控制器 _packet_in_handler 调用"""
        datapath = msg.datapath
        dpid = datapath.id
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match.get('in_port', -1)

        if in_port == -1:
            self.logger.warning("数据包无in_port，跳过")
            return

        if in_port >= ofproto.OFPP_MAX:
            return

        # ① 解析
        pkt = pkt_lib.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)

        # ② 非以太网 → 泛洪
        if not eth:
            self._send(datapath, in_port, msg.buffer_id, msg.data,
                       ofproto.OFPP_FLOOD, ofproto, parser)
            return

        # ③ LLDP → 拓扑发现
        if eth.ethertype == ethernet.ether.ETH_TYPE_LLDP:
            self.lldp_mgr.handle_lldp_packet(dpid, in_port, pkt)
            return

        # ④ MAC 学习
        self.mac_to_port.setdefault(dpid, {})[eth.src] = in_port

        # ④½ ARP → 主机发现
        if eth.ethertype == ethernet.ether.ETH_TYPE_ARP:
            self._discover_from_arp(pkt, dpid, in_port, ofproto)

        # ⑤ 协议层
        ip = pkt.get_protocol(ipv4.ipv4)
        udp_pkt = pkt.get_protocol(udp.udp)

        # ⑥ IP 设备发现 + 身份识别
        if ip:
            self._handle_ip(eth, ip, udp_pkt, msg.data, dpid, in_port, ofproto)

        # ⑦ BLE 解析
        ext = self._parse_ble(ip, udp_pkt, msg.data)

        # ⑧ 路由 + 转发
        self._forward(datapath, dpid, eth, ip, msg, in_port,
                      parser, ext['priority'], ext['route'])

    # ═══════════════════ ARP 主机发现 ═══════════════════

    def _discover_from_arp(self, pkt, dpid, in_port, ofproto):
        arp_proto = pkt.get_protocol(arp_pkt.arp)
        if arp_proto and arp_proto.src_ip not in ('0.0.0.0', '192.168.1.1', '192.168.1.2'):
            dev_cfg = self.device_identity_config.get('devices', {}).get(arp_proto.src_ip)
            if in_port < ofproto.OFPP_MAX:
                self.topo_mgr.discover_device(
                    arp_proto.src_ip, arp_proto.src_mac, dpid, in_port, dev_cfg)

    # ═══════════════════ IP 处理 ═══════════════════

    def _handle_ip(self, eth, ip, udp_pkt, raw_data, dpid, in_port, ofproto):
        src_ip = ip.src
        self.ip_port_map[src_ip] = in_port

        if src_ip in ('192.168.1.1', '192.168.1.2'):
            return

        dev_cfg = self.device_identity_config.get('devices', {}).get(src_ip)
        if in_port < ofproto.OFPP_MAX:
            self.topo_mgr.discover_device(src_ip, eth.src, dpid, in_port, dev_cfg)

        if udp_pkt and udp_pkt.dst_port == 5005:
            self._warn_register(raw_data, ip)

    # ═══════════════════ BLE 解析 ═══════════════════

    def _parse_ble(self, ip, udp_pkt, raw_data):
        result = {'data': None, 'priority': 2, 'route': 'route_a'}
        if not (ip and udp_pkt and udp_pkt.dst_port == 5005):
            return result

        try:
            ip_header_len = (ip.version & 0xF) * 4
            total_header_len = 14 + ip_header_len + 8
            if total_header_len >= len(raw_data):
                return result

            raw = raw_data[total_header_len:].decode('utf-8', errors='ignore').strip()
            parts = raw.split(',', 2)
            if len(parts) < 3:
                return result

            ble_addr, ble_type, ble_value = parts
            self.ble_port_map[ble_addr] = -1  # port stored via ip_port_map
            self.logger.info("BLE: %s | %s | %s", ble_addr, ble_type, ble_value)

            try:
                requests.post(f"{self.web_panel_url}/api/logs",
                    json={"ble_addr": ble_addr, "type": ble_type,
                          "value": ble_value, "src_ip": ip.src}, timeout=1)
            except Exception:
                pass

            result = self.iot_proc.process(ble_type, ble_value)

        except Exception as e:
            self.logger.error("BLE解析失败: %s", e)

        return result

    # ═══════════════════ 转发 + 流表 ═══════════════════

    def _forward(self, datapath, dpid, eth, ip, msg, in_port, parser,
                 ext_priority, ext_route):
        ofproto = datapath.ofproto

        if ip and (
            ip.src in ('192.168.1.1', '192.168.1.2') or
            ip.dst.startswith(('224.', '239.', '255.'))
        ):
            return

        dst = eth.dst
        ip_dst = ip.dst if ip else '0.0.0.0'

        log_parts = [f"s{dpid} 收包 srcMAC={eth.src} dstMAC={dst} in={in_port}"]
        if ip:
            log_parts.append(f"srcIP={ip.src} dstIP={ip.dst}")
        self.logger.info(' '.join(log_parts))
        self.reporter.push_switch_log(dpid, ' '.join(log_parts))

        out_port, log_msg = self.resolve_route(
            dpid, dst, ip_dst if ip else None,
            self.mac_to_port, ext_route
        )
        self.logger.info(log_msg)
        self.reporter.push_switch_log(dpid, log_msg)

        if out_port is None:
            out_port = ofproto.OFPP_FLOOD

        self._send(datapath, in_port, msg.buffer_id, msg.data, out_port,
                   ofproto, parser)

        if out_port != ofproto.OFPP_FLOOD:
            if ip:
                match = parser.OFPMatch(eth_type=0x0800, ipv4_dst=ip.dst)
            else:
                match = parser.OFPMatch(in_port=in_port, eth_dst=dst)
            actions = [parser.OFPActionOutput(out_port)]
            priority = max(ext_priority * 10, 10)
            self.flow_mgr.add_flow(datapath, priority, match, actions, idle_timeout=60)
            self.logger.info(f"s{dpid} 流表: priority={priority} → port{out_port}")

    # ═══════════════════ PacketOut ═══════════════════

    def _send(self, datapath, in_port, buffer_id, data, out_port, ofproto, parser):
        actions = [parser.OFPActionOutput(out_port)]
        buf = buffer_id if buffer_id != ofproto.OFP_NO_BUFFER else ofproto.OFP_NO_BUFFER
        out = parser.OFPPacketOut(
            datapath=datapath, buffer_id=buf,
            in_port=in_port, actions=actions, data=data)
        datapath.send_msg(out)

    # ═══════════════════ 废弃消息检测 ═══════════════════

    def _warn_register(self, raw_data, ip):
        try:
            ip_header_len = (ip.version & 0xF) * 4
            total_header_len = 14 + ip_header_len + 8
            if total_header_len < len(raw_data):
                payload = raw_data[total_header_len:].decode('utf-8', errors='ignore').strip()
                if payload.startswith('register,'):
                    self.logger.warning("设备使用了已废弃的register消息，请通过Web面板配置")
        except Exception:
            pass
