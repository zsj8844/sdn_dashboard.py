"""
OpenFlow 1.3 Protocol Client for IoT Gateway.
=============================================
Implements the OpenFlow 1.3 switch-side wire protocol:
  - HELLO handshake (version bitmap negotiation)
  - Features Request / Reply
  - Packet-In (BLE sensor data → controller)
  - FlowMod / PacketOut reception (controller → gateway)
  - Echo keepalive

Uses manual struct packing for outgoing messages (Ryu's parser classes
don't implement _serialize_body for switch-side message types) and Ryu's
ofproto_parser.msg() for parsing incoming messages that are registered.
"""

from __future__ import annotations

import logging
import socket
import struct
import threading
import time
from typing import Any, Callable, Dict, List, Optional

# ── Ryu imports (for frame construction and message parsing) ──
from ryu.ofproto import ofproto_v1_3 as ofproto
from ryu.ofproto import ofproto_v1_3_parser as ofparser
from ryu.ofproto import ofproto_parser
from ryu.lib.packet import ethernet, ipv4, packet as ryu_packet, udp

logger = logging.getLogger("OF13Client")

# ═══════════════════════════════════════════════════════════════════════════
# Wire format constants (all from OF 1.3 spec)
# ═══════════════════════════════════════════════════════════════════════════

OFP_HEADER_PACK_STR = "!BBHI"
OFP_HEADER_SIZE     = 8
OFP_VERSION          = 0x04

OFP_SWITCH_FEATURES_PACK_STR = "!QIBB2xII"  # datapath_id n_buffers n_tables aux_id pad caps reserved
OFP_PORT_PACK_STR  = "!I4x6s2x16sIIIIIIII"
OFP_MATCH_PACK_STR = "!HHBBBB"
OFP_MATCH_SIZE     = 8
OFP_PACKET_IN_PACK_STR = "!IHBBQ"          # buffer_id total_len reason table_id cookie
OFP_FLOW_MOD_PACK_STR0 = "!QQBBHHHIIIH2x"  # OF 1.3 FlowMod body before match
OFP_FLOW_MOD_SIZE0     = 40
OFP_PACKET_OUT_PACK_STR = "!IIH6x"         # buffer_id in_port actions_len
OFP_HELLO_ELEM_PACK_STR = "!HH"            # element type, length

# ── OXM ──
OFPMT_OXM   = 1
OFPXMC_OPENFLOW_BASIC = 0x8000
OXM_OFB_IN_PORT  = 0
OXM_OFB_ETH_TYPE = 5

# ── Port feature flags ──
OFPPF_1GB_FD   = 1 << 5
OFPPF_COPPER   = 1 << 6
OFPPS_LIVE     = 1 << 2

# ── Experimenter ID (mirror project constant) ──
EXPERIMENTER_ID = 0x12345678


# ═══════════════════════════════════════════════════════════════════════════
# Helper: OXMTLV field packing
# ═══════════════════════════════════════════════════════════════════════════
# 构建 4 字节 OXM TLV header (class, field, has_mask, length)
def _oxm_tlv(oxm_class: int, field: int, has_mask: bool, length: int) -> bytes:
    """4-byte OXM TLV header."""
    v = (oxm_class << 16) | ((field & 0x7F) << 9) | ((1 if has_mask else 0) << 8) | length
    return struct.pack("!I", v)

# 构建 OFPMT_OXM match bytes (for PacketIn)
# [8字节Match头] + [4字节in_port标签头] + [4字节in_port值] + [4字节eth_type标签头] + [2字节eth_type值]
# 这是匹配字段（OXM Match Fields）—— 每一个值都必须带标签头
def _build_match(in_port: Optional[int] = None,
                 eth_type: Optional[int] = None) -> bytes:
    """Build OFPMT_OXM match bytes (for PacketIn)."""
    oxm = bytearray()
    if in_port is not None:
        oxm += _oxm_tlv(OFPXMC_OPENFLOW_BASIC, OXM_OFB_IN_PORT, False, 4)
        oxm += struct.pack("!I", in_port)
    if eth_type is not None:
        oxm += _oxm_tlv(OFPXMC_OPENFLOW_BASIC, OXM_OFB_ETH_TYPE, False, 2)
        oxm += struct.pack("!H", eth_type)
    hdr = struct.pack(OFP_MATCH_PACK_STR, OFPMT_OXM,
                      OFP_MATCH_SIZE + len(oxm), 0, 0, 0, 0)
    return hdr + bytes(oxm)


