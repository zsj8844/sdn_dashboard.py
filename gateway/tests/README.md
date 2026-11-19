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
# 阶段 6：DSCP + HTB
sudo /usr/bin/python3 gateway/tests/selftest_qos.py

# XDP 阶段 1 / 2（Go 版加载器）
cd gateway/xdp/goprobe
make
sudo ./selftest_go.sh
sudo ./selftest_go_probe.sh
```

- `selftest_qos.py` 用系统 Python；Go 自测是编译好的单二进制，不需要 BCC。
- `selftest_go.sh` / `selftest_go_probe.sh` / `selftest_qos.py` 都会自己创建/删除
  netns 和 veth，退出时清理；宿主机网络不受影响。
- 性能数字只对 veth + XDP generic（skb）模式有效，不能当作物理网卡结论。

## 被测实现的位置

- XDP 程序：`gateway/xdp/gw_filter_probe.c`（`gw_filter_logic.h` / `gw_filter_types.h`）
- Go 加载器 / 探针：`gateway/xdp/goprobe/`
- 出口 qdisc 脚本：`gateway/xdp/qos_egress.sh`
- 网关侧 probe 桥：`gateway/core/probe_bridge.py`
- 逐包优先级标记：`gateway/core/qos.py`
