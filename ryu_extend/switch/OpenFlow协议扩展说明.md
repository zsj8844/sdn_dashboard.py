# OpenFlow 协议扩展实现文档

## 项目概述
本项目实现了基于 OpenFlow 1.3 的 IoT 协议扩展，通过 Experimenter 字段为数据包添加业务标签，支持传感器类型识别、设备优先级标记、路由选择、应用下发和角色切换功能。

## 目录结构
```
ryu_extend/switch/
├── extensions/              # 扩展字段核心模块
│   ├── __init__.py          # 模块导出
│   ├── constants.py         # 常量定义（厂商ID、字段类型、映射表）
│   ├── manager.py           # 字段管理器 + TLV 编解码入口
│   ├── fields/              # 字段定义
│   │   ├── base_field.py    # TLV 基类（BaseField / UInt32Field）
│   │   ├── sensor_field.py  # 传感器类型字段
│   │   ├── priority_field.py# 设备优先级字段
│   │   ├── route_field.py   # 路由选择字段
│   │   ├── app_field.py     # 应用下发字段
│   │   └── role_field.py    # 角色切换字段
│   └── features/            # 业务模型（枚举与管理器，非线格式）
│       ├── app_deployment.py
│       └── role_switch.py
├── test/                    # 测试与调试脚本
└── ble_switch_13.py         # 主控制器（已集成扩展功能）
```

## 核心功能

### 1. 扩展字段定义
实现了5个扩展字段：

**SensorType（传感器类型）**
- 字段类型：1
- 取值范围：temp(1), humidity(2), light(3), motion(4), pressure(5), gas(6), sound(7)
- 用途：标识IoT设备的传感器类型

**DevicePriority（设备优先级）**
- 字段类型：2  
- 取值范围：1-5 (low, normal, high, critical, emergency)
- 用途：标识数据包的业务优先级

**RouteSelect（路由选择）**
- 字段类型：3
- 取值范围：route_a(1), route_b(2)
- 用途：指定数据包转发路径

**AppDeployment（应用下发）**
- 字段类型：4
- 负载：app_id(32B) + action(1B) + version(16B)，共49B
- 用途：向边缘设备下发应用及版本

**RoleSwitch（角色切换）**
- 字段类型：5
- 负载：target_mode(1B) + force(1B)，共2B
- 用途：切换设备工作模式，force 表示强制切换

### 2. 封装机制
```
数据包格式：
[标准OpenFlow头部] + [Experimenter字段]
                    ↓
              [厂商ID(4B)] + [字段计数(1B)] + [字段数据]
                                              ↓
                [字段类型(1B)] + [长度(1B)] + [保留(2B)] + [负载]
                |<---------- 4 字节头部 ---------->|

长度字段为整个字段的总长度（头部 + 负载），收方据此步进；
保留字段 2 字节，发送方填 0、接收方忽略。
```

### 3. 解析机制
- 自动识别厂商ID
- 按字段类型创建对应对象
- 提供友好的数据显示接口

## 使用方法

### 1. 基本使用
```python
from extensions import create_iot_extension

# 创建扩展字段
ext_mgr = create_iot_extension(
    sensor_type='temp',
    device_priority=3,
    route_select='route_a'
)

# 序列化
serialized_data = ext_mgr.serialize_to_experimenter()

# 反序列化
parsed_mgr = IoTExtensionManager.parse_from_experimenter(serialized_data)
```

### 2. 在控制器中使用
控制器在 Packet-In 路径中集成扩展字段（`Other_Modules/packet_processor.py:_parse_ble()` → `Other_Modules/device/iot_processor.py:IoTProcessor.process()`）：
1. 根据传感器类型创建 SensorType 字段
2. 根据数值大小确定 DevicePriority 字段（>80→5，>50→4，>30→3，否则 2）
3. priority ≥ 4 使用 RouteSelect=route_b，否则 route_a
4. 序列化结果通过 `OFPActionExperimenterUnknown` 注入被动下发的流表

