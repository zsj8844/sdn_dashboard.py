#!/usr/bin/env python3
"""端到端测试：注入器 → 网关 → Unix socket → 控制器接收器。

不需要 root、Mininet 或真实 BLE 硬件。
"""

import os
import subprocess
import sys
import threading
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SWITCH_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
PROJECT_DIR = os.path.abspath(os.path.join(SWITCH_DIR, '..', '..'))
GATEWAY_DIR = os.path.join(PROJECT_DIR, 'gateway')

sys.path.insert(0, SWITCH_DIR)
sys.path.insert(0, GATEWAY_DIR)

from Other_Modules.infra.ext_receiver import UDPExtensionReceiver  # noqa: E402
from iot_gateway_enhanced import IoTGatewayEnhanced  # noqa: E402

SOCKET_PATH = '/tmp/test_sdn_ble_e2e.sock'
GATEWAY_PORT = 15055
RECEIVER_PORT = 16655


def wait_for(predicate, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def main():
    received = []
    receiver = UDPExtensionReceiver(
        host='127.0.0.1', port=RECEIVER_PORT,
        unix_path=SOCKET_PATH, on_message=received.append)
    receiver.start()
    time.sleep(0.3)

    os.environ['SDN_EXT_SOCKET'] = SOCKET_PATH
    os.environ['SDN_EXT_TRANSPORT'] = 'auto'

    gateway = IoTGatewayEnhanced(
        listen_port=GATEWAY_PORT, target_port=GATEWAY_PORT,
        controller_ip='127.0.0.1', controller_port=RECEIVER_PORT)
    gateway.running = True

    worker = None
    try:
        if not gateway._init_listen_socket():
            print('网关监听失败', file=sys.stderr)
            return 1

        worker = threading.Thread(
            target=gateway.handle_received_data, daemon=True)
        worker.start()

        proc = subprocess.run(
            [sys.executable, os.path.join(GATEWAY_DIR, 'ble_injector.py'),
             '--target', '127.0.0.1', '--port', str(GATEWAY_PORT),
             '--count', '3', '--once'],
            capture_output=True, text=True)

        ok = wait_for(lambda: len(received) >= 3)

        print(f'injector rc = {proc.returncode}')
        for message in received:
            print(' ', message.get('ble_addr'), message.get('sensor_type'),
                  'priority=', message.get('device_priority'),
                  'route=', message.get('route_select'))

        assert proc.returncode == 0, proc.stderr
        assert ok, f'只收到 {len(received)} 条'
        assert len(received) == 3, f'收到 {len(received)} 条'
        assert {m['sensor_type'] for m in received} == {
            'temp', 'humidity', 'pos'}
        assert all(m.get('extension_data') for m in received)
        print('BLE chain E2E PASS')
        return 0
    finally:
        gateway.running = False
        if gateway.listen_socket is not None:
            try:
                gateway.listen_socket.close()
            except OSError:
                pass
        if worker is not None:
            worker.join(timeout=1)
        receiver.stop()
        os.environ.pop('SDN_EXT_SOCKET', None)
        os.environ.pop('SDN_EXT_TRANSPORT', None)


if __name__ == '__main__':
    sys.exit(main())