# ═══════════════════════════════════════════════════════════════════════════
# Message builders (outgoing: gateway → controller)
# ═══════════════════════════════════════════════════════════════════════════
# __init__tcp连接回复的静态简历
# Features Reply 消息（整封快递信）
# │
# ├── 固定头部（8字节）       ← 由 _header() 统一添加
# ├── 固定体（24字节）        ← 由 features_reply 直接 pack 填充（DPID、表数量等）
# └── 端口列表（变长）        ← 由 **port_desc** 生成，一个一个拼在尾部
#     ├── 端口1描述（64字节）  ← port_desc 生成
#     ├── 端口2描述（64字节）  ← port_desc 生成
#     └── 端口3描述（64字节）  ← port_desc 生成
class OFMessageBuilder:
    """Builds OF 1.3 binary messages with monotonic xid."""

    _xid: int = 0
    # 它就是自动给每封“信”贴上唯一流水号（XID）的机器，确保网关在和控制器“鱼雁传书”时，能准确地把“回信”和“寄出的信”
    @classmethod
    def _next_xid(cls) -> int:
        cls._xid = (cls._xid + 1) & 0xFFFFFFFF
        return cls._xid

    # 封装 OpenFlow 公共头部（8 字节） + 消息体
    @classmethod
    def _header(cls, msg_type: int, body: bytes, xid: Optional[int] = None) -> bytes:
        if xid is None:
            xid = cls._next_xid()
        total = OFP_HEADER_SIZE + len(body)
        hdr = struct.pack(OFP_HEADER_PACK_STR, OFP_VERSION, msg_type, total, xid)
        return hdr + body

    # ── OFPT_HELLO (0) ──
    # test对方也是1.3版本，发一个带版本位图的Hello消息
    @classmethod
    def hello(cls) -> bytes:
        """OFPHello with version bitmap element [0x04]."""
        bitmap = 1 << OFP_VERSION          # only OF 1.3
        elem = struct.pack("!HH4sI4x", 1, 8, b"\x00" * 4, bitmap)
        return cls._header(ofproto.OFPT_HELLO, elem)

    # ── OFPT_FEATURES_REPLY (6) ──
    # 构建 **功能**：构造 **OFPT_FEATURES_REPLY**（交换机特征回复）消息。
    # - **实现细节**：
    # - 固定体部分（`OFP_SWITCH_FEATURES_PACK_STR`）：包含 `datapath_id`、`n_buffers=0`、`n_tables=1`、`capabilities=0xC7`（代表支持流表、组表、端口统计等）。
    @classmethod
    def features_reply(cls, dpid: int, ports: Optional[bytes] = None) -> bytes:
        """OFPSwitchFeatures with optional port list."""
        body = struct.pack(OFP_SWITCH_FEATURES_PACK_STR,
                           dpid,               # datapath_id (uint64)
                           0,                  # n_buffers
                           1,                  # n_tables
                           0,                  # auxiliary_id
                           0xC7,              # capabilities (flow+table+port+group stats)
                           0)                 # reserved
        if ports:
            body += ports
        return cls._header(ofproto.OFPT_FEATURES_REPLY, body)

    #物理硬件端口（网口长什么样） 让控制器知道网关有几根网线、速度多少、是否在线。
    # Features Reply（自我介绍）
    @classmethod
    def port_desc(cls, port_no: int, hw_addr: str, port_name: Optional[str] = None) -> bytes:
        """Single OFPPort for use in Features Reply."""
        hw = bytes(int(b, 16) for b in hw_addr.split(":"))
        name = (port_name or f"gw-port{port_no}").encode()[:16].ljust(16, b"\x00")
        return struct.pack(OFP_PORT_PACK_STR,
                           port_no,
                           hw,
                           name,
                           0,                                 # config
                           OFPPS_LIVE,                        # state
                           OFPPF_1GB_FD | OFPPF_COPPER,       # curr
                           0, 0, 0,                           # advertised supported peer
                           1000000, 1000000)                   # curr_speed max_speed (kbps)
# 运行时数据上报
# PacketIn 消息（另一封快递信）
# │
# ├── 固定头部（8字节）
# ├── 固定体（16字节）
# └── 匹配字段（变长）        ← 由 **_build_match** 生成（告诉控制器包的入端口和类型）
#     └── （里面才有 _oxm_tlv 造的标签头）
    # ── OFPT_PACKET_IN (10) ──
    @classmethod
    def packet_in(cls, frame: bytes, in_port: int = 1,reason: int = ofproto.OFPR_NO_MATCH,buffer_id: int = ofproto.OFP_NO_BUFFER) -> bytes:
        """OFPPacketIn carrying an Ethernet frame as payload."""
        # PacketIn body (16 bytes after header)
        pi_hdr = struct.pack(OFP_PACKET_IN_PACK_STR,
                             buffer_id, len(frame), reason, 0, 0)
        # Match (with in_port + eth_type OXM)
        match = _build_match(in_port=in_port, eth_type=0x0800)
        # 2-byte pad → 8-byte alignment, then frame data
        body = pi_hdr + match + b"\x00\x00" + frame
        return cls._header(ofproto.OFPT_PACKET_IN, body)

    # ── OFPT_ECHO_REPLY (3) ──
    @classmethod
    def echo_reply(cls, data: bytes = b"", xid: int = 0) -> bytes:
        return cls._header(ofproto.OFPT_ECHO_REPLY, data, xid=xid)

    # ── OFPT_BARRIER_REPLY (21) ──
    @classmethod
    def barrier_reply(cls, xid: int = 0) -> bytes:
        return cls._header(ofproto.OFPT_BARRIER_REPLY, b"", xid=xid)


