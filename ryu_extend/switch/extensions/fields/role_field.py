"""
角色切换扩展字段
用于在OpenFlow消息中携带角色切换相关信息
"""

from .base_field import BaseField


class RoleSwitchField(BaseField):
    """角色切换字段"""
    
    FIELD_TYPE = 5
    FIELD_NAME = "role_switch"
    
    def __init__(self, target_mode: int, force: bool = False):
        super().__init__()
        self.target_mode = target_mode
        self.force = force
    
    def _serialize_data(self) -> bytes:
        """序列化字段数据"""
        return bytes([self.target_mode, 1 if self.force else 0])
    
    @classmethod
    def _deserialize_data(cls, data: bytes):
        """反序列化字段数据"""
        target_mode = data[0]
        force = data[1] == 1
        return cls(target_mode, force)
    
    def __str__(self):
        return f"RoleSwitch(target_mode={self.target_mode}, force={self.force})"

    def to_dict_entry(self):
        return {self.FIELD_NAME: {
            'target_mode': self.target_mode,
            'force': self.force
        }}
