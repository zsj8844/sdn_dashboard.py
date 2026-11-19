# goprobe — eBPF 网关探针的 Go 版本

数据面程序是 `../gw_filter_probe.c`（同一份 C，Makefile 按 libbpf 方式编译）；
Go 只负责用户态：加载/挂载 XDP、消费 ringbuf、与网关 `ProbeBridge` 走
Unix datagram JSON、回写 eBPF 缓存 map。

filter 逻辑和结构体分别在 `../gw_filter_logic.h` 与
`../gw_filter_types.h`；本目录的 Go 程序是唯一加载器（BCC/Python 版已移除）。

## 构建

```bash
cd /home/zhang/桌面/sdn/SDN_IOT/gateway/xdp/goprobe
make
```

产物：

- `gw_filter_probe.o`：clang 编译的 XDP 对象
- `gw-xdp-go`：Go 探针

需要 `clang`、`llvm`、`libbpf-dev`、Go。若缺：

```bash
sudo apt install clang llvm libbpf-dev golang-go
```

## 运行

在 Mininet CLI 的 iot3 命名空间内、以 root 运行（Mininet 不会创建名为
`iot3` 的 `ip netns`，所以用 `mininet> iot3 ...`）：

```bash
mininet> iot3 /home/zhang/桌面/sdn/SDN_IOT/gateway/xdp/goprobe/gw-xdp-go \
  --ifaces iot3-eth0,iot3-eth1,iot3-eth2 \
  --probe-sock /tmp/sdn_xdp_probe.sock
```

只过滤、不连网关：

```bash
mininet> iot3 /home/zhang/桌面/sdn/SDN_IOT/gateway/xdp/goprobe/gw-xdp-go --ifaces iot3-eth0 --no-probe
```

打开丢弃非 5005：

```bash
mininet> iot3 /home/zhang/桌面/sdn/SDN_IOT/gateway/xdp/goprobe/gw-xdp-go --ifaces iot3-eth0 --set-cfg drop-non5005
```

摘除：

```bash
mininet> iot3 /home/zhang/桌面/sdn/SDN_IOT/gateway/xdp/goprobe/gw-xdp-go --ifaces iot3-eth0 --detach-only
```

## 自测

两个脚本都会自建临时 netns + veth，退出时清理，不需要 Mininet：

```bash
cd /home/zhang/桌面/sdn/SDN_IOT/gateway/xdp/goprobe
make

# 阶段 1：挂载、filter 计数、1000 包全部接收
sudo ./selftest_go.sh

# 阶段 2：ringbuf → resolve → pending → flow_ready → 回写 READY
sudo ./selftest_go_probe.sh
```

## 常用参数

- `--ifaces` 用**逗号分隔**（Go `flag` 不吞后续位置参数）。
- `--keep` 使用 bpffs pin（`/sys/fs/bpf/sdn_xdp_<iface>`）保留挂载；`--detach-only` 会先删 pin 再摘除。
- `--json-out` 输出 `totals`、`hit_rate`、`probe`、`xdp_state`，作为验收证据。

## 运行前提

- 本机只有 Wi-Fi 物理网卡（`rtw89`），不支持 native XDP；Mininet 里用 veth，
  只能用 generic/skb 模式，性能数字不代表物理网卡。
- 切换前先摘除旧挂载：

```bash
mininet> iot3 /home/zhang/桌面/sdn/SDN_IOT/gateway/xdp/goprobe/gw-xdp-go --ifaces iot3-eth0 --detach-only
```

## 验收

`flow_cached + flow_miss` 等于 5005 包数；命中后不再产生 ringbuf 事件；
TTL 过期后重新触发；`--json-out` 输出 `totals`、`hit_rate`、`probe`、`xdp_state`。
