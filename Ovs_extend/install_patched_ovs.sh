#!/usr/bin/env bash
# 安装打过 IoT Experimenter 补丁的 OVS 3.3.9 二进制。
#
# 用法（需要 sudo）：
#   sudo ./install_patched_ovs.sh [目录]
#
# 目录可以是两种布局之一：
#   1. 已构建的 artifacts/bin：包含 ovs-vswitchd-3.3.9 / ovs-ofctl-3.3.9
#   2. OVS 源码树：包含 vswitchd/ovs-vswitchd / utilities/ovs-ofctl
#
# 不传参数时默认使用本脚本旁边的 artifacts/bin。
# 会备份系统中的 ovs-vswitchd 和 ovs-ofctl，并打印回滚命令。
set -euo pipefail

SRC="${1:-$(dirname "$0")/artifacts/bin}"
if [ -x "$SRC/vswitchd/ovs-vswitchd" ]; then
    VSWITCHD_SRC="$SRC/vswitchd/ovs-vswitchd"
    OFCTL_SRC="$SRC/utilities/ovs-ofctl"
elif [ -x "$SRC/ovs-vswitchd-3.3.9" ]; then
    VSWITCHD_SRC="$SRC/ovs-vswitchd-3.3.9"
    OFCTL_SRC="$SRC/ovs-ofctl-3.3.9"
else
    echo "错误：$SRC 里既没有源码树布局，也没有 artifacts/bin 布局" >&2
    exit 1
fi
VSWITCHD_DST="/usr/sbin/ovs-vswitchd"
OFCTL_DST="/usr/bin/ovs-ofctl"
STAMP="$(date +%Y%m%d-%H%M%S)"

for f in "$VSWITCHD_SRC" "$OFCTL_SRC"; do
    if [ ! -x "$f" ]; then
        echo "错误：找不到可执行文件 $f" >&2
        exit 1
    fi
done

echo "== 备份系统 OVS 二进制 =="
sudo cp -a "$VSWITCHD_DST" "$VSWITCHD_DST.bak-$STAMP"
sudo cp -a "$OFCTL_DST"    "$OFCTL_DST.bak-$STAMP"
echo "  $VSWITCHD_DST.bak-$STAMP"
echo "  $OFCTL_DST.bak-$STAMP"

echo "== 安装补丁版二进制 =="
sudo install -m 0755 "$VSWITCHD_SRC" "$VSWITCHD_DST"
sudo install -m 0755 "$OFCTL_SRC"    "$OFCTL_DST"

echo "== 重启 Open vSwitch =="
sudo systemctl restart openvswitch-switch

echo
echo "完成。验证："
echo "  ovs-ofctl --version"
echo "  ovs-ofctl ofp-parse /tmp/fm_exp2.bin   # 应显示 experimenter(0x12345678,...)"
echo
echo "回滚（一条命令）："
echo "  sudo cp -a $VSWITCHD_DST.bak-$STAMP $VSWITCHD_DST && \\"
echo "  sudo cp -a $OFCTL_DST.bak-$STAMP $OFCTL_DST && \\"
echo "  sudo systemctl restart openvswitch-switch"
echo
echo "注意：apt 升级 OVS 会覆盖补丁，升级后需要重新应用。"
