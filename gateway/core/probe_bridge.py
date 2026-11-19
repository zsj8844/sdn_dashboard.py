"""网关侧 probe 桥：XDP 探针 ↔ 本地 FlowTable（网关本地缓存）/ OpenFlow 客户端。

探针（root + BCC，独立进程）不直接连控制器，只通过 Unix datagram 问网关：

    resolve  {"op":"resolve","key":[5元组],"preview":hex}
    回包     {"op":"resolve_reply","key":[...],"status":"ready"|"pending",
              "target_ip":"...","ttl":秒}

网关收到的 FlowMod 写入网关本地缓存后，主动推送：

    flow_ready  {"op":"flow_ready","target_ip":"...","ttl":秒}
    flow_delete {"op":"flow_delete","target_ip":"..."}

这样 OF 客户端仍然只有网关一个，探针只负责 eBPF 缓存。
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple

DEFAULT_BRIDGE_SOCK = os.environ.get("SDN_XDP_PROBE_SOCK",
                                     "/tmp/sdn_xdp_probe.sock")
DEFAULT_TTL = 60


def resolve_target_ip(ble_addr: str) -> str:
    """BLE 地址 → 目标主机 IP（与网关原来的硬编码映射保持一致）。"""
    if ble_addr in ("aa:bb:cc:dd:ee:01", "aa:bb:cc:dd:ee:04"):
        return "192.168.1.20"
    if ble_addr == "aa:bb:cc:dd:ee:02":
        return "192.168.1.21"
    return "192.168.1.20"


def parse_preview(preview: bytes) -> Optional[Tuple[str, str, str]]:
    """从固定 24 字节预览里取 (ble_addr, sensor_type, value)。"""
    text = preview.rstrip(b"\x00").decode("utf-8", "replace")
    parts = text.split(",", 2)
    if len(parts) < 2 or len(parts[0]) != 17:
        return None
    return parts[0], parts[1], (parts[2] if len(parts) > 2 else "")


class ProbeBridge:
    """Unix datagram 服务端：resolve → 网关本地缓存查询/上报；FlowMod → 推送 flow_ready。"""

    def __init__(self, of_agent: Any,
                 sock_path: str = DEFAULT_BRIDGE_SOCK,
                 default_ttl: int = DEFAULT_TTL,
                 log: Optional[Callable[[str], None]] = None):
        self.of_agent = of_agent
        self.sock_path = sock_path
        self.default_ttl = default_ttl
        self._log = log or (lambda msg: None)
        self._sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._halt = threading.Event()
        self._probe_addr: Optional[str] = None
        self.stats = {"resolve": 0, "ready": 0, "pending": 0,
                      "flow_ready": 0, "flow_delete": 0, "errors": 0}

    # ── 生命周期 ──
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._halt.clear()
        try:
            os.unlink(self.sock_path)
        except FileNotFoundError:
            pass
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self._sock.bind(self.sock_path)
        self._sock.settimeout(0.5)
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="xdp-probe-bridge")
        self._thread.start()
        self._log(f"[probe] 探针桥已监听 {self.sock_path}")

    def stop(self) -> None:
        self._halt.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        try:
            os.unlink(self.sock_path)
        except FileNotFoundError:
            pass
        if self._thread:
            self._thread.join(timeout=1)

    # ── 控制器 → 网关（由 of_gateway_agent 回调） ──
    def on_flow_installed(self, match: Dict[str, Any],
                          idle_timeout: int = 0) -> None:
        target = (match or {}).get("dst_ip")
        if not target:
            return
        self.stats["flow_ready"] += 1
        self._push({"op": "flow_ready", "target_ip": target,
                    "ttl": int(idle_timeout or self.default_ttl)})
        self._log(f"[probe] FlowMod 写入网关本地缓存: {target}，推送 flow_ready")

    def on_flow_deleted(self, match: Dict[str, Any]) -> None:
        target = (match or {}).get("dst_ip")
        if not target:
            return
        self.stats["flow_delete"] += 1
        self._push({"op": "flow_delete", "target_ip": target})
        self._log(f"[probe] Flow 删除: {target}，推送 flow_delete")

    # ── 探针 → 网关 ──
    def _run(self) -> None:
        while not self._halt.is_set():
            try:
                data, addr = self._sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                msg = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self.stats["errors"] += 1
                continue
            self._probe_addr = addr
            try:
                self._handle(msg, addr)
            except Exception as exc:  # noqa: BLE001 - 桥不能拖垮网关
                self.stats["errors"] += 1
                self._log(f"[probe] 处理 resolve 失败: {exc}")

    def _handle(self, msg: Dict[str, Any], addr: str) -> None:
        if msg.get("op") != "resolve":
            return
        self.stats["resolve"] += 1
        key = msg.get("key") or []
        preview_hex = msg.get("preview") or ""
        try:
            preview = bytes.fromhex(preview_hex)
        except ValueError:
            preview = b""

        parsed = parse_preview(preview)
        if parsed is None:
            ble_addr, sensor_type, value = "unknown", "temp", ""
        else:
            ble_addr, sensor_type, value = parsed
        target_ip = resolve_target_ip(ble_addr)

        entry = self.of_agent.flows.lookup(dst_ip=target_ip, eth_type=0x0800)
        if entry is not None:
            ttl = self._remaining_ttl(entry)
            if ttl > 0:
                self.stats["ready"] += 1
                self._reply(addr, {"op": "resolve_reply", "key": key,
                                   "status": "ready", "target_ip": target_ip,
                                   "ttl": ttl})
                return

        self.stats["pending"] += 1
        try:
            self.of_agent.note_sensor_data(ble_addr, sensor_type, value,
                                           target_ip)
        except Exception as exc:  # noqa: BLE001
            self.stats["errors"] += 1
            self._log(f"[probe] 上报控制器失败: {exc}")
        self._reply(addr, {"op": "resolve_reply", "key": key,
                           "status": "pending", "target_ip": target_ip})

    def _remaining_ttl(self, entry: Any) -> int:
        ttl = int(getattr(entry, "idle_timeout", 0) or self.default_ttl)
        last = getattr(entry, "last_used", None)
        if last is None:
            return ttl
        return max(0, int(ttl - (time.monotonic() - last)))

    def _reply(self, addr: str, payload: Dict[str, Any]) -> None:
        if self._sock is None:
            return
        try:
            self._sock.sendto(json.dumps(payload).encode("utf-8"), addr)
        except OSError as exc:
            self.stats["errors"] += 1
            self._log(f"[probe] 回包失败: {exc}")

    def _push(self, payload: Dict[str, Any]) -> None:
        if self._sock is None or self._probe_addr is None:
            return
        try:
            self._sock.sendto(json.dumps(payload).encode("utf-8"),
                              self._probe_addr)
        except OSError:
            pass
