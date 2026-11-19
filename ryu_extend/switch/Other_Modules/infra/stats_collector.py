"""
统计采集模块
定时向交换机请求端口/流表/表统计，解析回复并存储，上报 Web 面板。
"""

import time
import logging
from ryu.lib import hub

logger = logging.getLogger(__name__)


class StatsCollector:
    """交换机统计信息采集器"""

    INTERVAL = 10  # 采集间隔（秒）

    def __init__(self, topology, stats_store, report_callback=None):
        """
        topology:      控制器 self.topology 字典（共享 switches）
        stats_store:   控制器 self.port_stats / self.flow_stats / self.table_stats
        report_callback: function(stats_type, dpid, data) — 上报 Web 面板
        """
        self.topology = topology
        self.port_stats = stats_store.get('port_stats')
        self.flow_stats = stats_store.get('flow_stats')
        self.table_stats = stats_store.get('table_stats')
        self.report = report_callback
        self._thread = None

    def start(self):
        """启动定时采集线程"""
        self._thread = hub.spawn(self._collector_loop)
        logger.info("统计采集已启动 (间隔=%ds)", self.INTERVAL)

    # ==================== 定时循环 ====================

    def _collector_loop(self):
        while True:
            hub.sleep(self.INTERVAL)
            for dpid, datapath in list(self.topology.get('switches', {}).items()):
                try:
                    self._request_port(datapath)
                    self._request_flow(datapath)
                    self._request_table(datapath)
                except Exception as e:
                    logger.warning("收集交换机 %s 统计失败: %s", dpid, e)

    def _request_port(self, datapath):
        parser = datapath.ofproto_parser
        datapath.send_msg(parser.OFPPortStatsRequest(datapath, 0, datapath.ofproto.OFPP_ANY))

    def _request_flow(self, datapath):
        parser = datapath.ofproto_parser
        match = parser.OFPMatch()
        datapath.send_msg(parser.OFPFlowStatsRequest(
            datapath, 0, 0xff, datapath.ofproto.OFPP_ANY, datapath.ofproto.OFPG_ANY, 0, 0, match
        ))

    def _request_table(self, datapath):
        parser = datapath.ofproto_parser
        datapath.send_msg(parser.OFPTableStatsRequest(datapath, 0))

    # ==================== 事件处理 ====================

    def on_port_stats_reply(self, ev):
        datapath = ev.msg.datapath
        dpid = datapath.id
        stats = [{
            'port_no': s.port_no,
            'rx_packets': s.rx_packets, 'tx_packets': s.tx_packets,
            'rx_bytes': s.rx_bytes, 'tx_bytes': s.tx_bytes,
            'rx_dropped': s.rx_dropped, 'tx_dropped': s.tx_dropped,
            'rx_errors': s.rx_errors, 'tx_errors': s.tx_errors,
            'collisions': s.collisions, 'timestamp': time.time()
        } for s in ev.msg.body]
        self.port_stats[dpid] = stats
        logger.debug("交换机 %s 端口统计已更新: %d 个端口", dpid, len(stats))
        if self.report:
            self.report('port_stats', dpid, stats)

    def on_flow_stats_reply(self, ev):
        datapath = ev.msg.datapath
        dpid = datapath.id
        flows = [{
            'table_id': s.table_id,
            'duration_sec': s.duration_sec, 'duration_nsec': s.duration_nsec,
            'priority': s.priority, 'idle_timeout': s.idle_timeout,
            'hard_timeout': s.hard_timeout, 'packet_count': s.packet_count,
            'byte_count': s.byte_count,
            'match': _match_to_dict(s.match),
            'instructions': _instructions_to_list(s.instructions),
            'timestamp': time.time()
        } for s in ev.msg.body]
        self.flow_stats[dpid] = flows
        logger.debug("交换机 %s 流表统计已更新: %d 条", dpid, len(flows))
        if self.report:
            self.report('flow_stats', dpid, flows)

    def on_table_stats_reply(self, ev):
        datapath = ev.msg.datapath
        dpid = datapath.id
        tables = {
            s.table_id: {
                'table_id': s.table_id, 'active_count': s.active_count,
                'lookup_count': s.lookup_count, 'matched_count': s.matched_count,
                'timestamp': time.time()
            } for s in ev.msg.body
        }
        self.table_stats[dpid] = tables
        logger.debug("交换机 %s 表统计已更新: %d 个表", dpid, len(tables))
        if self.report:
            self.report('table_stats', dpid, tables)


# ==================== 辅助函数 ====================

def _match_to_dict(match):
    result = {}
    for k, v in match.items():
        if isinstance(v, bytes):
            result[k] = ':'.join(f'{b:02x}' for b in v)
        else:
            result[k] = v
    return result


def _instructions_to_list(instructions):
    result = []
    for inst in instructions:
        d = {'type': inst.type}
        if hasattr(inst, 'actions'):
            d['actions'] = [str(a) for a in inst.actions]
        result.append(d)
    return result
