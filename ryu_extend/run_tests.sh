#!/bin/bash
set -euo pipefail

# ==================== 测试配置 ====================
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
GATEWAY_SIMULATOR="topology/iot_gateway_enhanced.py"
FORWARDING_TEST="switch/test/gateway_forwarding_test.py"
FULL_CHAIN_TEST="switch/test/full_chain_test.py"

# ==================== 日志文件 ====================
LOG_DIR="$PROJECT_DIR/logs"
GATEWAY_LOG="$LOG_DIR/gateway.log"
TEST_LOG="$LOG_DIR/test.log"
PID_FILE="$PROJECT_DIR/run.pid"

# ==================== 工具函数 ====================
info() { echo -e "\033[32m[INFO] $1\033[0m"; }
error() { echo -e "\033[31m[ERROR] $1\033[0m"; exit 1; }
warning() { echo -e "\033[33m[WARNING] $1\033[0m"; }

# ==================== 测试函数 ====================
start_gateway_simulator() {
    info "启动独立网关模拟器..."
    cd "$PROJECT_DIR" || error "项目目录不存在"
    nohup $VENV_PYTHON3 "$GATEWAY_SIMULATOR" > "$GATEWAY_LOG" 2>&1 &
    echo $! >> "$PID_FILE"
    info "网关模拟器PID：$(tail -n1 $PID_FILE)，日志：$GATEWAY_LOG"
}

run_forwarding_test() {
    info "运行网关转发验证测试..."
    cd "$PROJECT_DIR" || error "项目目录不存在"
    $VENV_PYTHON3 "$FORWARDING_TEST" > "$TEST_LOG" 2>&1
    info "转发测试完成，日志：$TEST_LOG"
}

run_full_chain_test() {
    info "运行全链路流转测试..."
    cd "$PROJECT_DIR" || error "项目目录不存在"
    $VENV_PYTHON3 "$FULL_CHAIN_TEST" > "$TEST_LOG" 2>&1
    info "全链路测试完成，日志：$TEST_LOG"
}

# ==================== 主测试流程 ====================
main() {
    info "========================================"
    info "🧪 开始阶段三测试（网关模拟+全链路验证）"
    info "========================================"

    start_gateway_simulator

    sleep 5

    run_forwarding_test

    run_full_chain_test

    info "========================================"
    info "✅ 阶段三测试完成！"
    info "测试日志：tail -f $TEST_LOG"
    info "网关日志：tail -f $GATEWAY_LOG"
    info "========================================"
}

# ==================== 帮助信息 ====================
show_help() {
    echo "用法: $0 [选项]"
    echo "选项:"
    echo "  run        运行完整测试流程（默认）"
    echo "  gateway    仅启动网关模拟器"
    echo "  forward    仅运行转发测试"
    echo "  chain      仅运行全链路测试"
    echo "  help       显示帮助信息"
    echo ""
    echo "环境变量:"
    echo "  VENV_NAME  虚拟环境名称（默认：ryu-env）"
}

# ==================== 参数处理 ====================
case "${1:-run}" in
    run)
        main
        ;;
    gateway)
        start_gateway_simulator
        ;;
    forward)
        run_forwarding_test
        ;;
    chain)
        run_full_chain_test
        ;;
    help)
        show_help
        ;;
    *)
        error "未知选项: $1\n$(show_help)"
        ;;
esac
