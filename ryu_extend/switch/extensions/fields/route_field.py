"""
路由选择字段实现
"""

import struct
from .base_field import IoTExtensionField
from ..constants import ROUTE_OPTIONS

class RouteSelectField(IoTExtensionField):
    """路由选择字段"""

    FIELD_NAME = 'route_select'

    def __init__(self, route):
        if isinstance(route, str):
            route = ROUTE_OPTIONS.get(route.lower(), 1)
        super().__init__(3, route)
    
    def serialize(self):
        """序列化路由选择字段"""
        return struct.pack('!BBI', self.field_type, self.reserved, self.value)
    
    @classmethod
    def parse(cls, data):
        """解析路由选择字段"""
        field_type, reserved, value = struct.unpack('!BBI', data[:6])
        return cls(value)
    
    def __str__(self):
        route_names = {1: '路径A(主路径)', 2: '路径B(备用路径)'}
        name = route_names.get(self.value, f'路径{self.value}')
        return f'RouteSelect: {name}'

    def to_dict_entry(self):
        return {self.FIELD_NAME: self.value}