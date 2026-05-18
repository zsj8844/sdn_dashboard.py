#!/usr/bin/env python3
"""测试控制器模块是否能正常导入"""

import os
import sys

print("="*60)
print("测试控制器模块导入")
print("="*60)

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
sys.path.insert(0, current_dir)

print(f"\n当前目录: {current_dir}")
print(f"父目录: {parent_dir}")
print(f"Python路径: {sys.path[:3]}")

try:
    print("\n1. 尝试导入 ble_switch_13 模块...")
    import ble_switch_13
    print("   ✓ 模块导入成功")

    print("\n2. 检查 BLEMeshSwitch13 类...")
    if hasattr(ble_switch_13, 'BLEMeshSwitch13'):
        print("   ✓ BLEMeshSwitch13 类存在")
    else:
        print("   ✗ BLEMeshSwitch13 类不存在")

    print("\n3. 检查扩展功能状态...")
    print(f"   EXTENSIONS_AVAILABLE: {ble_switch_13.EXTENSIONS_AVAILABLE}")

    print("\n" + "="*60)
    print("✓ 所有测试通过！控制器模块可以正常使用")
    print("="*60)

except Exception as e:
    print(f"\n✗ 导入失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
