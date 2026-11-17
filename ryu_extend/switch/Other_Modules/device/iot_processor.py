"""
IoT 扩展字段处理模块

根据 BLE 传感器数据（类型 + 值）计算优先级和路由，
仅用于 Web 面板展示，不影响转发决策。
"""

import logging
import requests

logger = logging.getLogger(__name__)


class IoTProcessor:
    """BLE 数据 → IoT 扩展字段 + 优先级 + 路由"""

    def __init__(self, extension_enabled=False, web_panel_url="http://localhost:5000"):
        self.extension_enabled = extension_enabled
        self.web_panel_url = web_panel_url

    def process(self, ble_type, ble_value):
        """
        根据 BLE 传感器类型和数值，生成扩展字段。

        返回: dict {
            'data': <序列化字节>, 'priority': int 2-5,
            'sensor_type': str, 'route': 'route_a'|'route_b'
        }
        如果扩展功能未启用，返回默认值。
        """
        logger.info("========== 开始处理IoT扩展字段 ==========")
        logger.info(f"输入参数 - ble_type: {ble_type}, ble_value: {ble_value}")

        try:
            if not self.extension_enabled:
                logger.warning("扩展功能未启用，跳过处理")
                return {'data': None, 'priority': 2, 'sensor_type': 'temp', 'route': 'route_a'}

            # 类型归一 + 优先级 + 路由：与网关共用 extensions.priority
            from extensions.priority import (
                calculate_priority, normalize_sensor_type, select_route,
            )
            sensor_type = normalize_sensor_type(ble_type)
            priority = calculate_priority(sensor_type, ble_value)
            route = select_route(priority)
            logger.info("类型=%s, 优先级=%d, 路由=%s",
                        sensor_type, priority, route)

            # 创建扩展字段
            from extensions.manager import create_iot_extension
            ext_mgr = create_iot_extension(
                sensor_type=sensor_type,
                device_priority=priority,
                route_select=route
            )
            logger.info("IoT扩展字段创建成功")
            extension_data = ext_mgr.serialize_fields()
            logger.info(f"扩展字段序列化完成 ({len(extension_data)} bytes)")

            # 推送到 Web 面板
            field_dict = ext_mgr.get_field_dict()
            try:
                requests.post(
                    f"{self.web_panel_url}/api/iot-extension",
                    json=field_dict, timeout=1
                )
                logger.info("IoT扩展字段已成功发送到Web面板")
            except Exception as e:
                logger.warning(f"发送IoT扩展字段到Web面板失败: {e}")

            logger.info("========== IoT扩展字段处理完成 ==========")
            return {
                'data': extension_data,
                'priority': priority,
                'sensor_type': sensor_type,
                'route': route
            }

        except Exception as e:
            logger.error(f"处理IoT扩展字段时出错: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {'data': None, 'priority': 2, 'sensor_type': 'temp', 'route': 'route_a'}
