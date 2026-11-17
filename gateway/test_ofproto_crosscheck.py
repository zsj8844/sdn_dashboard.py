#!/usr/bin/env python3
"""用 Ryu 的 OpenFlow 1.3 解析器交叉验证 ofproto_client 的报文格式。

运行：
    SDN_IOT/.venv/bin/python gateway/test_ofproto_crosscheck.py
"""

import struct
import sys

sys.path.insert(0, __file__.rsplit('/', 1)[0])

from ryu.ofproto import ofproto_v1_3 as ofp
from ryu.ofproto import ofproto_v1_3_parser as ofpp

from ofproto_client import (
    OFMessageBuilder, FlowEntry, FlowTable, _build_match, _match_subset,
    _parse_flow_mod,
)


class FakeDatapath:
    ofproto = ofp
    ofproto_parser = ofpp

    def __init__(self):
        self.id = 1


DP = FakeDatapath()


def check(name):
    print(f"  [PASS] {name}")


def test_hello():
    msg = OFMessageBuilder.hello()
    parsed = ofpp.OFPHello.parser(
        DP, ofp.OFP_VERSION, ofp.OFPT_HELLO, len(msg), 1, msg)
    assert len(parsed.elements) == 1
    elem = parsed.elements[0]
    assert elem.type == 1 and elem.length == 8
    assert elem.versions == [ofp.OFP_VERSION]
    check("HELLO version bitmap 长度/内容")


def test_match_and_packet_in():
    # match：4 字节头 + 14 字节 OXM = 18，补齐到 24
    match = _build_match(in_port=3, eth_type=0x0800)
    assert len(match) == 24, len(match)
    m = ofpp.OFPMatch.parser(match, 0)
    assert m.length == 18
    assert m['in_port'] == 3 and m['eth_type'] == 0x0800
    check("OFPMatch 4 字节头 + 8 字节对齐")

    frame = b'\xff' * 6 + b'\x00' * 6 + b'\x08\x00' + b'\x00' * 46
    msg = OFMessageBuilder.packet_in(frame, in_port=3)
    parsed = ofpp.OFPPacketIn.parser(
        DP, ofp.OFP_VERSION, ofp.OFPT_PACKET_IN, len(msg), 1, msg)
    assert parsed.match['in_port'] == 3
    assert parsed.match['eth_type'] == 0x0800
    assert parsed.data == frame
    check("PacketIn match 尾部对齐 / 数据偏移")


def test_flowmod_with_actions():
    m = ofpp.OFPMatch(in_port=3, eth_type=0x0800)
    actions = [
        ofpp.OFPActionOutput(2),
        ofpp.OFPActionExperimenterUnknown(
            experimenter=0x12345678, data=b'\x01\x02\x03\x04'),
    ]
    fm = ofpp.OFPFlowMod(
        datapath=DP, priority=130, match=m,
        instructions=[ofpp.OFPInstructionActions(
            ofp.OFPIT_APPLY_ACTIONS, actions)])
    fm._serialize_pre()
    fm._serialize_body()
    fm._serialize_header()

    parsed = _parse_flow_mod(bytes(fm.buf))
    assert parsed is not None
    assert parsed['priority'] == 130
    assert parsed['match']['in_port'] == 3
    assert parsed['match']['eth_type'] == 0x0800
    assert len(parsed['actions']) == 2, parsed['actions']
    assert parsed['actions'][0]['type'] == 'OUTPUT'
    assert parsed['actions'][0]['port'] == 2
    assert parsed['actions'][1]['type'] == 'EXPERIMENTER'
    assert parsed['actions'][1]['experimenter'] == 0x12345678
    check("FlowMod 指令头 8 字节 / actions 解析")


def test_multipart_port_desc():
    ports = (OFMessageBuilder.port_desc(1, '00:00:00:00:00:03') +
             OFMessageBuilder.port_desc(2, '00:00:00:00:00:03'))
    msg = OFMessageBuilder.multipart_port_desc_reply(ports, xid=7)
    reply = ofpp.OFPPortDescStatsReply.parser(
        DP, ofp.OFP_VERSION, ofp.OFPT_MULTIPART_REPLY, len(msg), 7, msg)
    assert len(reply.body) == 2
    assert [p.port_no for p in reply.body] == [1, 2]
    check("Multipart PortDesc 回复")


def test_table_miss():
    assert _match_subset({'in_port': 1}, {}) is True
    ft = FlowTable()
    ft.add(FlowEntry(match={}, actions=[{'type': 'CONTROLLER'}], priority=0))
    ft.add(FlowEntry(match={'data_type': 'gas'},
                     actions=[{'type': 'FORWARD'}], priority=200))
    # 非 gas 的包应命中空 match 的 table-miss
    e = ft.lookup(data_type='temp')
    assert e is not None and e.priority == 0
    # gas 仍然优先命中高优先级条目
    e = ft.lookup(data_type='gas')
    assert e is not None and e.priority == 200
    check("table-miss 空 match 语义")


if __name__ == '__main__':
    print("=== OF 1.3 协议格式交叉验证 ===")
    test_hello()
    test_match_and_packet_in()
    test_flowmod_with_actions()
    test_multipart_port_desc()
    test_table_miss()
    print("全部通过 ✓")
