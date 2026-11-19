"""
OpenFlow 扩展字段基类

统一采用 TLV 编码：

    字节  0          1          2  3        4 ........
         +----------+----------+--------+------------------+
         | type(1B) | len(1B)  | rsv(2B)|      payload     |
         +----------+----------+--------+------------------+
         |<--------- 4 字节头部 --------->|

    len  整个字段的总长度（头部 + 负载），收方据此步进
    rsv  保留 2 字节，发送方填 0、接收方忽略
"""

import struct
from abc import ABC, abstractmethod

TLV_FORMAT = '!BBH'
TLV_HEADER_SIZE = struct.calcsize(TLV_FORMAT)   # 4
TLV_RESERVED = 0
TLV_MAX_LENGTH = 0xFF

class BaseField(ABC):
    """扩展字段基类（TLV 编码）"""

    FIELD_TYPE = None
    FIELD_NAME = None

    def __init__(self):
        pass

    def serialize(self) -> bytes:
        """序列化为 TLV 字段"""
        data = self._serialize_data()
        length = TLV_HEADER_SIZE + len(data)
        if length > TLV_MAX_LENGTH:
            raise ValueError(
                f"字段 {self.FIELD_NAME or self.FIELD_TYPE} 共 {length} 字节，"
                f"超出 TLV 长度字段上限 {TLV_MAX_LENGTH}"
            )
        return struct.pack(TLV_FORMAT, self.FIELD_TYPE, length, TLV_RESERVED) + data

    @abstractmethod
    def _serialize_data(self) -> bytes:
        """序列化具体字段数据"""
        pass

    @staticmethod
    def read_header(data: bytes):
        """读取 TLV 头部，返回 (类型, 长度, 保留)"""
        if len(data) < TLV_HEADER_SIZE:
            raise ValueError(f"数据不足 {TLV_HEADER_SIZE} 字节，无法读取 TLV 头部")
        return struct.unpack(TLV_FORMAT, data[:TLV_HEADER_SIZE])

    @classmethod
    def parse(cls, data: bytes):
        """从二进制数据解析字段（允许存在尾随字节）"""
        field_type, length, reserved = cls.read_header(data)
        if length < TLV_HEADER_SIZE:
            raise ValueError(f"字段声明长度 {length} 小于头部长度 {TLV_HEADER_SIZE}")
        if length > len(data):
            raise ValueError(f"字段声明长度 {length} 超出可用数据 {len(data)}")
        return cls._deserialize_data(data[TLV_HEADER_SIZE:length])

    @classmethod
    @abstractmethod
    def _deserialize_data(cls, data: bytes):
        """反序列化具体字段数据"""
        pass

    @abstractmethod
    def __str__(self):
        """字符串表示"""
        pass

class UInt32Field(BaseField):
    """单值字段：负载为 4 字节大端无符号整数"""

    def __init__(self, value):
        self.value = value

    def _serialize_data(self) -> bytes:
        return struct.pack('!I', self.value)

    @classmethod
    def _deserialize_data(cls, data: bytes):
        return cls(struct.unpack('!I', data[:4])[0])

    def to_dict_entry(self):
        return {self.FIELD_NAME: self.value}

# 旧名保留：历史上两个基类并存导致的编码二义性已合并进 BaseField
IoTExtensionField = BaseField
