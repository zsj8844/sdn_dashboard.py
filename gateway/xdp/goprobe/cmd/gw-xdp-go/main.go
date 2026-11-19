// iot3 网关入向 XDP filter + probe（Go 用户态版本）。
//
// 数据面程序是 C（../../gw_filter_probe.c），由 clang 编译成 .o；
// 这个进程只负责：加载/挂载 XDP、消费 ringbuf、与网关 ProbeBridge
// 走 Unix datagram JSON 协议、回写 eBPF 缓存 map。
//
// 必须在 iot3 命名空间内以 root 运行：
//
//	sudo ip netns exec iot3 ./gw-xdp-go --ifaces iot3-eth0,iot3-eth1,iot3-eth2
package main

import (
	"log"
	"os"

	"github.com/cilium/ebpf"
	"github.com/cilium/ebpf/ringbuf"

	"sdn-iot/gateway/xdp/goprobe/internal/probe"
	"sdn-iot/gateway/xdp/goprobe/internal/xdp"
)

func main() {
	log.SetFlags(0)
	cfg := parseConfig()

	if len(cfg.ifaces) == 0 {
		log.Fatal("没有接口")
	}
	if cfg.mode != "auto" && cfg.mode != "skb" && cfg.mode != "drv" {
		log.Fatalf("未知 mode: %s", cfg.mode)
	}
	if cfg.setCfg != "" && cfg.setCfg != "count" && cfg.setCfg != "drop-non5005" {
		log.Fatalf("未知 --set-cfg: %s", cfg.setCfg)
	}
	if os.Geteuid() != 0 {
		log.Fatal("需要 root：加载 XDP 需要 CAP_BPF")
	}

	if cfg.detachOnly {
		if !xdp.DetachAll(cfg.ifaces) {
			os.Exit(1)
		}
		return
	}

	objPath := cfg.objPath
	if objPath == "" {
		objPath = xdp.DefaultObject()
	}
	if _, err := os.Stat(objPath); err != nil {
		log.Fatalf("找不到 eBPF 对象文件 %s（先 make）", objPath)
	}

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

	if cfg.setCfg != "" {
		var v uint32
		if cfg.setCfg == "drop-non5005" {
			v = 1
		}
		if err := cfgMap.Update(uint32(0), v, ebpf.UpdateAny); err != nil {
			log.Fatalf("设置 cfg 失败: %v", err)
		}
	}
	// 挂载 XDP 到接口
	links, pinned, attached := xdp.AttachAll(prog, cfg.ifaces, cfg.mode, cfg.keep)
	if len(links) == 0 {
		log.Fatal("没有成功挂载任何接口")
	}
	// 启动 probe 线程
	var p *probe.Probe
	if !cfg.noProbe {
		p, err = probe.New(flows, cfg.probeSock, cfg.clientSock, cfg.probeRate, cfg.ttl)
		if err != nil {
			log.Fatalf("启动 probe 失败: %v", err)
		}
		defer p.Stop()
		log.Printf("probe 已启动：resolve → %s，本进程监听 %s，上限 %d/s",
			cfg.probeSock, cfg.clientSock, cfg.probeRate)
	} else {
		log.Printf("probe 未启用（--no-probe）：ringbuf 事件只打日志")
	}
	// 启动 ringbuf 消费线程
	rd, err := ringbuf.NewReader(misses)
	if err != nil {
		log.Fatalf("ringbuf reader 失败: %v", err)
	}
	defer rd.Close()
	go consumeRingbuf(rd, p)

	cfgLabel := "count-only"
	if cfg.setCfg == "drop-non5005" {
		cfgLabel = "drop-non5005"
	}
	log.Printf("PID=%d netns=%s mode=%s cfg=%s", os.Getpid(), xdp.NetnsID(), cfg.mode, cfgLabel)
	if cfg.readyFile != "" {
		if err := os.WriteFile(cfg.readyFile, nil, 0o644); err != nil {
			log.Printf("写 ready 文件失败: %v", err)
		}
	}

	totals := runLoop(cfg, statsMap, p)
	writeSummary(cfg, totals, attached, links, pinned, p, cfgLabel)
}
