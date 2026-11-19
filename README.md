# SDN IoT 实验项目

基于 Ryu 控制器、OpenFlow 1.3、Mininet 与 Open vSwitch 的 BLE-IoT SDN 实验原型。
IoT 数据从 iot3 网关进入 SDN 域，控制器完成主机发现、路由决策与流表下发，并通过 OpenFlow Experimenter 字段携带传感器类型、优先级等业务元数据；同时提供 Flask API 与 Vue 3 可视化面板。

## 当前状态

| 能力 | 状态 |
|------|------|
| OpenFlow 1.3 流表下发 / 统计采集 | ✅ 可用 |
| LLDP 拓扑发现、主机发现、拓扑可视化 | ✅ 可用 |
| 设备身份配置（IP → 设备信息）热加载 | ✅ 可用 |
| 网关属性上报（UDP 6650 / Unix socket） | ✅ 控制器接收器已接入；本地 UDP/Unix 已验证，Mininet 待联调 |
| 流表增删改查 | ✅ 增/删/改可用；本地缓存已同步 |
| 流表去重与重连失效 | ✅ 相同 FlowMod 重复下发会被跳过；交换机重连清空本地缓存 |
| route_b 备用链路 | ⚠️ 拓扑中没有第二条物理链路，route_b 降级为 route_a 并打日志标注（不再假装切换） |
| 业务优先级影响转发（meter） | ✅ 优先级 ≤3 的扩展流走 64 kbps meter（`SDN_LOW_PRIO_METER_KBPS` 可调，`SDN_QOS_METER=0` 关闭）；本地单测通过，真实 OVS 待 Mininet 联调 |
| Experimenter 字段编解码与流表注入 | ⚠️ 编码/注入/补丁 OVS 验证通过；标准 OVS 拒收自定义 vendor，需应用 `Ovs_extend` 补丁 |
| 真实 BLE Mesh 接入 | ❌ 网关没有 BLE 协议栈；宿主机 bleak 扫描器已提供（需硬件） |
| 边缘应用下发 / 设备角色切换 | ❌ 面板内存模型，无设备侧执行 |
| 网关侧 OpenFlow 协议客户端 | ✅ 已接入网关：dpid=3 完成 HELLO/FEATURES 握手，PacketIn 上报、FlowMod 写入本地流表；已对真实控制器本地验证，Mininet 待联调 |
| 网关入向 XDP filter + 流探针（eBPF，Go 版） | ✅ 隔离 veth 已验证：阶段 1（filter 计数 + 1000 包全收）、阶段 2（ringbuf → resolve → pending → flow_ready → READY）；真实拓扑联调待做 |
| 优先级标记 + 出口 HTB（阶段 6） | ✅ 隔离 veth 已验证：拥塞时 EF 队列平均延迟 176 ms vs 普通 632 ms；空闲和移除 qdisc 后无差异 |
| 阶段 7 测量 | ⚠️ 原 BCC 自测已随 BCC 加载器移除，未在 Go 版复测 |
| Go 版探针（cilium/ebpf） | ✅ 唯一加载器：`selftest_go.sh` / `selftest_go_probe.sh` 在隔离 veth 通过 |

未完成项、根因与实施路线见 [问题.md](问题.md)。

## 目录结构

```
SDN_IOT/
├── gateway/                     # IoT 网关（UDP 收数、BLE 编码、IP 转发）
│   ├── iot_gateway_enhanced.py  # 入口：收数/解析/转发/上报
│   ├── core/                    # 网关核心模块
│   │   ├── ofproto_client.py    # switch 端 OpenFlow 1.3 客户端（已接入）
│   │   ├── of_gateway_agent.py  # 网关 OF 代理：握手/重连、PacketIn、本地流表
│   │   ├── probe_bridge.py      # XDP 探针 ↔ 网关流表/控制器回路（Unix socket）
│   │   └── qos.py               # 逐包优先级：SO_PRIORITY + DSCP
│   ├── tools/                   # 辅助工具
│   │   ├── ble_injector.py      # 无硬件 BLE 数据注入（模拟 N 个设备）
│   │   ├── ble_scanner.py       # 宿主机 BLE 扫描（bleak，可选）
│   │   └── iot_gateway_simulator.py # 旧版模拟器，未被引用
│   ├── xdp/                     # eBPF 入向过滤 + 流探针（实现）
│   │   ├── gw_filter_types.h    # 结构体/常量（内核与用户态共享契约）
│   │   ├── gw_filter_logic.h    # filter 逻辑
│   │   ├── gw_filter_probe.c    # XDP 程序（libbpf / SEC(".maps")）
│   │   ├── qos_egress.sh        # 出口 HTB + DSCP 分类（tc）
│   │   └── goprobe/             # Go 加载器 + 自测（cilium/ebpf）
│   └── tests/                   # 所有网关测试
│       ├── selftest_qos.py      # 阶段 6：拥塞下延迟对比（需 root）
│       ├── test_stage4_loop.py  # 阶段 4 网关侧 OF 回路（无需 root）
│       ├── test_gateway_of_agent.py
│       └── test_ofproto_crosscheck.py
├── ryu_extend/
│   ├── switch/
│   │   ├── ble_switch_13.py     # 主控制器（装配层）
│   │   ├── Other_Modules/       # 转发、拓扑、流表、统计、HTTP 控制
│   │   ├── extensions/          # Experimenter 字段与业务模型
│   │   ├── config/              # 设备身份配置（实际使用）
│   │   └── test/                # 分阶段测试脚本
│   ├── topology/iot_sdn_topology.py
│   ├── templates/               # Flask 面板 + Vue 3 前端
│   ├── docx/                    # 项目文档
│   ├── manage.py                # 启动 / 停止 / 状态管理
│   └── run_tests.py
├── requirements.txt
└── create_venv.sh
```

