"""
IoT扩展字段管理器
负责字段的创建、序列化和反序列化
"""

import struct
from .constants import EXPERIMENTER_ID
from .sensor_field import SensorTypeField
from .priority_field import DevicePriorityField
from .route_field import RouteSelectField
from .app_field import AppDeploymentField
from .role_field import RoleSwitchField

class IoTExtensionManager:
    """IoT扩展字段管理器"""
    
    def __init__(self):
        self.fields = []
    
    def add_field(self, field):
        """添加字段"""
        self.fields.append(field)
    
    def serialize_fields(self):
        """仅序列化字段数据（不含 Experimenter ID 头），用于 OFPActionExperimenter"""
        data = struct.pack('!B', len(self.fields))
        for field in self.fields:
            data += field.serialize()
        return data

    def serialize_to_experimenter(self):
        """序列化为Experimenter字段格式"""
        # 构造数据: 厂商ID(4B) + 字段数(1B) + 字段数据
        data = struct.pack('!IB', EXPERIMENTER_ID, len(self.fields))

        for field in self.fields:
            data += field.serialize()

        return data
    
    @classmethod
    def parse_from_experimenter(cls, data):
        """从Experimenter数据解析"""
        if len(data) < 5:
            raise ValueError("数据长度不足")
        
        exp_id, field_count = struct.unpack('!IB', data[:5])
        if exp_id != EXPERIMENTER_ID:
            raise ValueError(f"厂商ID不匹配: 期望0x{EXPERIMENTER_ID:08x}, 实际0x{exp_id:08x}")
        
        manager = cls()
        buf = data[5:]
        
        field_classes = {
            1: SensorTypeField,
            2: DevicePriorityField,
            3: RouteSelectField,
            4: AppDeploymentField,
            5: RoleSwitchField
        }
        
        for i in range(field_count):
            if len(buf) < 6:
                break
            field_type = buf[0]
            field_class = field_classes.get(field_type)
            if field_class:
                field = field_class.parse(buf)
                manager.add_field(field)
            buf = buf[6:]
        
        return manager
    
    def get_field_dict(self):
        """获取字段字典"""
        result = {}
        for field in self.fields:
            if isinstance(field, SensorTypeField):
                result['sensor_type'] = field.value
            elif isinstance(field, DevicePriorityField):
                result['device_priority'] = field.value
            elif isinstance(field, RouteSelectField):
                result['route_select'] = field.value
            elif isinstance(field, AppDeploymentField):
                result['app_deployment'] = {
                    'app_id': field.app_id,
                    'action': field.action,
                    'version': field.version
                }
            elif isinstance(field, RoleSwitchField):
                result['role_switch'] = {
                    'target_mode': field.target_mode,
                    'force': field.force
                }
        return result
    
    def print_fields(self):
        """打印所有字段"""
        for field in self.fields:
            print(f"  {field}")

def create_iot_extension(
    sensor_type=None,
    device_priority=None,
    route_select=None,
    app_deployment=None,
    role_switch=None
):
    """创建IoT扩展字段的便捷函数"""
    manager = IoTExtensionManager()
    
    if sensor_type is not None:
        manager.add_field(SensorTypeField(sensor_type))
    
    if device_priority is not None:
        manager.add_field(DevicePriorityField(device_priority))
    
    if route_select is not None:
        manager.add_field(RouteSelectField(route_select))
    
    if app_deployment is not None:
        manager.add_field(
            AppDeploymentField(
                app_deployment.get('app_id', ''),
                app_deployment.get('action', 0),
                app_deployment.get('version', '')
            )
        )
    
    if role_switch is not None:
        manager.add_field(
            RoleSwitchField(
                role_switch.get('target_mode', 1),
                role_switch.get('force', False)
            )
        )
    
    return manager