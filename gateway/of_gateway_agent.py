"""网关侧 OpenFlow 1.3 代理 — 把 ofproto_client 接进网关主流程。

职责：
  1. 后台线程连到控制器（默认 6634），完成 HELLO → FEATURES 握手，断线自动重连；
  2. BLE 数据以 PacketIn 上报控制器（仅当本地流表未命中）；
  3. 接收控制器下发的 FlowMod，解析 match/actions/Experimenter，
     写入网关本地 FlowTable；之后同目的地的数据命中本地流表，不再上送；
  4. 接收 PacketOut / Echo，维持通道并记录控制器下发内容。
"""

from __future__ import annotations

import logging
import struct
import threading
import time
from typing import Any, Callable, Dict, Optional

from ryu.ofproto import ofproto_v1_3 as ofproto

from ofproto_client import (
    EXPERIMENTER_ID,
    FlowEntry,
    FlowTable,
    OF13Client,
    build_ble_packet_in_frame,
)

logger = logging.getLogger("GatewayOFAgent")

# 控制器可能下发的 port 常量
_CONTROLLER_PORTS = (
    ofproto.OFPP_CONTROLLER,
    ofproto.OFPP_FLOOD,
    ofproto.OFPP_ALL,
)


def _to_local_match(of_match: Dict[str, Any]) -> Dict[str, Any]:
    """把 OF match 字段名映射成网关本地流表的字段名。"""
    mapping = {
        'in_port': 'in_port',
        'eth_type': 'eth_type',
        'ipv4_src': 'src_ip',
        'ipv4_dst': 'dst_ip',
        'udp_src': 'udp_sport',
        'udp_dst': 'udp_dport',
    }
    return {mapping[k]: v for k, v in of_match.items()
            if k in mapping and v is not None}


def _describe_experimenter(data: bytes) -> Dict[str, Any]:
    """解出控制器嵌入 FlowMod 的 IoT TLV 字段（失败时返回原始十六进制）。"""
    from extensions.manager import IoTExtensionManager
    try:
        # OFPActionExperimenter 的 data 只含 TLV 负载，不含厂商 ID
        payload = struct.pack("!I", EXPERIMENTER_ID) + bytes(data)
        mgr = IoTExtensionManager.parse_from_experimenter(payload)
        return mgr.get_field_dict()
    except Exception:
        return {"experimenter_raw": bytes(data).hex()}


