#!/usr/bin/env bash
# Gin 面板 API 冒烟测试：不碰 UDP 5005 / OVS，跑完自动退出。
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
BASE=$(cd "$HERE/.." && pwd)
BIN="$BASE/bin/dashboard-go"
PORT=${PORT:-15001}
LOG=$(mktemp)
PID=

cleanup() {
    [ -n "${PID:-}" ] && kill "$PID" 2>/dev/null || true
    rm -f "$LOG"
}
trap cleanup EXIT

[ -x "$BIN" ] || { echo "先执行 make"; exit 1; }

"$BIN" --base "$BASE" --port "$PORT" --no-ble --no-connectivity > "$LOG" 2>&1 &
PID=$!

for _ in $(seq 1 50); do
    if curl -sf "http://127.0.0.1:$PORT/health" > /dev/null; then
        break
    fi
    sleep 0.1
done
curl -sf "http://127.0.0.1:$PORT/health" > /dev/null || { cat "$LOG"; exit 1; }

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

status, health = call("GET", "/health")
assert status == 200 and health["status"] == "healthy", health

status, data = call("GET", "/api/data")
assert status == 200
for key in ("s1_logs", "s2_logs", "s1_flows", "s2_flows"):
    assert data[key] == [], (key, data[key])

status, _ = call("POST", "/api/logs", {
    "ble_addr": "aa:bb:cc:dd:ee:01", "type": "temp",
    "value": 25, "src_ip": "192.168.2.10",
})
assert status == 200

status, iot = call("POST", "/api/iot-extension", {"sensor_type": "gas"})
assert status == 200
status, iot = call("GET", "/api/iot-extension")
assert iot.get("sensor_type") == "gas" and "timestamp" in iot, iot

status, _ = call("POST", "/api/topology", {"switches": [1], "links": [], "hosts": []})
assert status == 200
status, topo = call("GET", "/api/topology")
assert topo["switches"] == [1], topo

status, _ = call("POST", "/api/stats", {"type": "port_stats", "dpid": 1, "data": [1]})
assert status == 200
status, stats = call("GET", "/api/stats")
assert stats["port_stats"]["1"] == [1], stats

status, app = call("POST", "/api/apps", {
    "app_id": "smoke-app", "app_name": "smoke", "app_type": 1,
    "app_code": "print(1)", "version": "1.0.0",
})
assert status == 200, app
status, _ = call("POST", "/api/apps/smoke-app/deploy", {"device_id": "d1"})
assert status == 200
status, hist = call("GET", "/api/apps/smoke-app/history")
assert len(hist["history"]) == 1, hist
status, _ = call("DELETE", "/api/apps/smoke-app")
assert status == 200

status, dev = call("POST", "/api/devices", {
    "device_id": "d1", "device_name": "edge", "initial_mode": 1,
    "capabilities": {"cpu_cores": 4, "memory_mb": 2048,
                     "supports_nat": True, "supports_ble": True},
})
assert status == 200, dev
status, rec = call("POST", "/api/devices/d1/switch-mode", {"target_mode": 2})
assert status == 200 and rec["record"]["new_mode"] == "COMPUTE_HYBRID", rec
status, ident = call("POST", "/api/devices/d1/identify",
                     {"resource_usage": {"cpu_usage": 80}})
assert ident["identified_mode"] == 2, ident
status, _ = call("DELETE", "/api/devices/d1")
assert status == 200

status, _ = call("POST", "/api/logs", {"type": "temp"})
assert status == 400

print("ALL SMOKE ASSERTIONS PASSED")
PY

echo "PASS：Gin 面板 API 冒烟测试"
