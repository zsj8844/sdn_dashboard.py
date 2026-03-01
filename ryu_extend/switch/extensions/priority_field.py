"""
设备优先级字段实现
"""

import struct
from .base_field import IoTExtensionField
from .constants import PRIORITY_LEVELS

class DevicePriorityField(IoTExtensionField):
    """设备优先级字段"""
    
    def __init__(self, priority):
        if isinstance(priority, str):
            priority = PRIORITY_LEVELS.get(priority.lower(), 2)
        super().__init__(2, priority)
    
    def serialize(self):
        """序列化设备优先级字段"""
        return struct.pack('!BBI', self.field_type, self.reserved, self.value)
    
    @classmethod
    def parse(cls, data):
        """解析设备优先级字段"""
        field_type, reserved, value = struct.unpack('!BBI', data[:6])
        return cls(value)
    
    def __str__(self):
        priority_names = {
            1: '低优先级', 2: '普通优先级', 3: '高优先级',
            4: '关键优先级', 5: '紧急优先级'
        }
        name = priority_names.get(self.value, f'级别{self.value}')
        return f'DevicePriority: {name}'