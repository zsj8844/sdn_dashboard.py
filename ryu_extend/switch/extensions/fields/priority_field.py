"""
设备优先级字段实现
"""

from .base_field import UInt32Field
from ..constants import PRIORITY_LEVELS

class DevicePriorityField(UInt32Field):
    """设备优先级字段"""

    FIELD_TYPE = 2
    FIELD_NAME = 'device_priority'

    def __init__(self, priority):
        if isinstance(priority, str):
            priority = PRIORITY_LEVELS.get(priority.lower(), 2)
        super().__init__(priority)

    def __str__(self):
        priority_names = {
            1: '低优先级', 2: '普通优先级', 3: '高优先级',
            4: '关键优先级', 5: '紧急优先级'
        }
        name = priority_names.get(self.value, f'级别{self.value}')
        return f'DevicePriority: {name}'
