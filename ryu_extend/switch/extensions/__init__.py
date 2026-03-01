"""
OpenFlow IoT 扩展字段模块
提供传感器类型、设备优先级、路由选择、应用下发和角色切换等扩展功能
"""

from .manager import IoTExtensionManager, create_iot_extension
from .app_deployment import AppDeploymentManager, EdgeApplication, AppType, AppStatus
from .role_switch import DeviceRoleManager, DeviceMode, DeviceCapabilities

__all__ = [
    'IoTExtensionManager',
    'create_iot_extension',
    'AppDeploymentManager',
    'EdgeApplication',
    'AppType',
    'AppStatus',
    'DeviceRoleManager',
    'DeviceMode',
    'DeviceCapabilities'
]
