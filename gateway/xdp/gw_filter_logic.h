/* iot3 网关 XDP 程序的共享逻辑。
 *
 * 只共享流程，不共享 map 访问方式：
 *   - BCC 版定义 GW_USE_BCC，使用 flows.lookup() / flows.update() /
 *     cfg.lookup() / stats.lookup() / misses.ringbuf_output()。
 *   - libbpf 版使用 bpf_map_lookup_elem() / bpf_map_update_elem() /
 *     bpf_ringbuf_output()。
 *
 * 注意：这些调用必须写成字面量，不能包进宏。BCC 的源码重写器只认
 * 源码里的 map.lookup(...)，宏展开后的调用会报
 * "cannot use map function inside a macro"。
 */
#ifndef GW_FILTER_LOGIC_H
#define GW_FILTER_LOGIC_H

static __always_inline void bump(__u32 k)
{
#ifdef GW_USE_BCC
    __u64 *v = stats.lookup(&k);
#else
    __u64 *v = bpf_map_lookup_elem(&stats, &k);
#endif
    if (v)
        __sync_fetch_and_add(v, 1);
}

static __always_inline int gw_filter_impl(struct xdp_md *ctx)
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
#ifdef GW_USE_BCC
        __u32 *drop = cfg.lookup(&k);
#else
        __u32 *drop = bpf_map_lookup_elem(&cfg, &k);
#endif
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

#ifdef GW_USE_BCC
    struct flow_val *v = flows.lookup(&key);
#else
    struct flow_val *v = bpf_map_lookup_elem(&flows, &key);
#endif
    if (v && v->expires_ns > now) {
        bump(ST_FLOW_CACHED);
        return XDP_PASS;
    }

    /* 未命中 / 已过期：先写 PENDING 做冷却，再发一个事件。 */
    struct flow_val pending = {
        .expires_ns = now + COOLDOWN_NS,
        .flags = 0,
    };
#ifdef GW_USE_BCC
    flows.update(&key, &pending);
#else
    bpf_map_update_elem(&flows, &key, &pending, BPF_ANY);
#endif
    bump(ST_FLOW_MISS);

    struct miss_evt evt;
    __builtin_memset(&evt, 0, sizeof(evt));
    evt.key = key;
    evt.ts_ns = now;
    __u8 *payload = (void *)udp + sizeof(struct udp_hdr);
    if ((void *)(payload + PREVIEW_LEN) <= data_end)
        __builtin_memcpy(evt.preview, payload, PREVIEW_LEN);

#ifdef GW_USE_BCC
    if (misses.ringbuf_output(&evt, sizeof(evt), 0) != 0)
#else
    if (bpf_ringbuf_output(&misses, &evt, sizeof(evt), 0) != 0)
#endif
        bump(ST_RINGBUF_FULL);

    return XDP_PASS;
}

#endif /* GW_FILTER_LOGIC_H */
