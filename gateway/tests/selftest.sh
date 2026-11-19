#!/usr/bin/env bash
# 不依赖 Mininet 的 XDP filter 自测（阶段 1 的 T1/T7）。
# 需要 root。临时创建 netns xdp-selftest + 两条 veth，退出时清理。
#
# 覆盖：
#   1) 只统计：1000 个 UDP 5005 全部计数且 Python 收到；非 5005 单独计数；解析错误 0
#      （同一 5 元组：首包 flow_miss，其余 flow_cached，两者之和 = 1000）
#   2) 丢弃分支（cfg=1）：非 5005 被丢，5005 的计数不受影响
#   3) 多接口挂载（两个 veth，对应拓扑里 iot3-eth0/1/2）
#   4) 退场：退出后接口上不再有 xdp 程序
set -euo pipefail

NS=xdp-selftest
VH1=sel-vh1; VN1=sel-vn1
VH2=sel-vh2; VN2=sel-vn2
PY=/usr/bin/python3
HERE=$(cd "$(dirname "$0")" && pwd)
XDP=$(cd "$HERE/../xdp" && pwd)
WORK=$(mktemp -d)
RECV=$WORK/recv.py
RECV_PID=

cleanup() {
    [ -n "${RECV_PID:-}" ] && kill "$RECV_PID" 2>/dev/null || true
    ip netns del "$NS" 2>/dev/null || true
    ip link del "$VH1" 2>/dev/null || true
    ip link del "$VH2" 2>/dev/null || true
    rm -rf "$WORK"
}
trap cleanup EXIT

[ "$(id -u)" = 0 ] || { echo "需要 root（sudo $0）"; exit 1; }

cat > "$RECV" <<'PY'
import socket, sys
want = int(sys.argv[1])
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 << 20)
s.bind(("0.0.0.0", 5005))
n = 0
while n < want:
    s.recvfrom(2048)
    n += 1
print(n, flush=True)
PY

start_loader() {
    local out=$1 ready=$2
    shift 2
    rm -f "$ready"
    ip netns exec "$NS" "$PY" "$XDP/gw_xdp_filter.py" --ifaces "$VN1" "$VN2" \
        --interval 1 --json-out "$out" --ready-file "$ready" "$@" &
    LOADER=$!
    for _ in $(seq 1 150); do
        if [ -e "$ready" ]; then return 0; fi
        sleep 0.1
    done
    echo "XDP 挂载未就绪（见上面的报错）"
    exit 1
}

assert_json() {
    local out=$1
    shift
    "$PY" - "$out" "$@" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
t = d["totals"]
checks = sys.argv[2:]
print(json.dumps(d, ensure_ascii=False, indent=2))
for c in checks:
    expr = c
    if not eval(expr, {"t": t}):   # 自测脚本内部使用，输入来自本脚本
        raise SystemExit(f"断言失败: {expr} -> {t}")
print("断言通过:", ", ".join(checks))
PY
}

check_detached() {
    for i in "$VN1" "$VN2"; do
        if ip netns exec "$NS" ip -d link show dev "$i" | grep -qi xdp; then
            echo "退出后 XDP 仍在 $i 上（退场回滚失败）"
            exit 1
        fi
    done
    echo "退场检查通过：两个接口上都没有 XDP"
}

echo "== 建 netns + 两条 veth =="
ip netns add "$NS"
ip link add "$VH1" type veth peer name "$VN1"
ip link add "$VH2" type veth peer name "$VN2"
ip link set "$VN1" netns "$NS"
ip link set "$VN2" netns "$NS"
ip addr add 10.99.0.1/24 dev "$VH1"
ip addr add 10.99.1.1/24 dev "$VH2"
ip link set "$VH1" up
ip link set "$VH2" up
ip netns exec "$NS" ip addr add 10.99.0.2/24 dev "$VN1"
ip netns exec "$NS" ip addr add 10.99.1.2/24 dev "$VN2"
ip netns exec "$NS" ip link set "$VN1" up
ip netns exec "$NS" ip link set "$VN2" up
ip netns exec "$NS" ip link set lo up

echo "== T1：只统计（两个接口都挂）=="
timeout 20 ip netns exec "$NS" "$PY" "$RECV" 1000 > "$WORK/recv.out" 2>&1 &
RECV_PID=$!
start_loader "$WORK/stats1.json" "$WORK/ready1" --duration 10 --mode auto --no-probe
"$PY" - <<'PY'
import socket, time
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
payload = b"aa:bb:cc:dd:ee:01,temp,25.0"
for i in range(1000):
    s.sendto(payload, ("10.99.0.2", 5005))
    if i % 50 == 49:
        time.sleep(0.01)
for _ in range(50):
    s.sendto(b"noise", ("10.99.0.2", 9999))
PY
wait "$LOADER" || true
wait "$RECV_PID" 2>/dev/null || true
RECV_PID=

[ -f "$WORK/stats1.json" ] || { echo "没有拿到计数文件（加载器提前退出？）"; exit 1; }
if [ "$(cat "$WORK/recv.out")" != "1000" ]; then
    echo "接收端没有收满 1000 个包（XDP 的 PASS 或数据面有问题）"
    exit 1
fi
assert_json "$WORK/stats1.json" \
    't["flow_miss"] >= 1' 't["flow_cached"] + t["flow_miss"] == 1000' \
    't["non_5005"] >= 50' 't["parse_error"] == 0' 't["dropped"] == 0'

check_detached

echo "== T7：打开 cfg 丢弃非 5005 =="
start_loader "$WORK/stats2.json" "$WORK/ready2" --duration 6 --mode skb --no-probe --set-cfg drop-non5005
"$PY" - <<'PY'
import socket, time
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
for _ in range(100):
    s.sendto(b"aa:bb:cc:dd:ee:01,temp,25.0", ("10.99.0.2", 5005))
for _ in range(100):
    s.sendto(b"noise", ("10.99.0.2", 9999))
time.sleep(0.2)
PY
wait "$LOADER" || true

[ -f "$WORK/stats2.json" ] || { echo "没有拿到计数文件（加载器提前退出？）"; exit 1; }
assert_json "$WORK/stats2.json" \
    't["flow_cached"] + t["flow_miss"] == 100' \
    't["non_5005"] >= 100' 't["dropped"] >= 100' 't["parse_error"] == 0'

check_detached

echo "PASS 阶段 1：T1 只统计 + T7 丢弃分支 + 多接口挂载 + 退场回滚"
