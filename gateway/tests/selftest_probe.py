#!/usr/bin/env python3
"""XDP probe 自测（阶段 2/3/4/5/7），需要 root。

在隔离 netns + 一条 veth 上跑真实的 XDP 程序和探针，用假的网关 Unix
socket 模拟网关本地缓存命中 / pending → flow_ready 推送，断言只看真实计数器：

    --stage 2   ringbuf 事件 + PENDING 1 s 冷却（T2/T3 的 XDP 半边）
    --stage 3   网关本地缓存 ready → 写 eBPF 缓存 READY，后续包 0 事件（T3）
    --stage 4   pending → flow_ready → 写 eBPF 缓存（控制器回路在探针侧的那一半）
    --stage 5   TTL 过期重新触发（T4）+ 全局 50 次/s（T6）
    --stage 7   命中率 / 事件数 / pps / CPU / 丢包测量

不需要 Mininet；退出时删除 netns 和 veth。宿主机网络不受影响。
"""

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time

NS = "xdp-probe-test"
VH = "pp-vh"
VN = "pp-vn"
HOST_IP = "10.98.0.1"
NS_IP = "10.98.0.2"
GW_SOCK = "/tmp/xdp-selftest-gw.sock"
CLIENT_SOCK = "/tmp/xdp-selftest-client.sock"
HERE = os.path.dirname(os.path.abspath(__file__))
XDP_DIR = os.path.join(os.path.dirname(HERE), "xdp")
PY = "/usr/bin/python3"

RECV_SRC = r'''
import socket, sys, time
port = int(sys.argv[1]); duration = float(sys.argv[2])
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 << 20)
s.bind(("0.0.0.0", port))
s.settimeout(0.2)
deadline = time.monotonic() + duration
n = 0
while time.monotonic() < deadline:
    try:
        s.recvfrom(2048)
        n += 1
    except socket.timeout:
        pass
print(n, flush=True)
'''


def sh(*cmd, check=True):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise SystemExit(f"命令失败: {' '.join(cmd)}\n{r.stdout}\n{r.stderr}")
    return r


def _unlink(path):
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def cleanup():
    sh("ip", "netns", "del", NS, check=False)
    sh("ip", "link", "del", VH, check=False)
    for p in (GW_SOCK, CLIENT_SOCK):
        _unlink(p)


def setup():
    cleanup()
    sh("ip", "netns", "add", NS)
    sh("ip", "link", "add", VH, "type", "veth", "peer", "name", VN)
    sh("ip", "link", "set", VN, "netns", NS)
    sh("ip", "addr", "add", f"{HOST_IP}/24", "dev", VH)
    sh("ip", "link", "set", VH, "up")
    sh("ip", "netns", "exec", NS, "ip", "addr", "add", f"{NS_IP}/24", "dev", VN)
    sh("ip", "netns", "exec", NS, "ip", "link", "set", VN, "up")
    sh("ip", "netns", "exec", NS, "ip", "link", "set", "lo", "up")


class FakeGateway(threading.Thread):
    """假网关：回 resolve，并可定时推送 flow_ready。"""

    def __init__(self, mode, ttl=60, push_delay=0.0):
        super().__init__(daemon=True)
        self.mode = mode            # ready | pending | pending_push
        self.ttl = ttl
        self.push_delay = push_delay
        self.resolves = 0
        self.replies = 0
        self.pushes = 0
        self._client = None
        self._push_at = None
        self._halt = threading.Event()
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        _unlink(GW_SOCK)
        self._sock.bind(GW_SOCK)
        self._sock.settimeout(0.05)

    def run(self):
        while not self._halt.is_set():
            now = time.monotonic()
            if self._push_at is not None and now >= self._push_at:
                self._push_at = None
                self._send(self._client, {"op": "flow_ready",
                                          "target_ip": "192.168.1.20",
                                          "ttl": self.ttl})
                self.pushes += 1
            try:
                data, addr = self._sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                msg = json.loads(data.decode())
            except ValueError:
                continue
            if msg.get("op") != "resolve":
                continue
            self.resolves += 1
            self._client = addr
            if self.mode == "ready":
                status = "ready"
            else:
                status = "pending"
            self._send(addr, {"op": "resolve_reply", "key": msg.get("key"),
                              "status": status,
                              "target_ip": "192.168.1.20",
                              "ttl": self.ttl})
            self.replies += 1
            if self.mode == "pending_push" and self._push_at is None:
                self._push_at = time.monotonic() + self.push_delay

    def _send(self, addr, payload):
        if addr is None:
            return
        try:
            self._sock.sendto(json.dumps(payload).encode(), addr)
        except OSError:
            pass

    def stop(self):
        self._halt.set()
        try:
            self._sock.close()
        except OSError:
            pass
        _unlink(GW_SOCK)


