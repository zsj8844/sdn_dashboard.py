#!/usr/bin/env python3
"""最小闭环测试：统一优先级 + UDP 扩展接收 + 网关编码。"""

import json
import os
import socket
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SWITCH_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
PROJECT_DIR = os.path.abspath(os.path.join(SWITCH_DIR, '..', '..'))
GATEWAY_DIR = os.path.join(PROJECT_DIR, 'gateway')

sys.path.insert(0, SWITCH_DIR)
sys.path.insert(0, GATEWAY_DIR)

from extensions.priority import (  # noqa: E402
    calculate_priority, normalize_sensor_type, select_route,
)
from Other_Modules.infra.ext_receiver import UDPExtensionReceiver  # noqa: E402


def check(name, condition, detail=''):
    status = 'PASS' if condition else 'FAIL'
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ''))
    if not condition:
        raise AssertionError(name)


def test_priority():
    check('温度正常 -> 2', calculate_priority('temp', 22) == 2)
    check('温度偏高 -> 4', calculate_priority('temp', 31) == 4)
    check('温度过高 -> 5', calculate_priority('temp', 36) == 5)
    check('湿度高 -> 5', calculate_priority('humidity', 85) == 5)
    check('气体固定 -> 5', calculate_priority('gas', 1) == 5)
    check('位置默认 -> 2', calculate_priority('pos', '(1.2,3.4)') == 2)
    check('别名 temperature', normalize_sensor_type('temperature') == 'temp')
    check('高优先级走 route_b', select_route(4) == 'route_b')
    check('低优先级走 route_a', select_route(3) == 'route_a')


def wait_for(received, timeout=2):
    deadline = time.time() + timeout
    while not received and time.time() < deadline:
        time.sleep(0.05)


def test_receiver():
    received = []
    receiver = UDPExtensionReceiver(host='127.0.0.1', port=16650,
                                    on_message=received.append)
    receiver.start()
    time.sleep(0.3)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(json.dumps({
        'ble_addr': 'aa:bb:cc:dd:ee:01',
        'sensor_type': 'temp',
        'device_priority': 4,
    }).encode(), ('127.0.0.1', 16650))
    sock.close()

    wait_for(received)
    receiver.stop()

    check('UDP 6650 接收', len(received) == 1, f'收到 {len(received)} 条')
    check('消息内容完整', received[0].get('sensor_type') == 'temp')
    check('附加来源字段', '_source' in received[0])


def test_receiver_unix():
    path = '/tmp/test_sdn_ext_receiver.sock'
    received = []
    receiver = UDPExtensionReceiver(host='127.0.0.1', port=16651,
                                    unix_path=path,
                                    on_message=received.append)
    receiver.start()
    time.sleep(0.3)

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    sock.sendto(json.dumps({'sensor_type': 'humidity'}).encode(), path)
    sock.close()

    wait_for(received)
    receiver.stop()

    check('Unix socket 接收', len(received) == 1, f'收到 {len(received)} 条')
    check('Unix 来源标记', received[0].get('_source') == 'unix:0')


def test_flow_manager_cache():
    from collections import defaultdict

    from ryu.ofproto import ofproto_v1_3 as ofp
    from ryu.ofproto import ofproto_v1_3_parser as parser

    from Other_Modules.infra.flow_manager import FlowManager

    class FakeDatapath:
        id = 1
        ofproto = ofp
        ofproto_parser = parser

        def send_msg(self, msg):
            pass

    manager = FlowManager(defaultdict(dict))
    datapath = FakeDatapath()
    match = parser.OFPMatch(eth_type=0x0800, ipv4_dst='192.168.1.20')

    manager.add_flow(datapath, 100, match,
                     [parser.OFPActionOutput(2)])
    check('add_flow 写入缓存', len(manager.get_flows(1, 0)) == 1)

    manager.add_flow(datapath, 100, match,
                     [parser.OFPActionOutput(2)])
    check('重复 add 不重复记录', len(manager.get_flows(1, 0)) == 1)

    old_action = manager.get_flows(1, 0)[0]['actions'][0]
    manager.modify_flow(datapath, 100, match,
                        [parser.OFPActionOutput(3)])
    flows = manager.get_flows(1, 0)
    check('modify_flow 更新缓存',
          len(flows) == 1 and flows[0]['actions'][0] != old_action)

    manager.delete_flow(datapath, match=match, priority=100)
    check('delete_flow 清理缓存', manager.get_flows(1, 0) == [])
    check('未知交换机返回空', manager.get_flows(9) == [])


def test_gateway_encode():
    from iot_gateway_enhanced import IoTGatewayEnhanced

    gateway = IoTGatewayEnhanced(controller_ip='127.0.0.1')
    info = gateway.encode_openflow_extension(
        'aa:bb:cc:dd:ee:01', 'temp', '36.5')

    check('网关编码成功', info is not None)
    check('优先级与控制器一致', info['device_priority'] == 5,
          f"priority={info['device_priority']}")
    check('路由随优先级变化', info['route_select'] == 'route_b')
    check('Experimenter 数据非空', bool(info['extension_data']))


def test_gateway_to_unix():
    path = '/tmp/test_gw_ext.sock'
    received = []
    receiver = UDPExtensionReceiver(host='127.0.0.1', port=16652,
                                    unix_path=path,
                                    on_message=received.append)
    receiver.start()
    time.sleep(0.3)

    os.environ['SDN_EXT_SOCKET'] = path
    os.environ['SDN_EXT_TRANSPORT'] = 'auto'
    try:
        from iot_gateway_enhanced import IoTGatewayEnhanced

        gateway = IoTGatewayEnhanced(controller_ip='127.0.0.1',
                                     controller_port=16652)
        gateway._process_received_data(
            b'aa:bb:cc:dd:ee:02,humidity,85', ('127.0.0.1', 1))
        wait_for(received)
    finally:
        os.environ.pop('SDN_EXT_SOCKET', None)
        os.environ.pop('SDN_EXT_TRANSPORT', None)
        receiver.stop()

    check('网关 → Unix socket', len(received) == 1,
          f'收到 {len(received)} 条')
    check('网关优先级=5', received[0].get('device_priority') == 5)
    check('网关路由=route_b', received[0].get('route_select') == 'route_b')


def main():
    print('=' * 60)
    print('IoT 扩展链路测试')
    print('=' * 60)
    test_priority()
    test_receiver()
    test_receiver_unix()
    test_gateway_encode()
    test_gateway_to_unix()
    test_flow_manager_cache()
    print('=' * 60)
    print('全部通过')
    return 0


if __name__ == '__main__':
    sys.exit(main())
