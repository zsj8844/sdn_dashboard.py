#!/usr/bin/env python3
"""
简单的网络连通性测试
"""

import socket
import time

def test_basic_connectivity():
    """测试基本网络连通性"""
    targets = [
        ('192.168.1.10', 'iot1'),
        ('192.168.1.11', 'iot2'), 
        ('192.168.1.12', 'iot3'),
        ('192.168.1.13', 'iot4'),
        ('192.168.1.20', 'h1'),
        ('192.168.1.21', 'h2')
    ]
    
    print("=== 网络设备连通性测试 ===")
    
    for ip, name in targets:
        try:
            # 尝试连接TCP端口
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex((ip, 22))  # 测试SSH端口
            sock.close()
            
            if result == 0:
                print(f"✓ {name} ({ip}) - 可达")
            else:
                print(f"✗ {name} ({ip}) - 不可达")
                
        except Exception as e:
            print(f"✗ {name} ({ip}) - 错误: {e}")

def send_simple_udp():
    """发送简单的UDP测试消息"""
    print("\n=== UDP消息测试 ===")
    
    target_ip = '192.168.1.21'  # h2
    target_port = 12345
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(3)
        
        message = "Hello from local test!"
        sock.sendto(message.encode('utf-8'), (target_ip, target_port))
        print(f"✓ 已向 {target_ip}:{target_port} 发送消息: {message}")
        
        sock.close()
        return True
        
    except Exception as e:
        print(f"✗ 发送失败: {e}")
        return False

if __name__ == '__main__':
    test_basic_connectivity()
    send_simple_udp()