# ═══════════════════════════════════════════════════════════════════════════
# Message parsers (incoming: controller → gateway)
# ═══════════════════════════════════════════════════════════════════════════
# 翻译成 Python 字典的形式，方便网关内部处理。
# 翻译成OUTEPUT和EXPERIMENTER的动作列表，方便网关内部处理。
def _parse_actions(buf: bytes, offset: int, actions_len: int) -> List[Dict[str, Any]]:
    """Parse OFPAction* list from action body bytes."""
    actions: List[Dict[str, Any]] = []
    end = offset + actions_len
    while offset + 4 <= end:
        a_type, a_len = struct.unpack_from("!HH", buf, offset)
        if a_len < 4 or offset + a_len > end:
            break
        if a_type == ofproto.OFPAT_OUTPUT and a_len >= 16:
            out_port, max_len = struct.unpack_from("!IH6x", buf, offset + 4)
            actions.append({"type": "OUTPUT", "port": out_port, "max_len": max_len})
        elif a_type == ofproto.OFPAT_EXPERIMENTER:
            exp_id = struct.unpack_from("!I", buf, offset + 4)[0]
            exp_data = buf[offset + 8 : offset + a_len]
            actions.append({"type": "EXPERIMENTER", "experimenter": exp_id,
                            "data": bytes(exp_data)})
        else:
            actions.append({"type": f"UNKNOWN({a_type})", "len": a_len})
        offset += a_len
    return actions

