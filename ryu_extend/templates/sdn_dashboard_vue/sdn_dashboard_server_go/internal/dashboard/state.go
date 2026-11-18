package dashboard

import (
	"context"
	"fmt"
	"log"
	"net"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"sync"
	"time"
)

type bleNode struct {
	ID      string `json:"id"`
	Type    string `json:"type"`
	Status  string `json:"status"`
	RSSI    int    `json:"rssi"`
	Battery int    `json:"battery"`
}

type switchStatus struct {
	Connected bool     `json:"connected"`
	LastSeen  *float64 `json:"last_seen"`
	DPID      *string  `json:"dpid"`
}

type state struct {
	mu sync.RWMutex

	gatewayLogs []string
	s1Logs      []string
	s2Logs      []string

	bleNodes     []bleNode
	connectivity map[string]string
	switches     map[string]*switchStatus

	topology     map[string]any
	portStats    map[string]any
	flowStats    map[string]any
	tableStats   map[string]any
	iotExtension map[string]any

	gatewayLogFile string
}

func newState() *state {
	nodes := []bleNode{
		{ID: "aa:bb:cc:dd:ee:01", Type: "温度传感器", Status: "离线", RSSI: -80, Battery: 85},
		{ID: "aa:bb:cc:dd:ee:02", Type: "湿度传感器", Status: "离线", RSSI: -75, Battery: 92},
		{ID: "aa:bb:cc:dd:ee:03", Type: "网关", Status: "离线", RSSI: -65, Battery: 100},
		{ID: "aa:bb:cc:dd:ee:04", Type: "光照传感器", Status: "离线", RSSI: -85, Battery: 78},
	}
	return &state{
		gatewayLogs:  []string{},
		s1Logs:       []string{},
		s2Logs:       []string{},
		bleNodes:     nodes,
		connectivity: map[string]string{},
		switches: map[string]*switchStatus{
			"s1": {Connected: false},
			"s2": {Connected: false},
		},
		topology:     map[string]any{"switches": []any{}, "links": []any{}, "hosts": []any{}, "timestamp": nil},
		portStats:    map[string]any{},
		flowStats:    map[string]any{},
		tableStats:   map[string]any{},
		iotExtension: nil,
	}
}

func (s *state) prependGateway(line string) {
	s.mu.Lock()
	s.gatewayLogs = prepend(s.gatewayLogs, line, 100)
	s.mu.Unlock()
}

func (s *state) prependS1(line string) {
	s.mu.Lock()
	s.s1Logs = prepend(s.s1Logs, line, 100)
	s.mu.Unlock()
}

func (s *state) prependS2(line string) {
	s.mu.Lock()
	s.s2Logs = prepend(s.s2Logs, line, 100)
	s.mu.Unlock()
}

func (s *state) snapshotGatewayLogs() []string {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return copyStrings(s.gatewayLogs)
}

func (s *state) snapshotS1Logs() []string {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return copyStrings(s.s1Logs)
}

func (s *state) snapshotS2Logs() []string {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return copyStrings(s.s2Logs)
}

func copyStrings(in []string) []string {
	out := make([]string, len(in))
	copy(out, in)
	return out
}

func (s *state) clearData() {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.gatewayLogs = []string{}
	s.s1Logs = []string{}
	s.s2Logs = []string{}
	s.iotExtension = nil
	for i := range s.bleNodes {
		s.bleNodes[i].Status = "离线"
		s.bleNodes[i].RSSI = -100
		s.bleNodes[i].Battery = 100
	}
	s.connectivity = map[string]string{}
}

func (s *state) listenBLE() {
	addr := &net.UDPAddr{IP: net.IPv4zero, Port: 5005}
	conn, err := net.ListenUDP("udp4", addr)
	if err != nil {
		log.Printf("BLE数据监听未启动：UDP 5005 已被占用（%v）。通常是 IoT 网关正在同一台机器上运行并监听该端口，此时面板不会直接接收 BLE 数据。", err)
		return
	}
	defer conn.Close()
	log.Printf("BLE数据监听已启动 (端口5005)")
	buf := make([]byte, 1024)
	for {
		n, _, err := conn.ReadFromUDP(buf)
		if err != nil {
			log.Printf("BLE数据解析警告: %v", err)
			continue
		}
		parts := strings.Split(strings.TrimSpace(string(buf[:n])), ",")
		if len(parts) != 3 {
			continue
		}
		stamp := time.Now().Format("2006-01-02 15:04:05")
		line := fmt.Sprintf("[%s] %s → %s：%s", stamp, parts[0], parts[1], parts[2])
		s.prependGateway(line)
		log.Printf("接收到BLE数据: %s", line)
	}
}

func (s *state) connectivityLoop() {
	for {
		s.updateConnectivity()
		time.Sleep(5 * time.Second)
	}
}

