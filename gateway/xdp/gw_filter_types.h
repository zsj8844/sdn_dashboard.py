/* iot3 网关 XDP 程序的共享类型定义。
 *
 * BCC 版和 libbpf 版都 include 这个文件，保证两边的结构体布局、
 * 统计项编号、常量和用户态解析端完全一致。
 */
#ifndef GW_FILTER_TYPES_H
#define GW_FILTER_TYPES_H

#define GW_UDP_PORT 5005
#define COOLDOWN_NS 1000000000ULL   /* 每 key 1 s 冷却 */
#define PREVIEW_LEN 24

/* stats 的 key，与 userspace 的 STAT_NAMES 顺序一致 */
enum stat_key {
    ST_NON_IP = 0,       /* 非 IPv4 */
    ST_NON_UDP = 1,      /* IPv4 非 UDP */
    ST_NON_5005 = 2,     /* UDP 非 5005 */
    ST_FLOW_CACHED = 3,  /* 5005 且 eBPF 缓存有未过期表项 */
    ST_FLOW_MISS = 4,    /* 5005 且缓存未命中/过期，本轮发了事件 */
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
    __u32 saddr;   /* 源 IP */
    __u32 daddr;   /* 目的 IP（网关自己） */
    __u16 sport;   /* 源端口 */
    __u16 dport;   /* 目的端口 5005 */
    __u8  proto;   /* UDP */
    __u8  pad[3];  /* 补齐到 16 字节 */
};

struct flow_val {
    __u64 expires_ns; /* 过期时间（纳秒） */
    __u32 flags;      /* 0=PENDING，1=READY */
    __u32 pad;
};

struct miss_evt {
    struct flow_key key;    /* 哪个 5 元组没命中 */
    __u64 ts_ns;            /* 发生时间 */
    __u8  preview[PREVIEW_LEN]; /* 载荷前 24 字节 */
};

#endif /* GW_FILTER_TYPES_H */
