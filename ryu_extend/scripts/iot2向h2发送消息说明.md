# IoT设备发送消息说明（v4.0.0）

## 📋 概述
本项目已升级到v4.0.0纯NAT网关架构。IoT设备（iot1/iot2/iot4）现在直接发送数据到目标主机（h1/h2），通过iot3的iptables NAT转发。

## 🚀 标准测试方法（推荐）

### 1. 启动网络拓扑
```bash
# 终端1：启动控制器
ryu-manager switch/ble_switch_13.py --verbose --ofp-tcp-listen-port 6634

# 终端2：启动Web面板
python3 templates/sdn_dashboard.py

# 终端3：启动拓扑
sudo python3 topology/iot_sdn_topology.py
```

### 2. 在目标主机启动监听
在mininet终端中：
```bash
mininet> xterm h1 h2
# 在h1窗口: nc -ul 5005
# 在h2窗口: nc -ul 5005
```

### 3. 从IoT设备发送消息
在mininet终端中：
```bash
# 测试iot1 → h1
mininet> iot1 echo "aa:bb:cc:dd:ee:01,temp,25.5" | nc -u 192.168.1.20 5005

# 测试iot2 → h2
mininet> iot2 echo "aa:bb:cc:dd:ee:02,humidity,65.3" | nc -u 192.168.1.21 5005

# 测试iot4 → h1
mininet> iot4 echo "aa:bb:cc:dd:ee:04,pos,(30.12,120.45)" | nc -u 192.168.1.20 5005
```

## 📊 架构说明（v4.0.0）

### 数据流向
```
IoT设备(iot1/iot2/iot4) 
  ↓ (UDP/5005 直接发送到 h1/h2)
iot3(NAT网关 - iptables转发) 
  ↓ (IP转发和NAT)
s1/s2(OpenFlow13交换机) 
  ↓ (控制器下发流表)
h1/h2(监控主机)
```

### 网络配置
- iot1: 192.168.2.10/24，网关 192.168.2.1
- iot2: 192.168.3.11/24，网关 192.168.3.1
- iot4: 192.168.4.13/24，网关 192.168.4.1
- iot3: 4个接口，启用iptables NAT
- h1: 192.168.1.20/24
- h2: 192.168.1.21/24

## 🎯 验证标准

- [ ] iot1 能成功发送数据到 h1
- [ ] iot2 能成功发送数据到 h2
- [ ] iot4 能成功发送数据到 h1
- [ ] Web面板显示s1/s2转发日志
- [ ] 控制器显示PacketIn和流表下发

## 📝 注意事项

1. **直接发送目标主机**：IoT设备数据必须直接发送到h1或h2，不是到网关
2. **端口5005**：统一使用5005端口进行数据传输
3. **网络先启动**：确保Mininet网络拓扑已完全启动
4. **目标主机监听**：h1和h2必须先启动UDP监听

## 🔄 故障排查

### 消息发送失败
```bash
# 1. 测试基本连通性
mininet> iot1 ping -c 3 192.168.1.20

# 2. 检查iptables规则
mininet> iot3 iptables -t nat -L -n -v

# 3. 检查交换机流表
mininet> sh ovs-ofctl dump-flows s1 -O OpenFlow13
```

---
*本文档最后更新：2026-02-24（v4.0.0）*
