package main

import (
	"encoding/json"
	"fmt"
	"log"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/cilium/ebpf"
	"github.com/cilium/ebpf/link"

	"sdn-iot/gateway/xdp/goprobe/internal/model"
	"sdn-iot/gateway/xdp/goprobe/internal/probe"
	"sdn-iot/gateway/xdp/goprobe/internal/stats"
	"sdn-iot/gateway/xdp/goprobe/internal/xdp"
)

// runLoop 周期性打印计数，直到收到信号或 --duration 到期，返回最终计数。
func runLoop(cfg config, statsMap *ebpf.Map, p *probe.Probe) map[string]uint64 {
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)

	intervalDur := time.Duration(cfg.interval * float64(time.Second))
	if intervalDur < 200*time.Millisecond {
		intervalDur = 200 * time.Millisecond
	}
	ticker := time.NewTicker(intervalDur)
	defer ticker.Stop()

	var deadline <-chan time.Time
	if cfg.duration > 0 {
		timer := time.NewTimer(time.Duration(cfg.duration * float64(time.Second)))
		defer timer.Stop()
		deadline = timer.C
	}

	start := time.Now()
	totals, err := stats.Read(statsMap)
	if err != nil {
		log.Fatalf("读取 stats 失败: %v", err)
	}
	last := stats.Copy(totals)

loop:
	for {
		select {
		case <-ticker.C:
			cur, err := stats.Read(statsMap)
			if err != nil {
				log.Printf("读取 stats 失败: %v", err)
				continue
			}
			deltas := stats.Diff(cur, last)
			last = cur
			printRow(cur, deltas, time.Since(start), p)
			totals = cur
		case <-sigCh:
			break loop
		case <-deadline:
			break loop
		}
	}

	final, err := stats.Read(statsMap)
	if err == nil {
		totals = final
	}
	return totals
}

func printRow(totals, deltas map[string]uint64, elapsed time.Duration, p *probe.Probe) {
	parts := []string{
		fmt.Sprintf("5005 cached=%d (+%d)", totals["flow_cached"], deltas["flow_cached"]),
		fmt.Sprintf("miss=%d (+%d)", totals["flow_miss"], deltas["flow_miss"]),
	}
	for _, name := range model.StatNames {
		if name == "flow_cached" || name == "flow_miss" {
			continue
		}
		if totals[name] != 0 || deltas[name] != 0 {
			parts = append(parts, fmt.Sprintf("%s=%d (+%d)", name, totals[name], deltas[name]))
		}
	}
	if p != nil {
		s := p.Snapshot()
		parts = append(parts, fmt.Sprintf("evt=%d resolve=%d ready=%d pending=%d rl=%d",
			s["events"], s["resolves"], s["ready"], s["pending"], s["rate_limited"]))
	}
	log.Printf("[%7.1fs] %s", elapsed.Seconds(), strings.Join(parts, "  "))
}

// writeSummary 打印最终统计，可选写 JSON，然后摘除 XDP（除非 --keep）。
func writeSummary(cfg config, totals map[string]uint64, attached []string,
	links map[string]link.Link, pinned map[string]string, p *probe.Probe, cfgLabel string) {

	hitRate := 0.0
	if total := totals["flow_cached"] + totals["flow_miss"]; total > 0 {
		hitRate = float64(totals["flow_cached"]) / float64(total)
	}
	var probeSnap map[string]uint64
	if p != nil {
		probeSnap = p.Snapshot()
	} else {
		probeSnap = map[string]uint64{}
	}
	log.Printf("[SUMMARY] cached=%d miss=%d hit_rate=%.3f events=%d resolves=%d ready=%d pending=%d rate_limited=%d ebpf_writes=%d",
		totals["flow_cached"], totals["flow_miss"], hitRate,
		probeSnap["events"], probeSnap["resolves"], probeSnap["ready"],
		probeSnap["pending"], probeSnap["rate_limited"], probeSnap["ebpf_writes"])

	if cfg.jsonOut != "" {
		xdpState := make(map[string]string, len(attached))
		for _, iface := range attached {
			xdpState[iface] = xdp.XDPLine(iface)
		}
		payload := map[string]any{
			"ts":        time.Now().Format("2006-01-02T15:04:05-0700"),
			"netns":     xdp.NetnsID(),
			"ifaces":    attached,
			"mode":      cfg.mode,
			"cfg":       cfgLabel,
			"totals":    totals,
			"hit_rate":  hitRate,
			"probe":     probeSnap,
			"xdp_state": xdpState,
		}
		data, _ := json.MarshalIndent(payload, "", "  ")
		if err := os.WriteFile(cfg.jsonOut, data, 0o644); err != nil {
			log.Printf("写 JSON 失败: %v", err)
		} else {
			log.Printf("计数已写入 %s", cfg.jsonOut)
		}
	}

	if cfg.keep {
		for iface, pinPath := range pinned {
			log.Printf("保留 XDP %s（pinned %s）", iface, pinPath)
		}
		return
	}
	for iface, lnk := range links {
		if err := lnk.Close(); err != nil {
			log.Printf("摘除 %s 失败: %v", iface, err)
		} else {
			log.Printf("已摘除 XDP：%s", iface)
		}
	}
}
