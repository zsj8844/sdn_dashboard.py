"""
应用下发扩展字段
用于在OpenFlow消息中携带应用下发相关信息
"""

from .base_field import BaseField


class AppDeploymentField(BaseField):
    """应用下发字段"""
    
    FIELD_TYPE = 4
    FIELD_NAME = "app_deployment"
    
    def __init__(self, app_id: str, action: int, version: str = ""):
        super().__init__()
        self.app_id = app_id
        self.action = action
        self.version = version
    
    def _serialize_data(self) -> bytes:
        """序列化字段数据"""
        app_id_bytes = self.app_id.encode('utf-8')[:32].ljust(32, b'\x00')
        version_bytes = self.version.encode('utf-8')[:16].ljust(16, b'\x00')
        return app_id_bytes + bytes([self.action]) + version_bytes
    
    @classmethod
    def _deserialize_data(cls, data: bytes):
        """反序列化字段数据"""
        app_id = data[:32].rstrip(b'\x00').decode('utf-8')
        action = data[32]
        version = data[33:49].rstrip(b'\x00').decode('utf-8')
        return cls(app_id, action, version)
    
    def __str__(self):
        return f"AppDeployment(app_id={self.app_id}, action={self.action}, version={self.version})"
