#!/usr/bin/env python3
"""生成一条带 Experimenter 动作的 OF 1.3 FlowMod，用于验证 OVS 补丁。

用法：
    SDN_IOT/.venv/bin/python build_test_flowmod.py /tmp/fm_exp.bin

输出文件是原始二进制 OpenFlow 消息，可直接喂给：
    ovs-ofctl ofp-parse /tmp/fm_exp.bin
"""

import sys

from ryu.ofproto import ofproto_v1_3 as ofp
from ryu.ofproto import ofproto_v1_3_parser as ofpp


class _FakeDatapath:
    ofproto = ofp
    ofproto_parser = ofpp

    def __init__(self):
        self.id = 1


def build(path, priority=150, out_port=2,
          experimenter=0x12345678, data=b'\x01\x02\x03\x04'):
    dp = _FakeDatapath()
    match = ofpp.OFPMatch(eth_type=0x0800, ipv4_dst='192.168.1.20')
    actions = [
        ofpp.OFPActionOutput(out_port),
        ofpp.OFPActionExperimenterUnknown(experimenter=experimenter, data=data),
    ]
    fm = ofpp.OFPFlowMod(
        datapath=dp, priority=priority, match=match,
        instructions=[ofpp.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS,
                                                 actions)])
    fm._serialize_pre()
    fm._serialize_body()
    fm._serialize_header()
    with open(path, 'wb') as f:
        f.write(bytes(fm.buf))
    return len(fm.buf)


if __name__ == '__main__':
    out = sys.argv[1] if len(sys.argv) > 1 else '/tmp/fm_exp.bin'
    print(f'wrote {build(out)} bytes to {out}')
