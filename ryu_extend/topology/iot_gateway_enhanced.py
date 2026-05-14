
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

sys.path.append(os.path.join(os.path.dirname(__file__), '../switch'))
try:
    from extensions.manager import IoTExtensionManager, create_iot_extension
    from extensions.constants import SENSOR_TYPES, PRIORITY_LEVELS
    EXTENSIONS_AVAILABLE = True
except ImportError:
    EXTENSIONS_AVAILABLE = False
    print("警告: 无法导入extensions模块，将使用基础模式")

class IoTGatewayEnhanced:
    """IoT网关模拟器 - 增强版"""
    
    def __init__(
        self, 
        gateway_ip='192.168.1.12',
        listen_port=5005,
        target_port=5005,
        controller_ip='127.0.0.1',
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
        log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
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
            
            ext_mgr = create_iot_extension(
                sensor_type=sensor_type,
                device_priority=device_priority,
                route_select='route_a'
            )
            
            serialized_data = ext_mgr.serialize_to_experimenter()
            
            extension_info = {
                'ble_addr': ble_addr,
                'sensor_type': sensor_type,
                'data_value': data_value,
                'device_priority': device_priority,
                'timestamp': time.time(),
                'extension_data': serialized_data.hex()
            }
            
            return extension_info
            
        except Exception as e:
            print(f"  编码OpenFlow扩展失败: {e}")
            return None
    
    def _calculate_priority(self, data_type, data_value):
        """根据数据类型和值计算优先级"""
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
        """发送扩展信息到控制器"""
        try:
            msg_data = json.dumps(extension_info).encode('utf-8')
            
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.sendto(msg_data, (self.controller_ip, self.controller_port))
            sock.close()
            
            print(f"  已发送扩展信息到控制器: {extension_info['ble_addr']} - {extension_info['sensor_type']}")
            
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
                if extension_info:
                    print(f"  OpenFlow扩展编码成功: 优先级={extension_info['device_priority']}")
                    self.send_to_controller(extension_info)
                
                if ble_addr in ['aa:bb:cc:dd:ee:01', 'aa:bb:cc:dd:ee:04']:
                    target_ip = '192.168.1.20'
                elif ble_addr == 'aa:bb:cc:dd:ee:02':
                    target_ip = '192.168.1.21'
                else:
                    target_ip = '192.168.1.20'
                
                self.forward_data(received_data, target_ip)
                fwd_msg = f"  数据已转发到: {target_ip}:{self.target_port}"
                print(fwd_msg)
                self._log_to_file(fwd_msg)
            else:
                err_msg = f"  数据格式错误: {received_data}"
                print(err_msg)
                self._log_to_file(err_msg)
        except Exception as e:
            err_msg = f"  处理数据失败: {e}"
            print(err_msg)
            self._log_to_file(err_msg)
    
    def forward_data(self, data, target_ip):
        """转发数据到目标主机"""
        try:
            if self.use_udp:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.sendto(data.encode('utf-8'), (target_ip, self.target_port))
                sock.close()
            else:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
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
            self.send_to_controller(extension_info)
        
        self.forward_data(packet_data, target_ip)
        send_msg = f"  网关发送: {sensor_type} -> {target_ip}"
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
        
        # 保持主线程运行，维持监听状态
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop_gateway()
    
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
        controller_ip='127.0.0.1',
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
