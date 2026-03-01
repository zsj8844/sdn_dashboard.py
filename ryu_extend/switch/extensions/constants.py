"""
OpenFlow 扩展字段常量定义
"""

# 厂商ID
EXPERIMENTER_ID = 0x12345678

# 字段类型定义
FIELD_TYPE_SENSOR = 1      # 传感器类型
FIELD_TYPE_PRIORITY = 2    # 设备优先级
FIELD_TYPE_ROUTE = 3       # 路由选择

# 传感器类型映射
SENSOR_TYPES = {
    'temp': 1,      # 温度传感器
    'humidity': 2,  # 湿度传感器
    'light': 3,     # 光照传感器
    'motion': 4,    # 移动传感器
    'pressure': 5,  # 压力传感器
    'gas': 6,       # 气体传感器
    'sound': 7      # 声音传感器
}

# 优先级映射
PRIORITY_LEVELS = {
    'low': 1,       # 低优先级
    'normal': 2,    # 普通优先级
    'high': 3,      # 高优先级
    'critical': 4,  # 关键优先级
    'emergency': 5  # 紧急优先级
}

# 路由选择映射
ROUTE_OPTIONS = {
    'route_a': 1,   # 路径A(主路径)
    'route_b': 2    # 路径B(备用路径)
}