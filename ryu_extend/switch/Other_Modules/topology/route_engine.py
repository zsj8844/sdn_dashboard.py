"""路由决策引擎 — 根据目的地址 + BLE 扩展路由计算出口端口"""


def resolve_out_port(dpid, dst_mac, ip_dst, mac_table, extension_route='route_a'):
    """
    纯函数：根据交换机 DPID、目的 MAC/IP 和路由策略，决定出口端口。

    Args:
        dpid: 交换机 DPID (1 或 2)
        dst_mac: 目的 MAC 地址
        ip_dst: 目的 IP 地址（可空）
        mac_table: {dpid: {mac: port}} 映射
        extension_route: 'route_a'（主路径）或 'route_b'（备用路径）

    Returns:
        (out_port, log_msg) — out_port 为 None 表示需要泛洪
    """
    route_tag = f"[{extension_route}]" if extension_route != 'route_a' else ''

    # 1. MAC 表命中
    if dpid in mac_table and dst_mac in mac_table[dpid]:
        port = mac_table[dpid][dst_mac]
        return port, f"s{dpid} MAC命中 {dst_mac} → port{port} {route_tag}"

    # 2. IP 路由
    if ip_dst:
        # IoT 子网设备 IP（回程路由，NAT 失效时作为兜底）
        iot_device_ips = (
            '192.168.2.1', '192.168.2.10',    # iot3-gw + iot1
            '192.168.3.1', '192.168.3.11',    # iot3-gw + iot2
            '192.168.4.1', '192.168.4.13',    # iot3-gw + iot4
        )

        if dpid == 1:
            if ip_dst in ('192.168.1.20', '192.168.1.21'):
                return 2, f"s1{route_tag} 转发到s2 (port2) → {ip_dst}"
            if ip_dst in ('192.168.1.10', '192.168.1.11', '192.168.1.12', '192.168.1.13'):
                return 1, f"s1{route_tag} 转发到iot3 (port1) → {ip_dst}"
            # IoT 子网回程：192.168.2.x/3.x/4.x → iot3 (port1)
            if ip_dst in iot_device_ips:
                return 1, f"s1{route_tag} IoT回程 → iot3 (port1) → {ip_dst}"

        elif dpid == 2:
            if extension_route == 'route_b':
                if ip_dst == '192.168.1.20':
                    return 3, f"s2[route_b] 备用路径 → h1 port3"
                if ip_dst == '192.168.1.21':
                    return 2, f"s2[route_b] 备用路径 → h2 port2"
                # IoT 子网回程 → s1
                if ip_dst in iot_device_ips:
                    return 1, f"s2[route_b] IoT回程 → s1 (port1) → {ip_dst}"
                return 1, f"s2[route_b] 转发到s1 (port1)"
            else:
                if ip_dst == '192.168.1.20':
                    return 2, f"s2 → h1 port2"
                if ip_dst == '192.168.1.21':
                    return 3, f"s2 → h2 port3"
                if ip_dst in ('192.168.1.10', '192.168.1.11', '192.168.1.12', '192.168.1.13'):
                    return 1, f"s2 转发到s1 (port1)"
                # IoT 子网回程 → s1
                if ip_dst in iot_device_ips:
                    return 1, f"s2 IoT回程 → s1 (port1) → {ip_dst}"

    return None, f"s{dpid} 未找到路由 → 泛洪"
