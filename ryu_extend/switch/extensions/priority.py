"""统一的 IoT 优先级与路由选择。

网关和控制器共用这一份逻辑，避免两边各写一套阈值。
"""

_ALIASES = {
    'temperature': 'temp',
    'humid': 'humidity',
    'position': 'pos',
    'location': 'pos',
    'gps': 'pos',
    'smoke': 'gas',
    'co2': 'gas',
}

_CRITICAL_TYPES = {'gas', 'motion'}


def normalize_sensor_type(sensor_type):
    """把常见别名归一成扩展字段使用的类型名。"""
    if not sensor_type:
        return 'temp'
    key = str(sensor_type).strip().lower()
    return _ALIASES.get(key, key)


def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def calculate_priority(sensor_type, value):
    """根据传感器类型和数值计算 1-5 级优先级。

    - 气体/移动类：固定 5 级
    - 温度：按过冷/过热阈值
    - 湿度：按潮湿阈值
    - 位置：默认 2 级（值不是单个数字）
    - 其他：通用数值阈值
    """
    stype = normalize_sensor_type(sensor_type)

    if stype in _CRITICAL_TYPES:
        return 5

    number = _to_float(value)
    if number is None:
        return 2

    if stype == 'temp':
        if number > 35 or number < 10:
            return 5
        if number > 30 or number < 15:
            return 4
        if number > 25 or number < 18:
            return 3
        return 2

    if stype == 'humidity':
        if number > 80:
            return 5
        if number > 70:
            return 4
        if number > 50:
            return 3
        return 2

    if stype == 'pos':
        return 2

    if number > 80:
        return 5
    if number > 50:
        return 4
    if number > 30:
        return 3
    return 2


def select_route(priority):
    """优先级 >=4 走备用路径 route_b，其余走 route_a。"""
    return 'route_b' if priority >= 4 else 'route_a'


__all__ = [
    'normalize_sensor_type',
    'calculate_priority',
    'select_route',
]
