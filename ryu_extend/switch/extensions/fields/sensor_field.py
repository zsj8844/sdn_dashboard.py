"""
传感器类型字段实现
"""

import struct
from .base_field import IoTExtensionField
from ..constants import SENSOR_TYPES

class SensorTypeField(IoTExtensionField):
    """传感器类型字段"""

    FIELD_NAME = 'sensor_type'

    def __init__(self, sensor_type):
        if isinstance(sensor_type, str):
            sensor_type = SENSOR_TYPES.get(sensor_type.lower(), 1)
        super().__init__(1, sensor_type)
    
    def serialize(self):
        """序列化传感器类型字段"""
        return struct.pack('!BBI', self.field_type, self.reserved, self.value)
    
    @classmethod
    def parse(cls, data):
        """解析传感器类型字段"""
        field_type, reserved, value = struct.unpack('!BBI', data[:6])
        return cls(value)
    
    def __str__(self):
        sensor_names = {
            1: '温度传感器', 2: '湿度传感器', 3: '光照传感器',
            4: '移动传感器', 5: '压力传感器', 6: '气体传感器', 7: '声音传感器'
        }
        name = sensor_names.get(self.value, f'未知传感器({self.value})')
        return f'SensorType: {name}'

    def to_dict_entry(self):
        return {self.FIELD_NAME: self.value}