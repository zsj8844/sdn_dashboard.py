#!/usr/bin/env python3
"""无硬件 BLE 数据注入器。

模拟若干 BLE 传感器，按网关现有格式往 UDP 5005 发送：

    <ble_addr>,<sensor_type>,<value>

用途：在没有 BLE dongle / 真实传感器时，先把
网关 -> SDN -> 控制器 的链路跑通。
"""

import argparse
import os
import random
import socket
import sys
import time

DEFAULT_TARGET = os.environ.get('SDN_GATEWAY_IP', '192.168.1.12')
DEFAULT_PORT = 5005

DEVICE_PROFILES = [
    {
        'addr': 'aa:bb:cc:dd:ee:01',
        'type': 'temp',
        'label': 'iot1 温度',
        'range': (20.0, 40.0),
        'decimals': 1,
    },
    {
        'addr': 'aa:bb:cc:dd:ee:02',
        'type': 'humidity',
        'label': 'iot2 湿度',
        'range': (40.0, 85.0),
        'decimals': 1,
    },
    {
        'addr': 'aa:bb:cc:dd:ee:04',
        'type': 'pos',
        'label': 'iot4 位置',
        'range': (-90.0, 90.0),
        'decimals': 2,
    },
    {
        'addr': 'aa:bb:cc:dd:ee:05',
        'type': 'gas',
        'label': '气体',
        'range': (0.0, 100.0),
        'decimals': 1,
    },
    {
        'addr': 'aa:bb:cc:dd:ee:06',
        'type': 'motion',
        'label': '移动',
        'range': (0, 1),
        'decimals': 0,
    },
]


def make_value(profile):
    """按设备类型生成一个模拟值。"""
    low, high = profile['range']

    if profile['type'] == 'pos':
        lat = round(random.uniform(low, high), profile['decimals'])
        lon = round(random.uniform(low, high), profile['decimals'])
        return f"({lat},{lon})"

    if profile['type'] == 'motion':
        return random.randint(int(low), int(high))

    return round(random.uniform(low, high), profile['decimals'])


def build_packet(profile):
    """返回网关期望的文本格式。"""
    return f"{profile['addr']},{profile['type']},{make_value(profile)}"


def main():
    parser = argparse.ArgumentParser(description='模拟 BLE 传感器数据并发送到 IoT 网关')
    parser.add_argument('--target', default=DEFAULT_TARGET,
                        help=f'网关 IP（默认 {DEFAULT_TARGET}）')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT,
                        help=f'网关 UDP 端口（默认 {DEFAULT_PORT}）')
    parser.add_argument('--count', type=int, default=3,
                        help='使用前 N 个设备配置（默认 3）')
    parser.add_argument('--interval', type=float, default=2.0,
                        help='每轮发送间隔秒数（默认 2）')
    parser.add_argument('--once', action='store_true',
                        help='只发送一轮后退出')
    parser.add_argument('--dry-run', action='store_true',
                        help='只打印，不真正发送')
    args = parser.parse_args()

    if args.count <= 0:
        print('--count 必须大于 0', file=sys.stderr)
        return 2

    profiles = DEVICE_PROFILES[:args.count]
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sent = 0
    failed = 0

    print(f"目标网关: {args.target}:{args.port}")
    print(f"模拟设备: {', '.join(p['label'] for p in profiles)}")
    print(f"模式: {'dry-run' if args.dry_run else 'UDP 发送'}"
          f"{'，单轮' if args.once else f'，每 {args.interval}s 一轮'}")
    print('-' * 60)

    try:
        while True:
            for profile in profiles:
                packet = build_packet(profile)
                if args.dry_run:
                    print(f"[DRY-RUN] {packet}")
                    sent += 1
                else:
                    try:
                        sock.sendto(packet.encode('utf-8'),
                                    (args.target, args.port))
                        print(f"[SEND] {packet}")
                        sent += 1
                    except OSError as exc:
                        print(f"[ERROR] 发送失败: {exc}", file=sys.stderr)
                        failed += 1

            if args.once:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print('\n已中断')
    finally:
        sock.close()

    print('-' * 60)
    print(f'共发送 {sent} 条' + (f'，失败 {failed} 条' if failed else ''))
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
