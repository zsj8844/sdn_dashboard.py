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

        self._record_flow(datapath.id, table_id, priority, match, actions,
                          idle_timeout, hard_timeout)
        logger.info("流表下发成功 - 表ID:%d, 优先级:%d, 端口:%s",
                    table_id, priority, actions[0].port if actions else '无')

    def delete_flow(self, datapath, match=None, priority=None, table_id=0):
        """删除流表"""
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        had_match = match is not None
        effective_priority = (
            priority if priority is not None
            else ofproto.OFP_DEFAULT_PRIORITY
        )
        if match is None:
            match = parser.OFPMatch()
        mod = parser.OFPFlowMod(
            datapath=datapath, table_id=table_id,
            priority=effective_priority,
            match=match, command=ofproto.OFPFC_DELETE,
            out_port=ofproto.OFPP_ANY, out_group=ofproto.OFPG_ANY
        )
        datapath.send_msg(mod)

        self._remove_flow(datapath.id, table_id,
                          match if had_match else None,
                          effective_priority)
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

        self._record_flow(datapath.id, table_id, priority, match, actions,
                          idle_timeout, hard_timeout)
        logger.info("流表修改成功 - 表ID:%d, 优先级:%d", table_id, priority)

    def _record_flow(self, dpid, table_id, priority, match, actions,
                     idle_timeout, hard_timeout):
        """写入本地缓存；同一优先级 + 匹配条件视为同一条流，覆盖旧记录。"""
        table = self.flow_tables[dpid].setdefault(table_id, [])
        match_dict = _match_to_dict(match)
        table[:] = [
            f for f in table
            if not (f['priority'] == priority and f['match'] == match_dict)
        ]
        table.append({
            'priority': priority,
            'table_id': table_id,
            'match': match_dict,
            'actions': [str(a) for a in actions],
            'idle_timeout': idle_timeout,
            'hard_timeout': hard_timeout,
            'added_at': time.time()
        })

    def _remove_flow(self, dpid, table_id, match, priority):
        """删除本地缓存记录。match 为 None 表示删除该优先级下的全部流。"""
        table = self.flow_tables.get(dpid, {}).get(table_id)
        if not table:
            return
        if match is None:
            self.flow_tables[dpid][table_id] = [
                f for f in table if f['priority'] != priority
            ]
            return
        match_dict = _match_to_dict(match)
        self.flow_tables[dpid][table_id] = [
            f for f in table
            if not (f['priority'] == priority and f['match'] == match_dict)
        ]

    def get_flows(self, dpid, table_id=None):
        """查询本地缓存的流表"""
        if dpid not in self.flow_tables:
            return []
        if table_id is not None:
            return list(self.flow_tables[dpid].get(table_id, []))

        result = []
        for tid, flows in self.flow_tables[dpid].items():
            for flow in flows:
                item = dict(flow)
                item['table_id'] = tid
                result.append(item)
        return result


def _match_to_dict(match):
    result = {}
    for k, v in match.items():
        if isinstance(v, bytes):
            result[k] = ':'.join(f'{b:02x}' for b in v)
        else:
            result[k] = v
    return result
