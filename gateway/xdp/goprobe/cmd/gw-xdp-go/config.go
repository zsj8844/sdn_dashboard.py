package main

import (
	"flag"
	"strings"
)

type config struct {
	ifaces     []string
	mode       string
	interval   float64
	duration   float64
	setCfg     string
	noProbe    bool
	probeSock  string
	clientSock string
	probeRate  int
	ttl        int
	detachOnly bool
	keep       bool
	jsonOut    string
	readyFile  string
	objPath    string
}

func parseConfig() config {
	ifacesFlag := flag.String("ifaces", "iot3-eth0,iot3-eth1,iot3-eth2", "逗号分隔的挂载接口")
	modeFlag := flag.String("mode", "auto", "XDP 模式：auto / skb / drv")
	interval := flag.Float64("interval", 2.0, "打印计数间隔秒")
	duration := flag.Float64("duration", 0, "运行多少秒后退出，0=一直运行")
	setCfg := flag.String("set-cfg", "", "count 或 drop-non5005")
	noProbe := flag.Bool("no-probe", false, "只消费 ringbuf 打日志，不连网关")
	probeSock := flag.String("probe-sock", "/tmp/sdn_xdp_probe.sock", "网关 ProbeBridge 的 Unix socket")
	clientSock := flag.String("probe-client-sock", "/tmp/sdn_xdp_probe_cli.sock", "探针自身绑定的 Unix socket")
	probeRate := flag.Int("probe-rate", 50, "全局探针速率上限（次/秒）")
	ttlFlag := flag.Int("ttl", 60, "eBPF 缓存 READY 默认 TTL 秒")
	detachOnly := flag.Bool("detach-only", false, "只摘除已挂载的 XDP")
	keep := flag.Bool("keep", false, "退出时保留 XDP（pin 住 link）")
	jsonOut := flag.String("json-out", "", "退出时把最终计数写成 JSON")
	readyFile := flag.String("ready-file", "", "挂载成功后创建该文件")
	objectFlag := flag.String("object", "", "eBPF .o 路径（默认与可执行文件同目录）")
	flag.Parse()

	return config{
		ifaces:     splitIfaces(*ifacesFlag),
		mode:       *modeFlag,
		interval:   *interval,
		duration:   *duration,
		setCfg:     *setCfg,
		noProbe:    *noProbe,
		probeSock:  *probeSock,
		clientSock: *clientSock,
		probeRate:  *probeRate,
		ttl:        *ttlFlag,
		detachOnly: *detachOnly,
		keep:       *keep,
		jsonOut:    *jsonOut,
		readyFile:  *readyFile,
		objPath:    *objectFlag,
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
