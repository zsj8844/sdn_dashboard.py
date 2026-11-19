# goprobe — eBPF 网关探针的 Go 版本

数据面程序仍然是 C（`bpf/gw_filter_probe.c`，libbpf 薄封装）；Go 只负责用户态：
加载/挂载 XDP、消费 ringbuf、与网关 `ProbeBridge` 走 Unix datagram JSON、
回写 eBPF 缓存 map。

filter 逻辑和结构体分别共享自 `../../gw_filter_logic.h` 与
`../../gw_filter_types.h`，与 BCC 版只差 map 定义和入口。

这是 `gateway/xdp/gw_xdp_filter.py`（BCC + Python）的替代实现，协议完全兼容。

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

在 iot3 命名空间内、以 root 运行：

```bash
sudo ip netns exec iot3 ./gw-xdp-go \
  --ifaces iot3-eth0,iot3-eth1,iot3-eth2 \
  --probe-sock /tmp/sdn_xdp_probe.sock
```

只过滤、不连网关：

```bash
sudo ip netns exec iot3 ./gw-xdp-go --ifaces iot3-eth0 --no-probe
```

打开丢弃非 5005：

```bash
sudo ip netns exec iot3 ./gw-xdp-go --ifaces iot3-eth0 --set-cfg drop-non5005
```

摘除：

```bash
sudo ip netns exec iot3 ./gw-xdp-go --ifaces iot3-eth0 --detach-only
```

## 与 Python 版的差异

- `--ifaces` 用**逗号分隔**（Python 版是空格分隔）。原因是 Go `flag` 不吞后续位置参数。
- `--keep` 使用 bpffs pin（`/sys/fs/bpf/sdn_xdp_<iface>`）保留挂载；`--detach-only` 会先删 pin 再摘除。
- 其余参数（`--mode`、`--interval`、`--duration`、`--probe-rate`、`--ttl`、`--json-out`、`--ready-file`）与 Python 版含义一致。

## 运行前提

- 本机只有 Wi-Fi 物理网卡（`rtw89`），不支持 native XDP；Mininet 里用 veth，
  只能用 generic/skb 模式，性能数字不代表物理网卡。
- Go 版和 Python 版不要同时挂同一个接口；先摘除再切换：

```bash
sudo ip netns exec iot3 ./gw-xdp-go --ifaces iot3-eth0 --detach-only
```

## 验收

与 Python 版一致：`flow_cached + flow_miss` 等于 5005 包数；命中后不再产生
ringbuf 事件；TTL 过期后重新触发；`--json-out` 输出 `totals`、`hit_rate`、
`probe`、`xdp_state`。
