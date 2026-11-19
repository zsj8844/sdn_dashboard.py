#!/usr/bin/env bash
# 网关出口 HTB 队列（路线 A）：按 DSCP 把优先级 5/4/3 放进高优先级类。
#
# 在 iot3 命名空间内、面向 SDN 的出口上执行（拓扑里通常是 eth3 → s1）：
#   ip netns exec iot3 ./qos_egress.sh setup eth3 1000
#   ip netns exec iot3 ./qos_egress.sh show eth3
#   ip netns exec iot3 ./qos_egress.sh teardown eth3
#
# 需要 root + tc（iproute2）。链路空闲时优先级没有意义；演示时要靠
# 这里的 rate 制造真实排队，或者注入超过带宽的流量。
set -euo pipefail

CMD=${1:-}
IFACE=${2:-}
RATE=${3:-1000}          # kbit

usage() {
    echo "用法: $0 {setup|teardown|show} <iface> [rate-kbit]" >&2
    exit 2
}

[ -n "$CMD" ] && [ -n "$IFACE" ] || usage

case "$CMD" in
setup)
    HIGH=$((RATE * 80 / 100))
    LOW=$((RATE * 10 / 100))
    [ "$HIGH" -ge 1 ] || HIGH=1
    [ "$LOW" -ge 1 ] || LOW=1
    tc qdisc del dev "$IFACE" root 2>/dev/null || true
    tc qdisc add dev "$IFACE" root handle 1: htb default 20
    tc class add dev "$IFACE" parent 1: classid 1:1 htb \
        rate "${RATE}kbit" ceil "${RATE}kbit"
    tc class add dev "$IFACE" parent 1:1 classid 1:10 htb \
        rate "${HIGH}kbit" ceil "${RATE}kbit" prio 1
    tc class add dev "$IFACE" parent 1:1 classid 1:20 htb \
        rate "${LOW}kbit" ceil "${RATE}kbit" prio 2
    # DSCP 46(EF)/34(AF41)/26(AF31) → 高优先级类；其余走 default 1:20
    for tos in 0xb8 0x88 0x68; do
        tc filter add dev "$IFACE" parent 1: protocol ip prio 1 u32 \
            match ip tos "$tos" 0xfc flowid 1:10
    done
    echo "已配置 $IFACE: 总速率 ${RATE}kbit（高 ${HIGH}kbit / 低 ${LOW}kbit）"
    ;;
teardown)
    tc qdisc del dev "$IFACE" root 2>/dev/null || true
    echo "已移除 $IFACE 的 root qdisc"
    ;;
show)
    tc -s qdisc show dev "$IFACE"
    echo "---"
    tc -s class show dev "$IFACE"
    ;;
*)
    usage
    ;;
esac
