from flask import Flask, render_template, jsonify, request
import subprocess
import threading
import time
from collections import deque, defaultdict
import logging
import json

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

GATEWAY_LOG = deque(maxlen=100)
S1_LOG = deque(maxlen=100)
S2_LOG = deque(maxlen=100)
BLE_MESH_NODES = [
    {"id": "aa:bb:cc:dd:ee:01", "type": "温度传感器", "status": "离线", "rssi": -80, "battery": 85},
    {"id": "aa:bb:cc:dd:ee:02", "type": "湿度传感器", "status": "离线", "rssi": -75, "battery": 92},
    {"id": "aa:bb:cc:dd:ee:03", "type": "网关", "status": "离线", "rssi": -65, "battery": 100},
    {"id": "aa:bb:cc:dd:ee:04", "type": "光照传感器", "status": "离线", "rssi": -85, "battery": 78}
]
CONNECTIVITY_STATUS = {}
SWITCHES_STATUS = {
    "s1": {"connected": False, "last_seen": None, "dpid": None},
    "s2": {"connected": False, "last_seen": None, "dpid": None}
}

# ============ 新增功能数据存储 ============
TOPOLOGY = {
    'switches': [],
    'links': [],
    'hosts': [],
    'timestamp': None
}

PORT_STATS = defaultdict(list)
FLOW_STATS = defaultdict(list)
TABLE_STATS = defaultdict(dict)
CURRENT_FLOWS = defaultdict(dict)

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

