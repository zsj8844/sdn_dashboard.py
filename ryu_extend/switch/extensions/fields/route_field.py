"""
路由选择字段实现
"""

from .base_field import UInt32Field
from ..constants import ROUTE_OPTIONS

class RouteSelectField(UInt32Field):
    """路由选择字段"""

    FIELD_TYPE = 3
    FIELD_NAME = 'route_select'

    def __init__(self, route):
        if isinstance(route, str):
            route = ROUTE_OPTIONS.get(route.lower(), 1)
        super().__init__(route)

    def __str__(self):
        route_names = {1: '路径A(主路径)', 2: '路径B(备用路径)'}
        name = route_names.get(self.value, f'路径{self.value}')
        return f'RouteSelect: {name}'
