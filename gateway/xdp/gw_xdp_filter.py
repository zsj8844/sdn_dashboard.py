#!/usr/bin/env python3
"""iot3 网关入向 XDP filter + probe 主机（阶段 1–5）。

必须在 iot3 网络命名空间内以 root 运行，且必须用系统 Python
（BCC 0.29 装在 /usr/bin/python3，项目 .venv 里没有）。

    # Mininet CLI 里（拓扑本身就是 root 启动的）：
    mininet> iot3 /usr/bin/python3 /home/zhang/桌面/sdn/SDN_IOT/gateway/xdp/gw_xdp_filter.py

    # 或者从宿主机 nsenter 进网关命名空间：
    PID=$(pgrep -f iot_gateway_enhanced.py | head -1)
    sudo nsenter -t "$PID" -n /usr/bin/python3 \
        /home/zhang/桌面/sdn/SDN_IOT/gateway/xdp/gw_xdp_filter.py

默认挂到 iot3-eth0/1/2（面向 iot1/2/4 的三个 veth），只统计不丢包；
Ctrl-C 退出时会摘掉 XDP（--keep 可保留）。

probe：未命中事件通过 Unix datagram 发给网关侧的 ProbeBridge
（默认 /tmp/sdn_xdp_probe.sock），网关查本地缓存后回 ready/pending；
收到 flow_ready 后把 eBPF 缓存表项写成 READY。网关不可达时只计数，
包照常 XDP_PASS。
"""

import argparse
import ctypes as ct
import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
from collections import deque

STAT_NAMES = (
    "non_ip",        # 非 IPv4
    "non_udp",       # IPv4 非 UDP
    "non_5005",      # UDP 非 5005
    "flow_cached",   # 5005 且 eBPF 缓存命中/冷却中
    "flow_miss",     # 5005 且 eBPF 缓存未命中/过期（本轮发事件）
    "dropped",       # 被 cfg 丢弃
    "ringbuf_full",  # ringbuf 写失败
    "parse_error",   # 截断 / 非法 IHL / 非首片
)
DEFAULT_IFACES = ("iot3-eth0", "iot3-eth1", "iot3-eth2")
MODE_FLAGS = {"auto": 0, "skb": 2, "drv": 4}
DETACH_FLAGS = (0, 2, 4)
DEFAULT_PROBE_SOCK = "/tmp/sdn_xdp_probe.sock"
DEFAULT_CLIENT_SOCK = "/tmp/sdn_xdp_probe_cli.sock"
DEFAULT_TTL = 60                 # 与控制器扩展流 idle_timeout=60 对齐
SRC_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "gw_filter_probe.c")

_stop = False


def _on_signal(signum, frame):
    global _stop
    _stop = True


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def _xdp_line(iface):
    """返回 `ip -d link show` 里描述 XDP 的那一行，用于证明挂载状态。"""
    out = _run(["ip", "-d", "link", "show", "dev", iface]).stdout
    for line in out.splitlines():
        if re.search(r"xdpgeneric|xdpdrv|xdpoffload|prog/xdp", line):
            return line.strip()
    return ""


def _iface_exists(iface):
    return _run(["ip", "link", "show", "dev", iface]).returncode == 0


def _netns_id():
    try:
        return os.readlink("/proc/self/ns/net")
    except OSError:
        return "unknown"


def _set_cfg(bpf, drop_non_5005):
    bpf["cfg"][ct.c_uint32(0)] = ct.c_uint32(1 if drop_non_5005 else 0)


def _snapshot(bpf):
    stats = bpf["stats"]
    return {name: int(sum(stats[i])) for i, name in enumerate(STAT_NAMES)}


# ── eBPF 缓存 flows map 的用户态结构 ────────────────────────────────────────────
class FlowKey(ct.Structure):
    _fields_ = [
        ("saddr", ct.c_uint32), ("daddr", ct.c_uint32),
        ("sport", ct.c_uint16), ("dport", ct.c_uint16),
        ("proto", ct.c_uint8), ("pad", ct.c_uint8 * 3),
    ]


class FlowVal(ct.Structure):
    _fields_ = [
        ("expires_ns", ct.c_uint64), ("flags", ct.c_uint32),
        ("pad", ct.c_uint32),
    ]


PREVIEW_LEN = 24


class MissEvt(ct.Structure):
    """BCC 不能为含嵌套 struct 的事件自动生成 ctypes，这里手工定义。"""
    _fields_ = [
        ("key", FlowKey),
        ("ts_ns", ct.c_uint64),
        ("preview", ct.c_uint8 * PREVIEW_LEN),
    ]


