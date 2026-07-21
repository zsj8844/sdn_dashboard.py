"""
流表管理模块
负责 OpenFlow 流表的增删改查 + 本地记录。
"""

import time
import logging

logger = logging.getLogger(__name__)


class FlowManager:
    """流表 CRUD 管理器"""

    def __init__(self, flow_tables):
        """
        flow_tables: defaultdict(dict) — 控制器级流表缓存
                     flow_tables[dpid][table_id] = [...]
        """
        self.flow_tables = flow_tables

    def add_flow(self, datapath, priority, match, actions,
                 idle_timeout=0, hard_timeout=0, table_id=0):
        """下发流表到交换机 + 本地记录"""
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(
            datapath=datapath, table_id=table_id, priority=priority,
            match=match, instructions=inst,
            idle_timeout=idle_timeout, hard_timeout=hard_timeout
        )
        datapath.send_msg(mod)

        dpid = datapath.id
        if table_id not in self.flow_tables[dpid]:
            self.flow_tables[dpid][table_id] = []
        self.flow_tables[dpid][table_id].append({
            'priority': priority,
            'match': _match_to_dict(match),
            'actions': [str(a) for a in actions],
            'idle_timeout': idle_timeout,
            'hard_timeout': hard_timeout,
            'added_at': time.time()
        })
        logger.info("流表下发成功 - 表ID:%d, 优先级:%d, 端口:%s",
                    table_id, priority, actions[0].port if actions else '无')

    def delete_flow(self, datapath, match=None, priority=None, table_id=0):
        """删除流表"""
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        if match is None:
            match = parser.OFPMatch()
        mod = parser.OFPFlowMod(
            datapath=datapath, table_id=table_id,
            priority=priority if priority is not None else ofproto.OFP_DEFAULT_PRIORITY,
            match=match, command=ofproto.OFPFC_DELETE,
            out_port=ofproto.OFPP_ANY, out_group=ofproto.OFPG_ANY
        )
        datapath.send_msg(mod)
        logger.info("流表删除请求 - 表ID:%d", table_id)

    def modify_flow(self, datapath, priority, match, actions,
                    idle_timeout=0, hard_timeout=0, table_id=0):
        """修改流表"""
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(
            datapath=datapath, table_id=table_id, priority=priority,
            match=match, instructions=inst,
            idle_timeout=idle_timeout, hard_timeout=hard_timeout,
            command=ofproto.OFPFC_MODIFY
        )
        datapath.send_msg(mod)
        logger.info("流表修改成功 - 表ID:%d, 优先级:%d", table_id, priority)

    def get_flows(self, dpid, table_id=None):
        """查询本地缓存的流表"""
        if dpid not in self.flow_stats:
            return []
        if table_id is not None:
            return [f for f in self.flow_stats[dpid] if f['table_id'] == table_id]
        return self.flow_stats[dpid]


def _match_to_dict(match):
    result = {}
    for k, v in match.items():
        if isinstance(v, bytes):
            result[k] = ':'.join(f'{b:02x}' for b in v)
        else:
            result[k] = v
    return result