#
def _parse_flow_mod(raw: bytes) -> Optional[Dict[str, Any]]:
    """Parse OFPT_FLOW_MOD → {match, command, priority, actions, ...}."""
    if len(raw) < OFP_HEADER_SIZE + OFP_FLOW_MOD_SIZE0:
        return None
    buf = raw(cookie, cookie_mask, table_id, command, idle_to, hard_to,priority, buffer_id, out_port, out_group, flags) = struct.unpack_from(OFP_FLOW_MOD_PACK_STR0, buf, OFP_HEADER_SIZE)

    # ── Parse OFPMatch (OXM) ──
    m_off = OFP_HEADER_SIZE + OFP_FLOW_MOD_SIZE0
    m_type, m_len = struct.unpack_from("!HH", buf, m_off)
    m_off += 4
    match: Dict[str, Any] = {}
    m_end = OFP_HEADER_SIZE + OFP_FLOW_MOD_SIZE0 + m_len
    while m_off + 4 <= m_end:
        oxm = struct.unpack_from("!I", buf, m_off)[0]
        oxm_class = (oxm >> 16) & 0xFFFF
        field     = (oxm >> 9) & 0x7F
        has_mask  = (oxm >> 8) & 1
        val_len   = oxm & 0xFF
        m_off += 4
        if m_off + val_len > m_end:
            break
        val = buf[m_off : m_off + val_len]
        m_off += val_len
        if has_mask:
            m_off += val_len
        if oxm_class == OFPXMC_OPENFLOW_BASIC:
            if field == OXM_OFB_IN_PORT:
                match["in_port"] = struct.unpack("!I", val)[0] if val_len >= 4 else None
            elif field == OXM_OFB_ETH_TYPE:
                match["eth_type"] = struct.unpack("!H", val)[0] if val_len >= 2 else None
            elif field == 11:
                match["ipv4_src"] = ".".join(str(b) for b in val)
            elif field == 12:
                match["ipv4_dst"] = ".".join(str(b) for b in val)
            elif field == 14:
                match["udp_src"] = struct.unpack("!H", val)[0] if val_len >= 2 else None
            elif field == 15:
                match["udp_dst"] = struct.unpack("!H", val)[0] if val_len >= 2 else None

    # ── Parse instructions ──
    inst_off = OFP_HEADER_SIZE + OFP_FLOW_MOD_SIZE0 + ((m_len + 7) // 8) * 8
    actions: List[Dict[str, Any]] = []
    msg_end = len(buf)
    while inst_off + 4 <= msg_end:
        i_type, i_len = struct.unpack_from("!HH", buf, inst_off)
        if i_len < 4 or inst_off + i_len > msg_end:
            break
        if i_type in (ofproto.OFPIT_APPLY_ACTIONS, ofproto.OFPIT_WRITE_ACTIONS):
            actions += _parse_actions(buf, inst_off + 4, i_len - 4)
        inst_off += i_len

    return {
        "command": command,
        "priority": priority,
        "match": match,
        "actions": actions,
        "cookie": cookie,
        "idle_timeout": idle_to,
        "hard_timeout": hard_to,
    }


def _parse_packet_out(raw: bytes) -> Optional[Dict[str, Any]]:
    """Parse OFPT_PACKET_OUT → {in_port, actions, data}."""
    if len(raw) < OFP_HEADER_SIZE + 16:
        return None
    buf = raw
    buffer_id, in_port, actions_len = struct.unpack_from(
        OFP_PACKET_OUT_PACK_STR, buf, OFP_HEADER_SIZE)
    data_offset = OFP_HEADER_SIZE + 16 + actions_len
    data = bytes(buf[data_offset:]) if data_offset < len(buf) else b""
    actions = _parse_actions(buf, OFP_HEADER_SIZE + 16, actions_len)
    return {"buffer_id": buffer_id, "in_port": in_port, "actions": actions, "data": data}


# ═══════════════════════════════════════════════════════════════════════════
# Fake datapath (for Ryu's ofproto_parser.msg())
# ═══════════════════════════════════════════════════════════════════════════

class _FakeDatapath:
    ofproto = ofproto
    ofproto_parser = ofparser

    def __init__(self, dpid: int):
        self.id = dpid

    def set_xid(self, msg: Any) -> None:
        pass

    def close(self) -> None:
        pass


# ═══════════════════════════════════════════════════════════════════════════
# OF13Client — main class
# ═══════════════════════════════════════════════════════════════════════════

class OF13Client:
    """Lightweight OpenFlow 1.3 switch-side protocol client.

    Usage::

        client = OF13Client(dpid=3, controller_host="127.0.0.1", controller_port=6653)
        client.on_flow_mod = lambda fm: print("FlowMod:", fm)
        client.on_packet_out = lambda po: print("PacketOut:", po)
        client.connect()                            # blocking handshake
        client.send_packet_in(eth_frame_bytes)      # send BLE data
        client.close()
    """

    def __init__(self,
                 dpid: int = 3,
                 controller_host: str = "127.0.0.1",
                 controller_port: int = 6653,
                 hw_addr: str = "00:00:00:00:00:03",
                 n_ports: int = 3,
                 echo_interval: float = 5.0):
        # ── Config ──
        self.dpid = dpid
        self.controller_host = controller_host
        self.controller_port = controller_port
        self.hw_addr = hw_addr
        self.n_ports = n_ports
        self.echo_interval = echo_interval

        # ── State ──
        self.state: str = "INIT"          # INIT → ESTABLISHED
        self.sock: Optional[socket.socket] = None
        self._fake_dp = _FakeDatapath(dpid)
        self._xid: int = 0
        self._running: bool = False
        self._recv_thread: Optional[threading.Thread] = None
        self._send_lock = threading.Lock()
        self._recv_buf = bytearray()
        self._last_echo_rx: float = 0.0

        # ── Callbacks ──
        self.on_flow_mod: Optional[Callable[[Dict[str, Any]], None]] = None
        self.on_packet_out: Optional[Callable[[Dict[str, Any]], None]] = None
        self.on_error: Optional[Callable[[Dict[str, Any]], None]] = None
        self.on_disconnect: Optional[Callable[[], None]] = None

    # ── Public API ────────────────────────────────────────────────────

    def connect(self) -> None:
        """TCP connect + OF 1.3 handshake (blocking, ~100ms).

        Raises OSError / socket.error on failure.
        """
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(5)
        self.sock.connect((self.controller_host, self.controller_port))
        logger.info("TCP connected to %s:%d", self.controller_host, self.controller_port)

        self._handshake()

        self.sock.settimeout(self.echo_interval)
        self._running = True
        self._last_echo_rx = time.monotonic()
        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True,
                                              name="of13-recv")
        self._recv_thread.start()
        logger.info("OF13Client ESTABLISHED (dpid=%d)", self.dpid)

    def close(self) -> None:
        """Graceful disconnect."""
        self._running = False
        if self.sock:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.sock.close()
            self.sock = None
        self.state = "INIT"
        logger.info("OF13Client disconnected")

    def is_connected(self) -> bool:
        return self.state == "ESTABLISHED" and self._running

    def send_packet_in(self, eth_frame: bytes, in_port: int = 1,
                       reason: int = ofproto.OFPR_NO_MATCH) -> None:
        """Send OFPT_PACKET_IN carrying *eth_frame* as payload."""
        if self.state != "ESTABLISHED":
            logger.warning("Cannot send PacketIn: state=%s", self.state)
            return
        msg = OFMessageBuilder.packet_in(eth_frame, in_port=in_port, reason=reason)
        self._send_raw(msg)
        logger.debug("PacketIn sent: in_port=%d, frame_len=%d", in_port, len(eth_frame))

    # ── Internal: handshake ───────────────────────────────────────────

    def _handshake(self) -> None:
        """Blocking OF 1.3 Hello → FeaturesRequest → FeaturesReply."""
        # 1. Send Hello
        self._send_raw(OFMessageBuilder.hello())
        self.state = "HELLO_SENT"

        # 2. Wait for controller Hello
        msg_type, xid, body = self._recv_one(timeout=5)
        if msg_type != ofproto.OFPT_HELLO:
            raise ConnectionError(f"Expected HELLO (0), got type={msg_type}")
        logger.debug("Received controller HELLO")

        # 3. Wait for FeaturesRequest
        msg_type, xid, body = self._recv_one(timeout=5)
        if msg_type != ofproto.OFPT_FEATURES_REQUEST:
            raise ConnectionError(
                f"Expected FEATURES_REQUEST (5), got type={msg_type}")

        # 4. Send FeaturesReply
        ports_bin = b""
        for i in range(1, self.n_ports + 1):
            ports_bin += OFMessageBuilder.port_desc(i, self.hw_addr)
        msg = OFMessageBuilder.features_reply(self.dpid, ports_bin)
        # Reuse controller's xid
        msg = msg[:4] + struct.pack("!I", xid) + msg[8:]
        self._send_raw(msg)
        self.state = "ESTABLISHED"

    # ── Internal: raw I/O ─────────────────────────────────────────────

    def _send_raw(self, data: bytes) -> None:
        if not self.sock:
            return
        with self._send_lock:
            self.sock.sendall(data)

    def _recv_exact(self, n: int, timeout: float = 5.0) -> Optional[bytes]:
        """Read exactly *n* bytes or None on timeout/EOF."""
        if not self.sock:
            return None
        data = b""
        deadline = time.monotonic() + timeout
        while len(data) < n:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                self.sock.settimeout(remaining)
                chunk = self.sock.recv(n - len(data))
                if not chunk:
                    return None
                data += chunk
            except socket.timeout:
                return None
        return data

    def _recv_one(self, timeout: float = 5.0) -> tuple:
        """Read one OF message → (msg_type, xid, body_bytes).

        Raises socket.timeout if no message within *timeout*.
        """
        hdr = self._recv_exact(8, timeout)
        if hdr is None:
            raise socket.timeout("No OF message received")
        version, msg_type, msg_len, xid = struct.unpack(OFP_HEADER_PACK_STR, hdr)
        if msg_len < 8:
            raise ConnectionError(f"Invalid msg_len={msg_len}")
        body = b""
        if msg_len > 8:
            body_data = self._recv_exact(msg_len - 8, timeout)
            if body_data is None:
                raise ConnectionError("Incomplete message body")
            body = body_data
        return msg_type, xid, body

    # ── Internal: receive loop ────────────────────────────────────────

    def _recv_loop(self) -> None:
        """Background thread: read, reassemble, dispatch OF messages."""
        while self._running and self.sock:
            try:
                data = self.sock.recv(4096)
                if not data:
                    logger.error("Controller closed connection")
                    break
                self._recv_buf.extend(data)
                self._process_buf()
            except socket.timeout:
                self._check_keepalive()
                continue
            except (ConnectionResetError, BrokenPipeError, OSError) as e:
                logger.error("OF recv error: %s", e)
                break
        # ── Disconnected ──
        self._running = False
        self.state = "INIT"
        if self.on_disconnect:
            self.on_disconnect()

    def _process_buf(self) -> None:
        """Extract complete messages from receive buffer."""
        while len(self._recv_buf) >= OFP_HEADER_SIZE:
            version, msg_type, msg_len, xid = struct.unpack_from(
                OFP_HEADER_PACK_STR, self._recv_buf, 0)
            if msg_len < OFP_HEADER_SIZE:
                logger.warning("Bad msg_len=%d — clearing buffer", msg_len)
                self._recv_buf.clear()
                return
            if len(self._recv_buf) < msg_len:
                return                        # wait for more data
            raw = bytes(self._recv_buf[:msg_len])
            del self._recv_buf[:msg_len]
            self._dispatch(msg_type, xid, raw)

    def _check_keepalive(self) -> None:
        """Send echo request if no controller echo seen recently."""
        now = time.monotonic()
        if now - self._last_echo_rx > self.echo_interval * 3:
            logger.warning("OF echo timeout — connection lost")
            self._running = False

    # ── Internal: message dispatch ────────────────────────────────────

    def _dispatch(self, msg_type: int, xid: int, raw: bytes) -> None:
        """Route parsed message to the appropriate handler."""
        if msg_type == ofproto.OFPT_ECHO_REQUEST:
            self._send_raw(OFMessageBuilder.echo_reply(
                data=raw[OFP_HEADER_SIZE:], xid=xid))
            self._last_echo_rx = time.monotonic()

        elif msg_type == ofproto.OFPT_ECHO_REPLY:
            self._last_echo_rx = time.monotonic()

        elif msg_type == ofproto.OFPT_FLOW_MOD:
            fm = _parse_flow_mod(raw)
            if fm and self.on_flow_mod:
                self.on_flow_mod(fm)

        elif msg_type == ofproto.OFPT_PACKET_OUT:
            po = _parse_packet_out(raw)
            if po and self.on_packet_out:
                self.on_packet_out(po)

        elif msg_type == ofproto.OFPT_ERROR:
            logger.warning("OF ERROR: type=%s", raw[OFP_HEADER_SIZE:].hex())
            if self.on_error:
                self.on_error({"raw": raw})

        elif msg_type == ofproto.OFPT_BARRIER_REQUEST:
            self._send_raw(OFMessageBuilder.barrier_reply(xid=xid))

        elif msg_type == ofproto.OFPT_EXPERIMENTER:
            logger.debug("OFPT_EXPERIMENTER received (len=%d)", len(raw))

        else:
            logger.debug("Unhandled OF msg type=%d len=%d", msg_type, len(raw))