def _parse_evt(data):
    return ct.cast(data, ct.POINTER(MissEvt)).contents


def _fmt_key(key):
    saddr, daddr, sport, dport, _proto = key
    ip = lambda v: ".".join(str((v >> s) & 0xFF) for s in (0, 8, 16, 24))
    return f"{ip(saddr)}:{sport}->{ip(daddr)}:{dport}"


def _key_struct(key):
    saddr, daddr, sport, dport, proto = key
    return FlowKey(saddr, daddr, sport, dport, proto)

def _write_flow(bpf, key, expires_ns, flags=1):
    from bcc import lib
    k = _key_struct(key)
    v = FlowVal(int(expires_ns), flags, 0)
    return lib.bpf_update_elem(bpf["flows"].map_fd, ct.byref(k), ct.byref(v), 0)


def _delete_flow(bpf, key):
    from bcc import lib
    k = _key_struct(key)
    return lib.bpf_delete_elem(bpf["flows"].map_fd, ct.byref(k))


class ProbeRuntime:
    """ringbuf 事件 → 网关 resolve → 写 eBPF 缓存 READY（或等 flow_ready 推送）。"""

    def __init__(self, bpf, gw_path, client_path, rate, log,
                 ttl_default=DEFAULT_TTL, timeout=0.0):
        self.bpf = bpf
        self.gw_path = gw_path
        self.client_path = client_path
        self.rate_limit = max(1, int(rate))
        self.ttl_default = int(ttl_default)
        self.timeout = timeout
        self._log = log
        self.stats = {
            "events": 0, "resolves": 0, "ready": 0, "pending": 0,
            "rate_limited": 0, "resolve_errors": 0,
            "flow_ready": 0, "flow_delete": 0,
            "ebpf_writes": 0, "ebpf_write_errors": 0,
        }
        self._window = deque()
        self._lock = threading.Lock()
        self._key_target = {}     # key tuple -> target_ip
        self._pending = {}        # key tuple -> target_ip（已上报，等 FlowMod）
        self.cfg_mode = "count-only"   # 由 main 覆盖：count-only / drop-non5005
        self.ifaces = []               # 由 main 覆盖：已挂载的接口
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            os.unlink(client_path)
        except FileNotFoundError:
            pass
        self._sock.bind(client_path)
        # 面板以普通用户身份查询计数器，root 创建的 socket 默认 0755 会被 EACCES 拒绝
        try:
            os.chmod(client_path, 0o666)
        except OSError:
            pass
        self._sock.settimeout(0.5)
        self._halt = threading.Event()
        self._thread = threading.Thread(target=self._recv_loop, daemon=True,
                                        name="xdp-probe-recv")

    # ── 生命周期 ──
    def start(self):
        self._thread.start()

    def stop(self):
        self._halt.set()
        try:
            self._sock.close()
        except OSError:
            pass
        try:
            os.unlink(self.client_path)
        except FileNotFoundError:
            pass

    # ── ringbuf 回调（BCC 线程） ──
    def on_miss(self, _ctx, data, _size):
        evt = _parse_evt(data)
        key = (evt.key.saddr, evt.key.daddr, evt.key.sport,
               evt.key.dport, evt.key.proto)
        preview = bytes(evt.preview)
        with self._lock:
            self.stats["events"] += 1
        self._log(f"[MISS] {_fmt_key(key)} preview={preview!r}")
        if not self._allow():
            return
        msg = {"op": "resolve", "key": list(key), "preview": preview.hex()}
        try:
            self._sock.sendto(json.dumps(msg).encode(), self.gw_path)
        except OSError as exc:
            with self._lock:
                self.stats["resolve_errors"] += 1
            self._log(f"[PROBE] resolve 发送失败: {exc}")
            return
        with self._lock:
            self.stats["resolves"] += 1

    def _allow(self):
        """全局探针速率上限：1 s 窗口内最多 rate_limit 次。"""
        now = time.monotonic()
        with self._lock:
            while self._window and now - self._window[0] > 1.0:
                self._window.popleft()
            if len(self._window) >= self.rate_limit:
                self.stats["rate_limited"] += 1
                return False
            self._window.append(now)
            return True

    # ── 网关 → 探针 ──
    def stats_payload(self):
        """当前计数器快照（供面板 / API 查询）"""
        totals = _snapshot(self.bpf)
        total_5005 = totals["flow_cached"] + totals["flow_miss"]
        with self._lock:
            probe_stats = dict(self.stats)
            cache_entries = len(self._key_target)
            pending = len(self._pending)
        return {
            "op": "stats_reply",
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "netns": _netns_id(),
            "ifaces": list(self.ifaces),
            "cfg": self.cfg_mode,
            "totals": totals,
            "total_5005": total_5005,
            "hit_rate": (totals["flow_cached"] / total_5005) if total_5005 else 0.0,
            "probe": probe_stats,
            "cache_entries": cache_entries,
            "pending": pending,
        }

    def _recv_loop(self):
        while not self._halt.is_set():
            try:
                data, _addr = self._sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                msg = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            op = msg.get("op")
            if op == "resolve_reply":
                self._on_reply(msg)
            elif op == "flow_ready":
                self._on_flow_ready(msg)
            elif op == "flow_delete":
                self._on_flow_delete(msg)
            elif op == "stats":
                try:
                    self._sock.sendto(
                        json.dumps(self.stats_payload()).encode("utf-8"), _addr)
                except OSError:
                    pass

    def _on_reply(self, msg):
        key = tuple(msg.get("key") or ())
        target = msg.get("target_ip")
        if len(key) != 5 or not target:
            return
        status = msg.get("status")
        if status == "ready":
            ttl = max(1, int(msg.get("ttl") or self.ttl_default))
            with self._lock:
                self.stats["ready"] += 1
                self._key_target[key] = target
                self._pending.pop(key, None)
            self._write_ready(key, ttl)
            self._log(f"[PROBE] 网关本地缓存命中 {_fmt_key(key)} → {target}，写 eBPF 缓存 READY ttl={ttl}s")
        elif status == "pending":
            with self._lock:
                self.stats["pending"] += 1
                self._key_target[key] = target
                self._pending[key] = target
            self._log(f"[PROBE] 网关本地缓存未命中 {_fmt_key(key)} → {target}，已上报，等 FlowMod")

    def _on_flow_ready(self, msg):
        target = msg.get("target_ip")
        ttl = max(1, int(msg.get("ttl") or self.ttl_default))
        with self._lock:
            keys = [k for k, t in self._key_target.items() if t == target]
            for k in [k for k, t in self._pending.items() if t == target]:
                if k not in keys:
                    keys.append(k)
                del self._pending[k]
            self.stats["flow_ready"] += 1
        for key in keys:
            self._write_ready(key, ttl)
        self._log(f"[PROBE] 收到 flow_ready {target} ttl={ttl}s，回写 {len(keys)} 条 eBPF 缓存")

    def _on_flow_delete(self, msg):
        target = msg.get("target_ip")
        with self._lock:
            keys = [k for k, t in self._key_target.items() if t == target]
            for k in keys:
                self._key_target.pop(k, None)
                self._pending.pop(k, None)
            self.stats["flow_delete"] += 1
        for key in keys:
            _delete_flow(self.bpf, key)
        self._log(f"[PROBE] 收到 flow_delete {target}，删除 {len(keys)} 条 eBPF 缓存")

    def _write_ready(self, key, ttl):
        expires = time.monotonic_ns() + ttl * 1_000_000_000
        try:
            rc = _write_flow(self.bpf, key, expires, flags=1)
        except Exception as exc:  # noqa: BLE001 - 只计数，不影响数据面
            rc = -1
            self._log(f"[PROBE] 写 eBPF 缓存异常: {exc}")
        with self._lock:
            if rc == 0:
                self.stats["ebpf_writes"] += 1
            else:
                self.stats["ebpf_write_errors"] += 1


