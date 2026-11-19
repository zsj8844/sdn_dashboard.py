# gateway 测试

所有网关相关测试集中在这里。命令均在 `SDN_IOT/` 目录下执行。

## 不需要 root / Mininet

```bash
.venv/bin/python gateway/tests/test_ofproto_crosscheck.py   # OF1.3 报文格式交叉验证
.venv/bin/python gateway/tests/test_gateway_of_agent.py     # 假控制器 ↔ 网关 OF 代理
.venv/bin/python gateway/tests/test_stage4_loop.py          # PacketIn → FlowMod → 网关本地缓存 → flow_ready
```

## 需要 root

```bash
sudo ./gateway/tests/selftest.sh                                   # 阶段 1：filter 计数/丢弃
sudo /usr/bin/python3 gateway/tests/selftest_probe.py --stage 2    # 阶段 2/3/4/5/7：probe
sudo /usr/bin/python3 gateway/tests/selftest_qos.py                # 阶段 6：DSCP + HTB
```

- `selftest_probe.py` / `selftest_qos.py` 用系统 Python（`/usr/bin/python3`，带 BCC），不要用项目 venv。
- 这两个脚本会自己创建/删除 netns 和 veth，退出时清理；宿主机网络不受影响。
- 性能数字只对 veth / copy 模式有效，不能当作物理网卡结论。

## Go 版探针（可选）

数据面是 C，用户态是 Go + `cilium/ebpf`，与 Python/BCC 版二选一：

```bash
cd gateway/xdp/goprobe && make
sudo ./selftest_go.sh          # 阶段 1 最小自测
sudo ip netns exec iot3 ./gw-xdp-go --ifaces iot3-eth0 --duration 10 --json-out /tmp/goprobe.json
```

- `--ifaces` 用逗号分隔（Python 版是空格分隔）。
- Go 版同样需要 root；C 程序在 `goprobe/bpf/`。

## 被测实现的位置

- XDP 程序与加载器：`gateway/xdp/`（`gw_filter_probe.c`、`gw_xdp_filter.py`）
- 出口 qdisc 脚本：`gateway/xdp/qos_egress.sh`
- 网关侧 probe 桥：`gateway/core/probe_bridge.py`
- 逐包优先级标记：`gateway/core/qos.py`
