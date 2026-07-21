"""拓扑管理模块 — 主机发现、身份同步、配置热加载"""

import time
import logging
from ryu.lib import hub

logger = logging.getLogger(__name__)


class TopologyManager:
    """管理 topology['hosts'] 的同步、发现与配置热加载"""

    def __init__(self, topology, config_manager, reporter):
        self.topology = topology
        self.config_manager = config_manager
        self.reporter = reporter

    # ==================== 配置同步 ====================

    def sync_hosts_from_config(self, device_identity_config):
        """从设备身份配置预填拓扑主机"""
        devices = device_identity_config.get('devices', {})
        for ip, info in devices.items():
            existing = None
            for mac, host in self.topology['hosts'].items():
                if host.get('ip') == ip:
                    existing = mac
                    break
            if existing:
                self.topology['hosts'][existing].update({
                    'device_id': info['device_id'],
                    'device_type': info['device_type'],
                    'role': info['role'],
                    'device_name': info.get('device_name', ''),
                })
            else:
                placeholder_mac = f'pending_{ip}'
                self.topology['hosts'][placeholder_mac] = {
                    'mac': placeholder_mac,
                    'ip': ip,
                    'switch_dpid': 0,
                    'port': 0,
                    'first_seen': time.time(),
                    'device_id': info['device_id'],
                    'device_type': info['device_type'],
                    'role': info['role'],
                    'device_name': info.get('device_name', ''),
                    'pending': True,
                }
        logger.info(f"拓扑主机已从配置同步: {len(self.topology['hosts'])} 个")
        self.reporter.report_topology(self.topology)

    # ==================== 设备发现 ====================

    def discover_device(self, src_ip, eth_src, dpid, in_port, device_config):
        """
        从 Packet-In 发现设备。替换占位条目或新增。
        返回 True 表示拓扑有变化。
        """
        SWITCH_SELF_IPS = {'192.168.1.1', '192.168.1.2'}
        if src_ip in SWITCH_SELF_IPS:
            return False

        placeholder_key = f'pending_{src_ip}'
        if placeholder_key in self.topology['hosts']:
            real_mac = eth_src
            host_entry = self.topology['hosts'].pop(placeholder_key)
            host_entry.update({
                'mac': real_mac, 'switch_dpid': dpid,
                'port': in_port, 'pending': False,
            })
            self.topology['hosts'][real_mac] = host_entry
            dev_id = device_config['device_id'] if device_config else src_ip
            logger.info(f"设备位置确认: {dev_id} → s{dpid}:{in_port}")
            self.reporter.report_topology(self.topology)
            return True

        if eth_src not in self.topology['hosts']:
            host_entry = {
                'mac': eth_src, 'ip': src_ip,
                'switch_dpid': dpid, 'port': in_port,
                'first_seen': time.time(),
            }
            if device_config:
                host_entry.update({
                    'device_id': device_config['device_id'],
                    'device_type': device_config['device_type'],
                    'role': device_config['role'],
                    'device_name': device_config.get('device_name', ''),
                })
                logger.info(f"发现已知设备: {device_config['device_id']} (IP:{src_ip})")
            else:
                host_entry.update({
                    'device_id': 'unknown', 'device_type': 'unknown',
                    'role': 'host', 'device_name': f'unknown_{src_ip}',
                })
                logger.info(f"发现未知设备: MAC:{eth_src}, IP:{src_ip}")

            self.topology['hosts'][eth_src] = host_entry
            self.reporter.report_topology(self.topology)
            return True

        return False

    # ==================== 配置热加载 ====================

    def start_reload_loop(self, get_config_cb, set_config_cb):
        """启动协程：每 3 秒检测配置变更并自动同步"""
        def _loop():
            while True:
                hub.sleep(3)
                try:
                    if self.config_manager.check_and_reload():
                        new_config = self.config_manager.get_config()
                        set_config_cb(new_config)
                        self.sync_hosts_from_config(new_config)
                        logger.info("设备身份配置已自动重载")
                except Exception as e:
                    logger.error(f"配置重载检查失败: {e}")
        hub.spawn(_loop)
