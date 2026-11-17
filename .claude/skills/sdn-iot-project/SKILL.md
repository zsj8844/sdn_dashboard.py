---
name: sdn-iot-project
description: 在 SDN_IoT 项目（Ryu + OpenFlow 1.3 + Mininet + BLE 网关）上工作。用于梳理项目、修改网关/控制器链路、验证功能、运行扩展链路测试，或同步 README/问题.md/文档。
---

# SDN_IoT 项目工作手册

## 项目定位

基于 Ryu、OpenFlow 1.3、Mininet、OVS 的 **BLE-IoT SDN 实验原型**，不是成品系统。

- 可用：OF1.3 流表、LLDP/ARP 拓扑发现、设备身份配置、Flask/Vue 面板。
- 未闭环：真实 BLE 协议栈、数据面差异化转发、应用下发到设备、网关 OpenFlow 客户端、内核 datapath。

## 铁律

1. **先核对代码再下结论**。文档可能过期，以代码为准。
2. **不要把“接口存在”说成“功能可用”**；区分“已实现 / 已接线 / 已验证”。
3. 改代码后同步 `README.md`、`问题.md` 和相关 docx 中的旧描述。
4. 需要 sudo、Mininet、硬件才能验证的内容，只能写“本地已验证，Mininet/硬件待联调”，不要声称已通过。
5. 网关跑在 Mininet `iot3` 命名空间里，`127.0.0.1` 不是宿主机；跨命名空间优先用 Unix socket。
6. `manage.py start_gateway()` **不能**再杀 6650——6650 现在是控制器内置接收器的端口。
7. Mininet 节点共享宿主机蓝牙，**不能**用 bleak 给每个节点模拟独立 BLE 设备。

## 关键链路

```
ble_injector / ble_scanner
        │  <ble_addr>,<type>,<value>  (UDP 5005)
        ▼
iot_gateway_enhanced.py
        │  编码 TLV
        │  优先 Unix socket /tmp/sdn_iot_ext.sock，退回 UDP 192.168.1.1:6650
        ▼
UDPExtensionReceiver（控制器进程内）
        │
        ▼
WebReporter → 面板 /api/iot-extension
```

相关环境变量：

- `SDN_CONTROLLER_IP`：网关上报地址，默认 `192.168.1.1`。
- `SDN_EXT_TRANSPORT`：`auto`（默认）/ `unix` / `udp`。
- `SDN_EXT_SOCKET`：Unix socket 路径，默认 `/tmp/sdn_iot_ext.sock`。

## 优先级与路由

统一逻辑在 `ryu_extend/switch/extensions/priority.py`，**网关和控制器共用**：

- `calculate_priority(sensor_type, value)` → 1–5
- `select_route(priority)` → `route_a` / `route_b`

改阈值只改这一处，不要在两边的各自函数里改。

## 测试

```bash
cd /home/zhang/桌面/sdn/SDN_IOT

# 组件测试（不需要 root / Mininet）
.venv/bin/python ryu_extend/switch/test/v4_全链路/test_extension_chain.py

# 端到端：注入器 → 网关 → Unix socket → 接收器
.venv/bin/python ryu_extend/switch/test/v4_全链路/test_ble_chain_e2e.py

# 注入器 dry-run
.venv/bin/python gateway/ble_injector.py --count 3 --once --dry-run

# BLE 扫描器（需要适配器已打开）
.venv/bin/python gateway/ble_scanner.py --timeout 1 --dry-run
```

本机全链路验证：

1. 启动控制器：`.venv/bin/python -m ryu.cmd.manager switch/ble_switch_13.py --ofp-tcp-listen-port 6634`（在 `ryu_extend/` 下）。
2. 启动网关：`.venv/bin/python gateway/iot_gateway_enhanced.py`（在 `SDN_IOT/` 下，注意 `main()` 会先 sleep 3 秒）。
3. 发送模拟数据：`.venv/bin/python gateway/ble_injector.py --target 127.0.0.1 --port 5005 --count 3 --once`。
4. 控制器日志出现 `收到IoT扩展信息` 即通过。

注意：项目没有真正的 pytest 测试；`scapy`、`pytest` 只是 requirements 里的未使用依赖，不要当作已使用的工具写进报告。

## 当前 P0 缺口（2026-11-17）

1. **真实 BLE 接入**：`ble_scanner.py` 已提供，但网关本身没有 BLE 协议栈；需要手机/ESP32/dongle 验证。
2. **属性上报**：代码已完成（UDP + Unix socket），本地已验证；Mininet 内跨命名空间待联调。
3. **差异化转发**：未实现。Experimenter 动作不参与匹配；主动流表 priority=100 遮蔽 20–50 的扩展流表；拓扑只有一条路径，`route_b` 只是交换 s2 出口端口，不是真正的备用路径。
4. **主动流表遮蔽 Packet-In**：装表后 IPv4 流量不再上送控制器。

## 修改检查清单

- [ ] 先看代码现状，再改
- [ ] 改完跑 `test_extension_chain.py`
- [ ] 对改动文件跑 `python -m py_compile`
- [ ] 行为变化同步 README / 问题.md / docx
- [ ] 未验证的部分明确标注
- [ ] 除非用户要求，否则不要 commit

## 常用文件

| 文件 | 作用 |
|------|------|
| `ryu_extend/switch/ble_switch_13.py` | 控制器装配层 |
| `ryu_extend/switch/Other_Modules/packet_processor.py` | Packet-In 全流程 |
| `ryu_extend/switch/Other_Modules/topology/route_engine.py` | 路由决策 |
| `ryu_extend/switch/Other_Modules/infra/flow_manager.py` | 流表增删改查（本地缓存与 add/delete/modify 同步） |
| `ryu_extend/switch/Other_Modules/infra/ext_receiver.py` | 6650 / Unix socket 接收器 |
| `ryu_extend/switch/extensions/priority.py` | 统一优先级与路由 |
| `gateway/iot_gateway_enhanced.py` | IoT 网关 |
| `gateway/ble_injector.py` | 无硬件 BLE 数据注入 |
| `gateway/ble_scanner.py` | 宿主机 bleak 扫描器 |
| `ryu_extend/topology/iot_sdn_topology.py` | Mininet 拓扑 |
| `ryu_extend/manage.py` | 启动/停止/状态 |

## 环境注意

- 项目 venv：`SDN_IOT/.venv`，Python 3.10.20。
- 这台机器的 Python **没有** `socket.AF_BLUETOOTH`，raw HCI 不可直接用；BLE 走 bleak → BlueZ D-Bus。
- BLE 适配器可能是 soft-blocked：`sudo rfkill unblock bluetooth`、`sudo bluetoothctl power on`。
- 网关文件 `iot_gateway_enhanced.py` 使用 CRLF 换行；`git diff --check` 会把它报成 trailing whitespace，属正常现象。
