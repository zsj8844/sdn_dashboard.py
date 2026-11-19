// iot3 网关入向 XDP filter + probe（Go 用户态版本）。
//
// 数据面程序仍然是 C（gw_filter_probe.c），由 clang 编译成 .o；
// 这个进程只负责：加载/挂载 XDP、消费 ringbuf、与网关 ProbeBridge
// 走 Unix datagram JSON 协议、回写 eBPF 缓存 map。
//
// 必须在 iot3 命名空间内以 root 运行：
//
//	sudo ip netns exec iot3 ./gw-xdp-go --ifaces iot3-eth0,iot3-eth1,iot3-eth2
package main

import (
	"bytes"
	"encoding/binary"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"log"
	"net"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/cilium/ebpf"
	"github.com/cilium/ebpf/link"
	"github.com/cilium/ebpf/ringbuf"
	"golang.org/x/sys/unix"
)

var statNames = []string{
	"non_ip", "non_udp", "non_5005", "flow_cached",
	"flow_miss", "dropped", "ringbuf_full", "parse_error",
}

const (
	defaultProbeSock  = "/tmp/sdn_xdp_probe.sock"
	defaultClientSock = "/tmp/sdn_xdp_probe_cli.sock"
	defaultTTL        = 60
	previewLen        = 24
)

type flowKey struct {
	Saddr uint32
	Daddr uint32
	Sport uint16
	Dport uint16
	Proto uint8
	Pad   [3]uint8
}

type flowVal struct {
	ExpiresNS uint64
	Flags     uint32
	Pad       uint32
}

type missEvt struct {
	Key     flowKey
	TsNS    uint64
	Preview [previewLen]uint8
}

type inMsg struct {
	Op       string   `json:"op"`
	Key      []uint32 `json:"key"`
	Status   string   `json:"status"`
	TargetIP string   `json:"target_ip"`
	TTL      int      `json:"ttl"`
}

type outMsg struct {
	Op      string   `json:"op"`
	Key     []uint32 `json:"key,omitempty"`
	Preview string   `json:"preview,omitempty"`
}

