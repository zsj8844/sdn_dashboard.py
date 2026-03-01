"""
OpenFlow 扩展字段基类
"""

import struct
from abc import ABC, abstractmethod

class IoTExtensionField(ABC):
    """IoT扩展字段基类"""
    
    def __init__(self, field_type, value):
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