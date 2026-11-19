"""
角色切换功能模块
负责设备模式识别和动态模式切换
"""

from enum import Enum
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass


class DeviceMode(Enum):
    """设备模式枚举"""
    PURE_FORWARDING = 1
    COMPUTE_HYBRID = 2
    IOT_GATEWAY = 3
    
    @classmethod
    def from_string(cls, mode_str: str) -> 'DeviceMode':
        """从字符串转换为设备模式"""
        mode_map = {
            'pure_forwarding': cls.PURE_FORWARDING,
            'compute_hybrid': cls.COMPUTE_HYBRID,
            'iot_gateway': cls.IOT_GATEWAY
        }
        return mode_map.get(mode_str.lower(), cls.PURE_FORWARDING)
    
    def to_string(self) -> str:
        """转换为字符串"""
        return self.name.lower()


@dataclass
class DeviceCapabilities:
    """设备能力描述"""
    cpu_cores: int = 1
    memory_mb: int = 512
    storage_mb: int = 1024
    network_ports: int = 2
    supports_nat: bool = False
    supports_container: bool = False
    supports_ble: bool = False


@dataclass
class ModeTransition:
    """模式转换规则"""
    from_mode: DeviceMode
    to_mode: DeviceMode
    transition_func: Optional[Callable] = None
    requires_reboot: bool = False


