// Package probe 实现 ringbuf 事件消费者：resolve → pending/ready →
// flow_ready/flow_delete → 回写 eBPF 缓存。
package probe

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"net"
	"os"
	"sync"
	"time"

	"github.com/cilium/ebpf"
	"golang.org/x/sys/unix"

	"sdn-iot/gateway/xdp/goprobe/internal/model"
)

type stats struct {
	mu              sync.Mutex
	events          uint64
	resolves        uint64
	ready           uint64
	pending         uint64
	rateLimited     uint64
	resolveErrors   uint64
	flowReady       uint64
	flowDelete      uint64
	ebpfWrites      uint64
	ebpfWriteErrors uint64
}

func (s *stats) inc(field *uint64) {
	s.mu.Lock()
	*field = *field + 1
	s.mu.Unlock()
}

type rateLimiter struct {
	mu     sync.Mutex
	window []time.Time
	limit  int
}

func newRateLimiter(limit int) *rateLimiter {
	if limit < 1 {
		limit = 1
	}
	return &rateLimiter{limit: limit}
}

func (r *rateLimiter) allow() bool {
	now := time.Now()
	cutoff := now.Add(-time.Second)
	r.mu.Lock()
	defer r.mu.Unlock()
	i := 0
	for i < len(r.window) && r.window[i].Before(cutoff) {
		i++
	}
	r.window = r.window[i:]
	if len(r.window) >= r.limit {
		return false
	}
	r.window = append(r.window, now)
	return true
}

// Probe 持有 flows map、网关/客户端 Unix socket 和探针统计。
type Probe struct {
	flows      *ebpf.Map
	conn       *net.UnixConn
	gwPath     string
	clientPath string
	rate       *rateLimiter
	ttlDefault int
	stats      stats

	mu        sync.Mutex
	keyTarget map[model.FlowKey]string
	pending   map[model.FlowKey]string

	halt chan struct{}
	done chan struct{}
}

func New(flows *ebpf.Map, gwPath, clientPath string, rate int, ttl int) (*Probe, error) {
	_ = os.Remove(clientPath)
	addr := &net.UnixAddr{Name: clientPath, Net: "unixgram"}
	conn, err := net.ListenUnixgram("unixgram", addr)
	if err != nil {
		return nil, err
	}
	p := &Probe{
		flows:      flows,
		conn:       conn,
		gwPath:     gwPath,
		clientPath: clientPath,
		rate:       newRateLimiter(rate),
		ttlDefault: ttl,
		keyTarget:  make(map[model.FlowKey]string),
		pending:    make(map[model.FlowKey]string),
		halt:       make(chan struct{}),
		done:       make(chan struct{}),
	}
	go p.recvLoop()
	return p, nil
}

func (p *Probe) Stop() {
	select {
	case <-p.halt:
	default:
		close(p.halt)
	}
	_ = p.conn.Close()
	_ = os.Remove(p.clientPath)
	select {
	case <-p.done:
	case <-time.After(time.Second):
	}
}

func (p *Probe) Snapshot() map[string]uint64 {
	p.stats.mu.Lock()
	defer p.stats.mu.Unlock()
	return map[string]uint64{
		"events":            p.stats.events,
		"resolves":          p.stats.resolves,
		"ready":             p.stats.ready,
		"pending":           p.stats.pending,
		"rate_limited":      p.stats.rateLimited,
		"resolve_errors":    p.stats.resolveErrors,
		"flow_ready":        p.stats.flowReady,
		"flow_delete":       p.stats.flowDelete,
		"ebpf_writes":       p.stats.ebpfWrites,
		"ebpf_write_errors": p.stats.ebpfWriteErrors,
	}
}

func (p *Probe) OnMiss(evt model.MissEvt) {
	p.stats.inc(&p.stats.events)
	log.Printf("[MISS] %s preview=%q", model.FmtKey(evt.Key),
		bytes.TrimRight(evt.Preview[:], "\x00"))
	if !p.rate.allow() {
		p.stats.inc(&p.stats.rateLimited)
		return
	}
	payload, _ := json.Marshal(model.OutMsg{
		Op:      "resolve",
		Key:     model.KeyList(evt.Key),
		Preview: fmt.Sprintf("%x", evt.Preview[:]),
	})
	if _, err := p.conn.WriteToUnix(payload, &net.UnixAddr{Name: p.gwPath, Net: "unixgram"}); err != nil {
		p.stats.inc(&p.stats.resolveErrors)
		log.Printf("[PROBE] resolve 发送失败: %v", err)
		return
	}
	p.stats.inc(&p.stats.resolves)
}

