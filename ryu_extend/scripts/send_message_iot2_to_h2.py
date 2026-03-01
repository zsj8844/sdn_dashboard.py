#!/usr/bin/env python3
"""
iot2向h2发送消息的简单脚本
"""

import socket
import time
import sys

def send_message_to_h2(message="Hello from iot2!", count=5, interval=2):
    """
    从iot2向h2发送UDP消息
    
    Args:
        message: 要发送的消息内容
        count: 发送次数
        interval: 发送间隔(秒)
    """
    
    # h2的IP地址和端口
    H2_IP = '192.168.1.21'
    H2_PORT = 12345  # 使用一个简单的UDP端口
    
    print(f"准备从iot2向h2发送消息...")
    print(f"目标地址: {H2_IP}:{H2_PORT}")
    print(f"消息内容: {message}")
    print(f"发送次数: {count}")
    print("=" * 50)
    
    try:
        # 创建UDP socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(3.0)
        
        success_count = 0
        
        for i in range(count):
            try:
                # 构造带序号的消息
                numbered_message = f"[{i+1}/{count}] {message}"
                
                # 发送消息
                sock.sendto(numbered_message.encode('utf-8'), (H2_IP, H2_PORT))
                print(f"✓ 第{i+1}条消息已发送: {numbered_message}")
                success_count += 1
                
                # 等待间隔
                if i < count - 1:  # 最后一次不需要等待
                    time.sleep(interval)
                    
            except Exception as e:
                print(f"✗ 第{i+1}条消息发送失败: {e}")
                continue
        
        sock.close()
        print("=" * 50)
        print(f"发送完成! 成功: {success_count}/{count}")
        
    except Exception as e:
        print(f"发送过程出错: {e}")

def receive_messages_on_h2():
    """
    在h2上接收消息的函数（用于测试验证）
    """
    H2_PORT = 12345
    
    print(f"h2开始监听端口 {H2_PORT}...")
    print("按Ctrl+C停止监听")
    print("=" * 50)
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(('0.0.0.0', H2_PORT))
        sock.settimeout(1.0)
        
        message_count = 0
        
        while True:
            try:
                data, addr = sock.recvfrom(1024)
                message = data.decode('utf-8')
                message_count += 1
                print(f"#{message_count} 收到来自 {addr} 的消息: {message}")
                
            except socket.timeout:
                continue
            except KeyboardInterrupt:
                break
                
    except Exception as e:
        print(f"监听出错: {e}")
    finally:
        sock.close()
        print(f"\n总共收到 {message_count} 条消息")

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'receive':
        # 在h2上接收消息
        receive_messages_on_h2()
    else:
        # 从iot2发送消息
        if len(sys.argv) > 1:
            message = sys.argv[1]
            send_message_to_h2(message)
        else:
            send_message_to_h2("Hello from iot2!")
