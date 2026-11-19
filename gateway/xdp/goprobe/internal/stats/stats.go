// Package stats 读取 eBPF 的 PERCPU 计数并做快照/差分。
package stats

import (
	"github.com/cilium/ebpf"

	"sdn-iot/gateway/xdp/goprobe/internal/model"
)

// Read 读取 PERCPU_ARRAY，并把每个 CPU 的值加起来。
func Read(m *ebpf.Map) (map[string]uint64, error) {
	out := make(map[string]uint64, len(model.StatNames))
	for i, name := range model.StatNames {
		var vals []uint64
		if err := m.Lookup(uint32(i), &vals); err != nil {
			return nil, err
		}
		var sum uint64
		for _, v := range vals {
			sum += v
		}
		out[name] = sum
	}
	return out, nil
}

func Copy(in map[string]uint64) map[string]uint64 {
	out := make(map[string]uint64, len(in))
	for k, v := range in {
		out[k] = v
	}
	return out
}

func Diff(cur, last map[string]uint64) map[string]uint64 {
	out := make(map[string]uint64, len(cur))
	for k, v := range cur {
		out[k] = v - last[k]
	}
	return out
}