# ═══════════════════════════════════════════════════════════════════════════
# FlowTable — 本地流表引擎
# ═══════════════════════════════════════════════════════════════════════════

# Action names (gateway-specific)
ACT_FORWARD    = "FORWARD"      # forward data to a specific IP
ACT_DROP       = "DROP"         # silently discard
ACT_CONTROLLER = "CONTROLLER"   # send PacketIn to controller
ACT_FLOOD      = "FLOOD"        # forward to all known hosts


class FlowEntry:
    """本地流表条目 — match 条件 + actions + 统计计数器."""

    __slots__ = (
        "match", "actions", "priority", "cookie",
        "idle_timeout", "hard_timeout", "table_id",
        "created_at", "last_used", "packet_count", "byte_count",
    )

    def __init__(self,
                 match: Dict[str, Any],
                 actions: List[Dict[str, Any]],
                 priority: int = 0,
                 cookie: int = 0,
                 idle_timeout: int = 0,
                 hard_timeout: int = 0,
                 table_id: int = 0):
        self.match = match
        self.actions = actions
        self.priority = priority
        self.cookie = cookie
        self.idle_timeout = idle_timeout
        self.hard_timeout = hard_timeout
        self.table_id = table_id
        self.created_at = time.monotonic()
        self.last_used = self.created_at
        self.packet_count = 0
        self.byte_count = 0

    def is_expired(self, now: float) -> bool:
        if self.hard_timeout and (now - self.created_at) > self.hard_timeout:
            return True
        if self.idle_timeout and (now - self.last_used) > self.idle_timeout:
            return True
        return False

    def hit(self, byte_count: int = 0) -> None:
        self.last_used = time.monotonic()
        self.packet_count += 1
        self.byte_count += byte_count

    def __repr__(self) -> str:
        return (f"FlowEntry(prio={self.priority}, match={self.match}, "
                f"actions={self.actions}, pkts={self.packet_count})")


