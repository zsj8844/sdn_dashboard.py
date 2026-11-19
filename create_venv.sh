#!/bin/bash
set -euo pipefail

# 创建并激活虚拟环境的脚本

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_NAME="${VENV_NAME:-ryu-env}"
VENV_DIR="$SCRIPT_DIR/.venv"

info() { echo -e "\033[32m[INFO] $1\033[0m"; }
error() { echo -e "\033[31m[ERROR] $1\033[0m"; exit 1; }

# 检查系统依赖
check_system_deps() {
    info "检查系统依赖..."
    if ! command -v ovs-vsctl &>/dev/null; then
        info "需要安装Open vSwitch，正在尝试安装..."
        sudo apt update && sudo apt install -y openvswitch-switch openvswitch-common || {
            error "Open vSwitch安装失败，请手动安装: sudo apt install openvswitch-switch openvswitch-common"
        }
    fi
    # 优先使用 Python 3.10+，兼容 ryu 4.34 构建
    for py in python3.10 python3.11 python3.12 python3; do
        if command -v "$py" &>/dev/null; then
            PYTHON_CMD="$py"
            break
        fi
    done
    if [ -z "${PYTHON_CMD:-}" ]; then
        error "Python 3 未安装，请先安装 Python 3.10+"
    fi
    info "使用 Python: $($PYTHON_CMD --version)"
    if ! command -v pip3 &>/dev/null; then
        error "pip3未安装，请先安装pip3: sudo apt install python3-pip"
    fi
}

# 创建虚拟环境
create_venv() {
    if [ -d "$VENV_DIR" ]; then
        info "虚拟环境已存在，删除后重新创建..."
        rm -rf "$VENV_DIR"
    fi
    
    info "创建虚拟环境: $VENV_DIR"
    $PYTHON_CMD -m venv "$VENV_DIR"
    
    # 升级pip
    info "升级pip..."
    "$VENV_DIR/bin/pip" install --upgrade pip
}

# 安装依赖
install_deps() {
    if [ ! -f "$SCRIPT_DIR/requirements.txt" ]; then
        error "requirements.txt文件不存在"
    fi
    
    info "安装项目依赖..."
    "$VENV_DIR/bin/pip" install -r "$SCRIPT_DIR/requirements.txt"
}

# 验证安装
verify_install() {
    info "验证依赖安装..."
    if "$VENV_DIR/bin/python" -c "import ryu" 2>&1 | grep -q "ImportError"; then
        error "Ryu安装失败"
    else
        info "Ryu安装成功"
    fi
    
    if "$VENV_DIR/bin/python" -c "import flask" 2>&1 | grep -q "ImportError"; then
        error "Flask安装失败"
    else
        info "Flask安装成功"
    fi
    
    info "所有依赖安装完成！"
}

# 显示使用说明
show_help() {
    echo "用法: $0 [选项]"
    echo "选项:"
    echo "  create    创建虚拟环境并安装依赖（默认）"
    echo "  install   仅安装依赖（使用现有虚拟环境）"
    echo "  verify    验证依赖安装"
    echo "  clean     清理虚拟环境"
    echo "  help      显示帮助信息"
    echo ""
    echo "环境变量:"
    echo "  VENV_NAME  虚拟环境名称（默认：ryu-env）"
}

# 主逻辑
case "${1:-create}" in
    create)
        check_system_deps
        create_venv
        install_deps
        verify_install
        ;;
    install)
        if [ ! -d "$VENV_DIR" ]; then
            error "虚拟环境不存在，请先运行: $0 create"
        fi
        install_deps
        verify_install
        ;;
    verify)
        if [ ! -d "$VENV_DIR" ]; then
            error "虚拟环境不存在，请先运行: $0 create"
        fi
        verify_install
        ;;
    clean)
        if [ -d "$VENV_DIR" ]; then
            info "清理虚拟环境: $VENV_DIR"
            rm -rf "$VENV_DIR"
            info "虚拟环境已清理"
        else
            info "虚拟环境不存在"
        fi
        ;;
    help)
        show_help
        ;;
    *)
        error "未知选项: $1\n$(show_help)"
        ;;
esac
