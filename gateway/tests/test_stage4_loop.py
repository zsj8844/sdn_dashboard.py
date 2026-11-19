#!/usr/bin/env python3
"""阶段 4 回路自测（宿主机，项目 venv，不需要 root）。

假控制器 ↔ 真实 GatewayOpenFlowAgent + ProbeBridge ↔ 假探针：

    resolve(网关本地缓存 miss) → PacketIn → FlowMod → 网关本地缓存写入 → flow_ready 推送
    FlowMod DELETE → flow_delete 推送

没有 XDP 的部分已在容器 selftest_probe.py --stage 4 验证；这里验证
网关侧的真实 OF 握手/解析和探针桥推送。

    .venv/bin/python gateway/tests/test_stage4_loop.py
"""

import json
import os
import socket
import struct
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
GATEWAY_DIR = os.path.dirname(HERE)
CORE_DIR = os.path.join(GATEWAY_DIR, "core")
sys.path.insert(0, GATEWAY_DIR)
sys.path.insert(0, CORE_DIR)

from of_gateway_agent import GatewayOpenFlowAgent  # noqa: E402
from probe_bridge import ProbeBridge  # noqa: E402

# OF 1.3
OFPT_HELLO = 0
OFPT_ECHO_REQUEST = 2
OFPT_ECHO_REPLY = 3
OFPT_FEATURES_REQUEST = 5
OFPT_FEATURES_REPLY = 6
OFPT_PACKET_IN = 10
OFPT_FLOW_MOD = 14
OFPT_BARRIER_REQUEST = 20
OFPFC_ADD = 0
OFPFC_DELETE = 3

GW_SOCK = "/tmp/xdp-stage4-gw.sock"
CLIENT_SOCK = "/tmp/xdp-stage4-client.sock"


def _hdr(msg_type, body, xid=1):
    return struct.pack("!BBHI", 4, msg_type, 8 + len(body), xid) + body


def _recv_exact(conn, n):
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("controller connection closed")
        buf += chunk
    return buf


def _recv_msg(conn):
    version, msg_type, length, xid = struct.unpack("!BBHI", _recv_exact(conn, 8))
    body = _recv_exact(conn, length - 8) if length > 8 else b""
    return msg_type, xid, body


def _match(dst_ip=None):
    """OFPMatch: eth_type=0x0800 [+ ipv4_dst]，补到 8 字节。"""
    oxm = struct.pack("!I", (0x8000 << 16) | (5 << 9) | 2) + struct.pack("!H", 0x0800)
    if dst_ip:
        oxm += struct.pack("!I", (0x8000 << 16) | (12 << 9) | 4)
        oxm += socket.inet_aton(dst_ip)
    match = struct.pack("!HH", 1, 4 + len(oxm)) + oxm
    return match + b"\x00" * ((8 - len(match) % 8) % 8)


def _flow_mod(dst_ip, command=OFPFC_ADD, idle_timeout=60, priority=200):
    body = struct.pack("!QQBBHHHIIIH2x", 0x1234, 0, 0, command,
                       idle_timeout, 0, priority, 0xFFFFFFFF, 0, 0, 0)
    if command == OFPFC_DELETE:
        return _hdr(OFPT_FLOW_MOD, body + _match(dst_ip), xid=9)
    action = struct.pack("!HHIH6x", 0, 16, 2, 0)          # OUTPUT:2
    inst = struct.pack("!HH4x", 4, 8 + len(action)) + action  # APPLY_ACTIONS
    return _hdr(OFPT_FLOW_MOD, body + _match(dst_ip) + inst, xid=8)