def get_switches_status():
    try:
        result = subprocess.run(
            ["sudo", "ovs-vsctl", "list-br"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            bridges = result.stdout.strip().split("\n")
            return [bridge for bridge in bridges if bridge in ["s1", "s2"]]
        else:
            return []
    except Exception:
        return []

def get_switch_dpid(switch_name):
    try:
        result = subprocess.run(
            ["sudo", "ovs-ofctl", "show", switch_name],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if "dpid:" in line:
                    dpid = line.split("dpid:")[1].strip().split()[0]
                    return dpid
        return None
    except Exception:
        return None

def check_connectivity_by_flows():
    while True:
        try:
            s1_flows = get_switch_flows("s1")
            s2_flows = get_switch_flows("s2")
            
            current_time = time.time()
            switches_connected = get_switches_status()
            
            global SWITCHES_STATUS
            for switch in ["s1", "s2"]:
                is_connected = switch in switches_connected
                if is_connected:
                    dpid = get_switch_dpid(switch)
                    SWITCHES_STATUS[switch]["connected"] = True
                    SWITCHES_STATUS[switch]["last_seen"] = current_time
                    if dpid:
                        SWITCHES_STATUS[switch]["dpid"] = dpid
                else:
                    SWITCHES_STATUS[switch]["connected"] = False
            
            has_ble_flow = any("priority=10" in flow and "udp_dst=5005" in flow for flow in s1_flows)
            has_gateway_log = len(GATEWAY_LOG) > 0
            iot_gateway_status = "✅ 已连通" if has_ble_flow or has_gateway_log else "❌ 未连通"
            
            s1_connected = SWITCHES_STATUS["s1"]["connected"] and len(s1_flows) > 0
            s2_connected = SWITCHES_STATUS["s2"]["connected"] and len(s2_flows) > 0
            controller_switch_status = "✅ 已连通" if s1_connected or s2_connected else "❌ 未连通"
            
            global CONNECTIVITY_STATUS
            CONNECTIVITY_STATUS = {
                "iot1 → 网关(iot3)": iot_gateway_status,
                "控制器 → 交换机": controller_switch_status
            }
            
            gateway_online = has_ble_flow or has_gateway_log
            for node in BLE_MESH_NODES:
                if node["id"] == "aa:bb:cc:dd:ee:03":
                    node["status"] = "在线" if gateway_online else "离线"
                else:
                    recent_activity = any(node["id"] in log for log in GATEWAY_LOG)
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
                    GATEWAY_LOG.appendleft(log_entry)
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
        "gateway_logs_count": len(GATEWAY_LOG),
        "s1_logs_count": len(S1_LOG),
        "s2_logs_count": len(S2_LOG),
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
        GATEWAY_LOG.appendleft(log_str)
        logger.info(f"接收网关日志: {log_str}")
        return jsonify({"status": "success"}), 200
    except Exception as e:
        logger.error(f"接收日志失败: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/logs/s1', methods=['POST'])
def receive_s1_logs():
    try:
        log_data = request.json
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        log_str = f"[{timestamp}] {log_data.get('message', 'S1 数据包')}"
        S1_LOG.appendleft(log_str)
        logger.info(f"接收S1日志: {log_str}")
        return jsonify({"status": "success"}), 200
    except Exception as e:
        logger.error(f"接收S1日志失败: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/logs/s2', methods=['POST'])
def receive_s2_logs():
    try:
        log_data = request.json
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        log_str = f"[{timestamp}] {log_data.get('message', 'S2 数据包')}"
        S2_LOG.appendleft(log_str)
        logger.info(f"接收S2日志: {log_str}")
        return jsonify({"status": "success"}), 200
    except Exception as e:
        logger.error(f"接收S2日志失败: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/data")
def api_data():
    return jsonify({
        "ble_mesh": {
            "nodes": BLE_MESH_NODES
        },
        "gateway_logs": list(GATEWAY_LOG),
        "s1_logs": list(S1_LOG),
        "s2_logs": list(S2_LOG),
        "s1_flows": get_switch_flows("s1")[:10],
        "s2_flows": get_switch_flows("s2")[:10],
        "switches_status": SWITCHES_STATUS.copy()
    })

@app.route('/api/clear-data', methods=['POST'])
def clear_data():
    try:
        GATEWAY_LOG.clear()
        S1_LOG.clear()
        S2_LOG.clear()
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

# ============ 新增功能：拓扑管理API ============
@app.route('/api/topology', methods=['GET', 'POST'])
def topology_api():
    if request.method == 'POST':
        try:
            topology_data = request.json
            global TOPOLOGY
            TOPOLOGY = topology_data
            logger.info(f"接收拓扑数据: {len(topology_data['switches'])} 交换机, {len(topology_data['links'])} 链接, {len(topology_data['hosts'])} 主机")
            return jsonify({"status": "success"}), 200
        except Exception as e:
            logger.error(f"接收拓扑数据失败: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500
    else:
        return jsonify(TOPOLOGY)

# ============ 新增功能：统计数据API ============
@app.route('/api/stats', methods=['GET', 'POST'])
def stats_api():
    if request.method == 'POST':
        try:
            stats_data = request.json
            stats_type = stats_data.get('type')
            dpid = stats_data.get('dpid')
            data = stats_data.get('data')
            
            if stats_type == 'port_stats':
                PORT_STATS[dpid] = data
            elif stats_type == 'flow_stats':
                FLOW_STATS[dpid] = data
            elif stats_type == 'table_stats':
                TABLE_STATS[dpid] = data
            
            logger.debug(f"接收{stats_type}数据: dpid={dpid}")
            return jsonify({"status": "success"}), 200
        except Exception as e:
            logger.error(f"接收统计数据失败: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500
    else:
        return jsonify({
            'port_stats': dict(PORT_STATS),
            'flow_stats': dict(FLOW_STATS),
            'table_stats': dict(TABLE_STATS)
        })

# ============ 新增功能：流表管理API ============
@app.route('/api/flows', methods=['GET', 'POST', 'DELETE'])
def flows_api():
    if request.method == 'POST':
        try:
            flow_data = request.json
            dpid = flow_data.get('dpid')
            switch_name = f's{dpid}' if dpid else None
            
            if not switch_name or switch_name not in ['s1', 's2']:
                return jsonify({"status": "error", "message": "无效的交换机ID"}), 400
            
            priority = flow_data.get('priority', 10)
            table_id = flow_data.get('table_id', 0)
            match_str = flow_data.get('match', '')
            actions_str = flow_data.get('actions', 'output:2')
            
            cmd = [
                "sudo", "ovs-ofctl", "add-flow", switch_name, "-O", "OpenFlow13",
                f"table={table_id},priority={priority},{match_str},actions={actions_str}"
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                logger.info(f"添加流表成功: {switch_name} - table={table_id}, priority={priority}")
                return jsonify({"status": "success", "message": "流表添加成功"}), 200
            else:
                return jsonify({"status": "error", "message": result.stderr}), 400
        except Exception as e:
            logger.error(f"添加流表失败: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500
    
    elif request.method == 'DELETE':
        try:
            flow_data = request.json
            dpid = flow_data.get('dpid')
            switch_name = f's{dpid}' if dpid else None
            table_id = flow_data.get('table_id')
            
            if not switch_name or switch_name not in ['s1', 's2']:
                return jsonify({"status": "error", "message": "无效的交换机ID"}), 400
            
            if table_id is not None:
                cmd = ["sudo", "ovs-ofctl", "del-flows", switch_name, "-O", "OpenFlow13", f"table={table_id}"]
            else:
                cmd = ["sudo", "ovs-ofctl", "del-flows", switch_name, "-O", "OpenFlow13"]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                logger.info(f"清空流表成功: {switch_name}")
                return jsonify({"status": "success", "message": "流表清空成功"}), 200
            else:
                return jsonify({"status": "error", "message": result.stderr}), 400
        except Exception as e:
            logger.error(f"清空流表失败: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500
    
    else:
        dpid = request.args.get('dpid')
        if dpid:
            switch_name = f's{dpid}'
            return jsonify({
                'flows': get_switch_flows(switch_name),
                'dpid': dpid
            })
        else:
            return jsonify({
                's1_flows': get_switch_flows('s1'),
                's2_flows': get_switch_flows('s2')
            })

# ============ 新增功能：增强版面板路由 ============
@app.route("/enhanced")
def enhanced_dashboard():
    return render_template("dashboard_enhanced.html", devices=DEVICES)

if __name__ == "__main__":
    threading.Thread(target=listen_ble_mesh_data, daemon=True, name="BLE_Listener").start()
    threading.Thread(target=check_connectivity_by_flows, daemon=True, name="Connectivity_Checker").start()
    
    logger.info("SDN IoT 监控面板启动（增强版）")
    logger.info("普通面板: http://localhost:5000")
    logger.info("增强版面板: http://localhost:5000/enhanced")
    
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