class Run:
    def __init__(self, duration, recv_seconds, no_probe=False,
                 gw_mode="ready", gw_ttl=60, push_delay=0.0, probe_rate=50):
        self.tmp = tempfile.mkdtemp(prefix="xdp-probe-")
        self.duration = duration
        self.recv_seconds = recv_seconds
        self.no_probe = no_probe
        self.gw = None if no_probe else FakeGateway(gw_mode, gw_ttl, push_delay)
        self.probe_rate = probe_rate
        self.loader = None
        self.recv = None
        self.loader_pid = None

    def start(self):
        self.recv_src = os.path.join(self.tmp, "recv.py")
        with open(self.recv_src, "w") as fh:
            fh.write(RECV_SRC)
        self.recv = subprocess.Popen(
            ["ip", "netns", "exec", NS, PY, self.recv_src, "5005",
             str(self.recv_seconds)],
            stdout=subprocess.PIPE, text=True)
        if self.gw:
            self.gw.start()

        json_out = os.path.join(self.tmp, "stats.json")
        ready = os.path.join(self.tmp, "ready")
        cmd = ["ip", "netns", "exec", NS, PY,
               os.path.join(XDP_DIR, "gw_xdp_filter.py"),
               "--ifaces", VN, "--mode", "skb", "--interval", "1",
               "--duration", str(self.duration), "--json-out", json_out,
               "--ready-file", ready]
        if self.no_probe:
            cmd.append("--no-probe")
        else:
            cmd += ["--probe-sock", GW_SOCK,
                    "--probe-client-sock", CLIENT_SOCK,
                    "--probe-rate", str(self.probe_rate)]
        self.log_path = os.path.join(self.tmp, "loader.log")
        log = open(self.log_path, "w")
        self.loader = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
        self.loader_pid = self.loader.pid
        for _ in range(200):
            if os.path.exists(ready):
                return
            if self.loader.poll() is not None:
                raise SystemExit("加载器提前退出：\n" + open(self.log_path).read())
            time.sleep(0.05)
        raise SystemExit("XDP 挂载未就绪：\n" + open(self.log_path).read())

    def stop(self):
        if self.loader and self.loader.poll() is None:
            self.loader.terminate()
        if self.loader:
            try:
                self.loader.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.loader.kill()
        recv_out = ""
        if self.recv:
            try:
                recv_out, _ = self.recv.communicate(timeout=self.recv_seconds + 10)
            except subprocess.TimeoutExpired:
                self.recv.kill()
                recv_out, _ = self.recv.communicate()
        if self.gw:
            self.gw.stop()
        stats = {}
        path = os.path.join(self.tmp, "stats.json")
        if os.path.exists(path):
            stats = json.load(open(path))
        log = open(self.log_path).read() if os.path.exists(self.log_path) else ""
        self.recv_count = int((recv_out or "0").strip().splitlines()[-1]) if recv_out.strip() else 0
        self.log = log
        self.stats = stats
        return stats, log, self.recv_count


def send_payloads(n, sport, payload=b"aa:bb:cc:dd:ee:01,temp,25.0",
                  pause_every=0, pause=0.0):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind((HOST_IP, sport))
    for i in range(n):
        s.sendto(payload, (NS_IP, 5005))
        if pause_every and i % pause_every == pause_every - 1:
            time.sleep(pause)
    s.close()


def assert_eq(name, got, want):
    if got != want:
        raise SystemExit(f"断言失败: {name}={got}，期望 {want}")
    print(f"  ok {name}={got}")


def assert_true(name, cond, detail=""):
    if not cond:
        raise SystemExit(f"断言失败: {name} {detail}")
    print(f"  ok {name} {detail}")


def _cpu_ticks(pid):
    try:
        with open(f"/proc/{pid}/stat") as fh:
            fields = fh.read().split()
        return int(fields[13]) + int(fields[14])
    except (OSError, IndexError, ValueError):
        return 0


