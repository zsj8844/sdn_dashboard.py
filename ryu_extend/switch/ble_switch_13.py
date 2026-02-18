# 顶部导入requests（新增，用于推送日志）
import requests
# 基础模块导入（原有）
from ryu.app import simple_switch_13
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, CONFIG_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ipv4, udp, arp
import time

# 自定义BLE扩展字段（原有）
BLE_ADDR_MATCH = 1001
BLE_OUTPUT_ACTION = 1002
MY_EXPERIMENTER_ID = 0xdeadbeef

# 扩展字段可用性标志
EXTENSIONS_AVAILABLE = False

# 尝试导入扩展模块
try:
    from extensions.manager import IoTExtensionManager, create_iot_extension
    EXTENSIONS_AVAILABLE = True
except ImportError:
    EXTENSIONS_AVAILABLE = False

class BLEMeshSwitch13(simple_switch_13.SimpleSwitch13):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ble_port_map = {}
        self.ip_port_map = {}  # 存储IP→端口映射，动态找iot3端口
        
        # OpenFlow扩展字段功能初始化
        self.extension_enabled = EXTENSIONS_AVAILABLE
        if self.extension_enabled:
            self.logger.info("OpenFlow扩展字段功能已启用")
            self.test_extension_functionality()
        else:
            self.logger.warning("OpenFlow扩展字段功能不可用")
            
        self.logger.info("BLE Mesh Switch 13 初始化完成")

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        super().switch_features_handler(ev)
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        
        # 安装默认流表
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)
        self.logger.info(f"交换机 {datapath.id} 默认流表安装完成")

    def add_flow(self, datapath, priority, match, actions, idle_timeout=0, hard_timeout=0):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(
            datapath=datapath, priority=priority, match=match,
            instructions=inst, idle_timeout=idle_timeout, hard_timeout=hard_timeout
        )
        datapath.send_msg(mod)
        self.logger.info(f"流表下发成功 - 优先级:{priority}, 超时:{idle_timeout}s, 端口:{actions[0].port if actions else '无'}")

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        try:
            msg = ev.msg
            datapath = msg.datapath
            ofproto = datapath.ofproto
            in_port = msg.match.get('in_port', -1)
            if in_port == -1:
                self.logger.warning("数据包无in_port，跳过处理")
                return
            pkt = packet.Packet(msg.data)
            self.logger.info(f"收到数据包: 端口{in_port} ({len(msg.data)}bytes)")
            eth_pkt = pkt.get_protocol(ethernet.ethernet)
            if not eth_pkt:
                self.logger.debug("非以太网包，泛洪转发")
                self._send_packet_out(datapath, in_port, msg.buffer_id, msg.data, ofproto.OFPP_FLOOD)
                return
            if eth_pkt.ethertype == 0x88cc:
                self.logger.debug("LLDP包，跳过处理")
                self._send_packet_out(datapath, in_port, msg.buffer_id, msg.data, ofproto.OFPP_FLOOD)
                return
            ip_pkt = pkt.get_protocol(ipv4.ipv4)
            udp_pkt = pkt.get_protocol(udp.udp)
            if ip_pkt:
                src_ip = ip_pkt.src
                self.ip_port_map[src_ip] = in_port
                # 在新的层级拓扑中，需要动态发现iot3网关端口
                # iot3现在通过其他IoT设备连接，端口需要动态学习
                self.logger.debug(f"IP端口映射更新: {self.ip_port_map}")
            if not (ip_pkt and udp_pkt and udp_pkt.dst_port == 5005):
                self.logger.debug(f"非BLE包 (UDP端口{udp_pkt.dst_port if udp_pkt else '无'}≠5005)，泛洪转发")
                self._send_packet_out(datapath, in_port, msg.buffer_id, msg.data, ofproto.OFPP_FLOOD)
                return
            try:
                ip_header_len = (ip_pkt.version & 0xF) * 4
                total_header_len = 13 + ip_header_len + 8
                if total_header_len >= len(msg.data):
                    self.logger.warning(f"数据包长度不足 (需{total_header_len}字节，实际{len(msg.data)}字节)，跳过解析")
                    self._send_packet_out(datapath, in_port, msg.buffer_id, msg.data, ofproto.OFPP_FLOOD)
                    return
                ble_raw_data = msg.data[total_header_len:].decode('utf-8', errors='ignore').strip()
                ble_data = ble_raw_data.split(',', 2)
                if len(ble_data) < 3:
                    self.logger.warning(f"BLE数据格式错误 (应为'地址,类型,数值'): {ble_raw_data}，跳过")
                    self._send_packet_out(datapath, in_port, msg.buffer_id, msg.data, ofproto.OFPP_FLOOD)
                    return
                ble_addr, ble_type, ble_value = ble_data
                self.ble_port_map[ble_addr] = in_port
                self.logger.info(f"解析BLE数据 - 地址:{ble_addr} | 类型:{ble_type} | 数值:{ble_value}")

                # 创建IoT扩展字段（演示用途）
                if self.extension_enabled:
                    self.process_iot_extension(ble_type, ble_value)

                # 推送日志到Web面板
                try:
                    log_data = {"ble_addr": ble_addr, "type": ble_type, "value": ble_value, "src_ip": ip_pkt.src}
                    requests.post("http://localhost:5000/api/logs", json=log_data, timeout=1)
                except Exception as e:
                    self.logger.warning(f"日志推送失败 (Web未启动?): {e}")

                # 获取iot3网关端口（需要从动态学习的映射中获取）
                iot3_port = None
                for ip, port in self.ip_port_map.items():
                    if '192.168.1.12' in ip or 'iot3' in ip.lower():
                        iot3_port = port
                        break
                
                if iot3_port is None:
                    self.logger.warning("未找到iot3网关端口，使用泛洪转发")
                    self._send_packet_out(datapath, in_port, msg.buffer_id, msg.data, ofproto.OFPP_FLOOD)
                    return
                self.logger.info(f"转发到iot3的端口: {iot3_port}")
                parser = datapath.ofproto_parser
                match = parser.OFPMatch(eth_type=0x0800, ip_proto=17, udp_dst=5005)
                actions = [parser.OFPActionOutput(iot3_port)]
                self.add_flow(datapath, 10, match, actions, idle_timeout=30)
                self._send_packet_out(datapath, in_port, msg.buffer_id, msg.data, iot3_port)
            except Exception as e:
                self.logger.error(f"BLE数据解析失败: {e}，泛洪转发")
                self._send_packet_out(datapath, in_port, msg.buffer_id, msg.data, ofproto.OFPP_FLOOD)
        except Exception as e:
            self.logger.error(f"_packet_in_handler函数异常 (不终止控制器): {e}")
            try:
                self._send_packet_out(datapath, in_port, msg.buffer_id, msg.data, ofproto.OFPP_FLOOD)
            except:
                pass

    def _send_packet_out(self, datapath, in_port, buffer_id, data, out_port):
        try:
            ofproto = datapath.ofproto
            parser = datapath.ofproto_parser
            actions = [parser.OFPActionOutput(out_port)]
            buffer_id = buffer_id if buffer_id != ofproto.OFP_NO_BUFFER else ofproto.OFP_NO_BUFFER
            out = parser.OFPPacketOut(
                datapath=datapath, buffer_id=buffer_id, in_port=in_port,
                actions=actions, data=data
            )
            datapath.send_msg(out)
        except Exception as e:
            self.logger.error(f"数据包转发失败: {e}")
    
    def test_extension_functionality(self):
        """测试扩展字段功能"""
        try:
            # 创建测试扩展字段
            ext_mgr = create_iot_extension(
                sensor_type='temp',
                device_priority=3,
                route_select='route_a'
            )
            
            # 序列化测试
            serialized = ext_mgr.serialize_to_experimenter()
            self.logger.info(f"扩展字段序列化测试成功 ({len(serialized)} bytes)")
            
            # 反序列化测试
            parsed_mgr = IoTExtensionManager.parse_from_experimenter(serialized)
            field_dict = parsed_mgr.get_field_dict()
            self.logger.info(f"扩展字段反序列化测试成功: {field_dict}")
            
        except Exception as e:
            self.logger.error(f"扩展字段功能测试失败: {e}")
            self.extension_enabled = False
    
    def process_iot_extension(self, ble_type, ble_value):
        """处理IoT扩展字段"""
        try:
            # 根据BLE数据类型创建相应的扩展字段
            sensor_mapping = {
                'temp': 'temp',
                'temperature': 'temp',
                'humidity': 'humidity',
                'light': 'light',
                'motion': 'motion',
                'pressure': 'pressure'
            }
            
            sensor_type = sensor_mapping.get(ble_type.lower(), 'temp')
            
            # 根据数值确定优先级
            try:
                value_float = float(ble_value)
                if value_float > 80:  # 高温/高湿等紧急情况
                    priority = 5
                elif value_float > 50:  # 较高值
                    priority = 4
                elif value_float > 30:  # 正常偏高
                    priority = 3
                else:  # 正常范围
                    priority = 2
            except ValueError:
                priority = 2  # 默认优先级
            
            # 创建扩展字段
            ext_mgr = create_iot_extension(
                sensor_type=sensor_type,
                device_priority=priority,
                route_select='route_a'
            )
            
            # 打印扩展字段信息
            self.logger.info("IoT扩展字段已创建:")
            ext_mgr.print_fields()
            
            # 序列化用于实际传输
            serialized_data = ext_mgr.serialize_to_experimenter()
            self.logger.debug(f"扩展字段序列化完成 ({len(serialized_data)} bytes)")
            
        except Exception as e:
            self.logger.warning(f"处理IoT扩展字段时出错: {e}")

if __name__ == '__main__':
    import sys
    from ryu.cmd import manager
    sys.argv.append(__file__)
    manager.main()

