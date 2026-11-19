"""
LLDP 拓扑发现模块
负责定期发送 LLDP 报文、解析收到的 LLDP 包、维护拓扑链路信息。
仅服务于 Web 面板的链路可视化，不影响转发决策。
"""

import time
import logging
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, lldp
from ryu.lib import hub

logger = logging.getLogger(__name__)


class LLDPManager:
    """
    LLDP 拓扑发现管理器

    用途：定期向所有交换机端口发送 LLDP 报文，邻居交换机收到后
    回传给控制器，控制器解析出链路关系并上报 Web 面板展示。
    """

    LLDP_INTERVAL = 5  # 发送间隔（秒）

    def __init__(self, topology, report_callback=None):
        """
        topology:      控制器的 self.topology 字典（共享读写 links）
        report_callback: 回调函数，链路变化时调用（如 _report_topology_to_web）
        """
        self.topology = topology
        self.report_callback = report_callback
        self._thread = None

    def start(self):
        """启动定时 LLDP 发送线程"""
        self._thread = hub.spawn(self._lldp_sender_loop)
        logger.info("LLDP 拓扑发现已启动 (间隔=%ds)", self.LLDP_INTERVAL)

    # ==================== 发送 ====================

    def _lldp_sender_loop(self):
        """定时向所有交换机请求端口信息，触发 LLDP 发送"""
        while True:
            hub.sleep(self.LLDP_INTERVAL)
            self._send_one_round()

    def force_send(self):
        """手动触发一轮 LLDP 发现并强制上报完整拓扑（由前端刷新按钮调用）"""
        logger.info("手动触发 LLDP 拓扑发现 + 拓扑全量上报...")
        # 清除已知链路缓存，允许 LLDP 重新发现并上报
        self.topology['links'] = []
        # 立即上报当前完整拓扑（交换机 + 主机数据始终在内存中）
        if self.report_callback:
            self.report_callback()
        # 再触发 LLDP 重新发现链路
        hub.spawn(self._send_one_round)

    def _send_one_round(self):
        """执行一轮 LLDP 请求"""
        for dpid, datapath in list(self.topology.get('switches', {}).items()):
            try:
                parser = datapath.ofproto_parser
                req = parser.OFPPortDescStatsRequest(datapath, 0)
                datapath.send_msg(req)
                logger.debug("LLDP 请求已发送到交换机 %s", dpid)
            except Exception as e:
                logger.warning("发送 LLDP 到交换机 %s 失败: %s", dpid, e)

    def on_port_desc_reply(self, ev):
        """
        收到交换机端口信息后，构造并发送 LLDP 报文到每个端口。
        由控制器 port_desc_stats_reply_handler 调用。
        """
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

            try:
                chassis_id_bytes = bytes.fromhex(port.hw_addr.replace(':', ''))
            except Exception:
                chassis_id_bytes = port.hw_addr.encode('utf-8')

            chassis_id = lldp.ChassisID(
                subtype=lldp.ChassisID.SUB_MAC_ADDRESS,
                chassis_id=chassis_id_bytes
            )
            port_tlv = lldp.PortID(
                subtype=lldp.PortID.SUB_PORT_COMPONENT,
                port_id=str(port_no).encode('utf-8')
            )
            ttl = lldp.TTL(ttl=10)
            system_name = lldp.SystemName(system_name=f'switch-{dpid}'.encode('utf-8'))
            end = lldp.End()

            lldp_pkt = lldp.lldp(tlvs=[chassis_id, port_tlv, ttl, system_name, end])
            pkt.add_protocol(lldp_pkt)
            pkt.serialize()

            self._send_packet_out(datapath, port_no, pkt.data)

    def _send_packet_out(self, datapath, port_no, data):
        """通过 PacketOut 向指定端口发送 LLDP 报文"""
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

    # ==================== 接收 & 解析 ====================

    def handle_lldp_packet(self, dpid, in_port, pkt):
        """
        解析收到的 LLDP 报文，提取链路信息并更新拓扑。
        由控制器 _packet_in_handler 调用（检测到 ETH_TYPE_LLDP 时）。
        """
        lldp_pkt = pkt.get_protocol(lldp.lldp)
        if not lldp_pkt:
            return

        chassis_id = None
        port_id = None
        system_name = None

        for tlv in lldp_pkt.tlvs:
            if isinstance(tlv, lldp.ChassisID):
                chassis_id = tlv.chassis_id
            elif isinstance(tlv, lldp.PortID):
                port_id = tlv.port_id
            elif isinstance(tlv, lldp.SystemName):
                system_name = tlv.system_name

        if not (chassis_id and port_id and system_name):
            return

        try:
            src_switch = system_name.decode('utf-8')
            src_port = int(port_id.decode('utf-8'))
            dst_switch = f'switch-{dpid}'
            dst_port = in_port

            links = self.topology.get('links', [])
            link_exists = any(
                (l['src_switch'] == src_switch and l['src_port'] == src_port and
                 l['dst_switch'] == dst_switch and l['dst_port'] == dst_port) or
                (l['src_switch'] == dst_switch and l['src_port'] == dst_port and
                 l['dst_switch'] == src_switch and l['dst_port'] == src_port)
                for l in links
            )

            if not link_exists:
                links.append({
                    'src_switch': src_switch,
                    'src_port': src_port,
                    'dst_switch': dst_switch,
                    'dst_port': dst_port,
                    'timestamp': time.time()
                })
                logger.info("发现新链路: %s:%d <-> %s:%d", src_switch, src_port, dst_switch, dst_port)
                if self.report_callback:
                    self.report_callback()

        except Exception as e:
            logger.warning("解析 LLDP 数据包失败: %s", e)