def _udp_errors():
    r = sh("ip", "netns", "exec", NS, "nstat", "-az", "UdpRcvbufErrors",
           check=False)
    for line in r.stdout.splitlines():
        parts = line.split()
        if parts and parts[0] == "UdpRcvbufErrors":
            return int(float(parts[-1]))
    return -1


def stage2():
    print("== 阶段 2：ringbuf 事件 + PENDING 1 s 冷却 ==")
    run = Run(duration=5, recv_seconds=6, no_probe=True)
    run.start()
    send_payloads(1000, 40100, pause_every=50, pause=0.002)
    time.sleep(1.2)               # PENDING 冷却（1 s）过期
    send_payloads(1, 40100)
    time.sleep(1.5)
    stats, log, recv_count = run.stop()
    t = stats["totals"]
    misses = log.count("[MISS]")
    print(f"  事件日志 {misses} 条，接收端 {recv_count} 包")
    assert_eq("flow_miss", t["flow_miss"], 2)
    assert_eq("flow_cached", t["flow_cached"], 999)
    assert_eq("ringbuf_full", t["ringbuf_full"], 0)
    assert_eq("parse_error", t["parse_error"], 0)
    assert_eq("ringbuf 事件数", misses, 2)
    assert_eq("接收端收到", recv_count, 1001)
    print("PASS 阶段 2")


def stage3():
    print("== 阶段 3：网关本地缓存 ready → 写 eBPF 缓存 READY（T3）==")
    run = Run(duration=4, recv_seconds=5, gw_mode="ready", gw_ttl=60)
    run.start()
    send_payloads(1, 40200)
    time.sleep(0.3)
    send_payloads(999, 40200, pause_every=50, pause=0.001)
    time.sleep(1.0)
    stats, log, recv_count = run.stop()
    t, p = stats["totals"], stats["probe"]
    assert_eq("flow_miss", t["flow_miss"], 1)
    assert_eq("flow_cached", t["flow_cached"], 999)
    assert_eq("探针事件", p["events"], 1)
    assert_eq("resolve 次数", p["resolves"], 1)
    assert_eq("网关本地缓存 ready 回复", p["ready"], 1)
    assert_eq("eBPF 缓存写入", p["ebpf_writes"], 1)
    assert_eq("接收端收到", recv_count, 1000)
    print("PASS 阶段 3（首包 1 次事件，其后 999 包 0 事件）")


def stage4():
    print("== 阶段 4：pending → flow_ready → 写 eBPF 缓存 ==")
    run = Run(duration=4, recv_seconds=5, gw_mode="pending_push",
              gw_ttl=60, push_delay=0.3)
    run.start()
    send_payloads(50, 40300)
    time.sleep(0.8)               # 等网关上报 + 下发 FlowMod 后推送
    send_payloads(500, 40300, pause_every=50, pause=0.001)
    time.sleep(1.0)
    stats, log, recv_count = run.stop()
    t, p = stats["totals"], stats["probe"]
    assert_eq("flow_miss", t["flow_miss"], 1)
    assert_eq("flow_cached", t["flow_cached"], 549)
    assert_eq("pending 回复", p["pending"], 1)
    assert_eq("收到 flow_ready", p["flow_ready"], 1)
    assert_eq("eBPF 缓存写入", p["ebpf_writes"], 1)
    assert_eq("接收端收到", recv_count, 550)
    print("PASS 阶段 4（探针侧：pending → flow_ready → eBPF 缓存 READY）")


