"""
Web 面板上报模块
负责向 Flask 面板推送拓扑、交换机日志、统计数据。
"""

import time
import logging
import requests

logger = logging.getLogger(__name__)


class WebReporter:
    """向 Web 面板推送数据的统一接口"""

    def __init__(self, web_panel_url="http://localhost:5000"):
        self.url = web_panel_url

    def push_switch_log(self, dpid, message):
        """推送交换机日志到 Web 面板"""
        try:
            endpoint = "s1" if dpid == 1 else "s2"
            requests.post(f"{self.url}/api/logs/{endpoint}",
                          json={"message": message}, timeout=1)
        except Exception:
            logger.debug("推送%s日志失败", endpoint)

    def report_topology(self, topology):
        """上报拓扑数据"""
        try:
            data = {
                'switches': list(topology.get('switches', {}).keys()),
                'links': topology.get('links', []),
                'hosts': list(topology.get('hosts', {}).values()),
                'timestamp': time.time()
            }
            requests.post(f"{self.url}/api/topology", json=data, timeout=1)
        except Exception:
            logger.debug("上报拓扑信息失败")

    def report_stats(self, stats_type, dpid, data):
        """上报统计数据"""
        try:
            requests.post(f"{self.url}/api/stats", json={
                'type': stats_type,
                'dpid': dpid,
                'data': data,
                'timestamp': time.time()
            }, timeout=1)
        except Exception:
            logger.debug("上报统计数据失败")
