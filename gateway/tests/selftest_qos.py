#!/usr/bin/env python3
"""阶段 6 自测：DSCP 标记 + HTB 出口队列（T8/T9/T10），需要 root。

结构：两个 netns（qos-snd / qos-rcv）+ 一条 veth；qdisc 挂在发送侧。
发包用 qos.mark_socket（与网关 forward_data 同一份逻辑），接收端
记录每类包的到达延迟（同一台机器的 CLOCK_MONOTONIC，可直接相减）。

    sudo /usr/bin/python3 gateway/tests/selftest_qos.py

数字只对本环境（veth、copy 模式、HTB 1 Mbit）有效。
"""

import json
import os
import signal
import socket
import struct
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
GATEWAY_DIR = os.path.dirname(HERE)
CORE_DIR = os.path.join(GATEWAY_DIR, "core")
XDP_DIR = os.path.join(GATEWAY_DIR, "xdp")
sys.path.insert(0, GATEWAY_DIR)
sys.path.insert(0, CORE_DIR)

from qos import mark_socket  # noqa: E402

SND_NS = "qos-snd"
RCV_NS = "qos-rcv"
SND_IF = "q0"
RCV_IF = "q1"
SND_IP = "10.96.0.1"
RCV_IP = "10.96.0.2"
RESULT_FILE = "/tmp/qos-selftest-results.txt"
PORT = 5005
PAYLOAD = 180


def sh(*cmd, check=True):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise SystemExit(f"命令失败: {' '.join(cmd)}\n{r.stdout}\n{r.stderr}")
    return r


def cleanup():
    sh("ip", "netns", "del", SND_NS, check=False)
    sh("ip", "netns", "del", RCV_NS, check=False)
    try:
        os.unlink(RESULT_FILE)
    except FileNotFoundError:
        pass


def setup_ns():
    cleanup()
    sh("ip", "netns", "add", SND_NS)
    sh("ip", "netns", "add", RCV_NS)
    sh("ip", "link", "add", SND_IF, "type", "veth", "peer", "name", RCV_IF)
    sh("ip", "link", "set", SND_IF, "netns", SND_NS)
    sh("ip", "link", "set", RCV_IF, "netns", RCV_NS)
    sh("ip", "netns", "exec", SND_NS, "ip", "addr", "add", f"{SND_IP}/24",
       "dev", SND_IF)
    sh("ip", "netns", "exec", SND_NS, "ip", "link", "set", SND_IF, "up")
    sh("ip", "netns", "exec", SND_NS, "ip", "link", "set", "lo", "up")
    sh("ip", "netns", "exec", RCV_NS, "ip", "addr", "add", f"{RCV_IP}/24",
       "dev", RCV_IF)
    sh("ip", "netns", "exec", RCV_NS, "ip", "link", "set", RCV_IF, "up")
    sh("ip", "netns", "exec", RCV_NS, "ip", "link", "set", "lo", "up")
    # 大 backlog，避免 qdisc 满之前先在 txqueue 阻塞
    sh("ip", "netns", "exec", SND_NS, "ip", "link", "set", SND_IF,
       "txqueuelen", "10000")


# ── 接收端（在 qos-rcv 里运行） ─────────────────────────────────────────
def receiver(path):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 << 20)
    s.bind((RCV_IP, PORT))
    s.settimeout(0.2)
    open(path, "w").close()
    fh = open(path, "a", buffering=1)
    stop = {"v": False}

    def _stop(_sig, _frm):
        stop["v"] = True
    signal.signal(signal.SIGTERM, _stop)
    while not stop["v"]:
        try:
            data, _ = s.recvfrom(2048)
        except socket.timeout:
            continue
        except OSError:
            break
        if len(data) < 15:
            continue
        typ, phase, seq, ts_ns = struct.unpack("!cBIQ", data[:14])
        delay = time.monotonic_ns() - ts_ns
        fh.write(f"{typ.decode()} {phase} {seq} {delay}\n")
    fh.close()


# ── 发送 + 统计 ───────────────────────────────────────────────────────
def phase_clear():
    open(RESULT_FILE, "w").close()


def send_phase(phase, n):
    hi = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    hi.bind((SND_IP, 42000))
    mark_socket(hi, 5)          # gas / 紧急 → DSCP 46（EF）
    lo = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    lo.bind((SND_IP, 42001))
    mark_socket(lo, 2)          # 普通温度 → DSCP 18（AF21）
    tail = b"x" * PAYLOAD
    for i in range(n):
        now = time.monotonic_ns()
        hi.sendto(struct.pack("!cBIQ", b"H", phase, i, now) + tail, (RCV_IP, PORT))
        now = time.monotonic_ns()
        lo.sendto(struct.pack("!cBIQ", b"L", phase, i, now) + tail, (RCV_IP, PORT))
    hi.close()
    lo.close()


