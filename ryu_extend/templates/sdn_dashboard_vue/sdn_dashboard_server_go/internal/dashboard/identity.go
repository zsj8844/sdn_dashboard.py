package dashboard

import (
	"encoding/json"
	"log"
	"os"
	"path/filepath"
	"sync"
	"time"
)

type identityManager struct {
	mu   sync.Mutex
	path string
	cfg  map[string]any
}

func newIdentityManager(path string) *identityManager {
	m := &identityManager{path: path}
	if data, err := os.ReadFile(path); err == nil {
		var cfg map[string]any
		if err := json.Unmarshal(data, &cfg); err == nil && cfg != nil {
			m.cfg = cfg
			log.Printf("已加载设备身份配置: %d 个设备", len(devicesMap(cfg)))
			return m
		}
		log.Printf("配置文件读取失败，使用默认配置")
	}
	m.cfg = buildDefaultConfig()
	m.save(m.cfg)
	log.Printf("已创建默认设备身份配置文件: %s", path)
	return m
}

func (m *identityManager) get() map[string]any {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.cfg == nil {
		return map[string]any{"version": "1.0", "updated_at": "", "devices": map[string]any{}}
	}
	return deepCopyMap(m.cfg)
}

func (m *identityManager) save(cfg map[string]any) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.saveLocked(cfg)
}

func (m *identityManager) saveLocked(cfg map[string]any) {
	if cfg == nil {
		cfg = map[string]any{}
	}
	cfg["updated_at"] = nowISO()
	if _, ok := cfg["version"]; !ok {
		cfg["version"] = "1.0"
	}
	if _, ok := cfg["devices"]; !ok {
		cfg["devices"] = map[string]any{}
	}
	if err := os.MkdirAll(filepath.Dir(m.path), 0o755); err != nil {
		log.Printf("创建配置目录失败: %v", err)
		return
	}
	data, err := json.MarshalIndent(cfg, "", "  ")
	if err != nil {
		log.Printf("序列化配置失败: %v", err)
		return
	}
	if err := os.WriteFile(m.path, data, 0o644); err != nil {
		log.Printf("配置文件写入失败: %v", err)
		return
	}
	m.cfg = deepCopyMap(cfg)
}

func devicesMap(cfg map[string]any) map[string]any {
	if cfg == nil {
		return map[string]any{}
	}
	if d, ok := cfg["devices"].(map[string]any); ok {
		return d
	}
	return map[string]any{}
}

func deepCopyMap(m map[string]any) map[string]any {
	if m == nil {
		return nil
	}
	data, err := json.Marshal(m)
	if err != nil {
		return nil
	}
	var out map[string]any
	if err := json.Unmarshal(data, &out); err != nil {
		return nil
	}
	return out
}

func nowISO() string {
	return time.Now().Format("2006-01-02T15:04:05.000000")
}

func buildDefaultConfig() map[string]any {
	devices := map[string]any{
		"192.168.2.10": map[string]any{
			"device_id": "iot1", "device_name": "温度传感器",
			"device_type": "temperature_sensor", "role": "iot",
			"description": "BLE温度传感器节点（iot3子网）",
		},
		"192.168.3.11": map[string]any{
			"device_id": "iot2", "device_name": "湿度传感器",
			"device_type": "humidity_sensor", "role": "iot",
			"description": "BLE湿度传感器节点（iot3子网）",
		},
		"192.168.1.12": map[string]any{
			"device_id": "iot3", "device_name": "IoT网关",
			"device_type": "gateway", "role": "gateway",
			"description": "BLE/IoT协议网关",
		},
		"192.168.4.13": map[string]any{
			"device_id": "iot4", "device_name": "位置传感器",
			"device_type": "position_sensor", "role": "iot",
			"description": "BLE位置传感器节点（iot3子网）",
		},
		"192.168.1.20": map[string]any{
			"device_id": "h1", "device_name": "传统终端1",
			"device_type": "host", "role": "host",
			"description": "传统IP终端",
		},
		"192.168.1.21": map[string]any{
			"device_id": "h2", "device_name": "传统终端2",
			"device_type": "host", "role": "host",
			"description": "传统IP终端",
		},
	}
	return map[string]any{"version": "1.0", "updated_at": "", "devices": devices}
}
