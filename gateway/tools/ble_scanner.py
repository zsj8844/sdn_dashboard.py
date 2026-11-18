#!/usr/bin/env python3
"""宿主机 BLE 广播扫描器（可选，需要 bleak）。

扫描真实 BLE 广播，转换成网关现有的文本格式，再通过 UDP 发到 5005：

    <ble_addr>,<sensor_type>,<value>

注意：广播载荷是厂商自定义的。下面的 parse_advertisement() 只是一个
通用示例（把载荷当成 UTF-8 的 "type,value"），接真实传感器时需要按
厂商协议修改解析逻辑。

依赖：
    pip install bleak
Linux 还需要 BlueZ (>=5.55) 和可用的蓝牙适配器。
"""

import argparse
import asyncio
import os
import socket
import sys
import time

try:
    from bleak import BleakScanner
except ImportError:  # pragma: no cover - 取决于是否安装可选依赖
    BleakScanner = None

DEFAULT_TARGET = os.environ.get('SDN_GATEWAY_IP', '192.168.1.12')
DEFAULT_PORT = 5005


def parse_advertisement(advertisement):
    """从广播数据中提取 (sensor_type, value)。

    默认策略：
      1. 优先取 manufacturer_data 的第一段
      2. 其次取 service_data 的第一段
      3. 把字节按 UTF-8 解码，要求格式为 "type,value"

    返回值 None 表示这条广播不按当前策略处理。
    真实项目应在这里按传感器厂商协议解析二进制字段。
    """
    payload = None
    if advertisement.manufacturer_data:
        payload = next(iter(advertisement.manufacturer_data.values()))
    elif advertisement.service_data:
        payload = next(iter(advertisement.service_data.values()))

    if not payload:
        return None

    text = payload.decode('utf-8', errors='ignore').strip().strip('\x00')
    if ',' not in text:
        return None

    sensor_type, value = text.split(',', 1)
    sensor_type = sensor_type.strip()
    value = value.strip()
    if not sensor_type or not value:
        return None
    return sensor_type, value


async def scan_loop(args, sock):
    """持续扫描并把解析成功的数据发往网关。"""
    last_sent = {}

    def on_detect(device, advertisement):
        parsed = parse_advertisement(advertisement)

        if args.verbose:
            mfg = {k: v.hex() for k, v in advertisement.manufacturer_data.items()}
            print(f"[BLE] {device.address} rssi={advertisement.rssi} "
                  f"name={device.name!r} mfg={mfg} parsed={parsed}")

        if not parsed:
            return

        now = time.monotonic()
        if args.dedup > 0:
            previous = last_sent.get(device.address, 0.0)
            if now - previous < args.dedup:
                return
        last_sent[device.address] = now

        sensor_type, value = parsed
        packet = f"{device.address},{sensor_type},{value}"

        if args.dry_run:
            print(f"[DRY-RUN] {packet}")
            return

        try:
            sock.sendto(packet.encode('utf-8'), (args.target, args.port))
            print(f"[SEND] {packet}")
        except OSError as exc:
            print(f"[ERROR] 发送失败: {exc}", file=sys.stderr)

    scanner = BleakScanner(detection_callback=on_detect)
    try:
        await scanner.start()
    except Exception as exc:
        print(f"[ERROR] 启动 BLE 扫描失败: {exc}", file=sys.stderr)
        print("请先打开蓝牙适配器：", file=sys.stderr)
        print("  sudo rfkill unblock bluetooth", file=sys.stderr)
        print("  sudo bluetoothctl power on", file=sys.stderr)
        return False

    print(f"开始扫描 BLE 广播（目标 {args.target}:{args.port}）...")

    try:
        if args.timeout > 0:
            await asyncio.sleep(args.timeout)
        else:
            await asyncio.Event().wait()
    finally:
        try:
            await scanner.stop()
        except Exception as exc:
            print(f"[WARN] 停止扫描失败: {exc}", file=sys.stderr)
        print("扫描已停止")
    return True


def main():
    parser = argparse.ArgumentParser(description='扫描 BLE 广播并转发到 IoT 网关')
    parser.add_argument('--target', default=DEFAULT_TARGET,
                        help=f'网关 IP（默认 {DEFAULT_TARGET}）')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT,
                        help=f'网关 UDP 端口（默认 {DEFAULT_PORT}）')
    parser.add_argument('--timeout', type=float, default=0,
                        help='扫描秒数，0 表示一直运行（默认 0）')
    parser.add_argument('--dedup', type=float, default=1.0,
                        help='同一设备最短发送间隔秒数（默认 1）')
    parser.add_argument('--dry-run', action='store_true',
                        help='只打印，不发送')
    parser.add_argument('--verbose', action='store_true',
                        help='打印所有扫描到的设备及原始厂商数据')
    args = parser.parse_args()

    if BleakScanner is None:
        print('未安装 bleak。请在宿主机执行：pip install bleak', file=sys.stderr)
        return 2

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        ok = asyncio.run(scan_loop(args, sock))
    except KeyboardInterrupt:
        print('\n已中断')
        return 0
    except Exception as exc:
        print(f"[ERROR] 扫描器异常退出: {exc}", file=sys.stderr)
        return 1
    finally:
        sock.close()
    return 0 if ok else 2


if __name__ == '__main__':
    sys.exit(main())
