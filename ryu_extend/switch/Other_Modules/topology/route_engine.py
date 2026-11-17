"""路由决策引擎 — 根据目的地址 + BLE 扩展路由计算出口端口。

拓扑端口映射（Mininet 按 addLink 顺序分配）：
    s1: port1→iot3, port2→s2
    s2: port1→s1,   port2→h1, port3→h2
    gateway(dpid=3，网关自身作为 OF 设备): port1→上行 s1, port2→下行 IoT 子网
"""

import os

# 网关以 OpenFlow 设备身份接入控制器时使用的 DPID
GATEWAY_DPID = int(os.environ.get('SDN_GATEWAY_DPID', '3'))

# 当前拓扑 s1—s2 之间只有一条链路，不存在独立的备用路径。
# route_b 只作为业务元数据保留，数据面必须回落到 route_a。
BACKUP_PATH_AVAILABLE = False

_IOT_DEVICE_IPS = (
    '192.168.2.1', '192.168.2.10',    # iot3-gw + iot1
    '192.168.3.1', '192.168.3.11',    # iot3-gw + iot2
    '192.168.4.1', '192.168.4.13',    # iot3-gw + iot4
)

_SDN_HOST_IPS = ('192.168.1.20', '192.168.1.21')


def effective_route(extension_route):
    """数据面实际使用的路由。

    route_b 在单链路拓扑下没有可用备用路径，回落 route_a；
    返回值同时用于日志，调用方可据此说明"无备用链路"。
    """
    if extension_route == 'route_b' and not BACKUP_PATH_AVAILABLE:
        return 'route_a'
    return extension_route


def resolve_out_port(dpid, dst_mac, ip_dst, mac_table, extension_route='route_a'):
    """
    纯函数：根据交换机 DPID、目的 MAC/IP 和路由策略，决定出口端口。

    Args:
        dpid: 交换机 DPID (1 / 2，或网关自身 3)
        dst_mac: 目的 MAC 地址
        ip_dst: 目的 IP 地址（可空）
        mac_table: {dpid: {mac: port}} 映射
        extension_route: 'route_a'（主路径）或 'route_b'（备用路径标记）

    Returns:
        (out_port, log_msg) — out_port 为 None 表示需要泛洪
    """
    requested = extension_route
    extension_route = effective_route(extension_route)
    if requested != extension_route:
        route_tag = '[route_b→route_a 无备用链路]'
    elif extension_route != 'route_a':
        route_tag = f'[{extension_route}]'
    else:
        route_tag = ''

    prefix = 'gw' if dpid == GATEWAY_DPID else f's{dpid}'

    # 1. MAC 表命中
    if dpid in mac_table and dst_mac in mac_table[dpid]:
        port = mac_table[dpid][dst_mac]
        return port, f"{prefix} MAC命中 {dst_mac} → port{port} {route_tag}"

    # 网关自身作为 OF 设备：port1 上行到 s1，port2 下行到 IoT 子网
    if dpid == GATEWAY_DPID:
        if ip_dst in _SDN_HOST_IPS or ip_dst in (
                '192.168.1.10', '192.168.1.11', '192.168.1.12', '192.168.1.13'):
            return 1, f"gw{route_tag} 上行口 port1 → {ip_dst}"
        if ip_dst in _IOT_DEVICE_IPS:
            return 2, f"gw{route_tag} 下行口 port2 → {ip_dst}"
        return 1, f"gw{route_tag} 默认上行口 port1 → {ip_dst}"

    # 2. IP 路由
    if ip_dst:
        if dpid == 1:
            if ip_dst in ('192.168.1.20', '192.168.1.21'):
                return 2, f"s1{route_tag} 转发到s2 (port2) → {ip_dst}"
            if ip_dst in ('192.168.1.10', '192.168.1.11', '192.168.1.12', '192.168.1.13'):
                return 1, f"s1{route_tag} 转发到iot3 (port1) → {ip_dst}"
            # IoT 子网回程：192.168.2.x/3.x/4.x → iot3 (port1)
            if ip_dst in _IOT_DEVICE_IPS:
                return 1, f"s1{route_tag} IoT回程 → iot3 (port1) → {ip_dst}"

        elif dpid == 2:
            # s2 port2→h1、port3→h2；单链路拓扑下 route_b 与 route_a 同口
            if ip_dst == '192.168.1.20':
                return 2, f"s2{route_tag} → h1 port2"
            if ip_dst == '192.168.1.21':
                return 3, f"s2{route_tag} → h2 port3"
            if ip_dst in ('192.168.1.10', '192.168.1.11', '192.168.1.12', '192.168.1.13'):
                return 1, f"s2{route_tag} 转发到s1 (port1)"
            # IoT 子网回程 → s1
            if ip_dst in _IOT_DEVICE_IPS:
                return 1, f"s2{route_tag} IoT回程 → s1 (port1) → {ip_dst}"

    return None, f"s{dpid}{route_tag} 未找到路由 → 泛洪"
