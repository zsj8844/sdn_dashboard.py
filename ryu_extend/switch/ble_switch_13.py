import requests
from ryu.app import simple_switch_13
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, CONFIG_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ipv4, udp, arp, lldp
from ryu.lib import hub
import time
import json
from collections import defaultdict
#用于匹配和处理1001和1002ble数据包的常量
BLE_ADDR_MATCH = 1001
BLE_OUTPUT_ACTION = 1002
MY_EXPERIMENTER_ID = 0xdeadbeef

EXTENSIONS_AVAILABLE = False

try:
    from extensions.manager import IoTExtensionManager, create_iot_extension #iot扩展管理器
    from extensions.app_deployment import AppDeploymentManager #应用部署管理器
    from extensions.role_switch import DeviceRoleManager, DeviceMode, DeviceCapabilities #设备角色管理器
    EXTENSIONS_AVAILABLE = True #尝试导入扩展模块
except ImportError:
    EXTENSIONS_AVAILABLE = False

#继承原来的simple_switch_13.SimpleSwitch13ryu控制器
class BLEMeshSwitch13(simple_switch_13.SimpleSwitch13):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ble_port_map = {}
        self.ip_port_map = {}
        self.mac_to_port = {}

        self.extension_enabled = EXTENSIONS_AVAILABLE
        if self.extension_enabled:
            self.logger.info("OpenFlow扩展字段功能已启用")
            self.test_extension_functionality()
        else:
            self.logger.warning("OpenFlow扩展字段功能不可用")

        # self.topology 是该实例的一个属性，用于存储网络拓扑信息，包括：
        # 'switches': 存储网络中所有交换机的信息
        # 'links': 存储交换机之间的连接关系
        # 'hosts': 存储网络中的主机设备信息
        self.topology = {
            'switches': {},
            'links': [],
            'hosts': {}
        }
        # defaultdict(list) - 默认值为列表的字典，当访问不存在的键时会自动创建一个空列表
        self.port_stats = defaultdict(list)
        self.flow_stats = defaultdict(list)
        self.table_stats = defaultdict(dict)

        #发送lldp协议信息 主动向邻居广播自己的身份和连接信息 拓扑管理
        self.lldp_thread = hub.spawn(self._lldp_sender)
        self.lldp_interval = 5

        # 收集网络设备的端口、刘表统计信息
        self.stats_thread = hub.spawn(self._stats_collector)
        self.stats_interval = 10

        self.flow_tables = defaultdict(dict)

        self.web_panel_url = "http://localhost:5000"

        if self.extension_enabled:
            self.app_deployment_manager = AppDeploymentManager()
            self.device_role_manager = DeviceRoleManager()
            self.logger.info("应用下发和角色切换功能已初始化")

        self.logger.info("BLE Mesh Switch 13 初始化完成（增强版）")

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        super().switch_features_handler(ev)
        datapath = ev.msg.datapath
        dpid = datapath.id
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        self.topology['switches'][dpid] = datapath
        self.logger.info(f"交换机 {dpid} 已连接")

        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)
        self.logger.info(f"交换机 {dpid} 默认流表安装完成")

        self._report_topology_to_web()

    def add_flow(self, datapath, priority, match, actions, idle_timeout=0, hard_timeout=0, table_id=0):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(
            datapath=datapath, table_id=table_id, priority=priority, match=match,
            instructions=inst, idle_timeout=idle_timeout, hard_timeout=hard_timeout
        )
        datapath.send_msg(mod)

        dpid = datapath.id
        if table_id not in self.flow_tables[dpid]:
            self.flow_tables[dpid][table_id] = []
        self.flow_tables[dpid][table_id].append({
            'priority': priority,
            'match': self._match_to_dict(match),
            'actions': [str(action) for action in actions],
            'idle_timeout': idle_timeout,
            'hard_timeout': hard_timeout,
            'added_at': time.time()
        })

        self.logger.info(f"流表下发成功 - 表ID:{table_id}, 优先级:{priority}, 超时:{idle_timeout}s, 端口:{actions[0].port if actions else '无'}")

    def push_switch_log(self, dpid, message):
        try:
            log_endpoint = "s1" if dpid == 1 else "s2"
            log_data = {"message": message}
            requests.post(f"http://localhost:5000/api/logs/{log_endpoint}", json=log_data, timeout=1)
        except Exception as e:
            self.logger.debug(f"推送{log_endpoint}日志失败: {e}")

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        try:
            msg = ev.msg
            datapath = msg.datapath
            dpid = datapath.id
            ofproto = datapath.ofproto
            parser = datapath.ofproto_parser
            in_port = msg.match.get('in_port', -1)
            if in_port == -1:
                self.logger.warning("数据包无in_port，跳过处理")
                return
            pkt = packet.Packet(msg.data)
            self.logger.info(f"交换机{dpid}收到数据包: 端口{in_port} ({len(msg.data)}bytes)")
            eth_pkt = pkt.get_protocol(ethernet.ethernet)
            if not eth_pkt:
                self.logger.debug("非以太网包，泛洪转发")
                self._send_packet_out(datapath, in_port, msg.buffer_id, msg.data, ofproto.OFPP_FLOOD)
                return

            if eth_pkt.ethertype == ethernet.ether.ETH_TYPE_LLDP:
                self._handle_lldp_packet(dpid, in_port, pkt)
                return

            if dpid not in self.mac_to_port:
                self.mac_to_port[dpid] = {}
            self.mac_to_port[dpid][eth_pkt.src] = in_port
            self.logger.debug(f"交换机{dpid} MAC学习: {eth_pkt.src} -> 端口{in_port}")

            ip_pkt = pkt.get_protocol(ipv4.ipv4)
            udp_pkt = pkt.get_protocol(udp.udp)
            if ip_pkt:
                src_ip = ip_pkt.src
                self.ip_port_map[src_ip] = in_port
                self.logger.debug(f"IP端口映射更新: {self.ip_port_map}")

                if eth_pkt.src not in self.topology['hosts']:
                    self.topology['hosts'][eth_pkt.src] = {
                        'mac': eth_pkt.src,
                        'ip': ip_pkt.src,
                        'switch_dpid': dpid,
                        'port': in_port,
                        'first_seen': time.time()
                    }
                    self._report_topology_to_web()

            is_ble_packet = (ip_pkt and udp_pkt and udp_pkt.dst_port == 5005)

            if is_ble_packet:
                try:
                    ip_header_len = (ip_pkt.version & 0xF) * 4
                    total_header_len = 14 + ip_header_len + 8
                    if total_header_len < len(msg.data):
                        ble_raw_data = msg.data[total_header_len:].decode('utf-8', errors='ignore').strip()
                        ble_data = ble_raw_data.split(',', 2)
                        if len(ble_data) >= 3:
                            ble_addr, ble_type, ble_value = ble_data
                            self.ble_port_map[ble_addr] = in_port
                            log_msg = f"解析BLE数据 - 地址:{ble_addr} | 类型:{ble_type} | 数值:{ble_value} | 源IP:{ip_pkt.src} | 目标IP:{ip_pkt.dst}"
                            self.logger.info(log_msg)

                            try:
                                web_log_data = {"ble_addr": ble_addr, "type": ble_type, "value": ble_value, "src_ip": ip_pkt.src}
                                requests.post("http://localhost:5000/api/logs", json=web_log_data, timeout=1)
                            except Exception as e:
                                self.logger.warning(f"推送网关日志失败: {e}")

                            if self.extension_enabled:
                                self.process_iot_extension(ble_type, ble_value)
                except Exception as e:
                    self.logger.debug(f"BLE数据解析跳过: {e}")

            dst = eth_pkt.dst
            out_port = None

            src_mac = eth_pkt.src
            log_msg_prefix = f"交换机{dpid} 收到数据包 - 源MAC:{src_mac}, 目标MAC:{dst}, 入端口:{in_port}"
            if ip_pkt:
                log_msg_prefix += f", 源IP:{ip_pkt.src}, 目标IP:{ip_pkt.dst}"
                if udp_pkt:
                    log_msg_prefix += f", UDP源端口:{udp_pkt.src_port}, 目标端口:{udp_pkt.dst_port}"
            self.logger.info(log_msg_prefix)
            self.push_switch_log(dpid, log_msg_prefix)

            if dst in self.mac_to_port.get(dpid, {}):
                out_port = self.mac_to_port[dpid][dst]
                self.logger.info(f"交换机{dpid} 找到目标{dst}在端口{out_port}")
                self.push_switch_log(dpid, f"找到目标MAC {dst} 在端口 {out_port}")
            elif ip_pkt:
                if dpid == 1:
                    if ip_pkt.dst in ['192.168.1.20', '192.168.1.21']:
                        out_port = 2
                        log_msg = f"s1转发数据到s2 (端口2) - 源IP:{ip_pkt.src} -> 目标IP:{ip_pkt.dst}"
                        self.logger.info(log_msg)
                        self.push_switch_log(1, log_msg)
                    elif ip_pkt.dst in ['192.168.1.10', '192.168.1.11', '192.168.1.12', '192.168.1.13']:
                        out_port = 1
                        log_msg = f"s1转发数据到iot3 (端口1) - 源IP:{ip_pkt.src} -> 目标IP:{ip_pkt.dst}"
                        self.logger.info(log_msg)
                        self.push_switch_log(1, log_msg)
                elif dpid == 2:
                    if ip_pkt.dst == '192.168.1.20':
                        out_port = 2
                        log_msg = f"s2转发数据到h1 (端口2) - 源IP:{ip_pkt.src} -> 目标IP:{ip_pkt.dst}"
                        self.logger.info(log_msg)
                        self.push_switch_log(2, log_msg)
                    elif ip_pkt.dst == '192.168.1.21':
                        out_port = 3
                        log_msg = f"s2转发数据到h2 (端口3) - 源IP:{ip_pkt.src} -> 目标IP:{ip_pkt.dst}"
                        self.logger.info(log_msg)
                        self.push_switch_log(2, log_msg)
                    elif ip_pkt.dst in ['192.168.1.10', '192.168.1.11', '192.168.1.12', '192.168.1.13']:
                        out_port = 1
                        log_msg = f"s2转发数据到s1 (端口1) - 源IP:{ip_pkt.src} -> 目标IP:{ip_pkt.dst}"
                        self.logger.info(log_msg)
                        self.push_switch_log(2, log_msg)

            if out_port is None:
                out_port = ofproto.OFPP_FLOOD
                log_msg = f"交换机{dpid} 未找到目标，泛洪转发 - 源MAC:{eth_pkt.src} -> 目标MAC:{eth_pkt.dst}"
                self.logger.info(log_msg)
                self.push_switch_log(dpid, log_msg)

            self._send_packet_out(datapath, in_port, msg.buffer_id, msg.data, out_port)

            if out_port != ofproto.OFPP_FLOOD:
                if ip_pkt:
                    match = parser.OFPMatch(eth_type=0x0800, ipv4_dst=ip_pkt.dst)
                else:
                    match = parser.OFPMatch(in_port=in_port, eth_dst=dst)
                actions = [parser.OFPActionOutput(out_port)]
                self.add_flow(datapath, 10, match, actions, idle_timeout=60)
                if ip_pkt:
                    log_msg = f"交换机{dpid} 安装流表: 目标IP={ip_pkt.dst} -> out_port={out_port}"
                else:
                    log_msg = f"交换机{dpid} 安装流表: in_port={in_port}, dst={dst} -> out_port={out_port}"
                self.logger.info(log_msg)
                self.push_switch_log(dpid, log_msg)

        except Exception as e:
            self.logger.error(f"_packet_in_handler函数异常: {e}")
            import traceback
            self.logger.error(traceback.format_exc())

    def _send_packet_out(self, datapath, in_port, buffer_id, data, out_port):
        try:
            ofproto = datapath.ofproto
            parser = datapath.ofproto_parser
            actions = [parser.OFPActionOutput(out_port)]
            buffer_id = buffer_id if buffer_id != ofproto.OFP_NO_BUFFER else ofproto.OFP_NO_BUFFER
            out = parser.OFPPacketOut(
                datapath=datapath, buffer_id=buffer_id, in_port=in_port,
                actions=actions, data=data
            )
            datapath.send_msg(out)
        except Exception as e:
            self.logger.error(f"数据包转发失败: {e}")

    def test_extension_functionality(self):
        try:
            ext_mgr = create_iot_extension(
                sensor_type='temp',
                device_priority=3,
                route_select='route_a'
            )

            serialized = ext_mgr.serialize_to_experimenter()
            self.logger.info(f"扩展字段序列化测试成功 ({len(serialized)} bytes)")

            parsed_mgr = IoTExtensionManager.parse_from_experimenter(serialized)
            field_dict = parsed_mgr.get_field_dict()
            self.logger.info(f"扩展字段反序列化测试成功: {field_dict}")

        except Exception as e:
            self.logger.error(f"扩展字段功能测试失败: {e}")
            self.extension_enabled = False

    def process_iot_extension(self, ble_type, ble_value):
        try:
            sensor_mapping = {
                'temp': 'temp',
                'temperature': 'temp',
                'humidity': 'humidity',
                'light': 'light',
                'motion': 'motion',
                'pressure': 'pressure'
            }

            sensor_type = sensor_mapping.get(ble_type.lower(), 'temp')

            try:
                value_float = float(ble_value)
                if value_float > 80:
                    priority = 5
                elif value_float > 50:
                    priority = 4
                elif value_float > 30:
                    priority = 3
                else:
                    priority = 2
            except ValueError:
                priority = 2

            ext_mgr = create_iot_extension(
                sensor_type=sensor_type,
                device_priority=priority,
                route_select='route_a'
            )

            self.logger.info("IoT扩展字段已创建:")
            ext_mgr.print_fields()

            serialized_data = ext_mgr.serialize_to_experimenter()
            self.logger.debug(f"扩展字段序列化完成 ({len(serialized_data)} bytes)")

        except Exception as e:
            self.logger.warning(f"处理IoT扩展字段时出错: {e}")

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def port_stats_reply_handler(self, ev):
        datapath = ev.msg.datapath
        dpid = datapath.id
        body = ev.msg.body

        stats = []
        for stat in body:
            port_stat = {
                'port_no': stat.port_no,
                'rx_packets': stat.rx_packets,
                'tx_packets': stat.tx_packets,
                'rx_bytes': stat.rx_bytes,
                'tx_bytes': stat.tx_bytes,
                'rx_dropped': stat.rx_dropped,
                'tx_dropped': stat.tx_dropped,
                'rx_errors': stat.rx_errors,
                'tx_errors': stat.tx_errors,
                'collisions': stat.collisions,
                'timestamp': time.time()
            }
            stats.append(port_stat)

        self.port_stats[dpid] = stats
        self.logger.debug(f"交换机 {dpid} 端口统计已更新: {len(stats)} 个端口")
        self._report_stats_to_web('port_stats', dpid, stats)

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def flow_stats_reply_handler(self, ev):
        datapath = ev.msg.datapath
        dpid = datapath.id
        body = ev.msg.body

        flows = []
        for stat in body:
            flow = {
                'table_id': stat.table_id,
                'duration_sec': stat.duration_sec,
                'duration_nsec': stat.duration_nsec,
                'priority': stat.priority,
                'idle_timeout': stat.idle_timeout,
                'hard_timeout': stat.hard_timeout,
                'packet_count': stat.packet_count,
                'byte_count': stat.byte_count,
                'match': self._match_to_dict(stat.match),
                'instructions': self._instructions_to_list(stat.instructions),
                'timestamp': time.time()
            }
            flows.append(flow)

        self.flow_stats[dpid] = flows
        self.logger.debug(f"交换机 {dpid} 流表统计已更新: {len(flows)} 条流表")
        self._report_stats_to_web('flow_stats', dpid, flows)

    @set_ev_cls(ofp_event.EventOFPTableStatsReply, MAIN_DISPATCHER)
    def table_stats_reply_handler(self, ev):
        datapath = ev.msg.datapath
        dpid = datapath.id
        body = ev.msg.body

        tables = {}
        for stat in body:
            tables[stat.table_id] = {
                'table_id': stat.table_id,
                'active_count': stat.active_count,
                'lookup_count': stat.lookup_count,
                'matched_count': stat.matched_count,
                'timestamp': time.time()
            }

        self.table_stats[dpid] = tables
        self.logger.debug(f"交换机 {dpid} 流表表统计已更新: {len(tables)} 个表")
        self._report_stats_to_web('table_stats', dpid, tables)

    def request_port_stats(self, datapath):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        req = parser.OFPPortStatsRequest(datapath, 0, ofproto.OFPP_ANY)
        datapath.send_msg(req)

    def request_flow_stats(self, datapath, table_id=0xff):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        match = parser.OFPMatch()
        req = parser.OFPFlowStatsRequest(
            datapath, 0, table_id,
            ofproto.OFPP_ANY, ofproto.OFPG_ANY,
            0, 0, match
        )
        datapath.send_msg(req)

    def request_table_stats(self, datapath):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        req = parser.OFPTableStatsRequest(datapath, 0)
        datapath.send_msg(req)

    def _stats_collector(self):
        while True:
            hub.sleep(self.stats_interval)
            for dpid, datapath in list(self.topology['switches'].items()):
                try:
                    self.request_port_stats(datapath)
                    self.request_flow_stats(datapath)
                    self.request_table_stats(datapath)
                except Exception as e:
                    self.logger.warning(f"收集交换机 {dpid} 统计失败: {e}")

    def _match_to_dict(self, match):
        result = {}
        for key, value in match.items():
            if isinstance(value, bytes):
                result[key] = ':'.join(f'{b:02x}' for b in value)
            else:
                result[key] = value
        return result

    def _instructions_to_list(self, instructions):
        result = []
        for inst in instructions:
            inst_dict = {'type': inst.type}
            if hasattr(inst, 'actions'):
                inst_dict['actions'] = [str(action) for action in inst.actions]
            result.append(inst_dict)
        return result

    def _report_stats_to_web(self, stats_type, dpid, data):
        try:
            url = f"{self.web_panel_url}/api/stats"
            payload = {
                'type': stats_type,
                'dpid': dpid,
                'data': data,
                'timestamp': time.time()
            }
            requests.post(url, json=payload, timeout=1)
        except Exception as e:
            self.logger.debug(f"上报统计数据失败: {e}")

    @set_ev_cls(ofp_event.EventOFPPortStatus, MAIN_DISPATCHER)
    def port_status_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        dpid = datapath.id
        port_no = msg.desc.port_no
        reason = msg.reason

        reason_str = {
            0: '添加',
            1: '删除',
            2: '修改'
        }.get(reason, '未知')

        self.logger.info(f"交换机 {dpid} 端口 {port_no} {reason_str}")
        self._report_topology_to_web()

    def _lldp_sender(self):
        while True:
            hub.sleep(self.lldp_interval)
            for dpid, datapath in list(self.topology['switches'].items()):
                try:
                    ofp_parser = datapath.ofproto_parser
                    req = ofp_parser.OFPPortDescStatsRequest(datapath, 0)
                    datapath.send_msg(req)
                except Exception as e:
                    self.logger.warning(f"发送LLDP到交换机 {dpid} 失败: {e}")

    @set_ev_cls(ofp_event.EventOFPPortDescStatsReply, MAIN_DISPATCHER)
    def port_desc_stats_reply_handler(self, ev):
        datapath = ev.msg.datapath
        dpid = datapath.id

        for port in ev.msg.body:
            port_no = port.port_no
            if port_no > ofproto_v1_3.OFPP_MAX:
                continue

            pkt = packet.Packet()
            eth = ethernet.ethernet(
                ethertype=ethernet.ether.ETH_TYPE_LLDP,
                src=port.hw_addr,
                dst=lldp.LLDP_MAC_NEAREST_BRIDGE
            )
            pkt.add_protocol(eth)

            chassis_id = lldp.ChassisID(
                subtype=lldp.ChassisID.SUB_MAC_ADDRESS,
                chassis_id=port.hw_addr
            )
            port_id = lldp.PortID(
                subtype=lldp.PortID.SUB_PORT_COMPONENT,
                port_id=str(port_no).encode('utf-8')
            )
            ttl = lldp.TTL(ttl=10)
            system_name = lldp.SystemName(system_name=f'switch-{dpid}'.encode('utf-8'))
            end = lldp.End()

            lldp_pkt = lldp.lldp(tlvs=[chassis_id, port_id, ttl, system_name, end])
            pkt.add_protocol(lldp_pkt)
            pkt.serialize()

            self._send_lldp_packet(datapath, port_no, pkt.data)

    def _send_lldp_packet(self, datapath, port_no, data):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        actions = [parser.OFPActionOutput(port_no)]
        out = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=ofproto.OFP_NO_BUFFER,
            in_port=ofproto.OFPP_CONTROLLER,
            actions=actions,
            data=data
        )
        datapath.send_msg(out)

    def _handle_lldp_packet(self, dpid, in_port, pkt):
        lldp_pkt = pkt.get_protocol(lldp.lldp)
        if not lldp_pkt:
            return

        chassis_id = None
        port_id = None
        system_name = None

        for tlv in lldp_pkt.tlvs:
            if tlv.tlv_type == lldp.lldp.LLDP_TLV_CHASSIS_ID:
                chassis_id = tlv.chassis_id
            elif tlv.tlv_type == lldp.lldp.LLDP_TLV_PORT_ID:
                port_id = tlv.port_id
            elif tlv.tlv_type == lldp.lldp.LLDP_TLV_SYSTEM_NAME:
                system_name = tlv.system_name

        if chassis_id and port_id and system_name:
            try:
                src_switch = system_name.decode('utf-8')
                src_port = int(port_id.decode('utf-8'))
                dst_switch = f'switch-{dpid}'
                dst_port = in_port

                link_exists = any(
                    (link['src_switch'] == src_switch and link['src_port'] == src_port and
                     link['dst_switch'] == dst_switch and link['dst_port'] == dst_port) or
                    (link['src_switch'] == dst_switch and link['src_port'] == dst_port and
                     link['dst_switch'] == src_switch and link['dst_port'] == src_port)
                    for link in self.topology['links']
                )

                if not link_exists:
                    self.topology['links'].append({
                        'src_switch': src_switch,
                        'src_port': src_port,
                        'dst_switch': dst_switch,
                        'dst_port': dst_port,
                        'timestamp': time.time()
                    })
                    self.logger.info(f"发现新链接: {src_switch}:{src_port} <-> {dst_switch}:{dst_port}")
                    self._report_topology_to_web()

            except Exception as e:
                self.logger.warning(f"解析LLDP数据包失败: {e}")

    def _report_topology_to_web(self):
        try:
            url = f"{self.web_panel_url}/api/topology"
            topology_data = {
                'switches': list(self.topology['switches'].keys()),
                'links': self.topology['links'],
                'hosts': list(self.topology['hosts'].values()),
                'timestamp': time.time()
            }
            requests.post(url, json=topology_data, timeout=1)
        except Exception as e:
            self.logger.debug(f"上报拓扑信息失败: {e}")

    def delete_flow(self, datapath, match=None, priority=None, table_id=0):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        if match is None:
            match = parser.OFPMatch()

        mod = parser.OFPFlowMod(
            datapath=datapath,
            table_id=table_id,
            priority=priority if priority is not None else ofproto.OFP_DEFAULT_PRIORITY,
            match=match,
            command=ofproto.OFPFC_DELETE,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY
        )
        datapath.send_msg(mod)
        self.logger.info(f"流表删除请求 - 表ID:{table_id}")

    def modify_flow(self, datapath, priority, match, actions, idle_timeout=0, hard_timeout=0, table_id=0):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]

        mod = parser.OFPFlowMod(
            datapath=datapath,
            table_id=table_id,
            priority=priority,
            match=match,
            instructions=inst,
            idle_timeout=idle_timeout,
            hard_timeout=hard_timeout,
            command=ofproto.OFPFC_MODIFY
        )
        datapath.send_msg(mod)
        self.logger.info(f"流表修改成功 - 表ID:{table_id}, 优先级:{priority}")

    def get_flows(self, dpid, table_id=None):
        if dpid not in self.flow_stats:
            return []

        if table_id is not None:
            return [flow for flow in self.flow_stats[dpid] if flow['table_id'] == table_id]
        return self.flow_stats[dpid]

    def create_edge_application(self, app_id, app_name, app_type, app_code, version="1.0.0", description="", requirements=None):
        """创建边缘应用"""
        if not self.extension_enabled:
            raise RuntimeError("扩展功能未启用")
        
        from extensions.app_deployment import AppType
        
        app_type_enum = AppType(app_type)
        app = self.app_deployment_manager.create_application(
            app_id=app_id,
            app_name=app_name,
            app_type=app_type_enum,
            app_code=app_code,
            version=version,
            description=description,
            requirements=requirements
        )
        self.logger.info(f"边缘应用创建成功: {app_id} - {app_name}")
        return app

    def deploy_application_to_device(self, app_id, device_id):
        """部署应用到设备"""
        if not self.extension_enabled:
            raise RuntimeError("扩展功能未启用")
        
        result = self.app_deployment_manager.deploy_application(app_id, device_id)
        self.logger.info(f"应用 {app_id} 已部署到设备 {device_id}")
        return result

    def undeploy_application_from_device(self, app_id, device_id):
        """从设备卸载应用"""
        if not self.extension_enabled:
            raise RuntimeError("扩展功能未启用")
        
        result = self.app_deployment_manager.undeploy_application(app_id, device_id)
        self.logger.info(f"应用 {app_id} 已从设备 {device_id} 卸载")
        return result

    def list_edge_applications(self):
        """列出所有边缘应用"""
        if not self.extension_enabled:
            raise RuntimeError("扩展功能未启用")
        
        return self.app_deployment_manager.list_applications()

    def register_device_with_role(self, device_id, device_name, initial_mode=1, capabilities=None):
        """注册设备并设置角色"""
        if not self.extension_enabled:
            raise RuntimeError("扩展功能未启用")
        
        if capabilities:
            caps = DeviceCapabilities(**capabilities)
        else:
            caps = DeviceCapabilities()
        
        mode = DeviceMode(initial_mode)
        device = self.device_role_manager.register_device(
            device_id=device_id,
            device_name=device_name,
            initial_mode=mode,
            capabilities=caps
        )
        self.logger.info(f"设备 {device_id} 已注册，初始模式: {mode.name}")
        return device

    def switch_device_role(self, device_id, target_mode, force=False):
        """切换设备角色"""
        if not self.extension_enabled:
            raise RuntimeError("扩展功能未启用")
        
        mode = DeviceMode(target_mode)
        result = self.device_role_manager.switch_mode(device_id, mode, force)
        self.logger.info(f"设备 {device_id} 已切换到模式: {mode.name}")
        return result

    def identify_device_mode(self, device_id, traffic_pattern=None, resource_usage=None):
        """识别设备模式"""
        if not self.extension_enabled:
            raise RuntimeError("扩展功能未启用")
        
        mode = self.device_role_manager.identify_device_mode(
            device_id=device_id,
            traffic_pattern=traffic_pattern,
            resource_usage=resource_usage
        )
        self.logger.info(f"设备 {device_id} 模式识别结果: {mode.name}")
        return mode

    def get_available_device_modes(self, device_id):
        """获取设备可用的模式列表"""
        if not self.extension_enabled:
            raise RuntimeError("扩展功能未启用")
        
        return self.device_role_manager.get_available_modes(device_id)

    def list_registered_devices(self):
        """列出所有已注册的设备"""
        if not self.extension_enabled:
            raise RuntimeError("扩展功能未启用")
        
        return self.device_role_manager.list_devices()


if __name__ == '__main__':
    import sys
    from ryu.cmd import manager
    sys.argv.append(__file__)
    manager.main()
