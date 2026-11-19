/* iot3 网关入向 XDP 程序（libbpf / clang 加载）。
 *
 * 数据面只保留这一份 C，由 goprobe 的 Makefile 编译成
 * gw_filter_probe.o，再由 Go（cilium/ebpf）加载。
 *
 * 共享的类型定义在 gw_filter_types.h，共享的 filter 逻辑在
 * gw_filter_logic.h；本文件只保留 map 定义和入口。
 *
 * 阶段 1：UDP 5005 分类、计数、按 cfg 丢弃非 5005。
 * 阶段 2：flows HASH（5 元组 → PENDING/READY + 过期时间），未命中时
 *         写 PENDING（1 s 冷却）并向 ringbuf 发一个事件；数据始终 XDP_PASS。
 * 阶段 3-5：用户态探针写 READY（TTL 60 s），过期后视同未命中。
 */
#include <linux/bpf.h>
#include <linux/if_ether.h>
#include <linux/in.h>
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_endian.h>

#include "gw_filter_types.h"

struct {
    __uint(type, BPF_MAP_TYPE_HASH);
    __uint(max_entries, 8192);
    __type(key, struct flow_key);
    __type(value, struct flow_val);
} flows SEC(".maps");

struct {
    __uint(type, BPF_MAP_TYPE_RINGBUF);
    __uint(max_entries, 1 << 18);
} misses SEC(".maps");

struct {
    __uint(type, BPF_MAP_TYPE_ARRAY);
    __uint(max_entries, 1);
    __type(key, __u32);
    __type(value, __u32);
} cfg SEC(".maps");

struct {
    __uint(type, BPF_MAP_TYPE_PERCPU_ARRAY);
    __uint(max_entries, ST_MAX);
    __type(key, __u32);
    __type(value, __u64);
} stats SEC(".maps");

#include "gw_filter_logic.h"

SEC("xdp")
int gw_filter(struct xdp_md *ctx)
{
    return gw_filter_impl(ctx);
}

char _license[] SEC("license") = "GPL";