func (p *Probe) recvLoop() {
	defer close(p.done)
	buf := make([]byte, 4096)
	for {
		select {
		case <-p.halt:
			return
		default:
		}
		_ = p.conn.SetReadDeadline(time.Now().Add(500 * time.Millisecond))
		n, _, err := p.conn.ReadFromUnix(buf)
		if err != nil {
			var ne net.Error
			if errors.As(err, &ne) && ne.Timeout() {
				continue
			}
			return
		}
		var msg model.InMsg
		if err := json.Unmarshal(buf[:n], &msg); err != nil {
			continue
		}
		switch msg.Op {
		case "resolve_reply":
			p.onReply(msg)
		case "flow_ready":
			p.onFlowReady(msg)
		case "flow_delete":
			p.onFlowDelete(msg)
		}
	}
}

func (p *Probe) onReply(msg model.InMsg) {
	if len(msg.Key) != 5 || msg.TargetIP == "" {
		return
	}
	key := model.KeyFromList(msg.Key)
	switch msg.Status {
	case "ready":
		ttl := msg.TTL
		if ttl <= 0 {
			ttl = p.ttlDefault
		}
		p.mu.Lock()
		p.stats.mu.Lock()
		p.stats.ready++
		p.stats.mu.Unlock()
		p.keyTarget[key] = msg.TargetIP
		delete(p.pending, key)
		p.mu.Unlock()
		p.writeReady(key, ttl)
		log.Printf("[PROBE] 网关本地缓存命中 %s → %s，写 eBPF 缓存 READY ttl=%ds",
			model.FmtKey(key), msg.TargetIP, ttl)
	case "pending":
		p.mu.Lock()
		p.stats.mu.Lock()
		p.stats.pending++
		p.stats.mu.Unlock()
		p.keyTarget[key] = msg.TargetIP
		p.pending[key] = msg.TargetIP
		p.mu.Unlock()
		log.Printf("[PROBE] 网关本地缓存未命中 %s → %s，已上报，等 FlowMod",
			model.FmtKey(key), msg.TargetIP)
	}
}

func (p *Probe) onFlowReady(msg model.InMsg) {
	if msg.TargetIP == "" {
		return
	}
	ttl := msg.TTL
	if ttl <= 0 {
		ttl = p.ttlDefault
	}
	p.mu.Lock()
	var keys []model.FlowKey
	for k, target := range p.keyTarget {
		if target == msg.TargetIP {
			keys = append(keys, k)
		}
	}
	for k, target := range p.pending {
		if target == msg.TargetIP {
			found := false
			for _, existing := range keys {
				if existing == k {
					found = true
					break
				}
			}
			if !found {
				keys = append(keys, k)
			}
			delete(p.pending, k)
		}
	}
	p.stats.mu.Lock()
	p.stats.flowReady++
	p.stats.mu.Unlock()
	p.mu.Unlock()

	for _, key := range keys {
		p.writeReady(key, ttl)
	}
	log.Printf("[PROBE] 收到 flow_ready %s ttl=%ds，回写 %d 条 eBPF 缓存",
		msg.TargetIP, ttl, len(keys))
}

func (p *Probe) onFlowDelete(msg model.InMsg) {
	if msg.TargetIP == "" {
		return
	}
	p.mu.Lock()
	var keys []model.FlowKey
	for k, target := range p.keyTarget {
		if target == msg.TargetIP {
			keys = append(keys, k)
			delete(p.keyTarget, k)
			delete(p.pending, k)
		}
	}
	p.stats.mu.Lock()
	p.stats.flowDelete++
	p.stats.mu.Unlock()
	p.mu.Unlock()

	for _, key := range keys {
		_ = p.flows.Delete(&key)
	}
	log.Printf("[PROBE] 收到 flow_delete %s，删除 %d 条 eBPF 缓存",
		msg.TargetIP, len(keys))
}

func (p *Probe) writeReady(key model.FlowKey, ttl int) {
	val := model.FlowVal{
		ExpiresNS: monotonicNS() + uint64(ttl)*1_000_000_000,
		Flags:     1,
	}
	err := p.flows.Update(&key, &val, ebpf.UpdateAny)
	p.stats.mu.Lock()
	if err == nil {
		p.stats.ebpfWrites++
	} else {
		p.stats.ebpfWriteErrors++
	}
	p.stats.mu.Unlock()
	if err != nil {
		log.Printf("[PROBE] 写 eBPF 缓存异常: %v", err)
	}
}

func monotonicNS() uint64 {
	var ts unix.Timespec
	if err := unix.ClockGettime(unix.CLOCK_MONOTONIC, &ts); err != nil {
		return uint64(time.Now().UnixNano())
	}
	return uint64(ts.Sec)*1_000_000_000 + uint64(ts.Nsec)
}
