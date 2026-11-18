
#!/usr/bin/env python3
"""
IoT网关模拟器 - 增强版（集成OpenFlow Experimenter扩展）
1. 监听5005端口，接收来自iot1/iot2/iot4的数据
2. 解析IoT数据，提取BLE地址、传感器类型等属性
3. 将属性封装为OpenFlow Experimenter扩展字段
4. 转发数据到目标主机，同时发送扩展字段信息到控制器
"""

import socket
import time
import random
import struct
import json
from threading import Thread
import sys
import os

# 控制器地址：默认走 s1 的网桥 IP，iot3 命名空间内也能到达宿主机
DEFAULT_CONTROLLER_IP = os.environ.get('SDN_CONTROLLER_IP', '192.168.1.1')
# Unix socket 备用通道（跨 Mininet 命名空间稳定）
DEFAULT_EXT_SOCKET = os.environ.get('SDN_EXT_SOCKET', '/tmp/sdn_iot_ext.sock')

sys.path.append(os.path.join(os.path.dirname(__file__), '../ryu_extend/switch'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'core'))
try:
    from extensions.manager import IoTExtensionManager, create_iot_extension
    from extensions.constants import SENSOR_TYPES, PRIORITY_LEVELS
    from extensions.priority import (
        calculate_priority as _shared_calculate_priority,
        select_route as _shared_select_route,
    )
    EXTENSIONS_AVAILABLE = True
except ImportError:
    EXTENSIONS_AVAILABLE = False
    _shared_calculate_priority = None
    _shared_select_route = None
    print("警告: 无法导入extensions模块，将使用基础模式")

# OpenFlow 1.3 设备侧客户端：网关以标准 OF 设备身份接入控制器 6634
try:
    from of_gateway_agent import GatewayOpenFlowAgent
    OF_AGENT_AVAILABLE = True
except ImportError as _of_import_err:
    GatewayOpenFlowAgent = None
    OF_AGENT_AVAILABLE = False
    print(f"警告: 无法导入 OpenFlow 客户端，网关将只做 IP 转发: {_of_import_err}")

# XDP 探针桥：探针通过 Unix socket 查网关本地缓存 / 接收 flow_ready
try:
    from probe_bridge import ProbeBridge, resolve_target_ip as _bridged_target_ip
    PROBE_BRIDGE_AVAILABLE = True
except ImportError as _bridge_import_err:
    ProbeBridge = None
    _bridged_target_ip = None
    PROBE_BRIDGE_AVAILABLE = False
    print(f"警告: 无法导入 XDP 探针桥: {_bridge_import_err}")

# 逐包优先级标记（SO_PRIORITY + DSCP）
try:
    from qos import mark_socket as _mark_socket
    QOS_AVAILABLE = True
except ImportError as _qos_import_err:
    _mark_socket = None
    QOS_AVAILABLE = False
    print(f"警告: 无法导入优先级标记模块: {_qos_import_err}")

