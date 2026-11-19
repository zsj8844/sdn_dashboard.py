#!/usr/bin/env python3
"""OpenFlow 扩展字段测试脚本"""

import sys
import os

# 添加父目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extensions.demo import demo_extension_usage

if __name__ == '__main__':
    print("测试 OpenFlow 扩展字段功能...")
    success = demo_extension_usage()
    exit(0 if success else 1)