class FakeController(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.conn = None
        self.packet_ins = 0
        self.flow_mods = 0
        self._send_lock = threading.Lock()
        self._halt = threading.Event()

    def run(self):
        try:
            self.conn, _ = self.sock.accept()
            self.conn.settimeout(5)
            _recv_msg(self.conn)                       # switch HELLO
            self._send(_hdr(OFPT_HELLO, b""))
            self._send(_hdr(OFPT_FEATURES_REQUEST, b"", xid=2))
            time.sleep(0.1)                            # 等 features reply
            self.conn.settimeout(0.2)
            while not self._halt.is_set():
                try:
                    msg_type, xid, body = _recv_msg(self.conn)
                except socket.timeout:
                    continue
                except (ConnectionError, OSError):
                    break
                if msg_type == OFPT_PACKET_IN:
                    self.packet_ins += 1
                    self._send(_flow_mod("192.168.1.20"))
                    self.flow_mods += 1
                elif msg_type == OFPT_ECHO_REQUEST:
                    self._send(_hdr(OFPT_ECHO_REPLY, body, xid))
                elif msg_type == OFPT_BARRIER_REQUEST:
                    self._send(_hdr(21, b"", xid))      # BARRIER_REPLY
        except Exception as exc:  # noqa: BLE001
            print(f"[fake-ctl] 异常: {exc}")

    def _send(self, data):
        with self._send_lock:
            if self.conn:
                self.conn.sendall(data)

    def send_delete(self, dst_ip="192.168.1.20"):
        self._send(_flow_mod(dst_ip, command=OFPFC_DELETE))

    def stop(self):
        self._halt.set()
        if self.conn:
            try:
                self.conn.close()
            except OSError:
                pass
        self.sock.close()


def wait_for(fn, timeout=5.0, what="条件"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if fn():
            return True
        time.sleep(0.02)
    raise SystemExit(f"等待超时: {what}")


def main():
    for path in (GW_SOCK, CLIENT_SOCK):
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass

    ctl = FakeController()
    ctl.start()

    logs = []
    agent = GatewayOpenFlowAgent(dpid=3, controller_host="127.0.0.1",
                                 controller_port=ctl.port, gateway_ip="192.168.1.12",
                                 log=lambda m: logs.append(m) or print(m))
    agent.start()
    wait_for(lambda: agent.connected, 5, "网关连接控制器")

    bridge = ProbeBridge(agent, sock_path=GW_SOCK, log=print)
    agent.on_flow_installed = bridge.on_flow_installed
    agent.on_flow_deleted = bridge.on_flow_deleted
    bridge.start()

    probe = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    probe.bind(CLIENT_SOCK)
    probe.settimeout(5)

    key = [0x0A63000A, 0x0C01080A, 40100, 5005, 17]
    preview = b"aa:bb:cc:dd:ee:01,temp,25.0"
    probe.sendto(json.dumps({"op": "resolve", "key": key,
                             "preview": preview.hex()}).encode(), GW_SOCK)

    reply = json.loads(probe.recvfrom(4096)[0])
    print("resolve_reply:", reply)
    assert reply["status"] == "pending", reply
    assert reply["target_ip"] == "192.168.1.20", reply

    ready = json.loads(probe.recvfrom(4096)[0])
    print("push:", ready)
    assert ready["op"] == "flow_ready", ready
    assert ready["target_ip"] == "192.168.1.20", ready
    assert ready["ttl"] == 60, ready

    entry = agent.flows.lookup(dst_ip="192.168.1.20", eth_type=0x0800)
    assert entry is not None, "网关本地缓存未写入"
    assert ctl.packet_ins == 1, ctl.packet_ins
    assert agent.stats["flow_mods"] == 1, agent.stats
    print(f"ok 网关本地缓存命中: {entry}")
    print(f"ok PacketIn={ctl.packet_ins} FlowMod={agent.stats['flow_mods']}")

    # 网关本地缓存命中后，相同的 resolve 应直接回 ready（不再上报）
    probe.sendto(json.dumps({"op": "resolve", "key": key + [],
                             "preview": preview.hex()}).encode(), GW_SOCK)
    reply2 = json.loads(probe.recvfrom(4096)[0])
    print("second resolve_reply:", reply2)
    assert reply2["status"] == "ready", reply2
    assert reply2["ttl"] > 0, reply2
    assert ctl.packet_ins == 1, "网关本地缓存命中后不应再上报"
    print(f"ok 网关本地缓存命中回 ready ttl={reply2['ttl']}s，PacketIn 仍为 1")

    ctl.send_delete("192.168.1.20")
    deleted = json.loads(probe.recvfrom(4096)[0])
    print("push:", deleted)
    assert deleted["op"] == "flow_delete", deleted
    wait_for(lambda: agent.flows.lookup(dst_ip="192.168.1.20",
                                        eth_type=0x0800) is None, 2,
             "网关本地缓存删除")
    print("ok FlowMod DELETE → 网关本地缓存删除 + flow_delete 推送")

    probe.close()
    bridge.stop()
    agent.stop()
    ctl.stop()
    os.unlink(GW_SOCK) if os.path.exists(GW_SOCK) else None
    os.unlink(CLIENT_SOCK) if os.path.exists(CLIENT_SOCK) else None
    print("PASS 阶段 4（控制器回路：PacketIn → FlowMod → 网关本地缓存 + flow_ready；DELETE 同步）")


if __name__ == "__main__":
    main()
