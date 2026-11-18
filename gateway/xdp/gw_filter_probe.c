/* iot3 网关入向 XDP 程序（BCC 加载）—— filter + eBPF 缓存 + 未命中事件。
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

#define GW_UDP_PORT 5005
#define COOLDOWN_NS 1000000000ULL   /* 每 key 1 s 冷却 */
#define PREVIEW_LEN 24

/* stats 的 key，与 userspace 的 STAT_NAMES 顺序一致 */
enum stat_key {
    ST_NON_IP = 0,       /* 非 IPv4 */
    ST_NON_UDP = 1,      /* IPv4 非 UDP */
    ST_NON_5005 = 2,     /* UDP 非 5005 */
    ST_FLOW_CACHED = 3,  /* 5005 且 eBPF 缓存有未过期表项（READY 或冷却中的 PENDING） */
    ST_FLOW_MISS = 4,    /* 5005 且 eBPF 缓存未命中/过期，本轮发了事件 */
    ST_DROPPED = 5,      /* 被 cfg 丢弃 */
    ST_RINGBUF_FULL = 6, /* ringbuf 写失败 */
    ST_PARSE_ERR = 7,    /* 截断 / 非法 IHL / 非首片 */
    ST_MAX = 8,
};

struct ipv4_hdr {
    __u8  ihl_version;
    __u8  tos;
    __u16 tot_len;
    __u16 id;
    __u16 frag_off;
    __u8  ttl;
    __u8  protocol;
    __u16 check;
    __u32 saddr;
    __u32 daddr;
};

struct udp_hdr {
    __u16 source;
    __u16 dest;
    __u16 len;
    __u16 check;
};

/* eBPF 缓存 key：入向 5 元组（daddr 是网关自己，dport=5005）。 */
struct flow_key {
    __u32 saddr;
    __u32 daddr;
    __u16 sport;
    __u16 dport;
    __u8  proto;
    __u8  pad[3];
};

struct flow_val {
    __u64 expires_ns;
    __u32 flags;        /* 0=PENDING，1=READY */
    __u32 pad;
};

struct miss_evt {
    struct flow_key key;
    __u64 ts_ns;
    __u8  preview[PREVIEW_LEN];
};

BPF_HASH(flows, struct flow_key, struct flow_val, 8192);
BPF_RINGBUF_OUTPUT(misses, 32);
BPF_ARRAY(cfg, u32, 1);
BPF_PERCPU_ARRAY(stats, u64, ST_MAX);

static __always_inline void bump(u32 k)
{
    u64 *v = stats.lookup(&k);
    if (v)
        __sync_fetch_and_add(v, 1);
}

int gw_filter(struct xdp_md *ctx)
{
    void *data = (void *)(long)ctx->data;
    void *data_end = (void *)(long)ctx->data_end;
    u64 now = bpf_ktime_get_ns();

    struct ethhdr *eth = data;
    if ((void *)(eth + 1) > data_end) {
        bump(ST_PARSE_ERR);
        return XDP_PASS;
    }
    if (bpf_ntohs(eth->h_proto) != ETH_P_IP) {
        bump(ST_NON_IP);
        return XDP_PASS;
    }

    struct ipv4_hdr *ip = (void *)(eth + 1);
    if ((void *)(ip + 1) > data_end) {
        bump(ST_PARSE_ERR);
        return XDP_PASS;
    }
    if ((ip->ihl_version & 0xf0) != 0x40) {
        bump(ST_PARSE_ERR);
        return XDP_PASS;
    }
    u32 ihl = (u32)(ip->ihl_version & 0x0f) * 4;
    if (ihl < sizeof(struct ipv4_hdr)) {
        bump(ST_PARSE_ERR);
        return XDP_PASS;
    }
    if (ip->protocol != IPPROTO_UDP) {
        bump(ST_NON_UDP);
        return XDP_PASS;
    }
    if (ip->frag_off & bpf_htons(0x1fff)) {
        bump(ST_PARSE_ERR);
        return XDP_PASS;
    }

    struct udp_hdr *udp = (void *)ip + ihl;
    if ((void *)(udp + 1) > data_end) {
        bump(ST_PARSE_ERR);
        return XDP_PASS;
    }

    if (bpf_ntohs(udp->dest) != GW_UDP_PORT) {
        bump(ST_NON_5005);
        u32 k = 0;
        u32 *drop = cfg.lookup(&k);
        if (drop && ((*drop) & 1)) {
            bump(ST_DROPPED);
            return XDP_DROP;
        }
        return XDP_PASS;
    }

    struct flow_key key = {
        .saddr = ip->saddr,
        .daddr = ip->daddr,
        .sport = udp->source,
        .dport = udp->dest,
        .proto = IPPROTO_UDP,
    };

    struct flow_val *v = flows.lookup(&key);
    if (v && v->expires_ns > now) {
        bump(ST_FLOW_CACHED);
        return XDP_PASS;
    }

    /* 未命中 / 已过期：先写 PENDING 做冷却，再发一个事件。 */
    struct flow_val pending = {
        .expires_ns = now + COOLDOWN_NS,
        .flags = 0,
    };
    flows.update(&key, &pending);
    bump(ST_FLOW_MISS);

    struct miss_evt evt = {};
    evt.key = key;
    evt.ts_ns = now;
    u8 *payload = (void *)udp + sizeof(struct udp_hdr);
    if ((void *)(payload + PREVIEW_LEN) <= data_end)
        __builtin_memcpy(evt.preview, payload, PREVIEW_LEN);

    if (misses.ringbuf_output(&evt, sizeof(evt), 0) != 0)
        bump(ST_RINGBUF_FULL);

    return XDP_PASS;
}
