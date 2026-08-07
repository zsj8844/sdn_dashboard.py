#!/usr/bin/env python3

import os
import sys
import time
import signal
import subprocess
import shutil

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = SCRIPT_DIR
VENV_DIR = os.path.join(os.path.dirname(PROJECT_DIR), ".venv")

if os.path.isdir(VENV_DIR):
    PYTHON = os.path.join(VENV_DIR, "bin", "python")
    PYTHON3 = os.path.join(VENV_DIR, "bin", "python3")
else:
    PYTHON = shutil.which("python3") or "python3"
    PYTHON3 = PYTHON

CTL_PORT = 6634
DASH_PORT = 5000
VUE_PORT = 5173
GW_PORT = 5005
EXT_PORT = 6650

VUE_DIR = os.path.join(PROJECT_DIR, "templates/sdn_dashboard_vue/sdn_dashboard_view")

LOG_DIR = os.path.join(PROJECT_DIR, "logs")
CTL_LOG = os.path.join(LOG_DIR, "controller.log")
DASH_LOG = os.path.join(LOG_DIR, "dashboard.log")
VUE_LOG = os.path.join(LOG_DIR, "vue.log")
GW_LOG = os.path.join(LOG_DIR, "gateway.log")
PID_FILE = os.path.join(PROJECT_DIR, "run.pid")


def info(msg):
    print(f"\033[32m[INFO]\033[0m {msg}")


def warn(msg):
    print(f"\033[33m[WARN]\033[0m {msg}")


def error(msg):
    print(f"\033[31m[ERROR]\033[0m {msg}")
    sys.exit(1)


def run(cmd, sudo=False, bg=False, log=None):
    if sudo:
        cmd = ["sudo"] + cmd
    if bg:
        with open(log, "w") as f:
            return subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT)
    return subprocess.run(cmd, capture_output=True, text=True)


def pid_of_port(port):
    try:
        result = subprocess.run(
            ["sudo", "lsof", "-i", f":{port}", "-t"],
            capture_output=True, text=True
        )
        return result.stdout.strip().split()
    except Exception:
        return []


def kill_port(port):
    pids = pid_of_port(port)
    if pids:
        info(f"杀掉占用 {port} 端口的进程: {' '.join(pids)}")
        subprocess.run(["sudo", "kill", "-9"] + pids, capture_output=True)
        return True
    return False


def clean():
    info("清理环境残留...")
    subprocess.run(["sudo", "killall", "-9", "mn", "ovs-vswitchd", "ovsdb-server"],
                   capture_output=True)
    subprocess.run(["sudo", "mn", "-c", "-f"], capture_output=True)
    subprocess.run(["sudo", "ovs-vsctl", "del-br", "s1", "s2"], capture_output=True)
    kill_port(CTL_PORT)
    kill_port(DASH_PORT)
    kill_port(VUE_PORT)
    kill_port(EXT_PORT)
    pids = subprocess.run(["pgrep", "-f", "ryu.cmd.manager"],
                          capture_output=True, text=True).stdout.strip().split()
    if pids:
        subprocess.run(["sudo", "kill", "-9"] + pids, capture_output=True)
    info("清理完成")


def status():
    def check(n, p):
        return "运行中" if pid_of_port(p) else "未运行"

    print(f"控制器    ({CTL_PORT}端口): {check('控制器', CTL_PORT)}")
    print(f"Web面板   ({DASH_PORT}端口): {check('Web面板', DASH_PORT)}")
    print(f"Vue前端   ({VUE_PORT}端口): {check('Vue', VUE_PORT)}")
    print(f"增强版网关({GW_PORT}/{EXT_PORT}端口): {check('网关', GW_PORT)}")

    mn = subprocess.run(["pgrep", "-f", "mininet"],
                        capture_output=True, text=True).stdout.strip()
    print(f"Mininet网络: {'运行中' if mn else '未运行'}")


def stop():
    info("关闭SDN系统...")

    if os.path.isfile(PID_FILE):
        with open(PID_FILE) as f:
            for line in f:
                pid = line.strip()
                if pid:
                    try:
                        os.kill(int(pid), signal.SIGTERM)
                    except (ProcessLookupError, ValueError):
                        pass
        os.remove(PID_FILE)

    subprocess.run(["sudo", "killall", "-9", "python3", "ryu-manager"],
                   capture_output=True)
    subprocess.run(["sudo", "mn", "-c"], capture_output=True)
    kill_port(CTL_PORT)
    kill_port(DASH_PORT)
    kill_port(VUE_PORT)
    kill_port(EXT_PORT)
    info("系统已关闭")


