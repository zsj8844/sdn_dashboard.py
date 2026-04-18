#!/bin/bash
# SDN系统核心控制脚本 - 简化版（支持增强版网关）

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT="$SCRIPT_DIR"
VENV_NAME="${VENV_NAME:-ryu-env}"
if [ -d "$SCRIPT_DIR/.venv/bin" ]; then
    RYU_PYTHON="$SCRIPT_DIR/.venv/bin/python"
    RYU_PYTHON3="$SCRIPT_DIR/.venv/bin/python3"
elif command -v conda &>/dev/null; then
    CONDA_PREFIX=$(conda info --base 2>/dev/null || echo "/opt/conda")
    RYU_PYTHON="$CONDA_PREFIX/envs/$VENV_NAME/bin/python"
    RYU_PYTHON3="$CONDA_PREFIX/envs/$VENV_NAME/bin/python3"
else
    RYU_PYTHON="python3"
    RYU_PYTHON3="python3"
fi
ACTION="${1:-help}"

# 颜色输出
info() { echo -e "\033[32m[INFO]\033[0m $1"; }
error() { echo -e "\033[31m[ERROR]\033[0m $1"; }

# 核心功能
start_all() {
    info "启动SDN系统..."
    cd "$PROJECT"

    sudo mn -c 2>/dev/null || true
    sudo killall -9 python3 ryu-manager 2>/dev/null || true
    sudo lsof -i:6634 -t | xargs -r kill -9 2>/dev/null || true
    sudo lsof -i:5000 -t | xargs -r kill -9 2>/dev/null || true
    sudo lsof -i:6650 -t | xargs -r kill -9 2>/dev/null || true

    info "启动控制器..."
    nohup $RYU_PYTHON -m ryu.cmd.manager \
        switch/ble_switch_13.py --ofp-tcp-listen-port 6634 \
        > logs/controller.log 2>&1 &
    CONTROLLER_PID=$!
    sleep 3

    info "启动Web面板..."
    nohup $RYU_PYTHON3 \
        templates/sdn_dashboard.py \
        > logs/dashboard.log 2>&1 &
    WEB_PID=$!
    sleep 3

    info "启动网络拓扑..."
    sudo nohup python3 topology/iot_sdn_topology.py \
        > logs/topology.log 2>&1 &
    TOPOLOGY_PID=$!
    sleep 3

    info "启动增强版网关（OpenFlow扩展）..."
    nohup $RYU_PYTHON3 \
        topology/iot_gateway_enhanced.py \
        > logs/gateway.log 2>&1 &
    GATEWAY_PID=$!

    echo "$CONTROLLER_PID" > logs/pids.txt
    echo "$WEB_PID" >> logs/pids.txt
    echo "$TOPOLOGY_PID" >> logs/pids.txt
    echo "$GATEWAY_PID" >> logs/pids.txt

    info "系统启动完成！"
    info "控制器PID: $CONTROLLER_PID"
    info "Web面板PID: $WEB_PID"
    info "网络拓扑PID: $TOPOLOGY_PID"
    info "增强版网关PID: $GATEWAY_PID"
    info "访问Web界面: http://localhost:5000"
    info "增强版面板: http://localhost:5000/enhanced"
}

start_enhanced_gateway() {
    info "启动增强版IoT网关..."
    cd "$PROJECT"

    sudo lsof -i:6650 -t | xargs -r kill -9 2>/dev/null || true
    sudo lsof -i:5005 -t | xargs -r kill -9 2>/dev/null || true

    nohup $RYU_PYTHON3 \
        topology/iot_gateway_enhanced.py \
        > logs/gateway.log 2>&1 &
    GATEWAY_PID=$!
    echo "$GATEWAY_PID" >> logs/pids.txt

    info "增强版IoT网关已启动，PID: $GATEWAY_PID"
    info "日志: tail -f logs/gateway.log"
}

stop_all() {
    info "关闭SDN系统..."
    cd "$PROJECT"

    if [ -f "logs/pids.txt" ]; then
        while read pid; do
            kill -TERM "$pid" 2>/dev/null || true
        done < logs/pids.txt
        rm -f logs/pids.txt
    fi

    sudo killall -9 python3 ryu-manager 2>/dev/null || true
    sudo mn -c 2>/dev/null || true
    sudo lsof -i:6634 -t | xargs -r kill -9 2>/dev/null || true
    sudo lsof -i:5000 -t | xargs -r kill -9 2>/dev/null || true

    info "系统已关闭"
}

check_status() {
    info "系统状态检查:"
    echo "控制器(6634端口): $(sudo lsof -i:6634 >/dev/null 2>&1 && echo '运行中' || echo '未运行')"
    echo "Web面板(5000端口): $(sudo lsof -i:5000 >/dev/null 2>&1 && echo '运行中' || echo '未运行')"
    echo "Mininet网络: $(pgrep -f mininet >/dev/null 2>&1 && echo '运行中' || echo '未运行')"
    echo "增强版网关(5005/6650端口): $(sudo lsof -i:5005 >/dev/null 2>&1 && echo '运行中' || echo '未运行')"
}

show_help() {
    echo "SDN物联网控制系统 - 简化控制脚本"
    echo
    echo "使用方法:"
    echo "  $0 start            启动完整系统（含增强版网关）"
    echo "  $0 gateway          仅启动增强版IoT网关"
    echo "  $0 stop             关闭系统"
    echo "  $0 status           查看系统状态"
    echo "  $0 help             显示帮助"
    echo
    echo "环境变量:"
    echo "  VENV_NAME  虚拟环境名称（默认：ryu-env）"
    echo
    echo "增强功能:"
    echo "  - OpenFlow 1.3 协议支持 (流表下发 / 统计收集)"
    echo "  - 拓扑管理 (自动发现 + 可视化)"
    echo "  - 流表管理 (增删改查 + 多级流表)"
    echo "  - OpenFlow Experimenter扩展（IoT属性封装）"
    echo
    echo "访问地址:"
    echo "  - 普通面板: http://localhost:5000"
    echo "  - 增强版面板: http://localhost:5000/enhanced"
}

case "$ACTION" in
    "start")
        start_all
        ;;
    "gateway")
        start_enhanced_gateway
        ;;
    "stop")
        stop_all
        ;;
    "status")
        check_status
        ;;
    "help"|*)
        show_help
        ;;
esac
