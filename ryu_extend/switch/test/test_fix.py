#!/usr/bin/env python3
"""测试修复后的代码"""

import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
sys.path.insert(0, current_dir)

print("="*60)
print("测试修复后的代码")
print("="*60)

# 1. 测试扩展模块导入
print("\n1. 测试扩展模块导入:")
try:
    from extensions.manager import IoTExtensionManager, create_iot_extension
    print("   ✓ 扩展模块导入成功")

    # 2. 测试创建扩展字段
    print("\n2. 测试创建扩展字段:")
    ext = create_iot_extension(sensor_type='temp', device_priority=5, route_select='route_a')
    field_dict = ext.get_field_dict()
    print(f"   ✓ 扩展字段创建成功")
    print(f"   字段内容: {field_dict}")

    # 3. 测试序列化
    print("\n3. 测试序列化:")
    serialized = ext.serialize_to_experimenter()
    print(f"   ✓ 序列化成功 ({len(serialized)} bytes)")
    print(f"   数据: {serialized.hex()}")

    # 4. 测试反序列化
    print("\n4. 测试反序列化:")
    parsed = IoTExtensionManager.parse_from_experimenter(serialized)
    parsed_dict = parsed.get_field_dict()
    print(f"   ✓ 反序列化成功")
    print(f"   解析后的字段: {parsed_dict}")

    print("\n" + "="*60)
    print("✓ 所有测试通过！扩展模块工作正常")
    print("="*60)

    print("\n下一步:")
    print("1. 启动控制器: ryu-manager switch/ble_switch_13.py")
    print("2. 启动拓扑: sudo python topology/iot_sdn_topology.py")
    print("3. 发送一些流量 (如 h1 ping h2)")
    print("4. 查看控制器日志，确认扩展字段被添加")
    print("5. 查看流表: ovs-ofctl dump-flows s1 -O OpenFlow13")

except Exception as e:
    print(f"   ✗ 测试失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