def stage5():
    print("== 阶段 5a：TTL 过期后重新触发（T4）==")
    run = Run(duration=6, recv_seconds=7, gw_mode="ready", gw_ttl=2)
    run.start()
    send_payloads(1, 40400)
    time.sleep(0.3)
    send_payloads(50, 40400)
    time.sleep(2.5)
    send_payloads(1, 40400)
    time.sleep(0.3)
    send_payloads(10, 40400)
    time.sleep(1.0)
    stats, log, recv_count = run.stop()
    t, p = stats["totals"], stats["probe"]
    assert_eq("flow_miss", t["flow_miss"], 2)
    assert_eq("flow_cached", t["flow_cached"], 60)
    assert_eq("探针事件", p["events"], 2)
    assert_eq("eBPF 缓存写入", p["ebpf_writes"], 2)
    assert_eq("接收端收到", recv_count, 62)
    print("PASS 阶段 5a（TTL=2 s：过期后只重新触发 1 次，不是每包一次）")

    print("== 阶段 5b：全局 50 次/s 上限（T6）==")
    run = Run(duration=4, recv_seconds=5, gw_mode="ready", gw_ttl=60,
              probe_rate=50)
    run.start()
    socks = []
    for i in range(1000):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind((HOST_IP, 41000 + i))
        socks.append(s)
    t0 = time.monotonic()
    for s in socks:
        s.sendto(b"aa:bb:cc:dd:ee:01,temp,25.0", (NS_IP, 5005))
    burst = time.monotonic() - t0
    for s in socks:
        s.close()
    time.sleep(1.5)
    stats, log, recv_count = run.stop()
    p = stats["probe"]
    print(f"  1000 个不同 key 在 {burst:.3f}s 内注入，网关收到 resolve "
          f"{run.gw.resolves} 次，限速 {p['rate_limited']} 次")
    assert_true("burst < 1s", burst < 1.0, f"({burst:.3f}s)")
    assert_true("resolve ≤ 50", run.gw.resolves <= 50, f"= {run.gw.resolves}")
    assert_true("rate_limited ≥ 900", p["rate_limited"] >= 900,
                f"= {p['rate_limited']}")
    assert_eq("接收端收到", recv_count, 1000)
    print("PASS 阶段 5b（上报次数受限，数据不丢）")


def _bench_once(no_probe):
    run = Run(duration=6, recv_seconds=7, no_probe=no_probe,
              gw_mode="ready", gw_ttl=60)
    run.start()
    pid, rpid = run.loader_pid, run.recv.pid
    err0 = _udp_errors()
    cpu0, rcpu0 = _cpu_ticks(pid), _cpu_ticks(rpid)
    t0 = time.monotonic()
    send_payloads(5000, 40500, pause_every=20, pause=0.0015)
    elapsed = time.monotonic() - t0
    time.sleep(1.2)
    cpu1, rcpu1 = _cpu_ticks(pid), _cpu_ticks(rpid)
    err1 = _udp_errors()
    stats, log, recv_count = run.stop()
    hz = os.sysconf("SC_CLK_TCK")
    t = stats.get("totals", {})
    p = stats.get("probe", {})
    total = t.get("flow_cached", 0) + t.get("flow_miss", 0)
    return {
        "mode": "filter-only" if no_probe else "filter+probe",
        "sent": 5000,
        "received": recv_count,
        "elapsed_s": round(elapsed, 3),
        "python_pps": round(recv_count / elapsed, 1) if elapsed else 0,
        "hit_rate": round(t.get("flow_cached", 0) / total, 4) if total else 0,
        "events": p.get("events", 0),
        "resolves": p.get("resolves", 0),
        "loader_cpu_pct": round((cpu1 - cpu0) / hz / elapsed * 100, 2),
        "recv_cpu_pct": round((rcpu1 - rcpu0) / hz / elapsed * 100, 2),
        "udp_rcvbuf_errors": (err1 - err0) if err0 >= 0 and err1 >= 0 else None,
        "xdp_env": "veth / skb(copy) mode",
    }


def stage7():
    print("== 阶段 7：测量（filter-only vs filter+probe）==")
    baseline = _bench_once(no_probe=True)
    probe = _bench_once(no_probe=False)
    print(json.dumps({"baseline": baseline, "probe": probe},
                     ensure_ascii=False, indent=2))
    assert_eq("baseline 接收", baseline["received"], 5000)
    assert_eq("probe 接收", probe["received"], 5000)
    assert_eq("probe 事件数", probe["events"], 1)
    assert_true("probe 命中率 > 0.99", probe["hit_rate"] > 0.99,
                f"= {probe['hit_rate']}")
    print("PASS 阶段 7（数字见上；性能结论仅适用于 veth / copy 模式）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", type=int, choices=(2, 3, 4, 5, 7), required=True)
    args = ap.parse_args()
    if os.geteuid() != 0:
        sys.exit("需要 root（sudo / 特权容器）")
    try:
        setup()
        {2: stage2, 3: stage3, 4: stage4, 5: stage5, 7: stage7}[args.stage]()
    finally:
        cleanup()


if __name__ == "__main__":
    main()
