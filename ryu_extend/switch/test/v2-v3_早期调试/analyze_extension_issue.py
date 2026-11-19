#!/usr/bin/env python3
"""深入分析 add_flow 函数的问题"""

import os
import sys
import struct

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from extensions.manager import create_iot_extension
from extensions.constants import EXPERIMENTER_ID

print("=== 深度分析扩展字段问题 ===\n")

# 1. 测试扩展字段创建
print("1. 测试扩展字段创建:")
ext = create_iot_extension(sensor_type='temp', device_priority=5, route_select='route_a')
field_dict = ext.get_field_dict()
print(f"   字段字典: {field_dict}")

# 2. 测试序列化
print("\n2. 测试序列化:")
serialized = ext.serialize_to_experimenter()
print(f"   序列化长度: {len(serialized)} bytes")
print(f"   原始数据: {serialized.hex()}")

# 3. 分析序列化数据结构
print("\n3. 分析数据结构:")
exp_id, field_count = struct.unpack('!IB', serialized[:5])
print(f"   Experimenter ID: 0x{exp_id:08x} (期望: 0x{EXPERIMENTER_ID:08x})")
print(f"   字段数量: {field_count}")

offset = 5
for i in range(field_count):
    if offset + 6 <= len(serialized):
        field_type, length, reserved = struct.unpack('!BBH', serialized[offset:offset+4])
        print(f"\n   字段 {i+1}:")
        print(f"      类型: {field_type}")
        print(f"      长度: {length}")
        print(f"      保留: 0x{reserved:04x}")
        field_data = serialized[offset+4:offset+length]
        print(f"      数据: {field_data.hex()}")
        offset += length

print("\n" + "="*50)
print("关键问题分析:")
print("="*50)
print("1. 扩展字段是通过 OFPActionExperimenter 作为 ACTION 添加的")
print("2. ovs-ofctl dump-flows 命令默认不会显示 Experimenter 动作的详细内容")
print("3. 但是问题中的流表甚至连 Experimenter 关键字都没有出现！")
print("\n可能的原因:")
print("- add_flow 函数没有被正确调用")
print("- 扩展模块导入失败导致 EXTENSIONS_AVAILABLE=False")
print("- 流表添加过程中出现异常被忽略")
