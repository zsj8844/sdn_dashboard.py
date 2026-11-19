/* iot3 网关入向 XDP 程序 —— 单文件，两个加载器共用。
 *
 * 用 GW_USE_BCC 选择加载方式：
 *   - BCC（gw_xdp_filter.py）：编译时带 -DGW_USE_BCC，使用 BPF_HASH 等宏
 *   - libbpf/Go（goprobe）：不带该宏，使用 SEC(".maps") 标准定义
 *
 * 共享的类型定义在 gw_filter_types.h，共享的 filter 逻辑在
 * gw_filter_logic.h；本文件只保留 map 定义和入口的差异。
 *
 * 阶段 1：UDP 5005 分类、计数、按 cfg 丢弃非 5005。
 * 阶段 2：flows HASH（5 元组 → PENDING/READY + 过期时间），未命中时
 *         写 PENDING（1 s 冷却）并向 ringbuf 发一个事件；数据始终 XDP_PASS。
 * 阶段 3-5：用户态探针写 READY（TTL 60 s），过期后视同未命中。
 */
#ifdef GW_USE_BCC
#include <uapi/linux/bpf.h>
#include <uapi/linux/if_ether.h>
#include <uapi/linux/in.h>
#else
#include <linux/bpf.h>
#include <linux/if_ether.h>
#include <linux/in.h>
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_endian.h>
#endif

#include "gw_filter_types.h"

#ifdef GW_USE_BCC
BPF_HASH(flows, struct flow_key, struct flow_val, 8192);
BPF_RINGBUF_OUTPUT(misses, 32);
BPF_ARRAY(cfg, u32, 1);
BPF_PERCPU_ARRAY(stats, u64, ST_MAX);
#else
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
#endif

#include "gw_filter_logic.h"

#ifdef GW_USE_BCC
int gw_filter(struct xdp_md *ctx)
{
    return gw_filter_impl(ctx);
}
#else
SEC("xdp")
int gw_filter(struct xdp_md *ctx)
{
    return gw_filter_impl(ctx);
}

char _license[] SEC("license") = "GPL";
#endif
