# SDN IoT 实验项目

基于 Ryu 控制器、OpenFlow 1.3、Mininet 与 Open vSwitch 的 BLE-IoT SDN 实验原型。
IoT 数据从 iot3 网关进入 SDN 域，控制器完成主机发现、路由决策与流表下发，并通过 OpenFlow Experimenter 字段携带传感器类型、优先级等业务元数据；同时提供 Flask API 与 Vue 3 可视化面板。

## 当前状态

| 能力 | 状态 |
|------|------|
| OpenFlow 1.3 流表下发 / 统计采集 | ✅ 可用 |
| LLDP 拓扑发现、主机发现、拓扑可视化 | ✅ 可用 |
| 设备身份配置（IP → 设备信息）热加载 | ✅ 可用 |
| 流表增删改查 | ✅ 增/删/改可用；`FlowManager.get_flows()` 有缺陷 |
| Experimenter 字段编解码与流表注入 | ⚠️ 编码可用，数据面不生效（被主动流表遮蔽） |
| 真实 BLE Mesh 接入 | ❌ 网关没有 BLE 协议栈 |
| 边缘应用下发 / 设备角色切换 | ❌ 面板内存模型，无设备侧执行 |
| 网关侧 OpenFlow 协议客户端 | ❌ 已实现但未接入 |
| OVS 内核 datapath 下沉 | ❌ 仍为 netdev 用户态 |

未完成项、根因与实施路线见 [问题.md](问题.md)。

## 目录结构

```
SDN_IOT/
├── gateway/                     # IoT 网关（UDP 收数、BLE 编码、IP 转发）
│   ├── iot_gateway_enhanced.py
│   ├── iot_gateway_simulator.py # 旧版模拟器，未被引用
│   └── ofproto_client.py        # switch 端 OpenFlow 1.3 客户端（未接入）
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
```

访问：

- 普通面板（Jinja2 + API）：http://localhost:5000
- Vue 开发服务器：http://localhost:5173
- 控制器日志：`ryu_extend/logs/controller.log`

## 端口

| 端口 | 用途 |
|------|------|
| 6634 | Ryu 控制器（OpenFlow 1.3） |
| 5000 | Flask API / 面板 |
| 5173 | Vue 开发服务器 |
| 5005 | IoT 数据 UDP 端口 |
| 16634 | 控制器内部控制 HTTP（仅 127.0.0.1） |

## 版本

当前文档对应代码版本 v4.5.2，最后更新 2026-11-17。