class IoTGatewayEnhanced:
    """IoT网关模拟器 - 增强版"""
    
    def __init__(
        self, 
        gateway_ip='192.168.1.12',
        listen_port=5005,
        target_port=5005,
        controller_ip=DEFAULT_CONTROLLER_IP,
        controller_port=6650,
        use_udp=True
    ):
        self.gateway_ip = gateway_ip
        self.listen_port = listen_port
        self.target_port = target_port
        self.controller_ip = controller_ip
        self.controller_port = controller_port
        self.use_udp = use_udp
        self.running = False
        self.receiver_thread = None
        self.sender_thread = None
        self.listen_socket = None
        self.controller_socket = None
        
        self.iot_devices = [
            {'type': 'temp', 'priority': 5, 'interval': 2},
            {'type': 'pos', 'priority': 2, 'interval': 5},
            {'type': 'humidity', 'priority': 3, 'interval': 3},
        ]
        
        self.registered_devices = {}

        # OpenFlow 客户端配置（可用环境变量覆盖）
        self.of_enabled = os.environ.get('SDN_OF_ENABLE', '1') not in ('0', 'false', 'no')
        self.of_controller_ip = os.environ.get('SDN_OF_CONTROLLER', DEFAULT_CONTROLLER_IP)
        self.of_controller_port = int(os.environ.get('SDN_OF_PORT', '6634'))
        self.of_dpid = int(os.environ.get('SDN_GATEWAY_DPID', '3'))
        self.of_agent = None
        self.probe_bridge = None
    
    def _init_listen_socket(self):
        """初始化监听socket"""
        try:
            if self.use_udp:
                self.listen_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.listen_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.listen_socket.bind(('0.0.0.0', self.listen_port))
                msg = f"  网关监听UDP端口成功: 0.0.0.0:{self.listen_port}"
                print(msg)
                self._log_to_file(msg)
            else:
                self.listen_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.listen_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.listen_socket.bind(('0.0.0.0', self.listen_port))
                self.listen_socket.listen(5)
                msg = f"  网关监听TCP端口成功: 0.0.0.0:{self.listen_port}"
                print(msg)
                self._log_to_file(msg)
            return True
        except Exception as e:
            msg = f"  初始化监听socket失败: {e}"
            print(msg)
            self._log_to_file(msg)
            self.listen_socket = None
            return False

    def _log_to_file(self, msg):
        """写入日志文件"""
        log_dir = os.path.join(os.path.dirname(__file__), '../ryu_extend/logs')
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, 'gateway.log')
        try:
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
                f.flush()
                os.fsync(f.fileno())
        except Exception as e:
            print(f"  [警告] 写入日志失败: {e}")
    
    def encode_openflow_extension(self, ble_addr, data_type, data_value):
        """将IoT数据编码为OpenFlow Experimenter扩展字段"""
        if not EXTENSIONS_AVAILABLE:
            return None
        
        try:
            sensor_type = data_type
            device_priority = self._calculate_priority(data_type, data_value)
            route_select = (
                _shared_select_route(device_priority)
                if _shared_select_route is not None else 'route_a'
            )

            ext_mgr = create_iot_extension(
                sensor_type=sensor_type,
                device_priority=device_priority,
                route_select=route_select
            )

            serialized_data = ext_mgr.serialize_to_experimenter()

            extension_info = {
                'ble_addr': ble_addr,
                'sensor_type': sensor_type,
                'data_value': data_value,
                'device_priority': device_priority,
                'route_select': route_select,
                'timestamp': time.time(),
                'extension_data': serialized_data.hex()
            }
            
            return extension_info
            
        except Exception as e:
            print(f"  编码OpenFlow扩展失败: {e}")
            return None
    
    def _target_ip_for(self, ble_addr):
        """BLE 地址 → 目标 IP（与 probe_bridge 共用同一份映射）。"""
        if _bridged_target_ip is not None:
            return _bridged_target_ip(ble_addr)
        if ble_addr in ['aa:bb:cc:dd:ee:01', 'aa:bb:cc:dd:ee:04']:
            return '192.168.1.20'
        if ble_addr == 'aa:bb:cc:dd:ee:02':
            return '192.168.1.21'
        return '192.168.1.20'

    def _calculate_priority(self, data_type, data_value):
        """根据数据类型和值计算优先级（与控制器共用同一份逻辑）"""
        if _shared_calculate_priority is not None:
            try:
                return _shared_calculate_priority(data_type, data_value)
            except Exception as e:
                print(f"  统一优先级计算失败，使用兜底逻辑: {e}")

        base_priority = 2

        if data_type == 'temp':
            try:
                temp = float(data_value)
                if temp > 35 or temp < 10:
                    return 5
                elif temp > 30 or temp < 15:
                    return 4
            except:
                pass
        elif data_type == 'gas':
            return 5
        elif data_type == 'motion':
            return 4
        
        return base_priority
    
    def send_to_controller(self, extension_info):
        """发送扩展信息到控制器。

        优先 Unix socket（跨 Mininet 命名空间稳定），否则退回 UDP。
        可用 SDN_EXT_TRANSPORT=unix|udp|auto 强制指定。
        """
        try:
            msg_data = json.dumps(extension_info).encode('utf-8')
            socket_path = os.environ.get('SDN_EXT_SOCKET', DEFAULT_EXT_SOCKET)
            transport = os.environ.get('SDN_EXT_TRANSPORT', 'auto').lower()

            sent_via = None

            if transport in ('auto', 'unix') and os.path.exists(socket_path):
                try:
                    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
                    sock.sendto(msg_data, socket_path)
                    sock.close()
                    sent_via = f"unix://{socket_path}"
                except OSError as exc:
                    if transport == 'unix':
                        raise
                    print(f"  Unix socket 发送失败，回退 UDP: {exc}")

            if sent_via is None and transport in ('auto', 'udp'):
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.sendto(msg_data, (self.controller_ip, self.controller_port))
                sock.close()
                sent_via = f"{self.controller_ip}:{self.controller_port}"

            if sent_via:
                print(f"  已发送扩展信息到控制器 ({sent_via}): "
                      f"{extension_info['ble_addr']} - {extension_info['sensor_type']}")
            else:
                print("  未找到可用的控制器通道，扩展信息未发送")

        except Exception as e:
            print(f"  发送到控制器失败: {e}")
    
    def handle_received_data(self):
        """处理接收到的数据"""
        while self.running:
            try:
                if self.listen_socket:
                    if self.use_udp:
                        data, addr = self.listen_socket.recvfrom(1024)
                        if data:
                            self._process_received_data(data, addr)
                    else:
                        conn, addr = self.listen_socket.accept()
                        data = conn.recv(1024)
                        if data:
                            self._process_received_data(data, addr)
                        conn.close()
            except Exception as e:
                if not self.running:
                    break
                error_msg = f"  接收数据异常: {e}"
                print(error_msg)
                self._log_to_file(error_msg)
    
    def _process_received_data(self, data, addr):
        """处理接收到的数据包"""
        try:
            received_data = data.decode('utf-8').strip()
            log_msg = f"  接收到IoT设备数据: {received_data} (来源: {addr})"
            print(f"\n{log_msg}")
            self._log_to_file(log_msg)
            
            parts = received_data.split(',', 2)
            if len(parts) >= 3:
                ble_addr, data_type, data_value = parts
                parse_msg = f"  解析结果: 设备地址={ble_addr}, 类型={data_type}, 值={data_value}"
                print(parse_msg)
                self._log_to_file(parse_msg)
                
                extension_info = self.encode_openflow_extension(ble_addr, data_type, data_value)
                target_ip = self._target_ip_for(ble_addr)

                if extension_info:
                    extension_info['target_ip'] = target_ip
                    print(f"  OpenFlow扩展编码成功: 优先级={extension_info['device_priority']}")
                    self.send_to_controller(extension_info)

                priority = (extension_info.get('device_priority')
                            if extension_info else
                            self._calculate_priority(data_type, data_value))
                self.forward_data(received_data, target_ip, priority)
                fwd_msg = (f"  数据已转发到: {target_ip}:{self.target_port}"
                           f"（优先级 {priority}）")
                print(fwd_msg)
                self._log_to_file(fwd_msg)

                # 以 OpenFlow 设备身份上报控制器（本地流表命中则跳过）
                self._report_to_openflow(ble_addr, data_type, data_value, target_ip)
            else:
                err_msg = f"  数据格式错误: {received_data}"
                print(err_msg)
                self._log_to_file(err_msg)
        except Exception as e:
            err_msg = f"  处理数据失败: {e}"
            print(err_msg)
            self._log_to_file(err_msg)
    
    def forward_data(self, data, target_ip, priority=None):
        """转发数据到目标主机；priority 1–5 会逐包贴 SO_PRIORITY + DSCP。"""
        try:
            if self.use_udp:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                if priority is not None and _mark_socket is not None:
                    _mark_socket(sock, priority)
                sock.sendto(data.encode('utf-8'), (target_ip, self.target_port))
                sock.close()
            else:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                if priority is not None and _mark_socket is not None:
                    _mark_socket(sock, priority)
                sock.connect((target_ip, self.target_port))
                sock.sendall(data.encode('utf-8'))
                sock.close()
        except Exception as e:
            print(f"  转发数据失败: {e}")
    
    def simulate_device_data(self, device_config):
        """模拟单个IoT设备的数据发送"""
        sensor_type = device_config['type']
        interval = device_config['interval']
        
        if sensor_type == 'temp':
            value = round(random.uniform(20.0, 40.0), 1)
        elif sensor_type == 'pos':
            lat = round(random.uniform(-100, 100), 2)
            lon = round(random.uniform(-100, 100), 2)
            value = "({},{})".format(lat, lon)
        elif sensor_type == 'humidity':
            value = round(random.uniform(30.0, 80.0), 1)
        else:
            value = round(random.uniform(0, 100), 1)
        
        ble_addr = 'aa:bb:cc:dd:ee:03'
        packet_data = f"{ble_addr},{sensor_type},{value}"
        
        target_ip = '192.168.1.20' if random.random() > 0.5 else '192.168.1.21'
        
        extension_info = self.encode_openflow_extension(ble_addr, sensor_type, str(value))
        if extension_info:
            extension_info['target_ip'] = target_ip
            self.send_to_controller(extension_info)
        
        priority = (extension_info.get('device_priority')
                    if extension_info else
                    self._calculate_priority(sensor_type, str(value)))
        self.forward_data(packet_data, target_ip, priority)
        send_msg = f"  网关发送: {sensor_type} -> {target_ip}（优先级 {priority}）"
        print(send_msg)
        self._log_to_file(send_msg)
        
        time.sleep(interval)
    
    def _send_iot_device_registration(self):
        """发送IoT设备注册消息"""
        register_msg1 = "register,iot1,temp"
        self.forward_data(register_msg1, '192.168.1.12')
        print(f"  发送注册消息: {register_msg1}")
        time.sleep(1)
        
        register_msg2 = "register,iot2,humidity"
        self.forward_data(register_msg2, '192.168.1.12')
        print(f"  发送注册消息: {register_msg2}")
        time.sleep(1)
        
        register_msg3 = "register,iot4,pos"
        self.forward_data(register_msg3, '192.168.1.12')
        print(f"  发送注册消息: {register_msg3}")
        time.sleep(1)
        
        print("  IoT设备注册消息发送完成")
    
    def start_gateway(self):
        """启动网关（仅接收和转发，不产生模拟数据）"""
        startup_msg = f"=== IoT网关启动（增强版）==="
        print(startup_msg)
        self._log_to_file(startup_msg)
        
        info1 = f"网关IP: {self.gateway_ip}"
        print(info1)
        self._log_to_file(info1)
        
        info2 = f"监听端口: {self.listen_port}"
        print(info2)
        self._log_to_file(info2)
        
        info3 = f"目标端口: {self.target_port}"
        print(info3)
        self._log_to_file(info3)
        
        info4 = f"控制器: {self.controller_ip}:{self.controller_port}"
        print(info4)
        self._log_to_file(info4)
        
        info5 = f"OpenFlow扩展: {'启用' if EXTENSIONS_AVAILABLE else '禁用'}"
        print(info5)
        self._log_to_file(info5)
        
        info6 = "功能: 接收IoT数据、编码OpenFlow扩展、转发到SDN网络"
        print(info6)
        self._log_to_file(info6)
        
        separator = "=" * 60
        print(separator)
        self._log_to_file(separator)
        
        self.running = True
        
        if self._init_listen_socket():
            self.receiver_thread = Thread(target=self.handle_received_data)
            self.receiver_thread.daemon = True
            self.receiver_thread.start()
            thread_msg = f"  接收线程已启动，等待真实IoT数据..."
            print(thread_msg)
            self._log_to_file(thread_msg)
        else:
            error_msg = f"  无法启动接收线程"
            print(error_msg)
            self._log_to_file(error_msg)
            return

        self._start_of_agent()

        # 保持主线程运行，维持监听状态
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop_gateway()

    def _of_log(self, msg):
        """OpenFlow 客户端日志：控制台 + 网关日志文件。"""
        print(msg)
        self._log_to_file(msg)

    def _start_of_agent(self):
        """启动 OpenFlow 设备侧客户端，连接控制器 6634。"""
        if not self.of_enabled:
            self._of_log("  OpenFlow 客户端已禁用 (SDN_OF_ENABLE=0)")
            return
        if not OF_AGENT_AVAILABLE or GatewayOpenFlowAgent is None:
            self._of_log("  OpenFlow 客户端不可用，跳过接入控制器")
            return

        self.of_agent = GatewayOpenFlowAgent(
            dpid=self.of_dpid,
            controller_host=self.of_controller_ip,
            controller_port=self.of_controller_port,
            gateway_ip=self.gateway_ip,
            log=self._of_log,
        )
        self.of_agent.start()
        self._of_log(
            f"  OpenFlow 客户端已启动: dpid={self.of_dpid} → "
            f"{self.of_controller_ip}:{self.of_controller_port}")
        self._start_probe_bridge()

    def _start_probe_bridge(self):
        """启动 XDP 探针桥：探针查网关本地缓存 / FlowMod 后推送 flow_ready。"""
        if os.environ.get('SDN_XDP_BRIDGE', '1') in ('0', 'false', 'no'):
            self._of_log("  XDP 探针桥已禁用 (SDN_XDP_BRIDGE=0)")
            return
        if not PROBE_BRIDGE_AVAILABLE or ProbeBridge is None:
            self._of_log("  XDP 探针桥不可用，跳过")
            return
        try:
            self.probe_bridge = ProbeBridge(self.of_agent, log=self._of_log)
            self.of_agent.on_flow_installed = self.probe_bridge.on_flow_installed
            self.of_agent.on_flow_deleted = self.probe_bridge.on_flow_deleted
            self.probe_bridge.start()
        except Exception as exc:  # noqa: BLE001 - 桥失败不影响网关数据面
            self.probe_bridge = None
            self._of_log(f"  XDP 探针桥启动失败: {exc}")

    def _report_to_openflow(self, ble_addr, data_type, data_value, target_ip):
        """BLE 数据 → 网关本地流表查询 / PacketIn 上报。"""
        if not self.of_agent:
            return
        try:
            self.of_agent.note_sensor_data(
                ble_addr, data_type, data_value, target_ip)
        except Exception as e:
            self._of_log(f"  OpenFlow 上报异常: {e}")

    def stop_gateway(self):
        """停止网关"""
        print("\n停止IoT网关...")
        self.running = False
        
        if self.listen_socket:
            try:
                self.listen_socket.close()
            except:
                pass
        
        if self.receiver_thread and self.receiver_thread.is_alive():
            self.receiver_thread.join(timeout=2)

        if self.probe_bridge:
            self.probe_bridge.stop()
            self.probe_bridge = None

        if self.of_agent:
            self.of_agent.stop()
            self.of_agent = None
        
        print("网关已停止")

def main():
    """主函数"""
    time.sleep(3)
    
    import sys
    # 强制刷新输出
    sys.stdout.reconfigure(line_buffering=True)
    
    gateway = IoTGatewayEnhanced(
        gateway_ip='192.168.1.12',
        listen_port=5005,
        target_port=5005,
        controller_ip=DEFAULT_CONTROLLER_IP,
        controller_port=6650,
        use_udp=True
    )
    
    # 启动网关服务
    try:
        gateway.start_gateway()
    except KeyboardInterrupt:
        print("\n收到中断信号...")
        gateway.stop_gateway()
        print("程序退出")

if __name__ == '__main__':
    main()
