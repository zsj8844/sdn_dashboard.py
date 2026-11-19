"""
流表管理模块
负责 OpenFlow 流表的增删改查 + 本地记录。
"""

import os
import time
import logging

logger = logging.getLogger(__name__)

# 低优先级扩展流使用的限速 meter（OF meter_id 从 1 开始）
LOW_PRIO_METER_ID = 1
DEFAULT_METER_KBPS = 64


class FlowManager:
    """流表 CRUD 管理器"""

    def __init__(self, flow_tables, low_prio_meter_kbps=None, meter_enabled=None):
        """
        flow_tables: defaultdict(dict) — 控制器级流表缓存
                     flow_tables[dpid][table_id] = [...]
        """
        self.flow_tables = flow_tables
        if meter_enabled is None:
            meter_enabled = os.environ.get('SDN_QOS_METER', '1') not in ('0', 'false', 'no')
        self.meter_enabled = meter_enabled
        self.low_prio_meter_kbps = int(
            low_prio_meter_kbps
            or os.environ.get('SDN_LOW_PRIO_METER_KBPS', DEFAULT_METER_KBPS)
        )
        # 每个交换机已下发的 meter，重连后需要重装
        self._meters = {}

    def add_flow(self, datapath, priority, match, actions,
                 idle_timeout=0, hard_timeout=0, table_id=0, meter_id=None):
        """下发流表到交换机 + 本地记录。

        完全相同的流（同一表、优先级、匹配、动作、超时、meter）不会再次
        下发：重复 ADD 会把交换机的 n_packets 计数清零，网关每次上报属性
        都会走到这里，所以必须去重。

        返回 True 表示真正发给了交换机，False 表示命中去重被跳过。
        """
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        if meter_id is not None and self.meter_enabled:
            self._ensure_meter(datapath, meter_id)
        else:
            meter_id = None

        signature = _flow_signature(priority, match, actions,
                                    idle_timeout, hard_timeout, meter_id)
        if self._has_same_flow(datapath.id, table_id, priority, match, signature):
            logger.debug("流表已存在，跳过重复下发 - dpid:%s 表ID:%d 优先级:%d",
                         datapath.id, table_id, priority)
            return False

        instructions = []
        if meter_id is not None:
            instructions.append(parser.OFPInstructionMeter(meter_id))
        instructions.append(
            parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions))
        mod = parser.OFPFlowMod(
            datapath=datapath, table_id=table_id, priority=priority,
            match=match, instructions=instructions,
            idle_timeout=idle_timeout, hard_timeout=hard_timeout
        )
        datapath.send_msg(mod)

        self._record_flow(datapath.id, table_id, priority, match, actions,
                          idle_timeout, hard_timeout, meter_id, signature)
        logger.info("流表下发成功 - 表ID:%d, 优先级:%d, 端口:%s%s",
                    table_id, priority, actions[0].port if actions else '无',
                    f", meter:{meter_id}" if meter_id is not None else '')
        return True

    def ensure_meter(self, datapath, meter_id=LOW_PRIO_METER_ID):
        """对外暴露：确保交换机上有该 meter（交换机重连后需要重装）。"""
        if self.meter_enabled:
            self._ensure_meter(datapath, meter_id)

    def _ensure_meter(self, datapath, meter_id):
        ready = self._meters.setdefault(datapath.id, set())
        if meter_id in ready:
            return
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        band = parser.OFPMeterBandDrop(
            rate=self.low_prio_meter_kbps,
            burst_size=max(1, self.low_prio_meter_kbps // 10),
        )
        mod = parser.OFPMeterMod(
            datapath=datapath,
            command=ofproto.OFPFC_ADD,
            flags=ofproto.OFPMF_KBPS | ofproto.OFPMF_BURST,
            meter_id=meter_id,
            bands=[band],
        )
        datapath.send_msg(mod)
        ready.add(meter_id)
        logger.info("低优先级 meter 已下发 - dpid:%s meter:%d 限速:%dkbps",
                    datapath.id, meter_id, self.low_prio_meter_kbps)

    def forget_switch(self, dpid):
        """交换机重连时清空该 dpid 的本地缓存和 meter 记录。"""
        self.flow_tables.pop(dpid, None)
        self._meters.pop(dpid, None)

    def _has_same_flow(self, dpid, table_id, priority, match, signature):
        for flow in self.flow_tables.get(dpid, {}).get(table_id, []):
            if (flow['priority'] == priority
                    and flow['match'] == _match_to_dict(match)
                    and flow.get('signature') == signature):
                return True
        return False

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
                    idle_timeout=0, hard_timeout=0, table_id=0, meter_id=None):
        """修改流表"""
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        if meter_id is not None and self.meter_enabled:
            self._ensure_meter(datapath, meter_id)
        else:
            meter_id = None

        signature = _flow_signature(priority, match, actions,
                                    idle_timeout, hard_timeout, meter_id)
        instructions = []
        if meter_id is not None:
            instructions.append(parser.OFPInstructionMeter(meter_id))
        instructions.append(
            parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions))
        mod = parser.OFPFlowMod(
            datapath=datapath, table_id=table_id, priority=priority,
            match=match, instructions=instructions,
            idle_timeout=idle_timeout, hard_timeout=hard_timeout,
            command=ofproto.OFPFC_MODIFY
        )
        datapath.send_msg(mod)

        self._record_flow(datapath.id, table_id, priority, match, actions,
                          idle_timeout, hard_timeout, meter_id, signature)
        logger.info("流表修改成功 - 表ID:%d, 优先级:%d", table_id, priority)

    def _record_flow(self, dpid, table_id, priority, match, actions,
                     idle_timeout, hard_timeout, meter_id=None, signature=None):
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
            'meter_id': meter_id,
            'signature': signature,
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


def _flow_signature(priority, match, actions, idle_timeout, hard_timeout,
                    meter_id):
    """完整流签名：只有这些字段都相同才算重复流。"""
    return (
        priority,
        repr(_match_to_dict(match)),
        tuple(str(a) for a in actions),
        idle_timeout,
        hard_timeout,
        meter_id,
    )


def _match_to_dict(match):
    result = {}
    for k, v in match.items():
        if isinstance(v, bytes):
            result[k] = ':'.join(f'{b:02x}' for b in v)
        else:
            result[k] = v
    return result