def start_controller():
    info("启动SDN控制器...")
    p = run([PYTHON, "-m", "ryu.cmd.manager",
             "switch/ble_switch_13.py",
             "--verbose", "--ofp-tcp-listen-port", str(CTL_PORT)],
            bg=True, log=CTL_LOG)
    with open(PID_FILE, "w") as f:
        f.write(f"{p.pid}\n")
    info(f"控制器 PID: {p.pid}")


def start_dashboard():
    info("启动监控面板...")
    p = run([PYTHON3, "templates/sdn_dashboard.py"],
            bg=True, log=DASH_LOG)
    with open(PID_FILE, "a") as f:
        f.write(f"{p.pid}\n")
    info(f"面板 PID: {p.pid}")


def start_topology():
    info("启动Mininet拓扑...")
    p = run(["python3", "topology/iot_sdn_topology.py"],
            sudo=True, bg=True,
            log=os.path.join(LOG_DIR, "topology.log"))
    with open(PID_FILE, "a") as f:
        f.write(f"{p.pid}\n")
    info(f"拓扑 PID: {p.pid}")
    time.sleep(5)


def start_gateway():
    info("启动增强版IoT网关...")
    kill_port(EXT_PORT)
    kill_port(GW_PORT)
    p = run([PYTHON3, "../gateway/iot_gateway_enhanced.py"],
            bg=True, log=GW_LOG)
    with open(PID_FILE, "a") as f:
        f.write(f"{p.pid}\n")
    info(f"网关 PID: {p.pid}")


def start_vue():
    info("启动Vue前端开发服务器...")
    kill_port(VUE_PORT)
    npm = shutil.which("npm")
    if not npm:
        warn("未找到 npm，跳过 Vue 前端启动")
        return
    p = subprocess.Popen(
        [npm, "run", "dev"],
        cwd=VUE_DIR,
        stdout=open(VUE_LOG, "w"),
        stderr=subprocess.STDOUT,
    )
    with open(PID_FILE, "a") as f:
        f.write(f"{p.pid}\n")
    info(f"Vue面板 PID: {p.pid}")


def check_service():
    info("等待服务就绪...")
    for port, name in [(CTL_PORT, "控制器"), (DASH_PORT, "Web面板"), (VUE_PORT, "Vue前端")]:
        for _ in range(30):
            if pid_of_port(port):
                info(f"✅ {name} 端口 {port} 已监听")
                break
            time.sleep(1)
        else:
            warn(f"{name} 未监听端口 {port}")


def deploy():
    info("=" * 50)
    info("  一键部署 SDN IoT 项目")
    info("=" * 50)
    os.makedirs(LOG_DIR, exist_ok=True)
    clean()
    start_controller()
    start_dashboard()
    start_gateway()
    start_vue()
    check_service()
    info("=" * 50)
    info("  部署完成！")
    info(f"  控制器日志: tail -f {CTL_LOG}")
    info(f"  网关日志:   tail -f {GW_LOG}")
    info(f"  Vue日志:     tail -f {VUE_LOG}")
    info(f"  普通面板:   http://localhost:{DASH_PORT}")
    info(f"  增强版面板: http://localhost:{DASH_PORT}/enhanced")
    info(f"  Vue面板:    http://localhost:{VUE_PORT}")
    info("=" * 50)


def full():
    deploy()
    time.sleep(5)
    info("运行网关转发测试...")
    run([PYTHON3, "switch/test/gateway_forwarding_test.py"])
    info("运行全链路测试...")
    run([PYTHON3, "switch/test/full_chain_test.py"])
    info("完整部署（含测试）完成！")


HELP = """
用法: python3 manage.py <命令>

命令:
  start     启动完整系统（控制器 + 面板 + 网关 + 拓扑）
  gateway   仅启动增强版IoT网关
  stop      关闭所有服务
  status    查看系统状态
  clean     清理环境残留
  help      显示此帮助

环境变量:
  VENV_NAME  虚拟环境名称（默认: ryu-env）
"""


def main():
    if len(sys.argv) < 2:
        action = "start"
    else:
        action = sys.argv[1]

    os.chdir(PROJECT_DIR)

    if action in ("start", "deploy"):
        deploy()
    elif action == "gateway":
        start_gateway()
    elif action == "stop":
        stop()
    elif action == "status":
        status()
    elif action == "clean":
        clean()
    elif action == "help":
        print(HELP)
    else:
        print(f"未知命令: {action}")
        print(HELP)
        sys.exit(1)


if __name__ == "__main__":
    main()
