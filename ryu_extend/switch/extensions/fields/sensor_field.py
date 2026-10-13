"""
传感器类型字段实现
"""

from .base_field import UInt32Field
from ..constants import SENSOR_TYPES

class SensorTypeField(UInt32Field):
    """传感器类型字段"""

    FIELD_TYPE = 1
    FIELD_NAME = 'sensor_type'

    def __init__(self, sensor_type):
        if isinstance(sensor_type, str):
            sensor_type = SENSOR_TYPES.get(sensor_type.lower(), 1)
        super().__init__(sensor_type)

    def __str__(self):
        sensor_names = {
            1: '温度传感器', 2: '湿度传感器', 3: '光照传感器',
            4: '移动传感器', 5: '压力传感器', 6: '气体传感器', 7: '声音传感器'
        }
        name = sensor_names.get(self.value, f'未知传感器({self.value})')
        return f'SensorType: {name}'
