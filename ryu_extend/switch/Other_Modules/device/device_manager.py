"""
设备管理模块

封装边缘应用下发和设备角色切换的对外接口。
对 AppDeploymentManager / DeviceRoleManager 做一层薄封装。
"""

import logging

logger = logging.getLogger(__name__)


class DeviceManager:
    """设备生命周期管理：注册 + 角色切换 + 应用部署"""

    def __init__(self, app_deployment_manager, device_role_manager, extension_enabled=True):
        self._app_mgr = app_deployment_manager
        self._role_mgr = device_role_manager
        self.enabled = extension_enabled

    def _require_enabled(self):
        if not self.enabled:
            raise RuntimeError("扩展功能未启用")

    # ==================== 边缘应用 ====================

    def create_app(self, app_id, app_name, app_type, app_code,
                   version="1.0.0", description="", requirements=None):
        self._require_enabled()
        from extensions.features.app_deployment import AppType
        app = self._app_mgr.create_application(
            app_id=app_id, app_name=app_name,
            app_type=AppType(app_type), app_code=app_code,
            version=version, description=description,
            requirements=requirements
        )
        logger.info(f"边缘应用创建成功: {app_id} - {app_name}")
        return app

    def deploy_app(self, app_id, device_id):
        self._require_enabled()
        result = self._app_mgr.deploy_application(app_id, device_id)
        logger.info(f"应用 {app_id} 已部署到设备 {device_id}")
        return result

    def undeploy_app(self, app_id, device_id):
        self._require_enabled()
        result = self._app_mgr.undeploy_application(app_id, device_id)
        logger.info(f"应用 {app_id} 已从设备 {device_id} 卸载")
        return result

    def list_apps(self):
        self._require_enabled()
        return self._app_mgr.list_applications()

    # ==================== 设备角色 ====================

    def register_device(self, device_id, device_name, initial_mode=1, capabilities=None):
        self._require_enabled()
        from extensions.features.role_switch import DeviceMode, DeviceCapabilities
        caps = DeviceCapabilities(**(capabilities or {}))
        mode = DeviceMode(initial_mode)
        device = self._role_mgr.register_device(
            device_id=device_id, device_name=device_name,
            initial_mode=mode, capabilities=caps
        )
        logger.info(f"设备 {device_id} 已注册，初始模式: {mode.name}")
        return device

    def switch_role(self, device_id, target_mode, force=False):
        self._require_enabled()
        from extensions.role_switch import DeviceMode
        result = self._role_mgr.switch_mode(device_id, DeviceMode(target_mode), force)
        logger.info(f"设备 {device_id} 已切换到模式: {DeviceMode(target_mode).name}")
        return result

    def identify_mode(self, device_id, traffic_pattern=None, resource_usage=None):
        self._require_enabled()
        mode = self._role_mgr.identify_device_mode(
            device_id=device_id, traffic_pattern=traffic_pattern,
            resource_usage=resource_usage
        )
        logger.info(f"设备 {device_id} 模式识别结果: {mode.name}")
        return mode

    def get_available_modes(self, device_id):
        self._require_enabled()
        return self._role_mgr.get_available_modes(device_id)

    def list_devices(self):
        self._require_enabled()
        return self._role_mgr.list_devices()
