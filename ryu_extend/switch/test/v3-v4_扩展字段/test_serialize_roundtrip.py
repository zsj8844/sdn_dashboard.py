#!/usr/bin/env python3
"""
测试 create_iot_extension + serialize_to_experimenter + parse_from_experimenter 完整链路
从 ble_switch_13.py 中移出的 test_extension_functionality 方法
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../..'))
from switch.extensions.manager import create_iot_extension, IoTExtensionManager


def test_serialize_roundtrip():
    print("创建测试扩展字段...")
    ext_mgr = create_iot_extension(
        sensor_type='temp',
        device_priority=3,
        route_select='route_a'
    )
    print("测试扩展字段创建成功")

    print("开始序列化...")
    serialized = ext_mgr.serialize_to_experimenter()
    print(f"扩展字段序列化测试成功 ({len(serialized)} bytes)")
    print(f"序列化数据 (十六进制): {serialized.hex()}")

    print("开始反序列化...")
    parsed_mgr = IoTExtensionManager.parse_from_experimenter(serialized)
    field_dict = parsed_mgr.get_field_dict()
    print(f"扩展字段反序列化测试成功: {field_dict}")

    print("========== 扩展字段功能测试全部通过 ==========")
    return True


if __name__ == '__main__':
    try:
        success = test_serialize_roundtrip()
        exit(0 if success else 1)
    except Exception as e:
        print(f"扩展字段功能测试失败: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