class FlowTable:
    """本地 OpenFlow 风格流表 — 支持 match/lookup/expire/dump.

    用法::

        ft = FlowTable()
        ft.add(FlowEntry(match={"ble_addr": "aa:bb:cc:dd:ee:01"},
                         actions=[{"type": "FORWARD", "ip": "192.168.1.20"}],
                         priority=100, idle_timeout=60))
        entry = ft.lookup(ble_addr="aa:bb:cc:dd:ee:01", data_type="temp")
        if entry:
            entry.hit()
            execute_actions(entry.actions)
        else:
            send_packet_in(...)
    """

    def __init__(self, max_entries: int = 1024):
        self._entries: List[FlowEntry] = []
        self._lock = threading.Lock()
        self.max_entries = max_entries
        self._last_expire: float = time.monotonic()

    # ── CRUD ──

    def add(self, entry: FlowEntry) -> None:
        """插入或更新一条流表项（按 cookie + match 去重）。"""
        with self._lock:
            # Dedup: same cookie + same match → replace
            for i, existing in enumerate(self._entries):
                if existing.cookie == entry.cookie and existing.match == entry.match:
                    self._entries[i] = entry
                    return
            # New entry
            self._entries.append(entry)
            # Sort by priority descending (highest prio first)
            self._entries.sort(key=lambda e: e.priority, reverse=True)
            # Cull if over max
            if len(self._entries) > self.max_entries:
                self._entries = self._entries[:self.max_entries]

    def delete(self, cookie: int = 0, match: Optional[Dict] = None,
               strict: bool = False) -> int:
        """删除匹配的流表项，返回删除数量."""
        removed = 0
        with self._lock:
            keep = []
            for e in self._entries:
                cookie_match = (cookie == 0 or e.cookie == cookie)
                match_match = (match is None or e.match == match)
                if strict:
                    if cookie_match and match_match:
                        removed += 1
                        continue
                else:
                    # Non-strict: delete-params must be a subset of entry's match
                    if match and all(
                        k in e.match and e.match[k] == v
                        for k, v in match.items()
                    ):
                        removed += 1
                        continue
                keep.append(e)
            self._entries = keep
        return removed

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    # ── Lookup ──

    def lookup(self, **fields) -> Optional[FlowEntry]:
        """用 BLE/网络字段查找最高优先级匹配的流表项.

        支持字段: ble_addr, data_type, dst_ip, in_port, udp_dport.

        返回 None 表示 table-miss → 需发 PacketIn.
        """
        now = time.monotonic()
        self._maybe_expire(now)
        with self._lock:
            for entry in self._entries:
                if _match_subset(fields, entry.match):
                    return entry
        return None

    # ── Maintenance ──

    def _maybe_expire(self, now: float) -> None:
        """每 1 秒批量清理过期条目."""
        if now - self._last_expire < 1.0:
            return
        self._last_expire = now
        with self._lock:
            self._entries = [e for e in self._entries if not e.is_expired(now)]

    def expire(self) -> int:
        """手动清理过期条目，返回清理数量."""
        now = time.monotonic()
        before = len(self._entries)
        with self._lock:
            self._entries = [e for e in self._entries if not e.is_expired(now)]
        self._last_expire = now
        return before - len(self._entries)

    def dump(self) -> List[FlowEntry]:
        """返回当前流表快照（最高优先级在前）."""
        with self._lock:
            return list(self._entries)

    def stats(self) -> Dict[str, Any]:
        """流表统计."""
        with self._lock:
            return {
                "total_entries": len(self._entries),
                "total_packets": sum(e.packet_count for e in self._entries),
                "total_bytes": sum(e.byte_count for e in self._entries),
            }

    def __len__(self) -> int:
        return len(self._entries)

