# gateway

IoT 网关（Mininet 里的 iot3）的用户态实现。

## 目录

| 路径 | 作用 |
|---|---|
| `iot_gateway_enhanced.py` | 入口：监听 UDP 5005、解析 BLE、上报控制器、转发数据 |
| `core/ofproto_client.py` | OpenFlow 1.3 switch 端协议客户端 |
| `core/of_gateway_agent.py` | OF 代理：握手/重连、PacketIn、本地流表 |
| `core/probe_bridge.py` | XDP 探针 ↔ 本地流表 / 控制器（Unix socket） |
| `core/qos.py` | 逐包优先级标记（SO_PRIORITY + DSCP） |
| `tools/ble_injector.py` | 无硬件 BLE 数据注入 |
| `tools/ble_scanner.py` | 宿主机 bleak 扫描 |
| `tools/iot_gateway_simulator.py` | 旧版模拟器（未被引用） |
| `xdp/` | XDP 过滤 / probe / qdisc 实现 |
| `tests/` | 所有网关测试，见 [tests/README.md](tests/README.md) |

## 启动

```bash
cd /home/zhang/桌面/sdn/SDN_IOT
.venv/bin/python gateway/iot_gateway_enhanced.py
```

入口启动时会把 `gateway/core/` 加入 `sys.path`，模块无需安装成包；测试脚本也各自设置了该路径。
