from flask import Flask, render_template, jsonify, request, send_from_directory
import subprocess
import threading
import time
from collections import deque, defaultdict
import logging
import json
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../switch')))
from extensions import (
    AppDeploymentManager, EdgeApplication, AppType, AppStatus,
    DeviceRoleManager, DeviceMode, DeviceCapabilities
)
from Other_Modules import config_manager

# 配置日志
log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../../logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'controller.log')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Vue 前端构建产物的路径（生产模式使用）
VUE_DIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../sdn_dashboard_view/dist')

app = Flask(
    __name__,
    static_folder=os.path.join(VUE_DIST, 'assets'),
    template_folder=VUE_DIST
)
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

APP_DEPLOYMENT_MANAGER = AppDeploymentManager()
DEVICE_ROLE_MANAGER = DeviceRoleManager()

# IoT扩展字段存储
IOT_EXTENSION_DATA = None


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


def get_gateway_logs():
    """从gateway.log文件读取最新的100行日志"""
    try:
        log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../../logs/gateway.log')
        if not os.path.exists(log_path):
            log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../logs/gateway.log')

        if os.path.exists(log_path):
            with open(log_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                logs = [line.strip() for line in lines if line.strip()]
                return list(reversed(logs[-100:]))
        return list(GATEWAY_LOG)
    except Exception as e:
        logger.error(f"读取网关日志失败: {e}")
        return list(GATEWAY_LOG)


def convert_match_keywords(match_str):
    keyword_map = {
        'ipv4_src': 'nw_src',
        'ipv4_dst': 'nw_dst',
        'tcp_src': 'tp_src',
        'tcp_dst': 'tp_dst',
        'udp_src': 'tp_src',
        'udp_dst': 'tp_dst'
    }
    for ryu_key, ovs_key in keyword_map.items():
        match_str = match_str.replace(ryu_key, ovs_key)
    return match_str


def device_to_dict(device):
    return {
        'device_id': device['device_id'],
        'device_name': device['device_name'],
        'current_mode': device['current_mode'].value,
        'current_mode_name': device['current_mode'].name,
        'capabilities': {
            'cpu_cores': device['capabilities'].cpu_cores,
            'memory_mb': device['capabilities'].memory_mb,
            'storage_mb': device['capabilities'].storage_mb,
            'network_ports': device['capabilities'].network_ports,
            'supports_nat': device['capabilities'].supports_nat,
            'supports_container': device['capabilities'].supports_container,
            'supports_ble': device['capabilities'].supports_ble
        },
        'registered_at': device['registered_at'],
        'last_mode_switch': device['last_mode_switch'],
        'switch_count': device['switch_count']
    }


# ============ Vue SPA 前端路由 ============

@app.route("/")
def index():
    """生产模式：托管 Vue SPA"""
    if os.path.exists(VUE_DIST):
        return send_from_directory(VUE_DIST, 'index.html')
    return jsonify({
        "message": "SDN Dashboard API Server",
        "mode": "development",
        "tip": "请启动 Vue 开发服务器: cd sdn_dashboard_view && npm run dev"
    })


@app.route("/<path:path>")
def spa_fallback(path):
    """SPA fallback: 非 API 路由全部返回 index.html"""
    if os.path.exists(VUE_DIST):
        file_path = os.path.join(VUE_DIST, path)
        if os.path.isfile(file_path):
            return send_from_directory(VUE_DIST, path)
        return send_from_directory(VUE_DIST, 'index.html')
    return jsonify({"error": "Not found", "path": path}), 404


# ============ 健康检查 ============

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


# ============ 日志 API ============

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


# ============ 数据 API ============

@app.route("/api/data")
def api_data():
    return jsonify({
        "ble_mesh": {
            "nodes": BLE_MESH_NODES
        },
        "gateway_logs": get_gateway_logs(),
        "s1_logs": list(S1_LOG),
        "s2_logs": list(S2_LOG),
        "s1_flows": get_switch_flows("s1")[:10],
        "s2_flows": get_switch_flows("s2")[:10],
        "switches_status": SWITCHES_STATUS.copy(),
        "iot_extension": IOT_EXTENSION_DATA
    })


@app.route('/api/iot-extension', methods=['GET', 'POST'])
def iot_extension_api():
    if request.method == 'POST':
        try:
            global IOT_EXTENSION_DATA
            extension_data = request.json
            IOT_EXTENSION_DATA = extension_data
            IOT_EXTENSION_DATA['timestamp'] = time.time()
            logger.info(f"接收IoT扩展字段: {extension_data}")
            return jsonify({"status": "success"}), 200
        except Exception as e:
            logger.error(f"接收IoT扩展字段失败: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500
    else:
        return jsonify(IOT_EXTENSION_DATA or {})


@app.route('/api/clear-data', methods=['POST'])
def clear_data():
    try:
        GATEWAY_LOG.clear()
        S1_LOG.clear()
        S2_LOG.clear()
        global IOT_EXTENSION_DATA
        IOT_EXTENSION_DATA = None
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


# ============ 拓扑管理 API ============

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


# ============ 统计数据 API ============

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


# ============ 流表管理 API ============

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

            match_str = convert_match_keywords(match_str)

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


# ============ 边缘应用管理 API ============

@app.route('/api/apps', methods=['GET', 'POST'])
def apps_api():
    if request.method == 'POST':
        try:
            app_data = request.json
            app_id = app_data.get('app_id')
            app_name = app_data.get('app_name')
            app_type = AppType(app_data.get('app_type'))
            app_code = app_data.get('app_code')
            version = app_data.get('version', '1.0.0')
            description = app_data.get('description', '')

            app = APP_DEPLOYMENT_MANAGER.create_application(
                app_id, app_name, app_type, app_code, version, description)
            logger.info(f"创建应用成功: {app_id} - {app_name}")
            return jsonify({"status": "success", "app": app.to_dict()}), 200
        except Exception as e:
            logger.error(f"创建应用失败: {e}")
            return jsonify({"status": "error", "message": str(e)}), 400
    else:
        apps = APP_DEPLOYMENT_MANAGER.list_applications()
        return jsonify({"apps": [app.to_dict() for app in apps]})


@app.route('/api/apps/<app_id>', methods=['GET', 'DELETE'])
def app_detail_api(app_id):
    if request.method == 'DELETE':
        try:
            app = APP_DEPLOYMENT_MANAGER.get_application(app_id)
            if not app:
                return jsonify({"status": "error", "message": f"应用 {app_id} 不存在"}), 404
            del APP_DEPLOYMENT_MANAGER.applications[app_id]
            logger.info(f"删除应用成功: {app_id}")
            return jsonify({"status": "success", "message": "应用已删除"}), 200
        except Exception as e:
            logger.error(f"删除应用失败: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500
    else:
        app = APP_DEPLOYMENT_MANAGER.get_application(app_id)
        if app:
            return jsonify(app.to_dict())
        return jsonify({"status": "error", "message": "应用不存在"}), 404


@app.route('/api/apps/<app_id>/deploy', methods=['POST'])
def deploy_app_api(app_id):
    try:
        device_id = request.json.get('device_id')
        if not device_id:
            return jsonify({"status": "error", "message": "缺少设备ID"}), 400
        record = APP_DEPLOYMENT_MANAGER.deploy_application(app_id, device_id)
        logger.info(f"部署应用成功: {app_id} -> {device_id}")
        return jsonify({"status": "success", "record": record}), 200
    except Exception as e:
        logger.error(f"部署应用失败: {e}")
        return jsonify({"status": "error", "message": str(e)}), 400


@app.route('/api/apps/<app_id>/undeploy', methods=['POST'])
def undeploy_app_api(app_id):
    try:
        device_id = request.json.get('device_id')
        if not device_id:
            return jsonify({"status": "error", "message": "缺少设备ID"}), 400
        record = APP_DEPLOYMENT_MANAGER.undeploy_application(app_id, device_id)
        logger.info(f"卸载应用成功: {app_id} -> {device_id}")
        return jsonify({"status": "success", "record": record}), 200
    except Exception as e:
        logger.error(f"卸载应用失败: {e}")
        return jsonify({"status": "error", "message": str(e)}), 400


@app.route('/api/apps/<app_id>/history', methods=['GET'])
def app_history_api(app_id):
    try:
        history = APP_DEPLOYMENT_MANAGER.get_deployment_history(app_id)
        return jsonify({"history": history})
    except Exception as e:
        logger.error(f"获取部署历史失败: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ============ 设备角色管理 API ============

@app.route('/api/devices', methods=['GET', 'POST'])
def devices_api():
    if request.method == 'POST':
        try:
            data = request.json
            device_id = data.get('device_id')
            device_name = data.get('device_name')
            initial_mode = DeviceMode(data.get('initial_mode', 1))

            capabilities_data = data.get('capabilities', {})
            capabilities = DeviceCapabilities(
                cpu_cores=capabilities_data.get('cpu_cores', 1),
                memory_mb=capabilities_data.get('memory_mb', 512),
                storage_mb=capabilities_data.get('storage_mb', 1024),
                network_ports=capabilities_data.get('network_ports', 2),
                supports_nat=capabilities_data.get('supports_nat', False),
                supports_container=capabilities_data.get('supports_container', False),
                supports_ble=capabilities_data.get('supports_ble', False)
            )

            device = DEVICE_ROLE_MANAGER.register_device(
                device_id, device_name, initial_mode, capabilities)
            logger.info(f"注册设备成功: {device_id} - {device_name}")
            return jsonify({"status": "success", "device": device_to_dict(device)}), 200
        except Exception as e:
            logger.error(f"注册设备失败: {e}")
            return jsonify({"status": "error", "message": str(e)}), 400
    else:
        devices = DEVICE_ROLE_MANAGER.list_devices()
        return jsonify({"devices": [device_to_dict(d) for d in devices]})


@app.route('/api/devices/<device_id>', methods=['GET', 'DELETE'])
def device_detail_api(device_id):
    if request.method == 'DELETE':
        try:
            device = DEVICE_ROLE_MANAGER.get_device(device_id)
            if not device:
                return jsonify({"status": "error", "message": f"设备 {device_id} 不存在"}), 404
            del DEVICE_ROLE_MANAGER.devices[device_id]
            logger.info(f"删除设备成功: {device_id}")
            return jsonify({"status": "success", "message": "设备已删除"}), 200
        except Exception as e:
            logger.error(f"删除设备失败: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500
    else:
        device = DEVICE_ROLE_MANAGER.get_device(device_id)
        if device:
            return jsonify(device_to_dict(device))
        return jsonify({"status": "error", "message": "设备不存在"}), 404


@app.route('/api/devices/<device_id>/switch-mode', methods=['POST'])
def switch_device_mode_api(device_id):
    try:
        data = request.json
        target_mode = DeviceMode(data.get('target_mode'))
        force = data.get('force', False)

        record = DEVICE_ROLE_MANAGER.switch_mode(device_id, target_mode, force)
        logger.info(f"切换设备模式成功: {device_id} -> {target_mode.name}")
        return jsonify({"status": "success", "record": record}), 200
    except Exception as e:
        logger.error(f"切换设备模式失败: {e}")
        return jsonify({"status": "error", "message": str(e)}), 400


@app.route('/api/devices/<device_id>/identify', methods=['POST'])
def identify_device_mode_api(device_id):
    try:
        data = request.json or {}
        traffic_pattern = data.get('traffic_pattern')
        resource_usage = data.get('resource_usage')

        mode = DEVICE_ROLE_MANAGER.identify_device_mode(device_id, traffic_pattern, resource_usage)
        available_modes = DEVICE_ROLE_MANAGER.get_available_modes(device_id)

        return jsonify({
            "status": "success",
            "identified_mode": mode.value,
            "identified_mode_name": mode.name,
            "available_modes": [m.value for m in available_modes],
            "available_mode_names": [m.name for m in available_modes]
        }), 200
    except Exception as e:
        logger.error(f"识别设备模式失败: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/devices/<device_id>/history', methods=['GET'])
def device_switch_history_api(device_id):
    try:
        history = DEVICE_ROLE_MANAGER.get_switch_history(device_id)
        return jsonify({"history": history})
    except Exception as e:
        logger.error(f"获取设备切换历史失败: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500



# ==================== 设备身份配置 ====================

@app.route('/api/device-identity/config', methods=['GET'])
def get_device_identity_config():
    """获取全部设备身份配置"""
    return jsonify(config_manager.get_config())


@app.route('/api/device-identity/config', methods=['PUT'])
def update_device_identity_config():
    """整量替换设备身份配置"""
    new_config = request.json
    if 'devices' not in new_config:
        return jsonify({"status": "error", "message": "缺少devices字段"}), 400
    config_manager.save_config(new_config)
    logger.info("设备身份配置已全局更新")
    return jsonify({"status": "success"}), 200


@app.route('/api/device-identity/device', methods=['POST'])
def add_device_identity():
    """添加单个设备身份映射"""
    data = request.json
    ip = data.get('ip', '').strip()
    if not ip:
        return jsonify({"status": "error", "message": "缺少IP地址"}), 400
    config = config_manager.get_config()
    config['devices'][ip] = {
        "device_id": data.get('device_id', ''),
        "device_name": data.get('device_name', ''),
        "device_type": data.get('device_type', 'host'),
        "role": data.get('role', 'host'),
        "description": data.get('description', '')
    }
    config_manager.save_config(config)
    logger.info(f"添加设备身份映射: {ip} -> {data.get('device_id')}")
    return jsonify({"status": "success"}), 200


@app.route('/api/device-identity/device/<ip>', methods=['PUT'])
def update_device_identity(ip):
    """修改单个设备身份映射"""
    data = request.json
    config = config_manager.get_config()
    if ip not in config['devices']:
        return jsonify({"status": "error", "message": f"IP {ip} 不存在"}), 404
    for field in ['device_id', 'device_name', 'device_type', 'role', 'description']:
        if field in data:
            config['devices'][ip][field] = data[field]
    config_manager.save_config(config)
    logger.info(f"更新设备身份映射: {ip}")
    return jsonify({"status": "success"}), 200


@app.route('/api/device-identity/device/<ip>', methods=['DELETE'])
def delete_device_identity(ip):
    """删除单个设备身份映射"""
    config = config_manager.get_config()
    if ip not in config['devices']:
        return jsonify({"status": "error", "message": f"IP {ip} 不存在"}), 404
    del config['devices'][ip]
    config_manager.save_config(config)
    logger.info(f"删除设备身份映射: {ip}")
    return jsonify({"status": "success"}), 200


@app.route('/api/device-identity/reload', methods=['POST'])
def trigger_controller_reload():
    """触发控制器重载配置"""
    config = config_manager.get_config()
    from datetime import datetime
    config['updated_at'] = datetime.now().isoformat()
    config_manager.save_config(config)
    logger.info("已触发控制器配置重载")
    return jsonify({"status": "success", "message": "重载信号已发出"}), 200


if __name__ == "__main__":
    # 首次启动时自动生成默认设备身份配置
    if not os.path.exists(config_manager.CONFIG_FILE):
        default_config = config_manager.build_default_config()
        config_manager.save_config(default_config)
        logger.info("已创建默认设备身份配置文件")
    config_manager.load_config()

    threading.Thread(target=listen_ble_mesh_data, daemon=True, name="BLE_Listener").start()
    threading.Thread(target=check_connectivity_by_flows, daemon=True, name="Connectivity_Checker").start()

    logger.info("=" * 60)
    logger.info("SDN Dashboard 服务器启动（Vue 版）")
    if os.path.exists(VUE_DIST):
        logger.info("生产模式: http://localhost:5000")
    else:
        logger.info("开发模式: http://localhost:5000 (API)")
        logger.info("前端请通过 Vite 开发服务器访问: cd sdn_dashboard_view && npm run dev")
    logger.info("=" * 60)

    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