class DeviceRoleManager:
    """设备角色管理器"""
    
    def __init__(self):
        self.devices: Dict[str, Dict[str, Any]] = {}
        self.mode_transitions: List[ModeTransition] = []
        self.switch_history: List[Dict[str, Any]] = []
        self._init_default_transitions()
    
    def _init_default_transitions(self):
        """初始化默认的模式转换规则"""
        self.add_transition(DeviceMode.PURE_FORWARDING, DeviceMode.COMPUTE_HYBRID, requires_reboot=False)
        self.add_transition(DeviceMode.PURE_FORWARDING, DeviceMode.IOT_GATEWAY, requires_reboot=True)
        self.add_transition(DeviceMode.COMPUTE_HYBRID, DeviceMode.PURE_FORWARDING, requires_reboot=False)
        self.add_transition(DeviceMode.COMPUTE_HYBRID, DeviceMode.IOT_GATEWAY, requires_reboot=True)
        self.add_transition(DeviceMode.IOT_GATEWAY, DeviceMode.PURE_FORWARDING, requires_reboot=True)
        self.add_transition(DeviceMode.IOT_GATEWAY, DeviceMode.COMPUTE_HYBRID, requires_reboot=True)
    
    def add_transition(
        self,
        from_mode: DeviceMode,
        to_mode: DeviceMode,
        transition_func: Optional[Callable] = None,
        requires_reboot: bool = False
    ):
        """添加模式转换规则"""
        transition = ModeTransition(
            from_mode=from_mode,
            to_mode=to_mode,
            transition_func=transition_func,
            requires_reboot=requires_reboot
        )
        self.mode_transitions.append(transition)
    
    def register_device(
        self,
        device_id: str,
        device_name: str,
        initial_mode: DeviceMode = DeviceMode.PURE_FORWARDING,
        capabilities: Optional[DeviceCapabilities] = None
    ) -> Dict[str, Any]:
        """注册设备"""
        if device_id in self.devices:
            raise ValueError(f"设备 {device_id} 已注册")
        
        self.devices[device_id] = {
            'device_id': device_id,
            'device_name': device_name,
            'current_mode': initial_mode,
            'target_mode': None,
            'capabilities': capabilities or DeviceCapabilities(),
            'registered_at': datetime.now().isoformat(),
            'last_mode_switch': None,
            'switch_count': 0
        }
        
        return self.devices[device_id]
    
    def identify_device_mode(
        self,
        device_id: str,
        traffic_pattern: Optional[Dict[str, Any]] = None,
        resource_usage: Optional[Dict[str, Any]] = None
    ) -> DeviceMode:
        """识别设备当前模式（基于流量和资源使用情况）"""
        if device_id not in self.devices:
            raise ValueError(f"设备 {device_id} 未注册")
        
        device = self.devices[device_id]
        identified_mode = device['current_mode']
        
        if traffic_pattern or resource_usage:
            identified_mode = self._analyze_and_identify(device, traffic_pattern, resource_usage)
        
        return identified_mode
    
    def _analyze_and_identify(
        self,
        device: Dict[str, Any],
        traffic_pattern: Optional[Dict[str, Any]] = None,
        resource_usage: Optional[Dict[str, Any]] = None
    ) -> DeviceMode:
        """分析设备状态并识别模式"""
        capabilities = device['capabilities']
        current_mode = device['current_mode']
        
        if resource_usage:
            cpu_usage = resource_usage.get('cpu_usage', 0)
            memory_usage = resource_usage.get('memory_usage', 0)
            
            if cpu_usage > 70 and capabilities.cpu_cores >= 2:
                if current_mode == DeviceMode.PURE_FORWARDING:
                    return DeviceMode.COMPUTE_HYBRID
        
        if traffic_pattern:
            iot_traffic_ratio = traffic_pattern.get('iot_traffic_ratio', 0)
            if iot_traffic_ratio > 50 and capabilities.supports_nat and capabilities.supports_ble:
                return DeviceMode.IOT_GATEWAY
        
        return current_mode
    
    def can_switch_mode(self, device_id: str, target_mode: DeviceMode) -> bool:
        """检查设备是否可以切换到目标模式"""
        if device_id not in self.devices:
            return False
        
        device = self.devices[device_id]
        current_mode = device['current_mode']
        
        if current_mode == target_mode:
            return False
        
        has_transition = any(
            t.from_mode == current_mode and t.to_mode == target_mode
            for t in self.mode_transitions
        )
        
        if not has_transition:
            return False
        
        capabilities = device['capabilities']
        
        if target_mode == DeviceMode.COMPUTE_HYBRID:
            if capabilities.cpu_cores < 2 or capabilities.memory_mb < 1024:
                return False
        
        if target_mode == DeviceMode.IOT_GATEWAY:
            if not capabilities.supports_nat or not capabilities.supports_ble:
                return False
        
        return True
    
    def switch_mode(
        self,
        device_id: str,
        target_mode: DeviceMode,
        force: bool = False
    ) -> Dict[str, Any]:
        """切换设备模式"""
        if device_id not in self.devices:
            raise ValueError(f"设备 {device_id} 未注册")
        
        if not force and not self.can_switch_mode(device_id, target_mode):
            raise ValueError(f"设备 {device_id} 无法切换到 {target_mode.name}")
        
        device = self.devices[device_id]
        old_mode = device['current_mode']
        
        transition_record = {
            'device_id': device_id,
            'old_mode': old_mode.name,
            'new_mode': target_mode.name,
            'timestamp': datetime.now().isoformat(),
            'status': 'pending'
        }
        
        transition = next(
            (t for t in self.mode_transitions if t.from_mode == old_mode and t.to_mode == target_mode),
            None
        )
        
        if transition and transition.transition_func:
            transition.transition_func(device)
        
        device['current_mode'] = target_mode
        device['target_mode'] = None
        device['last_mode_switch'] = datetime.now().isoformat()
        device['switch_count'] += 1
        
        transition_record['status'] = 'success'
        transition_record['requires_reboot'] = transition.requires_reboot if transition else False
        
        self.switch_history.append(transition_record)
        
        return transition_record
    
    def get_device(self, device_id: str) -> Optional[Dict[str, Any]]:
        """获取设备信息"""
        return self.devices.get(device_id)
    
    def list_devices(self) -> List[Dict[str, Any]]:
        """列出所有设备"""
        return list(self.devices.values())
    
    def get_switch_history(self, device_id: str = None) -> List[Dict[str, Any]]:
        """获取模式切换历史"""
        if device_id:
            return [h for h in self.switch_history if h['device_id'] == device_id]
        return self.switch_history
    
    def get_available_modes(self, device_id: str) -> List[DeviceMode]:
        """获取设备可用的模式列表"""
        if device_id not in self.devices:
            return []
        
        device = self.devices[device_id]
        current_mode = device['current_mode']
        
        available = []
        for transition in self.mode_transitions:
            if transition.from_mode == current_mode:
                if self.can_switch_mode(device_id, transition.to_mode):
                    available.append(transition.to_mode)
        
        return available
