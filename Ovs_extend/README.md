# OVS Experimenter 动作补丁（IoT vendor 0x12345678）

## 为什么需要这个补丁

OpenFlow 1.3 允许用 `OFPAT_EXPERIMENTER`（0xFFFF）+ 厂商 ID 扩展动作。
控制器把 IoT 属性编码成 Experimenter 动作放进 FlowMod：

```
actions = output:2, experimenter(0x12345678, <TLV>)
```

标准 Open vSwitch 只认识 Nicira（0x00002320）和 ONF（0x4f4e4600）两个厂商 ID，
遇到 `0x12345678` 会直接返回：

```
OpenFlow action has unknown vendor 0x12345678
***decode error: OFPBAC_BAD_VENDOR***
```

结果是**整个 FlowMod 被拒绝**，扩展流根本装不进交换机，`ovs-ofctl dump-flows`
自然也看不到它。

## 补丁做了什么

只改 `lib/ofp-actions.c`，约 100 行 diff：

1. **解码**：`ofpacts_decode_aligned()` 遇到 `type=0xFFFF` 且
   `vendor=0x12345678` 的动作时，不再报 `BAD_VENDOR`，而是把负载保存成
   内部的 `OFPACT_NOTE`（前面加 4 字节厂商 ID 作为标记）。
2. **格式化**：`format_NOTE()` 检测到标记时打印成
   `experimenter(0x12345678,...)`，而不是 `note:...`。
3. **编码**：`encode_NOTE()` 检测到标记时按原样编码回
   `OFPAT_EXPERIMENTER`，保证流表回读格式不变。

执行层面 `note` 是 no-op，所以**不改变转发行为**；它的作用是让 FlowMod
能被接受、被保存、在 `dump-flows` 里可见。

## 应用与构建

已经构建好的二进制、测试样本和 3.3.9 源码 tarball 都在 `artifacts/`，
可以直接重装，不需要 `/tmp`：

```bash
sudo ./install_patched_ovs.sh artifacts/bin
```

完整的 `/tmp` 构建目录（约 370 MB）没有复制进项目；需要重建时按
`artifacts/README.md` 的步骤，用 `artifacts/source/openvswitch_3.3.9.orig.tar.xz`
加本目录的 patch 重新编译。

从源码构建的原始步骤：

```bash
# 1. 在 OVS 源码根目录打补丁（4.0.90 已实测；3.3.9 预计可应用，行号可能偏移）
patch -p1 < iot-experimenter-action.patch

# 2. 构建（git 源码先 ./boot.sh；发行版 tarball 直接 configure）
./boot.sh
./configure --prefix=/tmp/ovs-inst --disable-ssl --disable-libcapng --disable-afxdp
make -j$(nproc) utilities/ovs-ofctl
```

## 验证

用 Ryu 生成一条带 Experimenter 动作的 FlowMod：

```bash
SDN_IOT/.venv/bin/python Ovs_extend/build_test_flowmod.py /tmp/fm_exp.bin
```

原版 OVS：

```bash
ovs-ofctl ofp-parse /tmp/fm_exp.bin
# ***decode error: OFPBAC_BAD_VENDOR***
```

打过补丁的 OVS：

```bash
/tmp/ovs-src/utilities/ovs-ofctl ofp-parse /tmp/fm_exp.bin
# ADD priority=150,ip,nw_dst=192.168.1.20 actions=output:2,experimenter(0x12345678,0102030400000000)
```

普通 `NXAST_NOTE` 动作不受影响，仍然显示为 `note:...`。

## 还要做什么才能"真正生效"

1. 把补丁应用到**系统正在使用的 OVS 版本**（当前是 3.3.9），安装并重启
   `ovs-vswitchd`；或者用打过补丁的 OVS 跑一个独立的 dummy datapath 做联调。
2. 调整控制器优先级：
   - 主动流表：`priority=100`（`control_http.py`）
   - 扩展流：`priority=max(ext_priority*10, 10)`（`packet_processor.py`）
   需要让扩展流高于主动流（例如主动流 50、扩展流 200），否则扩展流仍然不会命中。
3. 发一条高温 BLE 数据（priority=5），用 `ovs-ofctl dump-flows` 看扩展流的
   `n_packets` 是否增长，确认它真的被命中。

## 已验证的结果（2026-11-17）

在同一台机器上完成了三层验证：

1. **系统 OVS 3.3.9（未打补丁）**
   `ovs-ofctl ofp-parse` 对带 Experimenter 的 FlowMod 报
   `***decode error: OFPBAC_BAD_VENDOR***`。
2. **补丁版 OVS 3.3.9 / 4.0.90**
   同一条 FlowMod 正常解析：
   `actions=output:2,experimenter(0x12345678,0102030400000000)`。
3. **补丁版 OVS 3.3.9 独立 dummy 交换机**
   FlowMod 成功装入，`ovs-ofctl dump-flows` 显示：
   ```
   priority=150,ip,nw_dst=192.168.1.20 actions=output:2,experimenter(0x12345678,0102030400000000)
   ```
   普通 `NXAST_NOTE` 仍然显示为 `note:...`，没有被误判。
4. **全链路（网关上报 → 控制器 → OVS）**
   给 dummy 交换机接入项目控制器，通过 Unix socket 发送网关格式的
   IoT 属性（含 `target_ip`），控制器自动下发扩展流；再往 `p1` 注入一个
   目的为 `192.168.1.20` 的 IPv4 包，流表计数增长：
   ```
   n_packets=1, n_bytes=60, priority=130,ip,nw_dst=192.168.1.20
   actions=output:2,experimenter(0x12345678,030108...)
   ```
   证明扩展流不是"躺在表里"，而是真的被命中。

要把补丁用到系统 OVS 上：

```bash
sudo ./install_patched_ovs.sh artifacts/bin
```

脚本会备份原二进制并打印回滚命令。

## 优先级已同步调整

- 主动流表：`priority=100` → **50**（`control_http.py`）
- 扩展流：`max(priority*10, 10)` → **100 + priority*10 = 120–150**（`packet_processor.py`）

这样扩展流才会先于主动流命中。验证时建议用**普通温度**（priority 2–3、route_a），
因为 `route_b` 的端口映射目前仍是错的。

## 注意

- 这是实验性本地补丁，不是 OVS 上游代码；`apt` 升级 OVS 后需要重新应用。
- `route_b` 当前的备用路径端口映射指向了错误的主机（h1 → s2 port3 实际是 h2），
  在验证"路径切换"之前需要先修正。
- 替换系统 OVS 会重启 `ovs-vswitchd`，现有 Mininet 拓扑需要重新启动；
  流表由控制器重新预装。
