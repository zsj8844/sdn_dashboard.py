/* iot3 网关入向 XDP 程序（BCC 加载）—— 薄封装。
 *
 * 共享的类型定义在 gw_filter_types.h，共享的 filter 逻辑在
 * gw_filter_logic.h；本文件只保留 BCC 的 map 定义和入口函数。
 *
 * 阶段 1：UDP 5005 分类、计数、按 cfg 丢弃非 5005。
 * 阶段 2：flows HASH（5 元组 → PENDING/READY + 过期时间），未命中时
 *         写 PENDING（1 s 冷却）并向 ringbuf 发一个事件；数据始终 XDP_PASS。
 * 阶段 3-5：用户态探针写 READY（TTL 60 s），过期后视同未命中。
 *
 * 只使用 uapi 头（内核 7.0 的 linux/ip.h 与 BCC 0.29 冲突）。
 */
#include <uapi/linux/bpf.h>
#include <uapi/linux/if_ether.h>
#include <uapi/linux/in.h>

#include "gw_filter_types.h"

BPF_HASH(flows, struct flow_key, struct flow_val, 8192);
BPF_RINGBUF_OUTPUT(misses, 32);
BPF_ARRAY(cfg, u32, 1);
BPF_PERCPU_ARRAY(stats, u64, ST_MAX);

#define GW_USE_BCC 1
#include "gw_filter_logic.h"

int gw_filter(struct xdp_md *ctx)
{
    return gw_filter_impl(ctx);
}
