#!/usr/bin/env python3
"""验证扩展模块可用性"""

import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
sys.path.insert(0, current_dir)

print("=== 扩展模块可用性测试 ===")
print(f"当前目录: {current_dir}")
print(f"Python路径: {sys.path[:5]}")
print()

try:
    print("尝试导入扩展模块...")
    from extensions.manager import IoTExtensionManager, create_iot_extension
    from extensions.sensor_field import SensorTypeField
    from extensions.priority_field import DevicePriorityField
    from extensions.route_field import RouteSelectField

    print("✓ 扩展模块导入成功")
    print()

    print("测试 create_iot_extension...")
    ext = create_iot_extension(sensor_type='temp', device_priority=3, route_select='route_a')
    print("✓ create_iot_extension 成功")

    field_dict = ext.get_field_dict()
    print(f"  字段字典: {field_dict}")

    serialized = ext.serialize_to_experimenter()
    print(f"  序列化长度: {len(serialized)} bytes")

    print()
    print("✓ 所有测试通过！")
    sys.exit(0)

except Exception as e:
    print(f"✗ 测试失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