# 检查 candidate 是否匹配 pattern（pattern 中 None 或缺失的 key → 通配）
# 判断上是上行还是本地处理
# 只要有一条规则返回 True，网关就走本地快车道（执行该规则的动作，如转发）。
# 如果所有规则都返回 False，网关就走上报通道（发送 Packet-In 给控制器）。
def _match_subset(candidate: Dict[str, Any], pattern: Dict[str, Any]) -> bool:
    """检查 *candidate* 是否匹配 *pattern*.

    - pattern 中值为 None 或不存在的 key → 通配, 匹配任意值
    - candidate 中缺少 pattern 要求的 key → 不匹配
    - 所有存在的 key 必须相等
    """
    if not pattern:
        return False       # 空 match 不匹配任何包（保护性默认）
    for k, pat_val in pattern.items():
        cand_val = candidate.get(k)
        if cand_val == pat_val:
            continue
        if pat_val is None:
            continue
        return False
    return True


# ═══════════════════════════════════════════════════════════════════════════
# Ethernet frame helper — craft frames that match controller's PacketIn path
# ═══════════════════════════════════════════════════════════════════════════

def build_ble_packet_in_frame(src_mac: str,
                              src_ip: str,
                              dst_ip: str,
                              ble_addr: str,
                              data_type: str,
                              data_value: str,
                              udp_sport: int = 5005,
                              udp_dport: int = 5005) -> bytes:
    """Build an Ethernet/IP/UDP frame carrying BLE sensor data.

    The controller's ``PacketProcessor._packet_in_handler`` parses
    Ethernet → IP → UDP(dst=5005) → payload string, so this frame
    exactly mimics what an OVS switch would forward.

    Args:
        src_mac: Gateway MAC (e.g. '00:00:00:00:00:03')
        src_ip:  Gateway IP   (e.g. '192.168.1.12')
        dst_ip:  Destination  (e.g. '192.168.1.20' for h1)
        ble_addr, data_type, data_value: BLE sensor fields
        udp_sport, udp_dport: UDP ports (both 5005)

    Returns:
        Serialized Ethernet frame bytes.
    """
    payload = f"{ble_addr},{data_type},{data_value}".encode("utf-8")

    eth = ethernet.ethernet(
        dst="ff:ff:ff:ff:ff:ff",
        src=src_mac,
        ethertype=0x0800,
    )
    ip = ipv4.ipv4(
        src=src_ip,
        dst=dst_ip,
        proto=17,          # UDP
        ttl=64,
    )
    u = udp.udp(src_port=udp_sport, dst_port=udp_dport)

    pkt = ryu_packet.Packet()
    pkt.add_protocol(eth)
    pkt.add_protocol(ip)
    pkt.add_protocol(u)
    pkt.add_protocol(payload)
    pkt.serialize()
    return pkt.data


