# SDN Dashboard API（Gin / Go）

替代原 Flask 后端（已移除）。HTTP API 路径和 JSON 形状保持不变，
Vue 前端和 Vite 代理（`/api → localhost:5000`）无需修改。

## 目录结构

```
.
├── cmd/dashboard/main.go        # 入口：flag
├── internal/dashboard/          # 业务代码（一个包）
│   ├── server.go                # 启动、路由、静态托管、CORS
│   ├── handlers.go              # API handlers
│   ├── state.go                 # 日志、拓扑、统计、BLE、OVS
│   ├── apps.go / devices.go     # 应用与设备模型
│   └── identity.go              # device_identity.json
├── scripts/
│   ├── smoke_test.sh            # 无 root 冒烟测试
│   └── test_ovs_api.sh          # root 真实 OVS 测试
├── bin/dashboard-go             # 编译产物（gitignore）
├── Makefile
└── go.mod / go.sum
```

## 构建

```bash
cd /home/zhang/桌面/sdn/SDN_IOT/ryu_extend/templates/sdn_dashboard_vue/sdn_dashboard_server_go
make          # 输出 bin/dashboard-go
```

## 运行

```bash
# 生产模式：托管 ../sdn_dashboard_view/dist
./bin/dashboard-go --port 5000

# 开发模式：只提供 API，前端用 Vite (5173)
./bin/dashboard-go --port 5000 --no-ble --no-connectivity
```

常用参数：

| 参数 | 说明 |
|---|---|
| `--port` | 监听端口，默认 5000 |
| `--host` | 监听地址，默认 0.0.0.0 |
| `--base` | 本程序所在目录；默认按可执行文件推断 |
| `--dist` | 覆盖 Vue dist 路径 |
| `--no-ble` | 不监听 UDP 5005（避免与网关抢包） |
| `--no-connectivity` | 不轮询 OVS（测试时用） |
| `--debug` | Gin debug 模式 |

## API 兼容范围

- `/api/data`、`/api/logs`、`/api/logs/s1`、`/api/logs/s2`
- `/api/iot-extension`、`/api/clear-data`
- `/api/topology`、`/api/stats`、`/api/flows`
- `/api/apps`、`/api/apps/:id`、deploy / undeploy / history
- `/api/devices`、`/api/devices/:id`、switch-mode / identify / history
- `/api/device-identity/config`、`/device`、`/device/:ip`、`/reload`
- `/health`、`/`、SPA fallback

## 依赖与副作用

- `/api/flows` 与连通性轮询会执行 `sudo ovs-ofctl` / `sudo ovs-vsctl`。
- BLE 监听会尝试绑定 UDP 5005；网关也在用时只应有一方绑定成功。
- 设备身份配置读写 `ryu_extend/switch/config/device_identity.json`。
- 应用和设备角色数据仍只存在内存中，重启清空。

## 自测

```bash
./scripts/smoke_test.sh      # 无需 root，不碰 UDP 5005 / OVS
sudo ./scripts/test_ovs_api.sh   # 需要 root，临时创建/删除 s1
```

`smoke_test.sh` 在 15001 端口启动临时实例；`test_ovs_api.sh` 验证真实 OVS 连通性与流表增删。
