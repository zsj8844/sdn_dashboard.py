"""逐包优先级标记：SO_PRIORITY + DSCP（路线 A）。

优先级 1–5 由 extensions/priority.py 在 Python 里算好；这里只负责把
标记贴到每个发出的包上。出口 qdisc（见 gateway/xdp/qos_egress.sh）
按 DSCP 分类，拥塞时高优先级先出队。
"""

import socket

DSCP_BY_PRIORITY = {5: 46, 4: 34, 3: 26, 2: 18, 1: 10}


def normalize_priority(priority) -> int:
    try:
        value = int(priority)
    except (TypeError, ValueError):
        return 2
    return min(5, max(1, value))


def priority_to_dscp(priority) -> int:
    return DSCP_BY_PRIORITY[normalize_priority(priority)]


def priority_to_tos(priority) -> int:
    """IPv4 TOS 字节：DSCP 占高 6 位。"""
    return priority_to_dscp(priority) << 2


def mark_socket(sock, priority) -> int:
    """给 socket 贴 SO_PRIORITY 和 DSCP；失败不影响发送。"""
    value = normalize_priority(priority)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_PRIORITY, value)
    except OSError:
        pass
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_TOS,
                        priority_to_tos(value))
    except OSError:
        pass
    return value


__all__ = ["normalize_priority", "priority_to_dscp", "priority_to_tos",
           "mark_socket", "DSCP_BY_PRIORITY"]
