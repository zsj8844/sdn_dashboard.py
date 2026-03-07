"""
OpenFlow 扩展字段基类
"""

import struct
from abc import ABC, abstractmethod

class IoTExtensionField(ABC):
    """IoT扩展字段基类"""
    
    def __init__(self, field_type=None, value=None):
        self.field_type = field_type
        self.value = value
        self.reserved = 0
    
    @abstractmethod
    def serialize(self):
        """序列化字段为二进制数据"""
        pass
    
    @classmethod
    @abstractmethod
    def parse(cls, data):
        """从二进制数据解析字段"""
        pass
    
    @abstractmethod
    def __str__(self):
        """字符串表示"""
        pass

class BaseField(ABC):
    """扩展字段基类（新版本接口）"""
    
    FIELD_TYPE = None
    FIELD_NAME = None
    
    def __init__(self):
        pass
    
    def serialize(self) -> bytes:
        """序列化字段为二进制数据"""
        # 格式: 类型(1B) + 长度(1B) + 保留(2B) + 数据
        data = self._serialize_data()
        length = len(data) + 6  # 6字节头部
        return struct.pack('!BBH', self.FIELD_TYPE, length, 0) + data
    
    @abstractmethod
    def _serialize_data(self) -> bytes:
        """序列化具体字段数据"""
        pass
    
    @classmethod
    def parse(cls, data: bytes):
        """从二进制数据解析字段"""
        # 跳过头部(6字节)
        field_data = data[6:]
        return cls._deserialize_data(field_data)
    
    @classmethod
    @abstractmethod
    def _deserialize_data(cls, data: bytes):
        """反序列化具体字段数据"""
        pass
    
    @abstractmethod
    def __str__(self):
        """字符串表示"""
        pass
