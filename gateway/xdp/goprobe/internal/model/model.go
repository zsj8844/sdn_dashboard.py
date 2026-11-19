// Package model 定义 Go 用户态与 eBPF 数据面共享的结构和常量。
package model

import "fmt"

// StatNames 与 C 端 enum stat_key 的顺序一致。
var StatNames = []string{
	"non_ip", "non_udp", "non_5005", "flow_cached",
	"flow_miss", "dropped", "ringbuf_full", "parse_error",
}

const (
	DefaultProbeSock  = "/tmp/sdn_xdp_probe.sock"
	DefaultClientSock = "/tmp/sdn_xdp_probe_cli.sock"
	DefaultTTL        = 60
	PreviewLen        = 24
)

type FlowKey struct {
	Saddr uint32
	Daddr uint32
	Sport uint16
	Dport uint16
	Proto uint8
	Pad   [3]uint8
}

type FlowVal struct {
	ExpiresNS uint64
	Flags     uint32
	Pad       uint32
}

type MissEvt struct {
	Key     FlowKey
	TsNS    uint64
	Preview [PreviewLen]uint8
}

type InMsg struct {
	Op       string   `json:"op"`
	Key      []uint32 `json:"key"`
	Status   string   `json:"status"`
	TargetIP string   `json:"target_ip"`
	TTL      int      `json:"ttl"`
}

type OutMsg struct {
	Op      string   `json:"op"`
	Key     []uint32 `json:"key,omitempty"`
	Preview string   `json:"preview,omitempty"`
}

func KeyList(k FlowKey) []uint32 {
	return []uint32{k.Saddr, k.Daddr, uint32(k.Sport), uint32(k.Dport), uint32(k.Proto)}
}

func KeyFromList(v []uint32) FlowKey {
	return FlowKey{
		Saddr: v[0],
		Daddr: v[1],
		Sport: uint16(v[2]),
		Dport: uint16(v[3]),
		Proto: uint8(v[4]),
	}
}

func FmtKey(k FlowKey) string {
	return fmt.Sprintf("%s:%d->%s:%d", IPString(k.Saddr), k.Sport,
		IPString(k.Daddr), k.Dport)
}

func IPString(v uint32) string {
	return fmt.Sprintf("%d.%d.%d.%d", byte(v), byte(v>>8), byte(v>>16), byte(v>>24))
}
