#!/usr/bin/env python3
"""网关 OpenFlow 代理的本地闭环测试（不需要 Mininet / root）。

用一个假控制器完成 HELLO → FEATURES 握手，向网关下发 FlowMod，
再验证：
  1. 网关完成握手（dpid=3）
  2. 控制器下发的 FlowMod（含 Experimenter 字段）进入网关本地流表
  3. table-miss 流被忽略
  4. 命中本地流表后不再发送 PacketIn
  5. 未命中时 PacketIn 能送到控制器

运行：SDN_IOT/.venv/bin/python gateway/test_gateway_of_agent.py
"""

import os
import socket
import struct
import sys
import threading
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SWITCH_DIR = os.path.join(BASE_DIR, '..', 'ryu_extend', 'switch')
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, SWITCH_DIR)

from ryu.ofproto import ofproto_v1_3 as ofp  # noqa: E402
from ryu.ofproto import ofproto_v1_3_parser as ofpp  # noqa: E402

from ofproto_client import OFMessageBuilder, OFP_HEADER_PACK_STR  # noqa: E402
from of_gateway_agent import GatewayOpenFlowAgent  # noqa: E402
from extensions.manager import create_iot_extension  # noqa: E402


def check(name, condition, detail=''):
    status = 'PASS' if condition else 'FAIL'
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ''))
    if not condition:
        raise AssertionError(name)


class _FakeDatapath:
    ofproto = ofp
    ofproto_parser = ofpp

    def __init__(self, dpid=3):
        self.id = dpid

    def set_xid(self, msg):
        msg.xid = 1

    def close(self):
        pass


def build_features_request(xid=2):
    return struct.pack(OFP_HEADER_PACK_STR, ofp.OFP_VERSION,
                       ofp.OFPT_FEATURES_REQUEST, 8, xid)


def build_flow_mod(priority, match_kwargs, actions, idle_timeout=60):
    dp = _FakeDatapath()
    fm = ofpp.OFPFlowMod(
        datapath=dp,
        priority=priority,
        match=ofpp.OFPMatch(**match_kwargs),
        instructions=[ofpp.OFPInstructionActions(
            ofp.OFPIT_APPLY_ACTIONS, actions)],
        idle_timeout=idle_timeout,
    )
    fm._serialize_pre()
    fm._serialize_body()
    fm._serialize_header()
    return bytes(fm.buf)


def _recv_exact(conn, n):
    data = b''
    while len(data) < n:
        chunk = conn.recv(n - len(data))
        if not chunk:
            raise ConnectionError('EOF')
        data += chunk
    return data


class FakeController(threading.Thread):
    """最小控制器：握手后下发两条 FlowMod，并记录收到的 PacketIn。"""

    def __init__(self):
        super().__init__(daemon=True)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('127.0.0.1', 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.hello_seen = False
        self.dpid = None
        self.packet_ins = []
        self.handshake_done = threading.Event()
        self._stop = threading.Event()

    def run(self):
        try:
            conn, _ = self.sock.accept()
            conn.settimeout(10)
            self._serve(conn)
        except Exception:
            pass

    def _recv_msg(self, conn):
        hdr = _recv_exact(conn, 8)
        _version, msg_type, msg_len, _xid = struct.unpack(
            OFP_HEADER_PACK_STR, hdr)
        body = _recv_exact(conn, msg_len - 8) if msg_len > 8 else b''
        return msg_type, body

    def _serve(self, conn):
        msg_type, _ = self._recv_msg(conn)
        self.hello_seen = (msg_type == ofp.OFPT_HELLO)
        conn.sendall(OFMessageBuilder.hello())
        conn.sendall(build_features_request())

        msg_type, body = self._recv_msg(conn)
        if msg_type == ofp.OFPT_FEATURES_REPLY:
            self.dpid = struct.unpack_from('!Q', body, 0)[0]

        # table-miss：网关必须忽略
        conn.sendall(build_flow_mod(
            0, {}, [ofpp.OFPActionOutput(ofp.OFPP_CONTROLLER,
                                         ofp.OFPCML_NO_BUFFER)]))
        # 真实扩展流：目的 h1，带 Experimenter TLV
        ext = create_iot_extension(
            sensor_type='temp', device_priority=4,
            route_select='route_a').serialize_fields()
        conn.sendall(build_flow_mod(
            140, {'eth_type': 0x0800, 'ipv4_dst': '192.168.1.20'},
            [ofpp.OFPActionOutput(1),
             ofpp.OFPActionExperimenterUnknown(
                 experimenter=0x12345678, data=ext)]))
        self.handshake_done.set()

        while not self._stop.is_set():
            try:
                msg_type, body = self._recv_msg(conn)
            except (socket.timeout, ConnectionError, OSError):
                break
            if msg_type == ofp.OFPT_PACKET_IN:
                self.packet_ins.append(body)

    def stop(self):
        self._stop.set()
        try:
            self.sock.close()
        except OSError:
            pass


def wait_until(predicate, timeout=5.0, interval=0.02):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def main():
    controller = FakeController()
    controller.start()

    logs = []
    agent = GatewayOpenFlowAgent(
        dpid=3,
        controller_host='127.0.0.1',
        controller_port=controller.port,
        report_interval=5.0,
        log=logs.append,
    )
    agent.start()

    try:
        check('握手完成（HELLO/FEATURES）',
              wait_until(lambda: agent.connected and controller.handshake_done.is_set()))
        check('网关 dpid=3 已注册', controller.dpid == 3, str(controller.dpid))
        def first_flow():
            return agent.flows.lookup(dst_ip='192.168.1.20', eth_type=0x0800)

        check('FlowMod 已进入本地流表',
              wait_until(lambda: first_flow() is not None),
              '\n'.join(logs[-3:]))

        entry = first_flow()
        check('本地流优先级 = 140', entry.priority == 140, str(entry.priority))
        check('table-miss 未被写入本地流表', len(agent.flows) == 1,
              f'entries={len(agent.flows)}')

        hit = agent.note_sensor_data(
            'aa:bb:cc:dd:ee:01', 'temp', '25.3', '192.168.1.20')
        check('命中本地流表后不再上报 PacketIn', hit is False)
        check('本地命中计数 +1', agent.stats['local_hits'] == 1,
              str(agent.stats['local_hits']))

        sent = agent.note_sensor_data(
            'aa:bb:cc:dd:ee:02', 'humidity', '55.0', '192.168.1.21')
        check('未命中时上报 PacketIn', sent is True)
        check('控制器收到 PacketIn',
              wait_until(lambda: len(controller.packet_ins) >= 1))
        frame = controller.packet_ins[0]
        check('PacketIn 携带 BLE 负载',
              b'aa:bb:cc:dd:ee:02,humidity,55.0' in frame)

        suppressed = agent.note_sensor_data(
            'aa:bb:cc:dd:ee:02', 'humidity', '56.0', '192.168.1.21')
        check('上报间隔内不重复 PacketIn', suppressed is False)
    finally:
        agent.stop()
        controller.stop()

    print('\n全部通过 ✓')


if __name__ == '__main__':
    main()