def _ring_poll(bpf, halt):
    """BCC 0.29 的 open_ring_buffer 只注册回调，必须自己 poll。"""
    print("[POLL] ringbuf 消费线程已启动", flush=True)
    while not halt.is_set():
        try:
            bpf.ring_buffer_poll(200)
        except Exception as exc:  # noqa: BLE001 - poll 失败只记录
            print(f"[PROBE] ringbuf poll 异常: {exc}", flush=True)
            return


def _print_row(totals, deltas, elapsed, probe):
    parts = [f"5005 cached={totals['flow_cached']} (+{deltas['flow_cached']})",
             f"miss={totals['flow_miss']} (+{deltas['flow_miss']})"]
    for name in STAT_NAMES:
        if name in ("flow_cached", "flow_miss"):
            continue
        if totals[name] or deltas[name]:
            parts.append(f"{name}={totals[name]} (+{deltas[name]})")
    if probe is not None:
        parts.append(f"evt={probe.stats['events']} resolve={probe.stats['resolves']} "
                     f"ready={probe.stats['ready']} pending={probe.stats['pending']} "
                     f"rl={probe.stats['rate_limited']}")
    print(f"[{elapsed:7.1f}s] " + "  ".join(parts), flush=True)


def _detach(ifaces, flags=None):
    """摘除 XDP。已知模式用对应 flags；未知时按 auto/skb/drv 依次试。

    注意：`ip link set dev X xdp off` 等价于 flags=0，摘不掉以
    XDP_FLAGS_SKB_MODE（flags=2）显式挂载的程序，所以这里必须带模式。
    """
    from bcc import lib
    ok = True
    for iface in ifaces:
        for f in ([flags] if flags is not None else DETACH_FLAGS):
            lib.bpf_attach_xdp(iface.encode(), -1, f)
            if not _xdp_line(iface):
                break
        if _xdp_line(iface):
            ok = False
            print(f"  摘除 {iface} 失败：接口上仍有 XDP", flush=True)
    return ok


