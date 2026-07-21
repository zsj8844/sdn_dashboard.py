"""BLE Mesh SDN 控制器 — 基于 Ryu OpenFlow 1.3"""

import time
from collections import defaultdict

from ryu.app import simple_switch_13
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, CONFIG_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib import hub

# ── 子模块 ──
from Other_Modules import (
    setup_logging,
    LLDPManager, ControlHTTPServer,
    WebReporter, StatsCollector, FlowManager,
    IoTProcessor, DeviceManager, TopologyManager,
    PacketProcessor, resolve_out_port,
    config_manager,
)

# ── 日志 ──
setup_logging()

# ── 常量 ──
EXTENSIONS_AVAILABLE = False
try:
    from extensions import AppDeploymentManager, DeviceRoleManager
    EXTENSIONS_AVAILABLE = True
except ImportError:
    pass


class BLEMeshSwitch13(simple_switch_13.SimpleSwitch13):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    # ═══════════════════ 初始化 ═══════════════════

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.extension_enabled = EXTENSIONS_AVAILABLE
        self.web_panel_url = "http://localhost:5000"

        self.logger.info("========== 控制器初始化开始 ==========")
        self.logger.info("EXTENSIONS_AVAILABLE=%s, extension_enabled=%s",
                         EXTENSIONS_AVAILABLE, self.extension_enabled)

        # 拓扑
        self.topology = {'switches': {}, 'links': [], 'hosts': {}}
        self.port_stats = defaultdict(list)
        self.flow_stats = defaultdict(list)
        self.table_stats = defaultdict(dict)
        self.flow_tables = defaultdict(dict)

        # 配置
        config_manager.load_config()
        self.device_identity_config = config_manager.get_config()
        self.logger.info("已加载设备身份配置: %d 个设备",
                         len(self.device_identity_config.get('devices', {})))

        # 子模块初始化
        self._init_modules()

        # 拓扑同步
        self.topo_mgr.sync_hosts_from_config(self.device_identity_config)
        self.topo_mgr.start_reload_loop(
            lambda: self.device_identity_config,
            lambda cfg: setattr(self, 'device_identity_config', cfg)
        )

        self.logger.info("BLE Mesh Switch 13 初始化完成")

    def _init_modules(self):
        """初始化所有子模块"""
        self.reporter = WebReporter(self.web_panel_url)

        # LLDP
        self.lldp_manager = LLDPManager(
            self.topology,
            report_callback=lambda: self.reporter.report_topology(self.topology)
        )
        self.lldp_manager.start()

        # 统计
        stats_store = {
            'port_stats': self.port_stats,
            'flow_stats': self.flow_stats,
            'table_stats': self.table_stats,
        }
        self.stats_collector = StatsCollector(
            self.topology, stats_store,
            report_callback=self.reporter.report_stats
        )
        self.stats_collector.start()

        # 流表
        self.flow_manager = FlowManager(self.flow_tables)

        # 内部控制 HTTP
        self.control_server = ControlHTTPServer(
            self.lldp_manager,
            flow_manager=self.flow_manager,
            topology=self.topology,
        )
        hub.spawn(self.control_server.start)

        # 扩展
        if self.extension_enabled:
            self.app_deployment_manager = AppDeploymentManager()
            self.device_role_manager = DeviceRoleManager()
            self.device_manager = DeviceManager(
                self.app_deployment_manager, self.device_role_manager, True
            )
        else:
            self.device_manager = DeviceManager(None, None, False)

        # IoT 处理器
        self.iot_processor = IoTProcessor(self.extension_enabled, self.web_panel_url)

        # 拓扑管理
        self.topo_mgr = TopologyManager(self.topology, config_manager, self.reporter)

        # Packet-In 处理器（委托核心转发逻辑）
        self.mac_to_port = {}
        self.ble_port_map = {}
        self.ip_port_map = {}
        shared_state = {
            'mac_to_port': self.mac_to_port,
            'ble_port_map': self.ble_port_map,
            'ip_port_map': self.ip_port_map,
            'topology': self.topology,
            'device_identity_config': self.device_identity_config,
        }
        proc_modules = {
            'lldp_manager': self.lldp_manager,
            'topo_mgr': self.topo_mgr,
            'flow_manager': self.flow_manager,
            'iot_processor': self.iot_processor,
            'reporter': self.reporter,
            'resolve_out_port': resolve_out_port,
            'web_panel_url': self.web_panel_url,
            'logger': self.logger,
        }
        self.packet_processor = PacketProcessor(shared_state, proc_modules)

    # ═══════════════════ 交换机连接 ═══════════════════

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        super().switch_features_handler(ev)
        datapath = ev.msg.datapath
        dpid = datapath.id
        self.topology['switches'][dpid] = datapath
        self.logger.info("交换机 %d 已连接", dpid)
        self.reporter.report_topology(self.topology)

        if len(self.topology['switches']) >= 2:
            hub.spawn(self._proactive_flow_install)

    # ═══════════════════ Packet-In → 委托 PacketProcessor ═══════════════════

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        self.packet_processor.handle(ev.msg)

    # ═══════════════════ 主动流表 ═══════════════════

    def _proactive_flow_install(self):
        """主动预装默认转发流表（交换机连接后延迟触发）"""
        time.sleep(2)
        s1_count, s2_count = self.control_server.install_default_flows()
        self.logger.info("主动流表预装完成: s1=%d条, s2=%d条", s1_count, s2_count)

    def process_iot_extension(self, ble_type, ble_value):
        """→ IoTProcessor"""
        return self.iot_processor.process(ble_type, ble_value)

    # ═══════════════════ 统计 → stats_collector ═══════════════════

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def port_stats_reply_handler(self, ev):
        self.stats_collector.on_port_stats_reply(ev)

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def flow_stats_reply_handler(self, ev):
        self.stats_collector.on_flow_stats_reply(ev)

    @set_ev_cls(ofp_event.EventOFPTableStatsReply, MAIN_DISPATCHER)
    def table_stats_reply_handler(self, ev):
        self.stats_collector.on_table_stats_reply(ev)

    def port_status_handler(self, ev):
        msg = ev.msg
        dpid, port_no, reason = msg.datapath.id, msg.desc.port_no, msg.reason
        reason_str = {0: '添加', 1: '删除', 2: '修改'}.get(reason, '未知')
        self.logger.info("交换机%d 端口%d %s", dpid, port_no, reason_str)
        self.reporter.report_topology(self.topology)

    # ═══════════════════ LLDP → lldp_manager ═══════════════════

    @set_ev_cls(ofp_event.EventOFPPortDescStatsReply, MAIN_DISPATCHER)
    def port_desc_stats_reply_handler(self, ev):
        self.lldp_manager.on_port_desc_reply(ev)

    # ═══════════════════ 流表 → flow_manager ═══════════════════

    def delete_flow(self, *args, **kwargs):
        return self.flow_manager.delete_flow(*args, **kwargs)

    def modify_flow(self, *args, **kwargs):
        return self.flow_manager.modify_flow(*args, **kwargs)

    def get_flows(self, *args, **kwargs):
        return self.flow_manager.get_flows(*args, **kwargs)

    # ═══════════════════ 设备管理 → device_manager ═══════════════════

    def create_edge_application(self, *args, **kwargs):
        return self.device_manager.create_app(*args, **kwargs)

    def deploy_application_to_device(self, *args, **kwargs):
        return self.device_manager.deploy_app(*args, **kwargs)

    def undeploy_application_from_device(self, *args, **kwargs):
        return self.device_manager.undeploy_app(*args, **kwargs)

    def list_edge_applications(self):
        return self.device_manager.list_apps()

    def register_device_with_role(self, *args, **kwargs):
        return self.device_manager.register_device(*args, **kwargs)

    def switch_device_role(self, *args, **kwargs):
        return self.device_manager.switch_role(*args, **kwargs)

    def identify_device_mode(self, *args, **kwargs):
        return self.device_manager.identify_mode(*args, **kwargs)

    def get_available_device_modes(self, *args, **kwargs):
        return self.device_manager.get_available_modes(*args, **kwargs)

    def list_registered_devices(self):
        return self.device_manager.list_devices()


if __name__ == '__main__':
    import sys
    from ryu.cmd import manager
    sys.argv.append(__file__)
    manager.main()
