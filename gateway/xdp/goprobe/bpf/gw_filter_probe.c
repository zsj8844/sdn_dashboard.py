/* iot3 网关入向 XDP 程序（libbpf / clang 加载）—— filter + eBPF 缓存 + 未命中事件。
 *
 * 这是 gw_filter_probe.c 的 libbpf 版本，逻辑相同，只把 BCC 的
 * BPF_HASH / BPF_ARRAY / BPF_RINGBUF_OUTPUT 宏换成标准 map 定义，
 * 供 Go（cilium/ebpf）或 bpftool 直接加载。
 */
#include <linux/bpf.h>
#include <linux/if_ether.h>
#include <linux/in.h>
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_endian.h>

#define GW_UDP_PORT 5005
#define COOLDOWN_NS 1000000000ULL   /* 每 key 1 s 冷却 */
#define PREVIEW_LEN 24

enum stat_key {
    ST_NON_IP = 0,
    ST_NON_UDP = 1,
    ST_NON_5005 = 2,
    ST_FLOW_CACHED = 3,
    ST_FLOW_MISS = 4,
    ST_DROPPED = 5,
    ST_RINGBUF_FULL = 6,
    ST_PARSE_ERR = 7,
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

static __always_inline void bump(__u32 k)
{
    __u64 *v = bpf_map_lookup_elem(&stats, &k);
    if (v)
        __sync_fetch_and_add(v, 1);
}

SEC("xdp")
int gw_filter(struct xdp_md *ctx)
{
    void *data = (void *)(long)ctx->data;
    void *data_end = (void *)(long)ctx->data_end;
    __u64 now = bpf_ktime_get_ns();

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
    __u32 ihl = (__u32)(ip->ihl_version & 0x0f) * 4;
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
        __u32 k = 0;
        __u32 *drop = bpf_map_lookup_elem(&cfg, &k);
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

    struct flow_val *v = bpf_map_lookup_elem(&flows, &key);
    if (v && v->expires_ns > now) {
        bump(ST_FLOW_CACHED);
        return XDP_PASS;
    }

    /* 未命中 / 已过期：先写 PENDING 做冷却，再发一个事件。 */
    struct flow_val pending = {
        .expires_ns = now + COOLDOWN_NS,
        .flags = 0,
    };
    bpf_map_update_elem(&flows, &key, &pending, BPF_ANY);
    bump(ST_FLOW_MISS);

    struct miss_evt evt;
    __builtin_memset(&evt, 0, sizeof(evt));
    evt.key = key;
    evt.ts_ns = now;
    __u8 *payload = (void *)udp + sizeof(struct udp_hdr);
    if ((void *)(payload + PREVIEW_LEN) <= data_end)
        __builtin_memcpy(evt.preview, payload, PREVIEW_LEN);

    if (bpf_ringbuf_output(&misses, &evt, sizeof(evt), 0) != 0)
        bump(ST_RINGBUF_FULL);

    return XDP_PASS;
}

char _license[] SEC("license") = "GPL";
