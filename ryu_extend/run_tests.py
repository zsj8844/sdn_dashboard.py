#!/usr/bin/env python3
"""SDN IoT 项目测试运行脚本"""

import os
import sys
import subprocess
import time
import shutil
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
LOG_DIR = SCRIPT_DIR / "logs"
PID_FILE = SCRIPT_DIR / "run.pid"

GATEWAY_SIMULATOR = "topology/iot_gateway_enhanced.py"
FORWARDING_TEST = "switch/test/v4_全链路/gateway_forwarding_test.py"
FULL_CHAIN_TEST = "switch/test/v4_全链路/full_chain_test.py"

RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RESET = "\033[0m"


def info(msg: str) -> None:
    print(f"{GREEN}[INFO]{RESET} {msg}")


def error(msg: str) -> int:
    print(f"{RED}[ERROR]{RESET} {msg}")
    sys.exit(1)


def warning(msg: str) -> None:
    print(f"{YELLOW}[WARNING]{RESET} {msg}")


def find_python() -> str:
    venv_dir = SCRIPT_DIR.parent / ".venv" / "bin"
    if (venv_dir / "python3").exists():
        return str(venv_dir / "python3")
    if (venv_dir / "python").exists():
        return str(venv_dir / "python")
    if shutil.which("python3"):
        return "python3"
    if shutil.which("python"):
        return "python"
    error("未找到可用的 Python 解释器")


def start_gateway() -> None:
    info("启动独立网关模拟器...")
    python = find_python()
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    gateway_script = SCRIPT_DIR / GATEWAY_SIMULATOR
    if not gateway_script.exists():
        error(f"网关脚本不存在: {gateway_script}")

    gateway_log = LOG_DIR / "gateway.log"
    with open(gateway_log, "a") as log_f:
        proc = subprocess.Popen(
            [python, str(gateway_script)],
            stdout=log_f, stderr=log_f,
            cwd=str(SCRIPT_DIR),
        )

    with open(PID_FILE, "a") as f:
        f.write(f"{proc.pid}\n")

    info(f"网关模拟器PID：{proc.pid}，日志：{gateway_log}")


def run_test(script_path: str, name: str) -> None:
    info(f"运行{name}...")
    python = find_python()

    test_script = SCRIPT_DIR / script_path
    if not test_script.exists():
        error(f"测试脚本不存在: {test_script}")

    test_log = LOG_DIR / "test.log"
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    with open(test_log, "a") as log_f:
        result = subprocess.run(
            [python, str(test_script)],
            stdout=log_f, stderr=log_f,
            cwd=str(SCRIPT_DIR),
        )

    status = "通过" if result.returncode == 0 else "失败"
    info(f"{name}完成（{status}），日志：{test_log}")


def run_all() -> None:
    info("=" * 50)
    info("开始阶段三测试（网关模拟 + 全链路验证）")
    info("=" * 50)

    start_gateway()
    time.sleep(5)
    run_test(FORWARDING_TEST, "网关转发验证测试")
    run_test(FULL_CHAIN_TEST, "全链路流转测试")

    info("=" * 50)
    info("阶段三测试完成！")
    info(f"测试日志：tail -f {LOG_DIR / 'test.log'}")
    info(f"网关日志：tail -f {LOG_DIR / 'gateway.log'}")
    info("=" * 50)


def show_help() -> None:
    print("用法: python run_tests.py [选项]")
    print("选项:")
    print("  run       运行完整测试流程（默认）")
    print("  gateway   仅启动网关模拟器")
    print("  forward   仅运行转发测试")
    print("  chain     仅运行全链路测试")
    print("  help      显示帮助信息")


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"

    handlers = {
        "run": run_all,
        "gateway": start_gateway,
        "forward": lambda: run_test(FORWARDING_TEST, "网关转发验证测试"),
        "chain": lambda: run_test(FULL_CHAIN_TEST, "全链路流转测试"),
        "help": show_help,
    }

    if cmd in handlers:
        handlers[cmd]()
    else:
        print(f"未知选项: {cmd}")
        show_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
