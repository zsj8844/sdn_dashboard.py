# SDN IoT 扩展项目

## 项目概述

这是一个基于Ryu控制器的软件定义网络(SDN)物联网(IoT)扩展项目，实现了BLE Mesh网络的数据收集、转发和可视化监控功能。

## 目录结构

```
ryu_extend/
├── switch/                 # 控制器扩展模块
│   └── ble_switch_13.py    # BLE Mesh交换机控制器
├── templates/              # Web监控面板
│   ├── sdn_dashboard.py    # 后端服务
│   └── dashboard.html      # 前端界面
├── topology/               # 网络拓扑脚本
│   └── iot_sdn_topology.py # Mininet拓扑定义
├── start_project.sh        # 一键启动脚本
└── docx/                   # 项目文档
    └── 无标题文档 .txt     # 详细技术文档
```

## 功能特性

### 核心功能
- **BLE数据转发**: 自动识别和转发BLE Mesh网络数据包
- **智能流表管理**: 动态下发OpenFlow流表规则
- **实时监控面板**: Web界面展示网络状态和设备信息
- **日志收集**: 实时收集和展示BLE设备数据
- **连通性检测**: 自动检测网络设备连通状态

### 技术特点
- 基于OpenFlow 1.3协议
- 支持RESTful API接口
- 响应式Web界面设计
- 多线程异步处理
- 完善的日志系统

## 快速开始

### 环境要求
- Ubuntu 20.04 LTS 或更高版本
- Python 3.8+
- Ryu控制器 4.34
- Mininet 2.3.0
- Open vSwitch 2.13+

### 一键部署

```bash
# 给启动脚本添加执行权限
chmod +x start_project.sh

# 运行一键部署脚本
./start_project.sh
```

### 手动部署

1. **启动控制器**
```bash
cd ryu_extend
ryu-manager switch/ble_switch_13.py --verbose --ofp-tcp-listen-port 6634
```

2. **启动Web面板**
```bash
python3 templates/sdn_dashboard.py
```

3. **启动网络拓扑**
```bash
sudo python3 topology/iot_sdn_topology.py
```

## 使用说明

### 访问监控面板
启动成功后，访问 `http://localhost:5000` 查看监控界面

### API接口

#### 接收BLE日志
```
POST /api/logs
Content-Type: application/json

{
    "ble_addr": "aa:bb:cc:dd:ee:01",
    "type": "temperature",
    "value": "25.6",
    "src_ip": "192.168.1.10"
}
```

#### 健康检查
```
GET /health
```

### 网络拓扑命令行参数

```bash
# 基本使用
sudo python3 topology/iot_sdn_topology.py

# 指定控制器地址
sudo python3 topology/iot_sdn_topology.py --controller-ip 192.168.1.100 --controller-port 6653

# 调试模式
sudo python3 topology/iot_sdn_topology.py --debug

# 不清理现有网络
sudo python3 topology/iot_sdn_topology.py --no-cleanup
```

## 架构说明

### 数据流向
```
BLE设备 → Mininet主机 → OpenFlow交换机 → Ryu控制器 → Web面板
```

### 组件交互
1. **BLE设备**通过UDP端口5005发送数据
2. **控制器**捕获数据包并解析BLE信息
3. **Web面板**通过API接收日志并在前端展示
4. **连通性检测**通过OVS流表分析网络状态

## 配置说明

### 控制器配置 (ble_switch_13.py)
- `BLE_ADDR_MATCH`: BLE地址匹配字段
- `BLE_OUTPUT_ACTION`: BLE输出动作
- `MY_EXPERIMENTER_ID`: 实验者ID

### Web面板配置 (sdn_dashboard.py)
- `DEVICES`: 网络设备定义
- `BLE_MESH_NODES`: BLE节点配置
- `BLE_MESH_LOG`: 日志缓存大小

### 启动脚本配置 (start_project.sh)
- `PROJECT_DIR`: 项目根目录
- `CONTROLLER_PORT`: 控制器监听端口
- `DASHBOARD_PORT`: Web面板端口

## 故障排除

### 常见问题

1. **控制器无法启动**
   - 检查Ryu是否正确安装
   - 确认端口未被占用
   - 查看控制器日志文件

2. **Web面板无法访问**
   - 检查5000端口是否开放
   - 确认防火墙设置
   - 查看dashboard.log日志

3. **网络连通性问题**
   - 使用`sudo mn -c`清理网络
   - 检查OVS服务状态
   - 验证控制器连接

### 日志文件位置
- 控制器日志: `~/ryucontronl/logs/controller.log`
- Web面板日志: `~/ryucontronl/logs/dashboard.log`
- 拓扑日志: `~/ryucontronl/logs/topology.log`

## 开发指南

### 代码规范
- 使用Python 3标准库
- 遵循PEP 8编码规范
- 添加适当的日志记录
- 编写清晰的注释

### 扩展建议
1. 添加更多传感器类型支持
2. 实现数据持久化存储
3. 增加安全认证机制
4. 支持多控制器部署

## 许可证

本项目仅供学习和研究使用。

## 联系方式

如有问题或建议，请提交issue或联系项目维护者。