## 文档索引

| 文档 | 说明 |
|------|------|
| [项目概述](ryu_extend/docx/项目文档/项目概述.md) | 项目定位、拓扑、端口、技术栈、目录结构 |
| [功能说明](ryu_extend/docx/项目文档/功能说明.md) | 各功能模块的实现位置与当前限制 |
| [安装与启动](ryu_extend/docx/项目文档/安装与启动.md) | 环境安装、启动顺序、故障排查 |
| [更新日志](ryu_extend/docx/项目文档/更新日志.md) | 版本演进 |
| [测试文档](ryu_extend/docx/测试文档/测试文档.md) | 基础网络与数据传输测试 |
| [测试文档_增强版](ryu_extend/docx/测试文档/测试文档_增强版.md) | 功能与集成测试用例 |
| [边缘应用管理测试文档](ryu_extend/docx/测试文档/边缘应用管理测试文档.md) | 面板接口测试（内存模型） |
| [设备角色切换测试文档](ryu_extend/docx/测试文档/设备角色切换测试文档.md) | 面板接口测试（内存模型） |
| [OpenFlow 协议扩展说明](ryu_extend/switch/OpenFlow协议扩展说明.md) | Experimenter 字段格式与编解码 |
| [问题日志](问题.md) | 已知问题、根因与后续路线 |

## 快速开始

```bash
cd SDN_IOT
source .venv/bin/activate

# 启动控制器、Flask 面板、网关、Vue 前端
python3 ryu_extend/manage.py start

# 拓扑需要单独启动（manage.py start 不包含拓扑）
cd ryu_extend
sudo python3 topology/iot_sdn_topology.py

# 另开终端，回到项目根目录
cd ..

# 无硬件验证：模拟 3 个 BLE 设备，数据发往 iot3 网关的 5005
python3 gateway/tools/ble_injector.py --target 192.168.1.12 --port 5005

# 有 BLE 硬件时：宿主机扫描真实广播（需 pip install bleak）
python3 gateway/tools/ble_scanner.py --target 192.168.1.12 --port 5005 --verbose

# 本机链路测试（不需要 root、Mininet 或 BLE 硬件）
python3 ryu_extend/switch/test/v4_全链路/test_extension_chain.py
python3 ryu_extend/switch/test/v4_全链路/test_ble_chain_e2e.py
python3 gateway/tests/test_ofproto_crosscheck.py
python3 gateway/tests/test_gateway_of_agent.py
```

访问：

- 普通面板（Jinja2 + API）：http://localhost:5000
- Vue 开发服务器：http://localhost:5173
- 控制器日志：`ryu_extend/logs/controller.log`

## eBPF / XDP 网关过滤、流探针与优先级（阶段 1–7）

在 iot3 面向数据源的 veth（`iot3-eth0/1/2`）上挂 XDP：对入向包分类计数，
`cfg[0] bit0=1` 时才丢弃非 5005 的 UDP。UDP 5005 命中 eBPF 缓存时直接
PASS；未命中时经 ringbuf 上报（写 1 秒 PENDING 冷却，同流只报一次），探针经
`probe_bridge.py` 查网关本地缓存或上报控制器，拿到结果后写回 eBPF 缓存 READY
（TTL 老化，全局上限 50 次/s）。eBPF 只做过滤和事件，不做转发、不解析 BLE
文本、不算业务优先级；优先级由 Python 算好后用 `SO_PRIORITY` + DSCP 逐包标记，
出口 `qos_egress.sh` 用 HTB 按 DSCP 调度。

