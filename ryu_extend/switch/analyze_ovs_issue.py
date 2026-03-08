#!/usr/bin/env python3
"""分析 Experimenter 动作问题"""

import os
import sys
import struct

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from extensions.manager import create_iot_extension, IoTExtensionManager
from extensions.constants import EXPERIMENTER_ID

print("="*60)
print("关键问题分析：")
print("="*60)

print("\n1. 即使我们添加了 OFPActionExperimenter")
print("   ovs-ofctl dump-flows 可能不会默认显示 Experimenter 动作的详细内容")
print("\n2. 问题中的流表显示 priority=10，这表明")
print("   - 要么扩展模块导入失败 (EXTENSIONS_AVAILABLE=False)")
print("   - 要么 add_flow 函数没有被正确调用")
print("   - 要么流表是通过其他方式添加的 (如 ovs-ofctl add-flow)")

print("\n" + "="*60)
print("让我们检查可能的解决方案：")
print("="*60)

print("\n关键修复方向：")
print("1. 确保 EXTENSIONS_AVAILABLE 总是为 True")
print("2. 即使扩展模块导入失败也要创建默认扩展字段")
print("3. 添加更详细的调试日志来跟踪问题")
print("4. 考虑使用其他方式验证扩展字段是否被正确添加")
