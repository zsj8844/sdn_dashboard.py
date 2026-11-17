# 构建产物

这里保存的是 2026-11-17 为验证 IoT Experimenter 动作而构建的 OVS 产物。
`/tmp` 里的完整构建目录（约 370 MB）没有复制进来；保留的是无法从源码
快速重现的部分，以及验证用的测试文件。

## 内容

```
artifacts/
├── bin/
│   ├── ovs-vswitchd-3.3.9   # 补丁版，与系统当前 /usr/sbin/ovs-vswitchd 哈希一致
│   ├── ovs-ofctl-3.3.9      # 补丁版，与系统当前 /usr/bin/ovs-ofctl 哈希一致
│   └── ovs-ofctl-4.0.90     # 4.0.90 补丁版，仅用于 ofp-parse 对比
├── source/
│   └── openvswitch_3.3.9.orig.tar.xz   # Ubuntu 3.3.9 源码，打补丁后可重建
├── test/
│   ├── fm_plain.bin         # 普通 FlowMod（output:2）
│   ├── fm_exp.bin           # 带 experimenter(0x12345678) 的 FlowMod
│   ├── fm_exp2.bin          # 同上，当前使用的测试样本
│   ├── fm_note.bin          # 普通 NXAST_NOTE，回归测试用
│   └── send_flowmod.py      # 向 dummy 交换机发送 FlowMod 并做 Barrier 的脚本
└── logs/
    ├── ovsdb.log
    └── vswitchd.log
```

## 直接用产物重装

```bash
cd /home/zhang/桌面/sdn/SDN_IOT/Ovs_extend
sudo ./install_patched_ovs.sh artifacts/bin
```

脚本会备份系统二进制并打印回滚命令。

## 从源码重建

```bash
cd /tmp
tar xf /home/zhang/桌面/sdn/SDN_IOT/Ovs_extend/artifacts/source/openvswitch_3.3.9.orig.tar.xz
cd openvswitch-3.3.9
patch -p1 < /home/zhang/桌面/sdn/SDN_IOT/Ovs_extend/iot-experimenter-action.patch
./configure --prefix=/tmp/ovs-3.3.9-inst --disable-ssl --disable-libcapng \
            --disable-afxdp --disable-dependency-tracking
touch Makefile.in
make -o Makefile.in include/odp-netlink.h include/odp-netlink-macros.h
make -o Makefile.in lib/vswitch-idl.h lib/ovsdb-server-idl.h
make -o Makefile.in ofproto/ipfix-entities.def
make -o Makefile.in -j$(nproc) vswitchd/ovs-vswitchd utilities/ovs-ofctl
```

3.3.9 的发行 tarball 自带 `configure`，不需要 autotools。

## 验证

```bash
ovs-ofctl ofp-parse artifacts/test/fm_exp2.bin
# 期望：
# ADD priority=150,ip,nw_dst=192.168.1.20
# actions=output:2,experimenter(0x12345678,0102030400000000)
```
