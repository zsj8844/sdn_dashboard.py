# OpenFlow 协议扩展实现文档

## 项目概述
本项目实现了基于 OpenFlow 1.3 的 IoT 协议扩展，通过 Experimenter 字段为数据包添加业务标签，支持传感器类型识别、设备优先级标记和路由选择功能。

## 目录结构
```
ryu_extend/switch/
├── extensions/           # 扩展字段核心模块
│   ├── __init__.py      # 模块导出
│   ├── constants.py     # 常量定义
│   ├── base_field.py    # 基类定义
│   ├── sensor_field.py  # 传感器类型字段
│   ├── priority_field.py # 设备优先级字段
│   ├── route_field.py   # 路由选择字段
│   ├── manager.py       # 字段管理器
│   └── demo.py          # 演示程序
├── test/                # 测试目录
│   ├── test_extensions.py # 扩展字段测试
│   └── analyze_packet.py  # 数据包分析工具
├── ble_switch_13.py     # 主控制器（已集成扩展功能）
└── README.md            # 项目说明文档
```

## 核心功能

### 1. 扩展字段定义
实现了3个核心扩展字段：

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

### 2. 封装机制
```
数据包格式：
[标准OpenFlow头部] + [Experimenter字段]
                    ↓
              [厂商ID(4B)] + [字段计数(1B)] + [字段数据]
                                              ↓
                                    [字段类型(1B)] + [保留(1B)] + [值(4B)]
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
控制器已自动集成扩展字段功能，在处理BLE数据包时会：
1. 根据传感器类型自动创建SensorType字段
2. 根据数值大小确定DevicePriority字段
3. 默认使用RouteSelect字段指向主路径

### 3. 测试验证
```bash
# 基本功能测试
cd ryu_extend/switch
python3 test/test_extensions.py

# 综合功能测试
python3 test/comprehensive_test.py

# OpenFlow数据包分析
python3 test/analyze_packet.py
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
只需继承`IoTExtensionField`基类并实现相应方法即可。

### 2. 新的映射关系
可在`constants.py`中添加新的映射表。

### 3. 协议版本升级
当前基于OpenFlow 1.3，可适配其他版本。

## 注意事项

1. **兼容性**：扩展字段基于Experimenter机制，与标准OpenFlow完全兼容
2. **性能影响**：字段封装增加约10字节开销，对网络性能影响极小
3. **安全性**：建议在生产环境中添加字段验证机制
4. **维护性**：模块化设计便于后续维护和扩展

## 项目架构更新（v4.0.0）

### 纯NAT网关架构
- 移除了复杂的网关模拟器
- 使用标准iptables NAT和IP转发
- IoT设备直接发送数据到目标主机（h1/h2）
- 控制器基于目标IP匹配流表，确保所有设备数据正常转发

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

### 测试命令
```bash
# iot1 → h1
mininet> iot1 echo "aa:bb:cc:dd:ee:01,temp,25.5" | nc -u 192.168.1.20 5005

# iot2 → h2
mininet> iot2 echo "aa:bb:cc:dd:ee:02,humidity,65.3" | nc -u 192.168.1.21 5005

# iot4 → h1
mininet> iot4 echo "aa:bb:cc:dd:ee:04,pos,(30.12,120.45)" | nc -u 192.168.1.20 5005
```

---
*本文档最后更新：2026-02-24（v4.0.0）*