"""
设备身份配置管理模块

从 JSON 文件加载 IP → 设备身份映射，支持：
- 线程安全的读写
- 基于文件修改时间的自动重载
- 首次启动自动生成默认配置
"""
import json
import os
import threading
import logging

logger = logging.getLogger(__name__)

CONFIG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../config')
CONFIG_FILE = os.path.join(CONFIG_DIR, 'device_identity.json')

_config_lock = threading.Lock()
_config_cache = None
_config_mtime = 0


def load_config():
    """从磁盘读取配置到缓存。线程安全。"""
    global _config_cache, _config_mtime
    with _config_lock:
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    _config_cache = json.load(f)
                _config_mtime = os.path.getmtime(CONFIG_FILE)
                logger.info(f"已加载设备身份配置: {len(_config_cache.get('devices', {}))} 个设备")
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"配置文件读取失败: {e}，使用空配置")
                _config_cache = {"version": "1.0", "updated_at": "", "devices": {}}
                _config_mtime = 0
        else:
            logger.info("配置文件不存在，使用空配置")
            _config_cache = {"version": "1.0", "updated_at": "", "devices": {}}
            _config_mtime = 0
        return _config_cache


def save_config(config):
    """保存配置到磁盘。线程安全，自动创建目录。"""
    global _config_cache, _config_mtime
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with _config_lock:
        from datetime import datetime
        config['updated_at'] = datetime.now().isoformat()
        config.setdefault('version', '1.0')
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            _config_cache = config
            _config_mtime = os.path.getmtime(CONFIG_FILE)
            logger.info("设备身份配置已保存")
        except IOError as e:
            logger.error(f"配置文件写入失败: {e}")


def get_config():
    """返回缓存配置的副本（快速，无磁盘IO）。"""
    with _config_lock:
        if _config_cache is None:
            return {"version": "1.0", "updated_at": "", "devices": {}}
        return json.loads(json.dumps(_config_cache))


def check_and_reload():
    """检测文件是否被外部修改，是则自动重载。返回 True 表示已重载。"""
    global _config_mtime
    if os.path.exists(CONFIG_FILE):
        try:
            mtime = os.path.getmtime(CONFIG_FILE)
            if mtime != _config_mtime:
                load_config()
                return True
        except OSError:
            pass
    return False


def build_default_config():
    """根据已知拓扑生成默认设备身份配置（首次启动时使用）。"""
    default = {
        "version": "1.0",
        "updated_at": "",
        "devices": {
            "192.168.2.10": {
                "device_id": "iot1",
                "device_name": "温度传感器",
                "device_type": "temperature_sensor",
                "role": "iot",
                "description": "BLE温度传感器节点（iot3子网）"
            },
            "192.168.3.11": {
                "device_id": "iot2",
                "device_name": "湿度传感器",
                "device_type": "humidity_sensor",
                "role": "iot",
                "description": "BLE湿度传感器节点（iot3子网）"
            },
            "192.168.1.12": {
                "device_id": "iot3",
                "device_name": "IoT网关",
                "device_type": "gateway",
                "role": "gateway",
                "description": "BLE/IoT协议网关"
            },
            "192.168.4.13": {
                "device_id": "iot4",
                "device_name": "位置传感器",
                "device_type": "position_sensor",
                "role": "iot",
                "description": "BLE位置传感器节点（iot3子网）"
            },
            "192.168.1.20": {
                "device_id": "h1",
                "device_name": "传统终端1",
                "device_type": "host",
                "role": "host",
                "description": "传统IP终端"
            },
            "192.168.1.21": {
                "device_id": "h2",
                "device_name": "传统终端2",
                "device_type": "host",
                "role": "host",
                "description": "传统IP终端"
            }
        }
    }
    return default