> **限制**：主动预装流表 priority=100 与扩展流表使用相同的 `eth_type+ipv4_dst` 匹配，会优先命中，扩展流表不会执行；主动流表生效后 IPv4 流量不再产生 Packet-In，该链路在稳态下基本不会运行。

### 3. 测试验证
```bash
# 基本功能测试
cd ryu_extend/switch
python3 test/v3-v4_扩展字段/test_all_extensions.py

# 综合功能测试
python3 test/v3-v4_扩展字段/comprehensive_test.py

# OpenFlow数据包分析
python3 test/v3-v4_扩展字段/analyze_packet.py
```

## 验收标准验证

### ✓ 封装/解析功能
- [✓] 控制器能正常执行封装/解析操作
- [✓] 无格式错误，能准确打印扩展字段值
- [✓] 提供完整的序列化和反序列化接口

### ✓ 网络功能兼容性
- [✓] 扩展字段封装/解析不影响原生OpenFlow功能
- [✓] 设备间基础ping通正常
- [✓] BLE数据包处理流程保持完整

### ✓ 字段功能验证
- [✓] 控制器添加打印逻辑，能展示字段值
- [✓] 支持模拟封装/解析操作
- [✓] 提供字段字典格式输出

## 技术特点

### 1. 模块化设计
- 各字段类型独立实现
- 统一的基类接口
- 灵活的管理器模式

### 2. 错误处理
- 完善的异常处理机制
- 数据格式验证
- 优雅的降级处理

### 3. 性能优化
- 高效的二进制序列化
- 最小化内存占用
- 快速字段查找

## 扩展性考虑

### 1. 新增字段类型
只需继承`BaseField`基类并实现 `_serialize_data()` / `_deserialize_data()` 即可。

### 2. 新的映射关系
可在`constants.py`中添加新的映射表。

### 3. 协议版本升级
当前基于OpenFlow 1.3，可适配其他版本。

## 注意事项

1. **兼容性**：扩展字段基于Experimenter机制，与标准OpenFlow完全兼容
2. **性能影响**：字段封装增加约30字节开销（3个字段），对网络性能影响极小
3. **安全性**：建议在生产环境中添加字段验证机制
4. **维护性**：模块化设计便于后续维护和扩展

## 当前架构（v4.5.2）

- 网关（iot3）开启 `net.ipv4.ip_forward`，不使用 iptables NAT
- 交换机 s1/s2 的转发由控制器预装 IPv4 流表完成
- 网关应用层监听 5005：解析 BLE 数据、编码 Experimenter 字段，并把原始数据转发到 h1/h2
- 扩展信息尝试发往 `127.0.0.1:6650`，但控制器未监听该端口，且 iot3 命名空间内 `127.0.0.1` 不是宿主机，因此不会到达控制器
- Experimenter 动作仅注入到 Packet-In 路径下发的流表中，受主动流表优先级遮蔽

### 数据流向

```
IoT设备(iot1/iot2/iot4)
  ↓ (UDP/5005)
iot3(网关：IP转发 + 应用层收数/编码/转发)
  ↓
s1/s2(OpenFlow13，控制器下发流表)
  ↓
h1/h2(监控主机)
```

### 测试命令

```bash
# iot1 → h1
mininet> iot1 echo "aa:bb:cc:dd:ee:01,temp,25.5" | nc -u 192.168.1.20 5005

# iot2 → h2
mininet> iot2 echo "aa:bb:cc:dd:ee:02,humidity,65.3" | nc -u 192.168.1.21 5005

# iot4 → h1
mininet> iot4 echo "aa:bb:cc:dd:ee:04,pos,(30.12,120.45)" | nc -u 192.168.1.20 5005

# 经过网关应用层处理
mininet> iot1 echo "aa:bb:cc:dd:ee:01,temp,25.5" | nc -u 192.168.2.1 5005
```

---
*本文档最后更新：2026-11-17（v4.5.2）*
