
#!/usr/bin/env python3
"""
IoT网关模拟器 - 完整版
1. 监听5005端口，接收来自iot1/iot2/iot4的数据
2. 转发接收到的数据到目标主机(h1或h2)
3. 同时发送模拟数据
"""

import socket
import time
import random
from threading import Thread

class IoTGatewaySimulator:
    """IoT网关模拟器 - 完整功能"""
    
    def __init__(
        self, 
        gateway_ip='192.168.1.12',
        listen_port=5005,
        target_port=5005,
        use_udp=True
    ):
        self.gateway_ip = gateway_ip
        self.listen_port = listen_port
        self.target_port = target_port
        self.use_udp = use_udp
        self.running = False
        self.receiver_thread = None
        self.sender_thread = None
        self.listen_socket = None
        
        # IoT数据模板
        self.iot_devices = [
            {'type': 'temp', 'priority': 5, 'interval': 2},
            {'type': 'pos', 'priority': 2, 'interval': 5},
            {'type': 'humidity', 'priority': 3, 'interval': 3},
        ]
    
    def _init_listen_socket(self):
        """初始化监听socket"""
        try:
            if self.use_udp:
                self.listen_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                # 绑定到所有接口的5005端口
                self.listen_socket.bind(('0.0.0.0', self.listen_port))
                print(f"  网关监听UDP端口成功: 0.0.0.0:{self.listen_port}")
            else:
                self.listen_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.listen_socket.bind(('0.0.0.0', self.listen_port))
                self.listen_socket.listen(5)
                print(f"  网关监听TCP端口成功: 0.0.0.0:{self.listen_port}")
            return True
        except Exception as e:
            print(f"  初始化监听socket失败: {e}")
            print(f"  可能是端口{self.listen_port}已被占用")
            self.listen_socket = None
            return False
    
    def handle_received_data(self):
        """处理接收到的数据"""
        while self.running:
            try:
                if self.listen_socket:
                    if self.use_udp:
                        # UDP接收
                        data, addr = self.listen_socket.recvfrom(1024)
                        if data:
                            self._process_received_data(data, addr)
                    else:
                        # TCP接收
                        conn, addr = self.listen_socket.accept()
                        data = conn.recv(1024)
                        if data:
                            self._process_received_data(data, addr)
                        conn.close()
            except Exception as e:
                if not self.running:
                    break
                # 忽略临时错误
                pass
    
    def _process_received_data(self, data, addr):
        """处理接收到的数据包"""
        try:
            received_data = data.decode('utf-8').strip()
            print(f"\n  接收到IoT设备数据: {received_data}")
            print(f"  来源地址: {addr}")
            
            # 解析数据
            parts = received_data.split(',', 2)
            if len(parts) >= 3:
                ble_addr, data_type, data_value = parts
                print(f"  解析结果: 设备地址={ble_addr}, 类型={data_type}, 值={data_value}")
                
                # 确定目标IP
                # 根据设备地址或数据类型确定目标
                if ble_addr in ['aa:bb:cc:dd:ee:01', 'aa:bb:cc:dd:ee:04']:
                    target_ip = '192.168.1.20'  # h1
                elif ble_addr == 'aa:bb:cc:dd:ee:02':
                    target_ip = '192.168.1.21'  # h2
                else:
                    # 默认发送到h1
                    target_ip = '192.168.1.20'
                
                # 转发数据
                self.forward_data(received_data, target_ip)
                print(f"  数据已转发到: {target_ip}:{self.target_port}")
            else:
                print(f"  数据格式错误: {received_data}")
        except Exception as e:
            print(f"  处理数据失败: {e}")
    
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
        
        # 生成模拟数值
        if sensor_type == 'temp':
            value = round(random.uniform(20.0, 40.0), 1)
        elif sensor_type == 'pos':
            value = f"({round(random.uniform(-100, 100), 2)},{round(random.uniform(-100, 100), 2)})"
        elif sensor_type == 'humidity':
            value = round(random.uniform(30.0, 80.0), 1)
        else:
            value = round(random.uniform(0, 100), 1)
        
        # 创建数据包格式
        ble_addr = 'aa:bb:cc:dd:ee:03'
        packet_data = f"{ble_addr},{sensor_type},{value}"
        
        # 随机选择目标
        target_ip = '192.168.1.20' if random.random() > 0.5 else '192.168.1.21'
        
        # 转发数据
        self.forward_data(packet_data, target_ip)
        print(f"  网关发送: {sensor_type} -> {target_ip}")
        
        time.sleep(interval)
    
    def start_simulation(self):
        """开始模拟"""
        print(f"=== IoT网关模拟器启动 ===")
        print(f"网关IP: {self.gateway_ip}")
        print(f"监听端口: {self.listen_port}")
        print(f"目标端口: {self.target_port}")
        print("功能: 接收IoT设备数据并转发")
        print("=" * 50)
        
        self.running = True
        
        # 启动接收线程
        if self._init_listen_socket():
            self.receiver_thread = Thread(target=self.handle_received_data)
            self.receiver_thread.daemon = True
            self.receiver_thread.start()
            print(f"  接收线程已启动")
        else:
            print(f"  无法启动接收线程")
        
        # 启动发送线程
        self.sender_thread = Thread(target=self._sender_loop)
        self.sender_thread.daemon = True
        self.sender_thread.start()
        print(f"  发送线程已启动")
        
        # 保持主线程运行
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop_simulation()
    
    def _sender_loop(self):
        """发送线程主循环"""
        while self.running:
            for device in self.iot_devices:
                if self.running:
                    self.simulate_device_data(device)
            
            if self.running:
                time.sleep(1)
    
    def stop_simulation(self):
        """停止模拟"""
        print("\n停止IoT网关模拟...")
        self.running = False
        
        # 关闭监听socket
        if self.listen_socket:
            try:
                self.listen_socket.close()
            except:
                pass
        
        # 等待线程结束
        if self.receiver_thread and self.receiver_thread.is_alive():
            self.receiver_thread.join(timeout=2)
        if self.sender_thread and self.sender_thread.is_alive():
            self.sender_thread.join(timeout=2)
        
        print("模拟器已停止")

def main():
    """主函数"""
    # 等待网络接口完全启动
    time.sleep(3)
    
    simulator = IoTGatewaySimulator(
        gateway_ip='192.168.1.12',
        listen_port=5005,
        target_port=5005,
        use_udp=True
    )
    
    try:
        simulator.start_simulation()
    except KeyboardInterrupt:
        print("\n收到中断信号...")
        simulator.stop_simulation()
        print("程序退出")

if __name__ == '__main__':
    main()

