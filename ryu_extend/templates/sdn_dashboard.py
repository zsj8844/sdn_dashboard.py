from flask import Flask, render_template, jsonify, request
import subprocess
import threading
import time
from collections import deque
import logging

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder='.')
app.config['JSON_AS_ASCII'] = False

# 基础配置
DEVICES = {
    "控制器": ["c0 (Ryu, 127.0.0.1:6634)"],
    "交换机": ["s1 (OpenFlow13)", "s2 (OpenFlow13)"],
    "物联网设备": ["iot1 (温度传感器, 192.168.1.10)", "iot2 (湿度传感器, 192.168.1.11)", 
                   "iot3 (网关, 192.168.1.12)", "iot4 (位置传感器, 192.168.1.13)"],
    "传统主机": ["h1 (终端, 192.168.1.20)", "h2 (终端, 192.168.1.21)"]
}

BLE_MESH_LOG = deque(maxlen=100)
BLE_MESH_NODES = [
    {"id": "aa:bb:cc:dd:ee:01", "type": "温度传感器", "status": "离线", "rssi": -80, "battery": 85},
    {"id": "aa:bb:cc:dd:ee:02", "type": "湿度传感器", "status": "离线", "rssi": -75, "battery": 92},
    {"id": "aa:bb:cc:dd:ee:03", "type": "网关", "status": "离线", "rssi": -65, "battery": 100},
    {"id": "aa:bb:cc:dd:ee:04", "type": "光照传感器", "status": "离线", "rssi": -85, "battery": 78}
]
CONNECTIVITY_STATUS = {}

def get_switch_flows(switch_name):
    try:
        result = subprocess.run(
            ["sudo", "ovs-ofctl", "dump-flows", switch_name, "-O", "OpenFlow13"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return [line.strip() for line in result.stdout.split("\n") if line.strip()]
        else:
            return []
    except Exception:
        return []

def check_connectivity_by_flows():
    while True:
        try:
            s1_flows = get_switch_flows("s1")
            s2_flows = get_switch_flows("s2")
            
            has_ble_flow = any("priority=10" in flow and "udp_dst=5005" in flow for flow in s1_flows)
            has_ble_log = len(BLE_MESH_LOG) > 0
            iot_gateway_status = "✅ 已连通" if has_ble_flow or has_ble_log else "❌ 未连通"
            controller_switch_status = "✅ 已连通" if len(s1_flows) > 0 and len(s2_flows) > 0 else "❌ 未连通"
            
            global CONNECTIVITY_STATUS
            CONNECTIVITY_STATUS = {
                "iot1 → 网关(iot3)": iot_gateway_status,
                "控制器 → 交换机": controller_switch_status
            }
            
            gateway_online = has_ble_flow or has_ble_log
            for node in BLE_MESH_NODES:
                if node["id"] == "aa:bb:cc:dd:ee:03":
                    node["status"] = "在线" if gateway_online else "离线"
                else:
                    recent_activity = any(node["id"] in log for log in BLE_MESH_LOG)
                    node["status"] = "在线" if recent_activity else "离线"
                
                if node["status"] == "在线":
                    node["rssi"] = max(-90, min(-50, node["rssi"] + (int(time.time()) % 3 - 1)))
                    node["battery"] = min(100, node["battery"] + 1) if node["battery"] < 100 else 100
                else:
                    node["rssi"] = max(-100, node["rssi"] - 1)
                    node["battery"] = max(0, node["battery"] - 1)
                    
        except Exception as e:
            logger.error(f"连通性检测异常: {e}")
        time.sleep(5)

def listen_ble_mesh_data():
    try:
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('0.0.0.0', 5005))
        logger.info("BLE数据监听已启动 (端口5005)")
        while True:
            try:
                data, addr = sock.recvfrom(1024)
                ble_data = data.decode('utf-8', errors='ignore').strip().split(",")
                if len(ble_data) == 3:
                    ble_addr, msg_type, value = ble_data
                    timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                    log_entry = f"[{timestamp}] {ble_addr} → {msg_type}：{value}"
                    BLE_MESH_LOG.appendleft(log_entry)
                    logger.info(f"接收到BLE数据: {log_entry}")
            except Exception as e:
                logger.warning(f"BLE数据解析警告: {e}")
                continue
    except Exception as e:
        logger.error(f"BLE监听错误: {e}")
        time.sleep(5)
        listen_ble_mesh_data()

# 路由定义
@app.route("/")
def index():
    return render_template("dashboard.html", devices=DEVICES)

@app.route("/health")
def health_check():
    return jsonify({
        "status": "healthy",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "ble_logs_count": len(BLE_MESH_LOG),
        "nodes_online": sum(1 for node in BLE_MESH_NODES if node["status"] == "在线")
    })

@app.route('/api/logs', methods=['POST'])
def receive_logs():
    try:
        log_data = request.json
        required_fields = ['ble_addr', 'type', 'value', 'src_ip']
        if not all(field in log_data for field in required_fields):
            return jsonify({"status": "error", "message": "缺少必要字段"}), 400
            
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        log_str = f"[{timestamp}] {log_data['ble_addr']} → {log_data['type']}：{log_data['value']} (来源：{log_data['src_ip']})"
        BLE_MESH_LOG.appendleft(log_str)
        logger.info(f"接收控制器日志: {log_str}")
        return jsonify({"status": "success"}), 200
    except Exception as e:
        logger.error(f"接收日志失败: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/data")
def api_data():
    return jsonify({
        "ble_mesh": {
            "nodes": BLE_MESH_NODES,
            "logs": list(BLE_MESH_LOG)
        },
        "connectivity": CONNECTIVITY_STATUS,
        "s1_flows": get_switch_flows("s1")[:10],
        "s2_flows": get_switch_flows("s2")[:10]
    })

@app.route('/api/clear-data', methods=['POST'])
def clear_data():
    try:
        BLE_MESH_LOG.clear()
        for node in BLE_MESH_NODES:
            node["status"] = "离线"
            node["rssi"] = -100
            node["battery"] = 100
        CONNECTIVITY_STATUS.clear()
        logger.info("数据已清空")
        return jsonify({"status": "success", "message": "数据清空完成"}), 200
    except Exception as e:
        logger.error(f"清空数据失败: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    threading.Thread(target=listen_ble_mesh_data, daemon=True, name="BLE_Listener").start()
    threading.Thread(target=check_connectivity_by_flows, daemon=True, name="Connectivity_Checker").start()
    
    logger.info("SDN IoT 监控面板启动")
    logger.info("访问地址: http://localhost:5000")
    
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)