def collect(phase, n, timeout=15.0):
    deadline = time.monotonic() + timeout
    want = n * 2
    rows = []
    while time.monotonic() < deadline:
        try:
            with open(RESULT_FILE) as fh:
                rows = [line.split() for line in fh if line.strip()]
        except FileNotFoundError:
            rows = []
        got = [r for r in rows if len(r) == 4 and int(r[1]) == phase]
        if len(got) >= want:
            break
        time.sleep(0.05)
    got = [r for r in rows if len(r) == 4 and int(r[1]) == phase]
    out = {}
    for typ in ("H", "L"):
        vals = [int(r[3]) / 1e6 for r in got if r[0] == typ]
        out[typ] = {
            "n": len(vals),
            "avg_ms": round(sum(vals) / len(vals), 3) if vals else None,
            "max_ms": round(max(vals), 3) if vals else None,
            "p95_ms": round(sorted(vals)[int(len(vals) * 0.95) - 1], 3) if vals else None,
        }
    return out


def qdisc(cmd, rate=None):
    args = ["bash", os.path.join(XDP_DIR, "qos_egress.sh"), cmd, SND_IF]
    if rate:
        args.append(str(rate))
    return sh(*args)


def run_phases():
    phase_clear()
    print("== T8：空闲链路（无 qdisc）==")
    send_phase(0, 200)
    t8 = collect(0, 200)
    print(json.dumps(t8))

    print("== T9：HTB 1 Mbit，拥塞 ==")
    qdisc("setup", 1000)
    phase_clear()
    send_phase(1, 400)
    t9 = collect(1, 400)
    print(json.dumps(t9))
    cls = sh("tc", "-s", "class", "show", "dev", SND_IF).stdout
    print(cls)
    qdisc("teardown")

    print("== T10：移除 qdisc 后重复 T9 的流量 ==")
    phase_clear()
    send_phase(2, 400)
    t10 = collect(2, 400)
    print(json.dumps(t10))

    def ok_phase(name, data, max_avg):
        assert data["H"]["n"] >= 200 and data["L"]["n"] >= 200, data
        assert data["H"]["avg_ms"] is not None, data
        assert data["L"]["avg_ms"] is not None, data
        print(f"  ok {name}: H avg={data['H']['avg_ms']}ms "
              f"L avg={data['L']['avg_ms']}ms max H/L="
              f"{data['H']['max_ms']}/{data['L']['max_ms']}ms")
        return data["H"]["avg_ms"] < max_avg

    ok_phase("T8 空闲链路两类都很快", t8, 5.0)
    assert t9["H"]["n"] >= 300 and t9["L"]["n"] >= 300, t9
    assert t9["H"]["avg_ms"] < t9["L"]["avg_ms"] * 0.5, (
        f"高优先级没有明显更快: H={t9['H']['avg_ms']} L={t9['L']['avg_ms']}")
    print(f"  ok T9: 高优先级 avg {t9['H']['avg_ms']}ms < 低优先级 "
          f"avg {t9['L']['avg_ms']}ms 的一半")
    ok_phase("T10 去掉 qdisc 差异消失", t10, 10.0)
    ratio = t10["H"]["avg_ms"] / max(t10["L"]["avg_ms"], 1e-6)
    assert 0.3 <= ratio <= 3.0, f"T10 两类仍有明显差异 ratio={ratio:.2f}"
    print(f"  ok T10: 差异消失（avg 比值 {ratio:.2f}）")
    print("PASS 阶段 6（DSCP 分类 + HTB 调度；空闲链路不伪造优势）")


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--receiver":
        receiver(sys.argv[2])
        return
    if os.environ.get("QOS_ROLE") == "snd":
        env = os.environ.copy()
        proc = subprocess.Popen(
            ["ip", "netns", "exec", RCV_NS, "/usr/bin/python3",
             os.path.abspath(__file__), "--receiver", RESULT_FILE])
        try:
            for _ in range(100):
                if os.path.exists(RESULT_FILE):
                    break
                time.sleep(0.05)
            time.sleep(0.2)
            run_phases()
        finally:
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=5)
        return
    if os.geteuid() != 0:
        sys.exit("需要 root")
    try:
        setup_ns()
        env = os.environ.copy()
        env["QOS_ROLE"] = "snd"
        rc = subprocess.call(["ip", "netns", "exec", SND_NS,
                              "/usr/bin/python3", os.path.abspath(__file__)],
                             env=env)
        if rc != 0:
            sys.exit(rc)
    finally:
        cleanup()


if __name__ == "__main__":
    main()
