#!/usr/bin/env python3
"""OpenFlow 扩展字段综合测试脚本
提供完整的功能验证和调试信息"""

import sys
import os

# 添加上级目录到Python路径
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parent_dir)

print("=== OpenFlow 扩展字段功能测试 ===\n")

try:
    # 测试基本导入
    from extensions.constants import EXPERIMENTER_ID
    print(f"✓ 成功导入常量，厂商ID: 0x{EXPERIMENTER_ID:08x}")
    
    # 测试字段创建
    from extensions.manager import create_iot_extension, IoTExtensionManager
    
    print("\n1. 创建扩展字段...")
    ext_mgr = create_iot_extension(
        sensor_type='temp',
        device_priority=3,
        route_select='route_a'
    )
    
    print("2. 显示字段信息:")
    ext_mgr.print_fields()
    
    # 测试序列化
    print("\n3. 序列化测试...")
    serialized = ext_mgr.serialize_to_experimenter()
    print(f"   序列化完成 ({len(serialized)} bytes)")
    
    # 测试反序列化
    print("\n4. 反序列化测试...")
    parsed_mgr = IoTExtensionManager.parse_from_experimenter(serialized)
    print("   反序列化完成")
    print("   解析结果:")
    parsed_mgr.print_fields()
    
    print("\n🎉 所有测试通过!")
    exit(0)
    
except ImportError as e:
    print(f"❌ 导入错误: {e}")
    exit(1)
except Exception as e:
    print(f"❌ 运行错误: {e}")
    import traceback
    traceback.print_exc()
    exit(1)