type probeStats struct {
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

func (s *probeStats) inc(field *uint64) {
	s.mu.Lock()
	*field = *field + 1
	s.mu.Unlock()
}

func (s *probeStats) snapshot() map[string]uint64 {
	s.mu.Lock()
	defer s.mu.Unlock()
	return map[string]uint64{
		"events":            s.events,
		"resolves":          s.resolves,
		"ready":             s.ready,
		"pending":           s.pending,
		"rate_limited":      s.rateLimited,
		"resolve_errors":    s.resolveErrors,
		"flow_ready":        s.flowReady,
		"flow_delete":       s.flowDelete,
		"ebpf_writes":       s.ebpfWrites,
		"ebpf_write_errors": s.ebpfWriteErrors,
	}
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

type probe struct {
	flows      *ebpf.Map
	conn       *net.UnixConn
	gwPath     string
	clientPath string
	rate       *rateLimiter
	ttlDefault int
	stats      probeStats

	mu        sync.Mutex
	keyTarget map[flowKey]string
	pending   map[flowKey]string

	halt chan struct{}
	done chan struct{}
}

func newProbe(flows *ebpf.Map, gwPath, clientPath string, rate int, ttl int) (*probe, error) {
	_ = os.Remove(clientPath)
	addr := &net.UnixAddr{Name: clientPath, Net: "unixgram"}
	conn, err := net.ListenUnixgram("unixgram", addr)
	if err != nil {
		return nil, err
	}
	p := &probe{
		flows:      flows,
		conn:       conn,
		gwPath:     gwPath,
		clientPath: clientPath,
		rate:       newRateLimiter(rate),
		ttlDefault: ttl,
		keyTarget:  make(map[flowKey]string),
		pending:    make(map[flowKey]string),
		halt:       make(chan struct{}),
		done:       make(chan struct{}),
	}
	go p.recvLoop()
	return p, nil
}

func (p *probe) stop() {
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

func (p *probe) onMiss(evt missEvt) {
	p.stats.inc(&p.stats.events)
	log.Printf("[MISS] %s preview=%q", fmtKey(evt.Key), bytes.TrimRight(evt.Preview[:], "\x00"))
	if !p.rate.allow() {
		p.stats.inc(&p.stats.rateLimited)
		return
	}
	payload, _ := json.Marshal(outMsg{
		Op:      "resolve",
		Key:     keyList(evt.Key),
		Preview: fmt.Sprintf("%x", evt.Preview[:]),
	})
	if _, err := p.conn.WriteToUnix(payload, &net.UnixAddr{Name: p.gwPath, Net: "unixgram"}); err != nil {
		p.stats.inc(&p.stats.resolveErrors)
		log.Printf("[PROBE] resolve 发送失败: %v", err)
		return
	}
	p.stats.inc(&p.stats.resolves)
}

func (p *probe) recvLoop() {
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
		var msg inMsg
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

func (p *probe) onReply(msg inMsg) {
	if len(msg.Key) != 5 || msg.TargetIP == "" {
		return
	}
	key := keyFromList(msg.Key)
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
			fmtKey(key), msg.TargetIP, ttl)
	case "pending":
		p.mu.Lock()
		p.stats.mu.Lock()
		p.stats.pending++
		p.stats.mu.Unlock()
		p.keyTarget[key] = msg.TargetIP
		p.pending[key] = msg.TargetIP
		p.mu.Unlock()
		log.Printf("[PROBE] 网关本地缓存未命中 %s → %s，已上报，等 FlowMod",
			fmtKey(key), msg.TargetIP)
	}
}

func (p *probe) onFlowReady(msg inMsg) {
	if msg.TargetIP == "" {
		return
	}
	ttl := msg.TTL
	if ttl <= 0 {
		ttl = p.ttlDefault
	}
	p.mu.Lock()
	var keys []flowKey
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

func (p *probe) onFlowDelete(msg inMsg) {
	if msg.TargetIP == "" {
		return
	}
	p.mu.Lock()
	var keys []flowKey
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

func (p *probe) writeReady(key flowKey, ttl int) {
	val := flowVal{
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

func keyList(k flowKey) []uint32 {
	return []uint32{k.Saddr, k.Daddr, uint32(k.Sport), uint32(k.Dport), uint32(k.Proto)}
}

func keyFromList(v []uint32) flowKey {
	return flowKey{
		Saddr: v[0],
		Daddr: v[1],
		Sport: uint16(v[2]),
		Dport: uint16(v[3]),
		Proto: uint8(v[4]),
	}
}

func fmtKey(k flowKey) string {
	return fmt.Sprintf("%s:%d->%s:%d", ipString(k.Saddr), k.Sport,
		ipString(k.Daddr), k.Dport)
}

func ipString(v uint32) string {
	return fmt.Sprintf("%d.%d.%d.%d", byte(v), byte(v>>8), byte(v>>16), byte(v>>24))
}

func monotonicNS() uint64 {
	var ts unix.Timespec
	if err := unix.ClockGettime(unix.CLOCK_MONOTONIC, &ts); err != nil {
		return uint64(time.Now().UnixNano())
	}
	return uint64(ts.Sec)*1_000_000_000 + uint64(ts.Nsec)
}

func readStats(m *ebpf.Map) (map[string]uint64, error) {
	out := make(map[string]uint64, len(statNames))
	for i, name := range statNames {
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

func xdpLine(iface string) string {
	out, _ := exec.Command("ip", "-d", "link", "show", "dev", iface).Output()
	re := regexp.MustCompile(`xdpgeneric|xdpdrv|xdpoffload|prog/xdp`)
	for _, line := range strings.Split(string(out), "\n") {
		if re.MatchString(line) {
			return strings.TrimSpace(line)
		}
	}
	return ""
}

func detachIface(iface string) bool {
	_ = os.Remove("/sys/fs/bpf/sdn_xdp_" + iface)
	for _, mode := range []string{"xdpgeneric", "xdpdrv", "xdp"} {
		_ = exec.Command("ip", "link", "set", "dev", iface, mode, "off").Run()
	}
	return xdpLine(iface) == ""
}

func netnsID() string {
	target, err := os.Readlink("/proc/self/ns/net")
	if err != nil {
		return "unknown"
	}
	return target
}

// 这个是 Go 版本的默认 eBPF 对象路径：与可执行文件同目录。
func defaultObject() string {
	if exe, err := os.Executable(); err == nil {
		p := filepath.Join(filepath.Dir(exe), "gw_filter_probe.o")
		if _, err := os.Stat(p); err == nil {
			return p
		}
	}
	return "gw_filter_probe.o"
}

func main() {
	log.SetFlags(0)
	var (
		ifacesFlag = flag.String("ifaces", "iot3-eth0,iot3-eth1,iot3-eth2", "逗号分隔的挂载接口")
		modeFlag   = flag.String("mode", "auto", "XDP 模式：auto / skb / drv")
		interval   = flag.Float64("interval", 2.0, "打印计数间隔秒")
		duration   = flag.Float64("duration", 0, "运行多少秒后退出，0=一直运行")
		setCfg     = flag.String("set-cfg", "", "count 或 drop-non5005")
		noProbe    = flag.Bool("no-probe", false, "只消费 ringbuf 打日志，不连网关")
		probeSock  = flag.String("probe-sock", defaultProbeSock, "网关 ProbeBridge 的 Unix socket")
		clientSock = flag.String("probe-client-sock", defaultClientSock, "探针自身绑定的 Unix socket")
		probeRate  = flag.Int("probe-rate", 50, "全局探针速率上限（次/秒）")
		ttlFlag    = flag.Int("ttl", defaultTTL, "eBPF 缓存 READY 默认 TTL 秒")
		detachOnly = flag.Bool("detach-only", false, "只摘除已挂载的 XDP")
		keep       = flag.Bool("keep", false, "退出时保留 XDP（pin 住 link）")
		jsonOut    = flag.String("json-out", "", "退出时把最终计数写成 JSON")
		readyFile  = flag.String("ready-file", "", "挂载成功后创建该文件")
		objectFlag = flag.String("object", "", "eBPF .o 路径（默认与可执行文件同目录）")
	)
	flag.Parse()

	ifaces := splitIfaces(*ifacesFlag)
	if len(ifaces) == 0 {
		log.Fatal("没有接口")
	}
	mode := *modeFlag
	if mode != "auto" && mode != "skb" && mode != "drv" {
		log.Fatalf("未知 mode: %s", mode)
	}
	if *setCfg != "" && *setCfg != "count" && *setCfg != "drop-non5005" {
		log.Fatalf("未知 --set-cfg: %s", *setCfg)
	}
	if os.Geteuid() != 0 {
		log.Fatal("需要 root：加载 XDP 需要 CAP_BPF")
	}

	if *detachOnly {
		ok := true
		for _, iface := range ifaces {
			if !detachIface(iface) {
				log.Printf("摘除 %s 失败：接口上仍有 XDP", iface)
				ok = false
			}
		}
		if !ok {
			os.Exit(1)
		}
		return
	}

	objPath := *objectFlag
	if objPath == "" {
		objPath = defaultObject()
	}
	if _, err := os.Stat(objPath); err != nil {
		log.Fatalf("找不到 eBPF 对象文件 %s（先 make）", objPath)
	}
	// 这个是 Go 版本的默认 eBPF 对象路径：与可执行文件同目录。
	spec, err := ebpf.LoadCollectionSpec(objPath)
	if err != nil {
		log.Fatalf("加载 spec 失败: %v", err)
	}
	coll, err := ebpf.NewCollection(spec)
	if err != nil {
		log.Fatalf("加载 collection 失败: %v", err)
	}
	defer coll.Close()

	prog := coll.Programs["gw_filter"]
	flows := coll.Maps["flows"]
	misses := coll.Maps["misses"]
	cfgMap := coll.Maps["cfg"]
	statsMap := coll.Maps["stats"]
	if prog == nil || flows == nil || misses == nil || cfgMap == nil || statsMap == nil {
		log.Fatal("eBPF 对象缺少 gw_filter / flows / misses / cfg / stats")
	}

	if *setCfg != "" {
		var v uint32
		if *setCfg == "drop-non5005" {
			v = 1
		}
		if err := cfgMap.Update(uint32(0), v, ebpf.UpdateAny); err != nil {
			log.Fatalf("设置 cfg 失败: %v", err)
		}
	}

	var flags link.XDPAttachFlags
	switch mode {
	case "skb":
		flags = link.XDPGenericMode
	case "drv":
		flags = link.XDPDriverMode
	}

	links := make(map[string]link.Link)
	pinned := make(map[string]string)
	for _, iface := range ifaces {
		ifi, err := net.InterfaceByName(iface)
		if err != nil {
			log.Printf("接口不存在: %s", iface)
			continue
		}
		lnk, err := link.AttachXDP(link.XDPOptions{
			Program:   prog,
			Interface: ifi.Index,
			Flags:     flags,
		})
		if err != nil {
			log.Printf("挂载 %s 失败: %v", iface, err)
			continue
		}
		links[iface] = lnk
		log.Printf("已挂载 %s  %s", iface, xdpLine(iface))
		if *keep {
			pinPath := "/sys/fs/bpf/sdn_xdp_" + iface
			if err := lnk.Pin(pinPath); err != nil {
				log.Printf("pin %s 失败（退出时会自动摘除）: %v", iface, err)
			} else {
				pinned[iface] = pinPath
			}
		}
	}
	if len(links) == 0 {
		log.Fatal("没有成功挂载任何接口")
	}

	attached := make([]string, 0, len(links))
	for iface := range links {
		attached = append(attached, iface)
	}

	var p *probe
	if !*noProbe {
		p, err = newProbe(flows, *probeSock, *clientSock, *probeRate, *ttlFlag)
		if err != nil {
			log.Fatalf("启动 probe 失败: %v", err)
		}
		defer p.stop()
		log.Printf("probe 已启动：resolve → %s，本进程监听 %s，上限 %d/s",
			*probeSock, *clientSock, *probeRate)
	} else {
		log.Printf("probe 未启用（--no-probe）：ringbuf 事件只打日志")
	}

	rd, err := ringbuf.NewReader(misses)
	if err != nil {
		log.Fatalf("ringbuf reader 失败: %v", err)
	}
	defer rd.Close()

	go func() {
		for {
			rec, err := rd.Read()
			if err != nil {
				return
			}
			var evt missEvt
			if err := binary.Read(bytes.NewReader(rec.RawSample), binary.LittleEndian, &evt); err != nil {
				log.Printf("[MISS] 解析事件失败: %v", err)
				continue
			}
			if p != nil {
				p.onMiss(evt)
			} else {
				log.Printf("[MISS] %s preview=%q", fmtKey(evt.Key),
					bytes.TrimRight(evt.Preview[:], "\x00"))
			}
		}
	}()

	cfgLabel := "count-only"
	if *setCfg == "drop-non5005" {
		cfgLabel = "drop-non5005"
	}
	log.Printf("PID=%d netns=%s mode=%s cfg=%s", os.Getpid(), netnsID(), mode, cfgLabel)
	if *readyFile != "" {
		if err := os.WriteFile(*readyFile, nil, 0o644); err != nil {
			log.Printf("写 ready 文件失败: %v", err)
		}
	}

	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)

	intervalDur := time.Duration(*interval * float64(time.Second))
	if intervalDur < 200*time.Millisecond {
		intervalDur = 200 * time.Millisecond
	}
	ticker := time.NewTicker(intervalDur)
	defer ticker.Stop()

	var deadline <-chan time.Time
	if *duration > 0 {
		timer := time.NewTimer(time.Duration(*duration * float64(time.Second)))
		defer timer.Stop()
		deadline = timer.C
	}

	start := time.Now()
	totals, err := readStats(statsMap)
	if err != nil {
		log.Fatalf("读取 stats 失败: %v", err)
	}
	last := copyMap(totals)

loop:
	for {
		select {
		case <-ticker.C:
			cur, err := readStats(statsMap)
			if err != nil {
				log.Printf("读取 stats 失败: %v", err)
				continue
			}
			deltas := diffMap(cur, last)
			last = cur
			printRow(cur, deltas, time.Since(start), p)
			totals = cur
		case <-sigCh:
			break loop
		case <-deadline:
			break loop
		}
	}

	final, err := readStats(statsMap)
	if err == nil {
		totals = final
	}
	hitRate := 0.0
	if total := totals["flow_cached"] + totals["flow_miss"]; total > 0 {
		hitRate = float64(totals["flow_cached"]) / float64(total)
	}
	var probeSnap map[string]uint64
	if p != nil {
		probeSnap = p.stats.snapshot()
	} else {
		probeSnap = map[string]uint64{}
	}
	log.Printf("[SUMMARY] cached=%d miss=%d hit_rate=%.3f events=%d resolves=%d ready=%d pending=%d rate_limited=%d ebpf_writes=%d",
		totals["flow_cached"], totals["flow_miss"], hitRate,
		probeSnap["events"], probeSnap["resolves"], probeSnap["ready"],
		probeSnap["pending"], probeSnap["rate_limited"], probeSnap["ebpf_writes"])

	if *jsonOut != "" {
		xdpState := make(map[string]string, len(attached))
		for _, iface := range attached {
			xdpState[iface] = xdpLine(iface)
		}
		payload := map[string]any{
			"ts":        time.Now().Format("2006-01-02T15:04:05-0700"),
			"netns":     netnsID(),
			"ifaces":    attached,
			"mode":      mode,
			"cfg":       cfgLabel,
			"totals":    totals,
			"hit_rate":  hitRate,
			"probe":     probeSnap,
			"xdp_state": xdpState,
		}
		data, _ := json.MarshalIndent(payload, "", "  ")
		if err := os.WriteFile(*jsonOut, data, 0o644); err != nil {
			log.Printf("写 JSON 失败: %v", err)
		} else {
			log.Printf("计数已写入 %s", *jsonOut)
		}
	}

	if *keep {
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

func splitIfaces(s string) []string {
	var out []string
	for _, part := range strings.Split(s, ",") {
		part = strings.TrimSpace(part)
		if part != "" {
			out = append(out, part)
		}
	}
	return out
}

func copyMap(in map[string]uint64) map[string]uint64 {
	out := make(map[string]uint64, len(in))
	for k, v := range in {
		out[k] = v
	}
	return out
}

func diffMap(cur, last map[string]uint64) map[string]uint64 {
	out := make(map[string]uint64, len(cur))
	for k, v := range cur {
		out[k] = v - last[k]
	}
	return out
}

func printRow(totals, deltas map[string]uint64, elapsed time.Duration, p *probe) {
	parts := []string{
		fmt.Sprintf("5005 cached=%d (+%d)", totals["flow_cached"], deltas["flow_cached"]),
		fmt.Sprintf("miss=%d (+%d)", totals["flow_miss"], deltas["flow_miss"]),
	}
	for _, name := range statNames {
		if name == "flow_cached" || name == "flow_miss" {
			continue
		}
		if totals[name] != 0 || deltas[name] != 0 {
			parts = append(parts, fmt.Sprintf("%s=%d (+%d)", name, totals[name], deltas[name]))
		}
	}
	if p != nil {
		s := p.stats.snapshot()
		parts = append(parts, fmt.Sprintf("evt=%d resolve=%d ready=%d pending=%d rl=%d",
			s["events"], s["resolves"], s["ready"], s["pending"], s["rate_limited"]))
	}
	log.Printf("[%7.1fs] %s", elapsed.Seconds(), strings.Join(parts, "  "))
}
