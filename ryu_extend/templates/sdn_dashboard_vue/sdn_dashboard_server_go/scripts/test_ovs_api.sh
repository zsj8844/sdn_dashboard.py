#!/usr/bin/env bash
# 真实 OVS 验证：连通性轮询 + 流表增删（需要 root，会临时创建/删除 s1）。
# 如果已存在 s1（例如 Mininet 正在运行），脚本会拒绝执行。
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
BASE=$(cd "$HERE/.." && pwd)
BIN="$BASE/bin/dashboard-go"
PORT=${PORT:-15002}
BR=s1
LOG=$(mktemp)
PID=

cleanup() {
    [ -n "${PID:-}" ] && kill "$PID" 2>/dev/null || true
    timeout 10 ovs-vsctl --timeout=5 del-br "$BR" 2>/dev/null || true
    rm -f "$LOG"
}
trap cleanup EXIT

[ "$(id -u)" = 0 ] || { echo "需要 root：sudo $0"; exit 1; }
if ! pgrep -x ovs-vswitchd > /dev/null; then
    echo "ovs-vswitchd 未运行，ovs-vsctl 会一直等待。"
    echo "先执行: sudo systemctl start openvswitch-switch"
    exit 1
fi
if timeout 10 ovs-vsctl --timeout=5 br-exists "$BR" 2>/dev/null; then
    echo "已存在网桥 $BR，可能是运行中的 Mininet；为安全起见不测试。"
    exit 1
fi
if ! timeout 10 ovs-vsctl --timeout=5 add-br "$BR"; then
    echo "创建 $BR 失败：确认 openvswitch-switch 服务在运行。"
    exit 1
fi

"$BIN" --base "$BASE" --port "$PORT" --no-ble > "$LOG" 2>&1 &
PID=$!
for _ in $(seq 1 50); do
    curl -sf "http://127.0.0.1:$PORT/health" > /dev/null && break
    sleep 0.1
done
curl -sf "http://127.0.0.1:$PORT/health" > /dev/null || { cat "$LOG"; exit 1; }

# 等一轮 5s 连通性轮询
sleep 6

/usr/bin/python3 - "$PORT" <<'PY'
import json, sys, urllib.request, urllib.error
port = sys.argv[1]
base = f"http://127.0.0.1:{port}"

def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")

status, data = call("GET", "/api/data")
assert status == 200, status
sw = data["switches_status"]["s1"]
assert sw["connected"] is True, sw
assert sw["dpid"], sw
print("connectivity: s1 connected dpid=%s" % sw["dpid"])

status, resp = call("POST", "/api/flows", {
    "dpid": 1, "priority": 123,
    "match": "ip,nw_dst=192.168.1.20", "actions": "drop",
})
assert status == 200, (status, resp)

status, flows = call("GET", "/api/flows?dpid=1")
assert status == 200, status
text = "\n".join(flows["flows"])
assert "priority=123" in text, flows["flows"]
print("add-flow: priority=123 visible")

status, resp = call("DELETE", "/api/flows", {"dpid": 1})
assert status == 200, (status, resp)

status, flows = call("GET", "/api/flows?dpid=1")
assert status == 200
assert "priority=123" not in "\n".join(flows["flows"]), flows["flows"]
print("del-flows: priority=123 removed")

status, data = call("GET", "/api/data")
assert status == 200
assert isinstance(data["s1_flows"], list), data["s1_flows"]
print("PASS OVS API: connectivity + add/del flow")
PY

echo "PASS：Gin 面板真实 OVS 验证"