def main():
    ap = argparse.ArgumentParser(
        description="iot3 网关入向 XDP filter + probe（阶段 2：ringbuf 事件）")
    ap.add_argument("--ifaces", nargs="+", default=list(DEFAULT_IFACES),
                    help="挂载接口（默认 iot3-eth0 iot3-eth1 iot3-eth2）")
    ap.add_argument("--mode", choices=sorted(MODE_FLAGS), default="auto",
                    help="XDP 模式：auto=内核自选，skb=通用模式，drv=驱动模式")
    ap.add_argument("--interval", type=float, default=2.0,
                    help="打印计数间隔秒，默认 2")
    ap.add_argument("--duration", type=float, default=0,
                    help="运行多少秒后退出，0=一直运行到 Ctrl-C")
    ap.add_argument("--set-cfg", choices=("count", "drop-non5005"),
                    help="运行期改策略：count=只统计（默认行为，cfg=0）；"
                         "drop-non5005=丢弃非 5005 的 UDP（cfg=1）")
    ap.add_argument("--no-probe", action="store_true",
                    help="只消费 ringbuf 打日志，不连网关、不写 eBPF 缓存（阶段 2）")
    ap.add_argument("--probe-sock", default=DEFAULT_PROBE_SOCK,
                    help=f"网关 ProbeBridge 的 Unix socket（默认 {DEFAULT_PROBE_SOCK}）")
    ap.add_argument("--probe-client-sock", default=DEFAULT_CLIENT_SOCK,
                    help=f"探针自身绑定的 Unix socket（默认 {DEFAULT_CLIENT_SOCK}）")
    ap.add_argument("--probe-rate", type=int, default=50,
                    help="全局探针速率上限（次/秒，默认 50）")
    ap.add_argument("--ttl", type=int, default=DEFAULT_TTL,
                    help=f"eBPF 缓存 READY 默认 TTL 秒（默认 {DEFAULT_TTL}，与控制器对齐）")
    ap.add_argument("--detach-only", action="store_true",
                    help="只摘除已挂载的 XDP，不加载程序")
    ap.add_argument("--keep", action="store_true",
                    help="退出时保留 XDP 挂载（默认退出即摘除）")
    ap.add_argument("--json-out", metavar="PATH",
                    help="退出时把最终计数写成 JSON，作为验收证据")
    ap.add_argument("--ready-file", metavar="PATH",
                    help="挂载成功后创建该文件，供脚本等待就绪（自测用）")
    ap.add_argument("--c-source", default=SRC_FILE,
                    help="eBPF C 源文件路径")
    args = ap.parse_args()

    missing = [i for i in args.ifaces if not _iface_exists(i)]
    if args.detach_only:
        if missing:
            sys.exit(f"接口不存在: {', '.join(missing)}（不在 iot3 命名空间？）")
        sys.exit(0 if _detach(args.ifaces) else 1)

    if os.geteuid() != 0:
        sys.exit("需要 root：加载 XDP 需要 CAP_BPF，请按 --help 里的方式用 sudo 运行")
    if missing:
        sys.exit(f"接口不存在: {', '.join(missing)}（不在 iot3 命名空间？）")
    if not os.path.exists(args.c_source):
        sys.exit(f"找不到 eBPF 源文件: {args.c_source}")

    from bcc import BPF

    flags = MODE_FLAGS[args.mode]
    # BCC 把源文件拼进 /virtual/main.c 再编译，quoted include 不会自动按
    # 源文件目录解析；显式把 eBPF 源目录加进 include path。
    src_dir = os.path.dirname(os.path.abspath(args.c_source))
    bpf = BPF(src_file=args.c_source, cflags=["-I" + src_dir])
    fn = bpf.load_func("gw_filter", BPF.XDP)

    if args.set_cfg:
        _set_cfg(bpf, args.set_cfg == "drop-non5005")

    attached = []
    for iface in args.ifaces:
        try:
            bpf.attach_xdp(iface, fn, flags)
        except Exception as exc:
            print(f"挂载 {iface} 失败: {exc}", flush=True)
            continue
        attached.append(iface)
        print(f"已挂载 {iface}  {_xdp_line(iface)}", flush=True)

    if not attached:
        sys.exit("没有成功挂载任何接口，检查是否已有 XDP 程序占用或模式不支持")

    poll_halt = threading.Event()
    probe = None
    if not args.no_probe:
        probe = ProbeRuntime(bpf, args.probe_sock, args.probe_client_sock,
                             args.probe_rate, lambda m: print(m, flush=True),
                             ttl_default=args.ttl)
        probe.start()
        probe.cfg_mode = args.set_cfg or "count-only"
        probe.ifaces = list(attached)
        bpf["misses"].open_ring_buffer(probe.on_miss)
        print(f"probe 已启动：resolve → {args.probe_sock}，"
              f"本进程监听 {args.probe_client_sock}，上限 {args.probe_rate}/s",
              flush=True)
    else:
        def _log_miss(_ctx, data, _size):
            evt = _parse_evt(data)
            key = (evt.key.saddr, evt.key.daddr, evt.key.sport,
                   evt.key.dport, evt.key.proto)
            print(f"[MISS] {_fmt_key(key)} preview={bytes(evt.preview)!r}",
                  flush=True)
        bpf["misses"].open_ring_buffer(_log_miss)
        print("probe 未启用（--no-probe）：ringbuf 事件只打日志", flush=True)

    threading.Thread(target=_ring_poll, args=(bpf, poll_halt),
                     daemon=True, name="xdp-ring-poll").start()

    print(f"PID={os.getpid()} netns={_netns_id()} mode={args.mode} "
          f"cfg={'drop-non5005' if args.set_cfg == 'drop-non5005' else 'count-only'}",
          flush=True)
    if args.ready_file:
        open(args.ready_file, "w").close()

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    interval = max(0.2, args.interval)
    start = time.monotonic()
    totals = _snapshot(bpf)
    last = dict(totals)
    try:
        while not _stop:
            time.sleep(interval)
            totals = _snapshot(bpf)
            deltas = {k: totals[k] - last[k] for k in STAT_NAMES}
            last = totals
            _print_row(totals, deltas, time.monotonic() - start, probe)
            if args.duration and time.monotonic() - start >= args.duration:
                break
    finally:
        try:
            totals = _snapshot(bpf)
            probe_stats = dict(probe.stats) if probe else {}
            total_5005 = totals["flow_cached"] + totals["flow_miss"]
            hit_rate = (totals["flow_cached"] / total_5005) if total_5005 else 0.0
            print(f"[SUMMARY] cached={totals['flow_cached']} miss={totals['flow_miss']} "
                  f"hit_rate={hit_rate:.3f} events={probe_stats.get('events', 0)} "
                  f"resolves={probe_stats.get('resolves', 0)} "
                  f"ready={probe_stats.get('ready', 0)} "
                  f"pending={probe_stats.get('pending', 0)} "
                  f"rate_limited={probe_stats.get('rate_limited', 0)} "
                  f"ebpf_writes={probe_stats.get('ebpf_writes', 0)}", flush=True)
            if args.json_out:
                payload = {
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "netns": _netns_id(),
                    "ifaces": attached,
                    "mode": args.mode,
                    "cfg": args.set_cfg or "count-only",
                    "totals": totals,
                    "hit_rate": hit_rate,
                    "probe": probe_stats,
                    "xdp_state": {i: _xdp_line(i) for i in attached},
                }
                with open(args.json_out, "w", encoding="utf-8") as fh:
                    json.dump(payload, fh, ensure_ascii=False, indent=2)
                print(f"计数已写入 {args.json_out}", flush=True)
        finally:
            poll_halt.set()
            if probe is not None:
                probe.stop()
            if args.keep:
                print("保留 XDP 挂载：" + " ".join(attached), flush=True)
            elif _detach(attached, flags):
                print("已摘除 XDP：" + " ".join(attached), flush=True)
            else:
                print("警告：部分接口上仍有 XDP，可再跑 --detach-only", flush=True)


if __name__ == "__main__":
    main()
