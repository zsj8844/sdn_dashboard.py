#!/bin/bash
set -euo pipefail

# ==================== 核心配置 ====================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"
VENV_NAME="${VENV_NAME:-ryu-env}"
if [ -d "$SCRIPT_DIR/.venv/bin" ]; then
    VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python"
    VENV_PYTHON3="$SCRIPT_DIR/.venv/bin/python3"
elif command -v conda &>/dev/null; then
    CONDA_PREFIX=$(conda info --base 2>/dev/null || echo "/opt/conda")
    VENV_PYTHON="$CONDA_PREFIX/envs/$VENV_NAME/bin/python"
    VENV_PYTHON3="$CONDA_PREFIX/envs/$VENV_NAME/bin/python3"
else
    VENV_PYTHON="python3"
    VENV_PYTHON3="python3"
fi
CONTROLLER_SCRIPT="switch/ble_switch_13.py"
DASHBOARD_SCRIPT="templates/sdn_dashboard.py"
TOPOLOGY_SCRIPT="topology/iot_sdn_topology.py"
GATEWAY_SCRIPT="topology/iot_gateway_enhanced.py"
CONTROLLER_PORT=6634
DASHBOARD_PORT=5000

# ==================== 日志文件 ====================
LOG_DIR="$PROJECT_DIR/logs"
CONTROLLER_LOG="$LOG_DIR/controller.log"
DASHBOARD_LOG="$LOG_DIR/dashboard.log"
TOPOLOGY_LOG="$LOG_DIR/topology.log"
GATEWAY_LOG="$LOG_DIR/gateway.log"
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
    if [ ! -d "$SCRIPT_DIR/.venv" ] && ! command -v conda &>/dev/null; then
        info "未检测到虚拟环境，使用系统Python继续..."
    fi
    if ! $VENV_PYTHON -c "import ryu" >/dev/null 2>&1 && ! $VENV_PYTHON -c "import ryu.cmd.manager" >/dev/null 2>&1; then
        info "ryu未安装或虚拟环境无效，使用系统Python"
    fi
    info "环境验证完成"
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
    sudo nohup python3 "$TOPOLOGY_SCRIPT" > "$TOPOLOGY_LOG" 2>&1 &
    TOPOLOGY_PID=$!
    echo $TOPOLOGY_PID >> "$PID_FILE"
    info "拓扑PID：$TOPOLOGY_PID，日志：$TOPOLOGY_LOG"
    sleep 5
}

start_gateway() {
    info "启动增强版IoT网关..."
    cd "$PROJECT_DIR" || error "项目目录不存在"
    sudo lsof -i:6650 -t | xargs -r kill -9 2>/dev/null || true
    sudo lsof -i:5005 -t | xargs -r kill -9 2>/dev/null || true
    nohup $VENV_PYTHON3 "$GATEWAY_SCRIPT" > "$GATEWAY_LOG" 2>&1 &
    GATEWAY_PID=$!
    echo $GATEWAY_PID >> "$PID_FILE"
    info "网关PID：$GATEWAY_PID，日志：$GATEWAY_LOG"
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

# ==================== 测试功能 ====================
test_components() {
    info "开始自动化测试..."

    sleep 5

    info "运行网关转发测试..."
    if [ -f "$PROJECT_DIR/switch/test/gateway_forwarding_test.py" ]; then
        $VENV_PYTHON3 "$PROJECT_DIR/switch/test/gateway_forwarding_test.py" || warning "转发测试执行失败"
    else
        warning "转发测试脚本不存在"
    fi

    info "运行全链路测试..."
    if [ -f "$PROJECT_DIR/switch/test/full_chain_test.py" ]; then
        $VENV_PYTHON3 "$PROJECT_DIR/switch/test/full_chain_test.py" || warning "全链路测试执行失败"
    else
        warning "全链路测试脚本不存在"
    fi
}

# ==================== 主流程 ====================
main() {
    info "========================================"
    info "🚀 开始一键部署SDN项目"
    info "========================================"
    init_env
    clean_env
    check_venv
    start_controller
    start_dashboard
    start_gateway
    check_service
    info "========================================"
    info "🎉 基础部署完成！"
    info "控制器日志：tail -f $CONTROLLER_LOG"
    info "网关日志：tail -f $GATEWAY_LOG"
    info "普通面板：http://localhost:$DASHBOARD_PORT"
    info "增强版面板：http://localhost:$DASHBOARD_PORT/enhanced"
    info "增强功能：OpenFlow 1.3、拓扑管理、流表管理"
    info "========================================"
}

# ==================== 完整流程 ====================
full_deployment() {
    info "========================================"
    info "🚀 开始完整部署流程（含测试）"
    info "========================================"
    init_env
    clean_env
    check_venv
    start_controller
    start_dashboard
    start_gateway
    check_service
    test_components
    info "========================================"
    info "🎉 完整部署完成！含自动化测试"
    info "控制器日志：tail -f $CONTROLLER_LOG"
    info "网关日志：tail -f $GATEWAY_LOG"
    info "普通面板：http://localhost:$DASHBOARD_PORT"
    info "增强版面板：http://localhost:$DASHBOARD_PORT/enhanced"
    info "增强功能：OpenFlow 1.3、拓扑管理、流表管理"
    info "========================================"
}

# ==================== 帮助信息 ====================
show_help() {
    echo "用法: $0 [选项]"
    echo "选项:"
    echo "  deploy     部署基础SDN环境（默认）"
    echo "  full       完整部署（含自动化测试）"
    echo "  clean      清理所有进程和网络"
    echo "  help       显示帮助信息"
    echo ""
    echo "环境变量:"
    echo "  VENV_NAME  虚拟环境名称（默认：ryu-env）"
    echo ""
    echo "增强功能:"
    echo "  - OpenFlow 1.3 协议支持 (流表下发 / 统计收集)"
    echo "  - 拓扑管理 (自动发现 + 可视化)"
    echo "  - 流表管理 (增删改查 + 多级流表)"
    echo ""
    echo "访问地址:"
    echo "  - 普通面板: http://localhost:5000"
    echo "  - 增强版面板: http://localhost:5000/enhanced"
    echo ""
    echo "测试相关：请使用 ./run_tests.sh"
}

# ==================== 参数处理 ====================
case "${1:-deploy}" in
    deploy)
        main
        ;;
    full)
        full_deployment
        ;;
    clean)
        clean_env
        ;;
    help)
        show_help
        ;;
    *)
        error "未知选项: $1\n$(show_help)"
        ;;
esac
