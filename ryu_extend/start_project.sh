#!/bin/bash
set -euo pipefail

# ==================== 核心配置（已适配你的环境）====================
PROJECT_DIR="/home/zhang/桌面/ryucontronl/ryu_extend"
VENV_PYTHON="/home/zhang/miniconda3/envs/ryu-env/bin/python"  # 你的虚拟环境Python路径
VENV_PYTHON3="/home/zhang/miniconda3/envs/ryu-env/bin/python3"
CONTROLLER_SCRIPT="switch/ble_switch_13.py"
DASHBOARD_SCRIPT="templates/sdn_dashboard.py"
TOPOLOGY_SCRIPT="topology/iot_sdn_topology.py"
CONTROLLER_PORT=6634
DASHBOARD_PORT=5000
TEST_TARGET_IP="192.168.1.12"
TEST_TARGET_PORT=5005

# ==================== 日志/进程文件 ====================
LOG_DIR="$PROJECT_DIR/logs"
CONTROLLER_LOG="$LOG_DIR/controller.log"
DASHBOARD_LOG="$LOG_DIR/dashboard.log"
TOPOLOGY_LOG="$LOG_DIR/topology.log"
PID_FILE="$PROJECT_DIR/run.pid"

# ==================== 工具函数 ====================
info() { echo -e "\033[32m[INFO] $1\033[0m"; }
error() { echo -e "\033[31m[ERROR] $1\033[0m"; exit 1; }
warning() { echo -e "\033[33m[WARNING] $1\033[0m"; }

kill_port() {
    local port=$1
    local pids=$(sudo lsof -i:"$port" -t 2>/dev/null)
    [ -n "$pids" ] && info "杀掉占用$port端口的进程：$pids" && sudo kill -9 "$pids" >/dev/null 2>&1 || true
}

# ==================== 初始化与清理 ====================
init_env() {
    info "初始化运行环境..."
    mkdir -p "$LOG_DIR" || error "日志目录创建失败"
    rm -f "$CONTROLLER_LOG" "$DASHBOARD_LOG" "$TOPOLOGY_LOG" "$PID_FILE"
}

clean_env() {
    info "清理环境残留..."
    sudo killall -9 mn ovs-vswitchd ovsdb-server >/dev/null 2>&1 || true
    sudo mn -c -f >/dev/null 2>&1 || warning "Mininet清理完成"
    sudo ovs-vsctl del-br s1 s2 >/dev/null 2>&1 || true
    kill_port "$CONTROLLER_PORT"
    kill_port "$DASHBOARD_PORT"
    pgrep -f "ryu.cmd.manager" && sudo kill -9 $(pgrep -f "ryu.cmd.manager") >/dev/null 2>&1 || true
}

# ==================== 验证环境 ====================
check_venv() {
    info "验证虚拟环境..."
    [ ! -f "$VENV_PYTHON" ] && error "Python路径不存在：$VENV_PYTHON"
    # 检查Ryu是否安装
    if ! $VENV_PYTHON -c "import ryu.cmd.manager" >/dev/null 2>&1; then
        info "ryu-env中未安装Ryu，开始自动安装..."
        $VENV_PYTHON -m pip install ryu==4.34 || error "Ryu安装失败！手动执行：$VENV_PYTHON -m pip install ryu==4.34"
    fi
    info "环境验证成功！"
}

# ==================== 启动组件 ====================
start_controller() {
    info "启动SDN控制器..."
    cd "$PROJECT_DIR" || error "项目目录不存在"
    nohup $VENV_PYTHON -m ryu.cmd.manager "$CONTROLLER_SCRIPT" --verbose --ofp-tcp-listen-port "$CONTROLLER_PORT" > "$CONTROLLER_LOG" 2>&1 &
    echo $! > "$PID_FILE"
    info "控制器PID：$(cat $PID_FILE)，日志：$CONTROLLER_LOG"
}

start_dashboard() {
    info "启动监控面板..."
    cd "$PROJECT_DIR" || error "项目目录不存在"
    nohup $VENV_PYTHON3 "$DASHBOARD_SCRIPT" > "$DASHBOARD_LOG" 2>&1 &
    echo $! >> "$PID_FILE"
    info "监控面板PID：$(tail -n1 $PID_FILE)，日志：$DASHBOARD_LOG"
}

start_topology() {
    info "启动Mininet拓扑..."
    cd "$PROJECT_DIR" || error "项目目录不存在"
    sudo python3 "$TOPOLOGY_SCRIPT" > "$TOPOLOGY_LOG" 2>&1 &
    echo $! >> "$PID_FILE"
    info "拓扑PID：$(tail -n1 $PID_FILE)，日志：$TOPOLOGY_LOG"
}

# ==================== 检查服务 ====================
check_service() {
    info "检查服务状态（等待30秒）..."
    local wait=0
    while [ $wait -lt 30 ]; do
        if sudo lsof -i:"$CONTROLLER_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
            info "✅ 控制器端口 $CONTROLLER_PORT 已监听！"
            break
        fi
        sleep 1 && wait=$((wait+1))
    done
    [ $wait -ge 30 ] && warning "控制器未监听端口，查看日志：tail -n20 $CONTROLLER_LOG"

    wait=0
    while [ $wait -lt 30 ]; do
        if sudo lsof -i:"$DASHBOARD_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
            info "✅ 监控面板端口 $DASHBOARD_PORT 已监听！"
            break
        fi
        sleep 1 && wait=$((wait+1))
    done
}

# ==================== 主流程 ====================
main() {
    info "========================================"
    info "🚀 开始一键部署SDN项目（适配你的环境）"
    info "========================================"
    init_env
    clean_env
    check_venv
    start_controller
    start_dashboard
    start_topology
    check_service
    info "========================================"
    info "🎉 部署完成！"
    info "控制器日志：tail -f $CONTROLLER_LOG"
    info "监控面板：http://localhost:$DASHBOARD_PORT"
    info "停止服务：sudo kill -9 \$(cat $PID_FILE) && sudo mn -c"
    info "========================================"
}

main


