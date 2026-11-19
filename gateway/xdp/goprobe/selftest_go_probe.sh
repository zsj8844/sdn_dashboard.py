#!/usr/bin/env bash
# Go 版探针回路自测（阶段 2/3）：ringbuf → resolve → pending → flow_ready → READY。
# 不需要 Mininet；需要 root，先 make。
set -euo pipefail

NS=go-probe-test
VH=go-pvh
VN=go-pvn
HERE=$(cd "$(dirname "$0")" && pwd)
WORK=$(mktemp -d)
RECV=$WORK/recv.py
GW=$WORK/fake_gw.py
RECV_PID=
GW_PID=

cleanup() {
    [ -n "${RECV_PID:-}" ] && kill "$RECV_PID" 2>/dev/null || true
    [ -n "${GW_PID:-}" ] && kill "$GW_PID" 2>/dev/null || true
    ip netns del "$NS" 2>/dev/null || true
    ip link del "$VH" 2>/dev/null || true
    rm -rf "$WORK"
}
trap cleanup EXIT

[ "$(id -u)" = 0 ] || { echo "需要 root（sudo $0）"; exit 1; }
[ -x "$HERE/gw-xdp-go" ] || { echo "先执行 make"; exit 1; }
[ -f "$HERE/gw_filter_probe.o" ] || { echo "缺少 gw_filter_probe.o，先执行 make"; exit 1; }

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

# 假网关：收 resolve，回 pending；随后向探针客户端 socket 推 flow_ready。
cat > "$GW" <<'PY'
import json, os, socket, sys, time
path = sys.argv[1]
try:
    os.unlink(path)
except FileNotFoundError:
    pass
s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
s.bind(path)
s.settimeout(15)
data, addr = s.recvfrom(4096)
msg = json.loads(data)
assert msg.get("op") == "resolve", msg
reply = {"op": "resolve_reply", "key": msg["key"],
         "status": "pending", "target_ip": "10.97.0.2"}
s.sendto(json.dumps(reply).encode(), addr)
time.sleep(0.3)
ready = {"op": "flow_ready", "target_ip": "10.97.0.2", "ttl": 60}
s.sendto(json.dumps(ready).encode(), addr)
print("FAKE_GW pending + flow_ready 已发送", flush=True)
PY

echo "== 建 netns + veth =="
ip netns add "$NS"
ip link add "$VH" type veth peer name "$VN"
ip link set "$VN" netns "$NS"
ip addr add 10.97.0.1/24 dev "$VH"
ip link set "$VH" up
ip netns exec "$NS" ip addr add 10.97.0.2/24 dev "$VN"
ip netns exec "$NS" ip link set "$VN" up
ip netns exec "$NS" ip link set lo up

echo "== 启动接收端、假网关、Go 探针 =="
timeout 25 ip netns exec "$NS" /usr/bin/python3 "$RECV" 1000 > "$WORK/recv.out" 2>&1 &
RECV_PID=$!
/usr/bin/python3 "$GW" "$WORK/probe.sock" > "$WORK/gw.out" 2>&1 &
GW_PID=$!
ip netns exec "$NS" "$HERE/gw-xdp-go" \
    --ifaces "$VN" --mode skb --interval 1 --duration 7 \
    --probe-sock "$WORK/probe.sock" \
    --probe-client-sock "$WORK/client.sock" \
    --ttl 60 --json-out "$WORK/stats.json" --ready-file "$WORK/ready" &
LOADER=$!
for _ in $(seq 1 100); do
    [ -e "$WORK/ready" ] && break
    sleep 0.1
done
[ -e "$WORK/ready" ] || { echo "Go 探针未就绪（见上面的报错）"; exit 1; }

echo "== 注入 1000 个 5005 包 + 50 个非 5005 包 =="
/usr/bin/python3 - <<'PY'
import socket, time
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
payload = b"aa:bb:cc:dd:ee:01,temp,25.0"
for i in range(1000):
    s.sendto(payload, ("10.97.0.2", 5005))
    if i % 50 == 49:
        time.sleep(0.01)
for _ in range(50):
    s.sendto(b"noise", ("10.97.0.2", 9999))
PY

wait "$LOADER" || true
wait "$RECV_PID" 2>/dev/null || true
RECV_PID=
wait "$GW_PID" 2>/dev/null || true
GW_PID=

[ -f "$WORK/stats.json" ] || { echo "没有拿到 stats.json（探针提前退出？）"; exit 1; }
/usr/bin/python3 - "$WORK/stats.json" "$WORK/recv.out" "$WORK/gw.out" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
t = d["totals"]
p = d["probe"]
print(json.dumps(d, ensure_ascii=False, indent=2))
assert t["flow_miss"] >= 1, t
assert t["flow_cached"] + t["flow_miss"] == 1000, t
assert t["non_5005"] >= 50, t
assert t["dropped"] == 0, t
assert p["events"] >= 1, p
assert p["resolves"] >= 1, p
assert p["pending"] >= 1, p
assert p["flow_ready"] >= 1, p
assert p["ebpf_writes"] >= 1, p
got = open(sys.argv[2]).read().strip()
assert got == "1000", f"接收端收到 {got} 个包"
gw = open(sys.argv[3]).read()
assert "pending" in gw and "flow_ready" in gw, gw
print("PASS Go 版阶段 2：ringbuf → resolve → pending → flow_ready → READY")
PY

if ip netns exec "$NS" ip -d link show dev "$VN" | grep -qi xdp; then
    echo "退出后 XDP 仍在 $VN 上"
    exit 1
fi
echo "退场检查通过：$VN 上已无 XDP"
