// Package xdp 负责 XDP 的挂载/摘除和接口状态查询。
package xdp

import (
	"log"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/cilium/ebpf"
	"github.com/cilium/ebpf/link"
)

// AttachAll 把同一个 XDP 程序挂到一组接口上，返回成功挂载的 link、
// pin 路径（keep）以及接口名列表。
func AttachAll(prog *ebpf.Program, ifaces []string, mode string, keep bool) (map[string]link.Link, map[string]string, []string) {
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
		log.Printf("已挂载 %s  %s", iface, XDPLine(iface))
		if keep {
			pinPath := "/sys/fs/bpf/sdn_xdp_" + iface
			if err := lnk.Pin(pinPath); err != nil {
				log.Printf("pin %s 失败（退出时会自动摘除）: %v", iface, err)
			} else {
				pinned[iface] = pinPath
			}
		}
	}

	attached := make([]string, 0, len(links))
	for iface := range links {
		attached = append(attached, iface)
	}
	return links, pinned, attached
}

func DetachAll(ifaces []string) bool {
	ok := true
	for _, iface := range ifaces {
		if !DetachIface(iface) {
			log.Printf("摘除 %s 失败：接口上仍有 XDP", iface)
			ok = false
		}
	}
	return ok
}

func XDPLine(iface string) string {
	out, _ := exec.Command("ip", "-d", "link", "show", "dev", iface).Output()
	re := regexp.MustCompile(`xdpgeneric|xdpdrv|xdpoffload|prog/xdp`)
	for _, line := range strings.Split(string(out), "\n") {
		if re.MatchString(line) {
			return strings.TrimSpace(line)
		}
	}
	return ""
}

func DetachIface(iface string) bool {
	_ = os.Remove("/sys/fs/bpf/sdn_xdp_" + iface)
	for _, mode := range []string{"xdpgeneric", "xdpdrv", "xdp"} {
		_ = exec.Command("ip", "link", "set", "dev", iface, mode, "off").Run()
	}
	return XDPLine(iface) == ""
}

func NetnsID() string {
	target, err := os.Readlink("/proc/self/ns/net")
	if err != nil {
		return "unknown"
	}
	return target
}

// DefaultObject 是 Go 版本的默认 eBPF 对象路径：与可执行文件同目录。
func DefaultObject() string {
	if exe, err := os.Executable(); err == nil {
		p := filepath.Join(filepath.Dir(exe), "gw_filter_probe.o")
		if _, err := os.Stat(p); err == nil {
			return p
		}
	}
	return "gw_filter_probe.o"
}