数据面 C 在 `gateway/xdp/gw_filter_probe.c`，由 `gateway/xdp/goprobe/Makefile`
用 clang 编译成 `gw_filter_probe.o`；用户态是 Go + `cilium/ebpf` 的单二进制
`gw-xdp-go`。必须 **root**，并在 Mininet CLI 的 iot3 命名空间内运行：

```bash
# 在 SDN_IOT 根目录先构建
make -C gateway/xdp/goprobe

# Mininet CLI 里（拓扑是 root 启动的）
# 完整探针：连网关 ProbeBridge（默认 /tmp/sdn_xdp_probe.sock）
mininet> iot3 /home/zhang/桌面/sdn/SDN_IOT/gateway/xdp/goprobe/gw-xdp-go --ifaces iot3-eth0,iot3-eth1,iot3-eth2

# 只过滤：ringbuf 事件仅打日志
mininet> iot3 /home/zhang/桌面/sdn/SDN_IOT/gateway/xdp/goprobe/gw-xdp-go --ifaces iot3-eth0 --no-probe

# 打开丢弃非 5005
mininet> iot3 /home/zhang/桌面/sdn/SDN_IOT/gateway/xdp/goprobe/gw-xdp-go --ifaces iot3-eth0 --set-cfg drop-non5005

# 出口优先级（拥塞时才有效果）：iot3 面向 s1 的接口
mininet> iot3 /home/zhang/桌面/sdn/SDN_IOT/gateway/xdp/qos_egress.sh setup iot3-eth3 1000

# 退场
mininet> iot3 /home/zhang/桌面/sdn/SDN_IOT/gateway/xdp/goprobe/gw-xdp-go --ifaces iot3-eth0 --detach-only
```

不依赖 Mininet 的自测（在 SDN_IOT 根目录执行，需要 root）：

```bash
sudo ./gateway/xdp/goprobe/selftest_go.sh          # 阶段 1：filter 计数 + 1000 包全部接收
sudo ./gateway/xdp/goprobe/selftest_go_probe.sh    # 阶段 2：ringbuf → resolve → pending → flow_ready → READY

# 阶段 6 出口 HTB；阶段 4 控制器回路（免 root）
sudo /usr/bin/python3 gateway/tests/selftest_qos.py
.venv/bin/python gateway/tests/test_stage4_loop.py
```

注意：XDP 挂在 iot3-eth0/1/2，只有从 iot1/2/4 发往网关的包会经过它；从宿主机
直接发给 192.168.1.12 的包走 iot3-eth3，不经过这个过滤点（要测就 `mininet> iot1
python3 /home/zhang/桌面/sdn/SDN_IOT/gateway/tools/ble_injector.py --target 192.168.2.1`）。

状态（2026-11-19，Go 版；隔离 veth + XDP generic（skb）模式，宿主机网络与
Mininet 未被改动；本机物理网卡是 Wi-Fi（rtw89），不支持 native XDP，数字不代表
物理网卡性能）：

- **阶段 1**（`selftest_go.sh`）：1000 个 5005 包 `flow_miss=1 + flow_cached=999`
  且接收端收到 1000；`non_5005 >= 50`、`parse_error=0`；退出后 XDP 已摘除。
- **阶段 2**（`selftest_go_probe.sh`）：1 个 ringbuf 事件 → 1 次 resolve →
  1 次 pending → 1 次 flow_ready → 1 次 eBPF READY 写回；
  `flow_cached=999 + flow_miss=1`，接收 1000。
- **阶段 4**（`test_stage4_loop.py`）：pending → 控制器 PacketIn → FlowMod →
  网关本地缓存 → `flow_ready`；FlowMod DELETE 同步。
- **阶段 6**（`selftest_qos.py`）：HTB 1 Mbit 下 EF 平均 176 ms / 普通 632 ms；
  空闲链路两者均 0.5 ms，移除 qdisc 后恢复 1.3 ms（无假优势）。

阶段 3/5/7 的原 BCC 自测随 BCC 加载器一并移除，未在 Go 版复测。

注意：`ip link set dev X xdp off` 等价于 flags=0，可能摘不掉用 `--mode skb`
显式挂载的程序；`gw-xdp-go --detach-only` 会按挂载时的 link 正确摘除，
并校验接口上确实没有 XDP 才报“已摘除”。

## 端口

| 端口 | 用途 |
|------|------|
| 6634 | Ryu 控制器（OpenFlow 1.3） |
| 5000 | Flask API / 面板 |
| 5173 | Vue 开发服务器 |
| 5005 | IoT 数据 UDP 端口 |
| 6650 | 网关属性上报 UDP（控制器内置接收器） |
| 16634 | 控制器内部控制 HTTP（仅 127.0.0.1） |

## 版本

当前文档对应代码版本 v4.5.2，最后更新 2026-11-19。