class GatewayOpenFlowAgent:
    """网关的 OpenFlow 1.3 设备侧代理。"""

    def __init__(self,
                 dpid: int = 3,
                 controller_host: str = "127.0.0.1",
                 controller_port: int = 6634,
                 gateway_ip: str = "192.168.1.12",
                 src_mac: str = "00:00:00:00:00:03",
                 n_ports: int = 3,
                 report_interval: float = 5.0,
                 reconnect_interval: float = 5.0,
                 log: Optional[Callable[[str], None]] = None):
        self.dpid = dpid
        self.controller_host = controller_host
        self.controller_port = controller_port
        self.gateway_ip = gateway_ip
        self.src_mac = src_mac
        self.n_ports = n_ports
        self.report_interval = report_interval
        self.reconnect_interval = reconnect_interval
        self._log = log or (lambda msg: print(msg, flush=True))

        self.flows = FlowTable()
        self.connected = False
        self.stats = {
            "reconnects": 0,
            "packet_ins": 0,
            "flow_mods": 0,
            "local_hits": 0,
            "packet_outs": 0,
        }

        self._client: Optional[OF13Client] = None
        self._client_lock = threading.Lock()
        self._last_report: Dict[str, float] = {}
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ── 生命周期 ────────────────────────────────────────────────

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="gw-of-agent")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._close_client()
        if self._thread:
            self._thread.join(timeout=2)
        self.connected = False

    # ── 对网关主流程的接口 ──────────────────────────────────────

    def note_sensor_data(self, ble_addr: str, sensor_type: str, value: str,
                         target_ip: str) -> bool:
        """BLE 数据到达时调用：本地流表命中则本地快转，否则上报 PacketIn。"""
        # 流表项通常带 eth_type=IPv4；lookup 要求候选字段覆盖 match 的所有 key。
        if self.flows.lookup(dst_ip=target_ip, eth_type=0x0800) is not None:
            self.stats["local_hits"] += 1
            self._log(f"[OF] 命中本地流表，跳过上报: → {target_ip}")
            return False

        with self._client_lock:
            client = self._client
        if not self.connected or client is None:
            return False

        now = time.monotonic()
        if now - self._last_report.get(target_ip, 0.0) < self.report_interval:
            return False
        self._last_report[target_ip] = now

        frame = build_ble_packet_in_frame(
            self.src_mac, self.gateway_ip, target_ip,
            ble_addr, sensor_type, value,
        )
        try:
            client.send_packet_in(frame, in_port=1)
        except Exception as exc:
            self._log(f"[OF] PacketIn 发送失败: {exc}")
            return False

        self.stats["packet_ins"] += 1
        self._log(f"[OF] PacketIn 上报: {ble_addr} {sensor_type}={value} → {target_ip}")
        return True

    def dump_flows(self) -> list:
        return [repr(e) for e in self.flows.dump()]

    # ── 后台连接线程 ────────────────────────────────────────────

    def _run(self) -> None:
        while not self._stop.is_set():
            client = self._new_client()
            with self._client_lock:
                self._client = client
            try:
                client.connect()
                self.connected = True
                self._log(f"[OF] 已连接控制器 {self.controller_host}:"
                          f"{self.controller_port} (dpid={self.dpid})，握手完成")
                while (not self._stop.is_set() and client.is_connected()):
                    time.sleep(0.5)
            except Exception as exc:
                self._log(f"[OF] 连接控制器失败: {exc}，"
                          f"{self.reconnect_interval:g}s 后重试")
            finally:
                self.connected = False
                self._close_client()
            if not self._stop.is_set():
                self.stats["reconnects"] += 1
                self._stop.wait(self.reconnect_interval)

    def _new_client(self) -> OF13Client:
        client = OF13Client(
            dpid=self.dpid,
            controller_host=self.controller_host,
            controller_port=self.controller_port,
            hw_addr=self.src_mac,
            n_ports=self.n_ports,
        )
        client.on_flow_mod = self._on_flow_mod
        client.on_packet_out = self._on_packet_out
        client.on_error = self._on_error
        client.on_disconnect = self._on_disconnect
        return client

    def _close_client(self) -> None:
        with self._client_lock:
            client = self._client
            self._client = None
        if client is not None:
            try:
                client.close()
            except Exception:
                pass

    # ── 控制器 → 网关 ────────────────────────────────────────────

    def _on_disconnect(self) -> None:
        self.connected = False
        self._log("[OF] 控制器连接断开，准备重连")

    def _on_error(self, message: Dict[str, Any]) -> None:
        self._log(f"[OF] 控制器返回错误: {message.get('raw', b'')[:32]!r}")

    def _on_flow_mod(self, fm: Dict[str, Any]) -> None:
        command = fm.get("command")
        if command in (ofproto.OFPFC_DELETE, ofproto.OFPFC_DELETE_STRICT):
            match = _to_local_match(fm.get("match") or {})
            removed = self.flows.delete(
                cookie=fm.get("cookie", 0),
                match=match or None,
                strict=(command == ofproto.OFPFC_DELETE_STRICT),
            )
            self._log(f"[OF] 收到 FlowMod DELETE，删除 {removed} 条本地流")
            return

        local_match = _to_local_match(fm.get("match") or {})
        actions = fm.get("actions") or []
        priority = fm.get("priority", 0)
        outputs = [a.get("port") for a in actions
                   if a.get("type") == "OUTPUT"]
        is_table_miss = (
            priority == 0
            or (not local_match and any(p in _CONTROLLER_PORTS for p in outputs))
        )

        ext_fields: Dict[str, Any] = {}
        for action in actions:
            if action.get("type") == "EXPERIMENTER":
                ext_fields = _describe_experimenter(action.get("data", b""))
                break

        if is_table_miss:
            self._log("[OF] 收到 table-miss 流（空匹配 → 控制器），不入本地流表")
            return

        entry = FlowEntry(
            match=local_match,
            actions=actions,
            priority=priority,
            cookie=fm.get("cookie", 0),
            idle_timeout=fm.get("idle_timeout", 0),
            hard_timeout=fm.get("hard_timeout", 0),
        )
        self.flows.add(entry)
        self.stats["flow_mods"] += 1
        ext_desc = f" IoT字段={ext_fields}" if ext_fields else ""
        self._log(f"[OF] 收到 FlowMod prio={priority} match={local_match} "
                  f"actions={[a.get('type') for a in actions]}{ext_desc}")

    def _on_packet_out(self, po: Dict[str, Any]) -> None:
        self.stats["packet_outs"] += 1
        actions = po.get("actions") or []
        self._log(f"[OF] 收到 PacketOut in_port={po.get('in_port')} "
                  f"actions={[a.get('type') for a in actions]} "
                  f"data={len(po.get('data') or b'')}B")
        # 数据面仍由网关自己的 UDP 转发负责，这里只记录控制器下发内容，
        # 避免同一条 BLE 数据被转发两次。