func (s *state) updateConnectivity() {
	s1Flows := getSwitchFlows("s1")
	s2Flows := getSwitchFlows("s2")
	now := float64(time.Now().UnixNano()) / 1e9
	connected := getSwitchesStatus()

	hasBLEFlow := false
	for _, flow := range s1Flows {
		if strings.Contains(flow, "priority=10") && strings.Contains(flow, "udp_dst=5005") {
			hasBLEFlow = true
			break
		}
	}
	hasGatewayLog := len(s.snapshotGatewayLogs()) > 0
	iotGatewayStatus := "❌ 未连通"
	if hasBLEFlow || hasGatewayLog {
		iotGatewayStatus = "✅ 已连通"
	}

	s.mu.Lock()
	for _, name := range []string{"s1", "s2"} {
		st := s.switches[name]
		if st == nil {
			st = &switchStatus{}
			s.switches[name] = st
		}
		isConnected := contains(connected, name)
		st.Connected = isConnected
		if isConnected {
			last := now
			st.LastSeen = &last
			if dpid := getSwitchDPID(name); dpid != "" {
				st.DPID = &dpid
			}
		}
	}
	s1Connected := s.switches["s1"].Connected && len(s1Flows) > 0
	s2Connected := s.switches["s2"].Connected && len(s2Flows) > 0
	controllerSwitchStatus := "❌ 未连通"
	if s1Connected || s2Connected {
		controllerSwitchStatus = "✅ 已连通"
	}
	s.connectivity["iot1 → 网关(iot3)"] = iotGatewayStatus
	s.connectivity["控制器 → 交换机"] = controllerSwitchStatus

	gatewayOnline := hasBLEFlow || hasGatewayLog
	for i := range s.bleNodes {
		node := &s.bleNodes[i]
		if node.ID == "aa:bb:cc:dd:ee:03" {
			node.Status = statusText(gatewayOnline)
		} else {
			recent := false
			for _, line := range s.gatewayLogs {
				if strings.Contains(line, node.ID) {
					recent = true
					break
				}
			}
			node.Status = statusText(recent)
		}
		if node.Status == "在线" {
			delta := int(time.Now().Unix())%3 - 1
			node.RSSI = clamp(node.RSSI+delta, -90, -50)
			if node.Battery < 100 {
				node.Battery++
			}
		} else {
			node.RSSI = clamp(node.RSSI-1, -100, 0)
			if node.Battery > 0 {
				node.Battery--
			}
		}
	}
	s.mu.Unlock()
}

func (s *state) getGatewayLogsFile() []string {
	data, err := os.ReadFile(s.gatewayLogFile)
	if err != nil {
		return s.snapshotGatewayLogs()
	}
	lines := strings.Split(string(data), "\n")
	out := make([]string, 0, 100)
	for i := len(lines) - 1; i >= 0 && len(out) < 100; i-- {
		line := strings.TrimSpace(lines[i])
		if line != "" {
			out = append(out, line)
		}
	}
	return out
}

func runOvs(timeout time.Duration, args ...string) (string, string, error) {
	if os.Geteuid() != 0 {
		args = append([]string{"sudo"}, args...)
	}
	return runCommand(timeout, args[0], args[1:]...)
}

func getSwitchFlows(switchName string) []string {
	stdout, _, err := runOvs(5*time.Second, "ovs-ofctl", "dump-flows", switchName, "-O", "OpenFlow13")
	if err != nil {
		return []string{}
	}
	out := []string{}
	for _, line := range strings.Split(stdout, "\n") {
		line = strings.TrimSpace(line)
		if line != "" {
			out = append(out, line)
		}
	}
	return out
}

func getSwitchesStatus() []string {
	stdout, _, err := runOvs(5*time.Second, "ovs-vsctl", "list-br")
	if err != nil {
		return []string{}
	}
	out := []string{}
	for _, bridge := range strings.Split(strings.TrimSpace(stdout), "\n") {
		bridge = strings.TrimSpace(bridge)
		if bridge == "s1" || bridge == "s2" {
			out = append(out, bridge)
		}
	}
	return out
}

func getSwitchDPID(switchName string) string {
	stdout, _, err := runOvs(5*time.Second, "ovs-ofctl", "show", switchName)
	if err != nil {
		return ""
	}
	for _, line := range strings.Split(stdout, "\n") {
		if idx := strings.Index(line, "dpid:"); idx >= 0 {
			rest := strings.TrimSpace(line[idx+len("dpid:"):])
			fields := strings.Fields(rest)
			if len(fields) > 0 {
				return fields[0]
			}
		}
	}
	return ""
}

func runCommand(timeout time.Duration, name string, args ...string) (string, string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, name, args...)
	var stdout, stderr strings.Builder
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	err := cmd.Run()
	return stdout.String(), stderr.String(), err
}

func prepend(list []string, value string, max int) []string {
	if max <= 0 {
		return list
	}
	if len(list) >= max {
		list = list[:max-1]
	}
	out := make([]string, 0, len(list)+1)
	out = append(out, value)
	out = append(out, list...)
	return out
}

func contains(list []string, v string) bool {
	for _, item := range list {
		if item == v {
			return true
		}
	}
	return false
}

func clamp(v, lo, hi int) int {
	if v < lo {
		return lo
	}
	if v > hi {
		return hi
	}
	return v
}

func statusText(online bool) string {
	if online {
		return "在线"
	}
	return "离线"
}

func atoiDefault(s string, def int) int {
	v, err := strconv.Atoi(s)
	if err != nil {
		return def
	}
	return v
}
