import sys
import os
import traceback

print("=== 开始测试 dashboard 启动 ===")

try:
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../switch')))
    print("✓ sys.path 设置成功")
    
    print("\n--- 尝试导入 extensions 模块 ---")
    from extensions import (
        AppDeploymentManager, EdgeApplication, AppType, AppStatus,
        DeviceRoleManager, DeviceMode, DeviceCapabilities
    )
    print("✓ extensions 模块导入成功")
    
    print("\n--- 尝试初始化管理器 ---")
    APP_DEPLOYMENT_MANAGER = AppDeploymentManager()
    DEVICE_ROLE_MANAGER = DeviceRoleManager()
    print("✓ 管理器初始化成功")
    
    print("\n--- 尝试导入 Flask 和其他依赖 ---")
    from flask import Flask, render_template, jsonify, request
    import subprocess
    import threading
    import time
    from collections import deque, defaultdict
    import logging
    import json
    print("✓ 所有依赖导入成功")
    
    print("\n✅ 所有测试通过！dashboard 应该可以正常启动。")
    
except Exception as e:
    print(f"\n❌ 错误: {e}")
    print("\n详细堆栈信息:")
    traceback.print_exc()
    sys.exit(1)
