package dashboard

import (
	"fmt"
	"sort"
	"sync"
)

type deviceCapabilities struct {
	CPUCores          int  `json:"cpu_cores"`
	MemoryMB          int  `json:"memory_mb"`
	StorageMB         int  `json:"storage_mb"`
	NetworkPorts      int  `json:"network_ports"`
	SupportsNAT       bool `json:"supports_nat"`
	SupportsContainer bool `json:"supports_container"`
	SupportsBLE       bool `json:"supports_ble"`
}

type dashDevice struct {
	DeviceID       string
	DeviceName     string
	CurrentMode    int
	Capabilities   deviceCapabilities
	RegisteredAt   string
	LastModeSwitch *string
	SwitchCount    int
}

type deviceManager struct {
	mu      sync.Mutex
	devices map[string]*dashDevice
	history []map[string]any
}

func newDeviceManager() *deviceManager {
	return &deviceManager{devices: map[string]*dashDevice{}, history: []map[string]any{}}
}

func (m *deviceManager) register(id, name string, mode int, caps deviceCapabilities) (*dashDevice, error) {
	if mode < 1 || mode > 3 {
		return nil, fmt.Errorf("无效的初始模式: %d", mode)
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	if _, exists := m.devices[id]; exists {
		return nil, fmt.Errorf("设备 %s 已注册", id)
	}
	dev := &dashDevice{
		DeviceID: id, DeviceName: name, CurrentMode: mode,
		Capabilities: caps, RegisteredAt: nowISO(), SwitchCount: 0,
	}
	m.devices[id] = dev
	return dev.clone(), nil
}

func (m *deviceManager) list() []*dashDevice {
	m.mu.Lock()
	defer m.mu.Unlock()
	out := make([]*dashDevice, 0, len(m.devices))
	for _, d := range m.devices {
		out = append(out, d.clone())
	}
	sort.Slice(out, func(i, j int) bool {
		return out[i].RegisteredAt < out[j].RegisteredAt
	})
	return out
}

func (m *deviceManager) get(id string) *dashDevice {
	m.mu.Lock()
	defer m.mu.Unlock()
	dev := m.devices[id]
	if dev == nil {
		return nil
	}
	return dev.clone()
}

func (d *dashDevice) clone() *dashDevice {
	if d == nil {
		return nil
	}
	cp := *d
	if d.LastModeSwitch != nil {
		last := *d.LastModeSwitch
		cp.LastModeSwitch = &last
	}
	return &cp
}

func (m *deviceManager) remove(id string) bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	if _, ok := m.devices[id]; !ok {
		return false
	}
	delete(m.devices, id)
	return true
}

func (m *deviceManager) canSwitch(dev *dashDevice, target int) bool {
	if dev == nil || target < 1 || target > 3 || dev.CurrentMode == target {
		return false
	}
	if target == 2 && (dev.Capabilities.CPUCores < 2 || dev.Capabilities.MemoryMB < 1024) {
		return false
	}
	if target == 3 && (!dev.Capabilities.SupportsNAT || !dev.Capabilities.SupportsBLE) {
		return false
	}
	return true
}

func (m *deviceManager) switchMode(id string, target int, force bool) (map[string]any, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	dev, ok := m.devices[id]
	if !ok {
		return nil, fmt.Errorf("设备 %s 未注册", id)
	}
	if !force && !m.canSwitch(dev, target) {
		return nil, fmt.Errorf("设备 %s 无法切换到 %s", id, modeName(target))
	}
	oldMode := dev.CurrentMode
	requiresReboot := oldMode == 3 || target == 3
	record := map[string]any{
		"device_id":       id,
		"old_mode":        modeName(oldMode),
		"new_mode":        modeName(target),
		"timestamp":       nowISO(),
		"status":          "success",
		"requires_reboot": requiresReboot,
	}
	dev.CurrentMode = target
	last := nowISO()
	dev.LastModeSwitch = &last
	dev.SwitchCount++
	m.history = append(m.history, record)
	return record, nil
}

func (m *deviceManager) identify(id string, traffic, resource map[string]any) (int, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	dev, ok := m.devices[id]
	if !ok {
		return 0, fmt.Errorf("设备 %s 未注册", id)
	}
	mode := dev.CurrentMode
	if resource != nil {
		cpu := floatFromAny(resource["cpu_usage"])
		if cpu > 70 && dev.Capabilities.CPUCores >= 2 && dev.CurrentMode == 1 {
			mode = 2
		}
	}
	if traffic != nil {
		ratio := floatFromAny(traffic["iot_traffic_ratio"])
		if ratio > 50 && dev.Capabilities.SupportsNAT && dev.Capabilities.SupportsBLE {
			mode = 3
		}
	}
	return mode, nil
}

func (m *deviceManager) availableModes(id string) []int {
	m.mu.Lock()
	defer m.mu.Unlock()
	dev, ok := m.devices[id]
	if !ok {
		return []int{}
	}
	out := []int{}
	for target := 1; target <= 3; target++ {
		if m.canSwitch(dev, target) {
			out = append(out, target)
		}
	}
	return out
}

func (m *deviceManager) historyFor(id string) []map[string]any {
	m.mu.Lock()
	defer m.mu.Unlock()
	out := []map[string]any{}
	for _, h := range m.history {
		if h["device_id"] == id {
			out = append(out, h)
		}
	}
	return out
}

func modeName(mode int) string {
	switch mode {
	case 2:
		return "COMPUTE_HYBRID"
	case 3:
		return "IOT_GATEWAY"
	default:
		return "PURE_FORWARDING"
	}
}

func deviceToDict(d *dashDevice) map[string]any {
	if d == nil {
		return nil
	}
	return map[string]any{
		"device_id":         d.DeviceID,
		"device_name":       d.DeviceName,
		"current_mode":      d.CurrentMode,
		"current_mode_name": modeName(d.CurrentMode),
		"capabilities":      d.Capabilities,
		"registered_at":     d.RegisteredAt,
		"last_mode_switch":  d.LastModeSwitch,
		"switch_count":      d.SwitchCount,
	}
}

func floatFromAny(v any) float64 {
	switch n := v.(type) {
	case float64:
		return n
	case float32:
		return float64(n)
	case int:
		return float64(n)
	case int64:
		return float64(n)
	default:
		return 0
	}
}