# ═══════════════════════════════════════════════════════════════════════════
# Self-test (run as `python3 ofproto_client.py`)
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # ── Test message builders ──
    print("=== OFMessageBuilder Tests ===")

    hello = OFMessageBuilder.hello()
    print(f"Hello: {len(hello)} bytes → {hello.hex()}")

    fr = OFMessageBuilder.features_reply(3, OFMessageBuilder.port_desc(1, "00:00:00:00:00:03"))
    print(f"FeaturesReply: {len(fr)} bytes")

    hdr = struct.unpack(OFP_HEADER_PACK_STR, fr[:8])
    print(f"  header: version={hdr[0]}, type={hdr[1]}, len={hdr[2]}")

    frame = build_ble_packet_in_frame("00:00:00:00:00:03", "192.168.1.12", "192.168.1.20","aa:bb:cc:dd:ee:01", "temp", "25.3")
    print(f"BLE frame: {len(frame)} bytes")

    pi = OFMessageBuilder.packet_in(frame, in_port=1)
    hdr = struct.unpack(OFP_HEADER_PACK_STR, pi[:8])
    print(f"PacketIn: {len(pi)} bytes, type={hdr[1]}(OFPT_PACKET_IN=10)")

    # ── Test FlowMod parser ──
    print("\n=== FlowMod Parser Test ===")
    # Build a minimal FlowMod → parse it back
    fm_body = struct.pack(OFP_FLOW_MOD_PACK_STR0,
                          0, 0, 0, ofproto.OFPFC_ADD, 60, 0,
                          100, ofproto.OFP_NO_BUFFER, ofproto.OFPP_ANY,
                          ofproto.OFPG_ANY, 0)
    match = _build_match(in_port=1)
    fm_raw = struct.pack(OFP_HEADER_PACK_STR, OFP_VERSION,
                          ofproto.OFPT_FLOW_MOD,
                          OFP_HEADER_SIZE + OFP_FLOW_MOD_SIZE0 + len(match),
                          1) + fm_body + match
    parsed = _parse_flow_mod(fm_raw)
    print(f"  parsed: command={parsed['command']}, priority={parsed['priority']}")
    print(f"  match: {parsed['match']}")

    # ── Test PacketOut parser ──
    print("\n=== PacketOut Parser Test ===")
    actions_bin = struct.pack("!HHIH", ofproto.OFPAT_OUTPUT, 16, 2, 0xFFFF)
    po_hdr = struct.pack(OFP_PACKET_OUT_PACK_STR,
                          ofproto.OFP_NO_BUFFER, ofproto.OFPP_CONTROLLER,
                          len(actions_bin))
    po_raw = struct.pack(OFP_HEADER_PACK_STR, OFP_VERSION,
                          ofproto.OFPT_PACKET_OUT,
                          OFP_HEADER_SIZE + 16 + len(actions_bin) + 4,
                          2) + po_hdr + actions_bin + b"data"
    parsed_po = _parse_packet_out(po_raw)
    print(f"  actions: {parsed_po['actions']}")
    print(f"  data: {parsed_po['data']}")

    # ── Test FlowTable ──
    print("\n=== FlowTable Tests ===")
    ft = FlowTable()

    # Add flows
    ft.add(FlowEntry(
        match={"ble_addr": "aa:bb:cc:dd:ee:01", "data_type": "temp"},
        actions=[{"type": "FORWARD", "ip": "192.168.1.20"}],
        priority=100, idle_timeout=60))
    ft.add(FlowEntry(
        match={"ble_addr": "aa:bb:cc:dd:ee:02"},
        actions=[{"type": "FORWARD", "ip": "192.168.1.21"}],
        priority=50, idle_timeout=60))
    ft.add(FlowEntry(
        match={"data_type": "gas"},
        actions=[{"type": "FORWARD", "ip": "192.168.1.20"}],
        priority=200))          # high priority catch-all for gas
    print(f"  Added 3 entries, ft len={len(ft)}")

    # Test exact match
    e = ft.lookup(ble_addr="aa:bb:cc:dd:ee:01", data_type="temp")
    assert e is not None, "should match temp entry"
    print(f"  lookup(temp): {e}")

    # Test wildcard match (data_type not in pattern → matches)
    e = ft.lookup(ble_addr="aa:bb:cc:dd:ee:02", data_type="humidity")
    assert e is not None and e.priority == 50, f"should match ee:02 entry, got {e}"
    print(f"  lookup(humidity): {e}")

    # Test priority ordering: gas matches higher-prio entry
    e = ft.lookup(ble_addr="aa:bb:cc:dd:ee:01", data_type="gas")
    assert e is not None and e.priority == 200, f"gas should win, got {e}"
    print(f"  lookup(gas): {e} (prio={e.priority}) — highest priority wins")

    # Test miss
    e = ft.lookup(ble_addr="ff:ff:ff:ff:ff:ff", data_type="light")
    assert e is None, f"should be miss, got {e}"
    print(f"  lookup(unknown): None — table miss ✓")

    # Test stats
    s = ft.stats()
    print(f"  stats: total={s['total_entries']}, pkts={s['total_packets']}, bytes={s['total_bytes']}")

    # Test delete
    removed = ft.delete(match={"ble_addr": "aa:bb:cc:dd:ee:01"})
    print(f"  delete(ee:01): removed={removed}, ft len={len(ft)}")

    # Test clear
    ft.clear()
    assert len(ft) == 0
    print(f"  clear: ft len={len(ft)}")

    print("\nAll self-tests passed ✓")
