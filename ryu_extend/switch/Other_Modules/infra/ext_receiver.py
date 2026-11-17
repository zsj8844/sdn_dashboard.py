"""控制器侧 IoT 扩展信息接收器。

网关把编码后的属性 JSON 发给控制器。支持两种通道：
  - UDP 6650
  - Unix datagram socket（默认 /tmp/sdn_iot_ext.sock）

Unix socket 用于 Mininet：网关在 iot3 命名空间里，127.0.0.1 不是宿主机，
而文件系统是共享的，走 Unix socket 最稳。

收到消息后：
  1. 记录最近一条消息；
  2. 交给回调（通常用于推到 Web 面板）。
"""

import json
import logging
import os
import select
import socket
import threading
import time

logger = logging.getLogger(__name__)


class UDPExtensionReceiver:
    """UDP + 可选 Unix socket 接收器。"""

    def __init__(self, host='0.0.0.0', port=6650, unix_path=None,
                 on_message=None):
        self.host = host
        self.port = port
        self.unix_path = unix_path
        self.on_message = on_message
        self.last_message = None
        self.received = 0
        self._udp_sock = None
        self._unix_sock = None
        self._thread = None
        self._running = False

    def start(self):
        """启动后台接收线程（非阻塞）。"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._serve, name='iot-ext-receiver', daemon=True)
        self._thread.start()

    def _open_udp(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.host, self.port))
        sock.setblocking(False)
        logger.info("IoT扩展接收器已启动: udp://%s:%d", self.host, self.port)
        return sock

    def _open_unix(self):
        if not self.unix_path:
            return None
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            os.unlink(self.unix_path)
        except FileNotFoundError:
            pass
        sock.bind(self.unix_path)
        os.chmod(self.unix_path, 0o666)
        sock.setblocking(False)
        logger.info("IoT扩展接收器已启动: unix://%s", self.unix_path)
        return sock

    def _serve(self):
        try:
            self._udp_sock = self._open_udp()
        except OSError as exc:
            logger.warning("UDP 扩展接收器启动失败 (%s:%d): %s",
                           self.host, self.port, exc)
            self._running = False
            return

        try:
            self._unix_sock = self._open_unix()
        except OSError as exc:
            logger.warning("Unix 扩展接收器启动失败 (%s): %s",
                           self.unix_path, exc)
            self._unix_sock = None

        socks = [s for s in (self._udp_sock, self._unix_sock) if s]
        while self._running:
            try:
                readable, _, _ = select.select(socks, [], [], 1.0)
            except (OSError, ValueError):
                break
            for sock in readable:
                try:
                    data, addr = sock.recvfrom(65535)
                except OSError:
                    continue
                if sock is self._unix_sock:
                    addr = ('unix', 0)
                self._handle(data, addr)

        for sock in socks:
            try:
                sock.close()
            except OSError:
                pass
        if self.unix_path:
            try:
                os.unlink(self.unix_path)
            except OSError:
                pass
        logger.info("IoT扩展接收器已停止")

    def _handle(self, data, addr):
        try:
            message = json.loads(data.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.warning("忽略非法扩展消息 (%s): %s", addr, exc)
            return

        if not isinstance(message, dict):
            logger.warning("忽略非对象扩展消息 (%s): %r", addr, message)
            return

        message['_source'] = f"{addr[0]}:{addr[1]}"
        message['_received_at'] = time.time()
        self.last_message = message
        self.received += 1
        logger.info("收到IoT扩展信息: %s", message)

        if self.on_message:
            try:
                self.on_message(message)
            except Exception:
                logger.exception("处理IoT扩展信息失败")

    def stop(self):
        """停止接收线程。"""
        self._running = False
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2)


__all__ = ['UDPExtensionReceiver']
