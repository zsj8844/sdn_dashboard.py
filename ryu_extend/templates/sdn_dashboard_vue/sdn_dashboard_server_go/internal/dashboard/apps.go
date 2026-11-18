package dashboard

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"sort"
	"sync"
)

const (
	appNotDeployed = 0
	appDeploying   = 1
	appRunning     = 2
	appStopped     = 3
	appError       = 4
)

type edgeApp struct {
	AppID           string         `json:"app_id"`
	AppName         string         `json:"app_name"`
	AppType         int            `json:"app_type"`
	AppCode         string         `json:"app_code"`
	Version         string         `json:"version"`
	Description     string         `json:"description"`
	Requirements    map[string]any `json:"requirements"`
	CreatedAt       string         `json:"created_at"`
	Checksum        string         `json:"checksum"`
	Status          int            `json:"status"`
	DeployedDevices []string       `json:"deployed_devices"`
}

type appManager struct {
	mu      sync.Mutex
	apps    map[string]*edgeApp
	history []map[string]any
}

func newAppManager() *appManager {
	return &appManager{apps: map[string]*edgeApp{}, history: []map[string]any{}}
}

func (m *appManager) create(appID, appName string, appType int, appCode, version, description string) (*edgeApp, error) {
	if appType < 1 || appType > 4 {
		return nil, fmt.Errorf("无效的应用类型: %d", appType)
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	if _, exists := m.apps[appID]; exists {
		return nil, fmt.Errorf("应用ID %s 已存在", appID)
	}
	sum := sha256.Sum256([]byte(appCode))
	app := &edgeApp{
		AppID:           appID,
		AppName:         appName,
		AppType:         appType,
		AppCode:         appCode,
		Version:         defaultString(version, "1.0.0"),
		Description:     description,
		Requirements:    map[string]any{},
		CreatedAt:       nowISO(),
		Checksum:        hex.EncodeToString(sum[:]),
		Status:          appNotDeployed,
		DeployedDevices: []string{},
	}
	m.apps[appID] = app
	return app.clone(), nil
}

func (m *appManager) list() []*edgeApp {
	m.mu.Lock()
	defer m.mu.Unlock()
	out := make([]*edgeApp, 0, len(m.apps))
	for _, app := range m.apps {
		out = append(out, app.clone())
	}
	sort.Slice(out, func(i, j int) bool {
		return out[i].CreatedAt < out[j].CreatedAt
	})
	return out
}

func (m *appManager) get(appID string) *edgeApp {
	m.mu.Lock()
	defer m.mu.Unlock()
	app := m.apps[appID]
	if app == nil {
		return nil
	}
	return app.clone()
}

func (a *edgeApp) clone() *edgeApp {
	if a == nil {
		return nil
	}
	cp := *a
	cp.DeployedDevices = append([]string(nil), a.DeployedDevices...)
	if cp.DeployedDevices == nil {
		cp.DeployedDevices = []string{}
	}
	cp.Requirements = map[string]any{}
	for k, v := range a.Requirements {
		cp.Requirements[k] = v
	}
	return &cp
}

func (m *appManager) remove(appID string) bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	if _, ok := m.apps[appID]; !ok {
		return false
	}
	delete(m.apps, appID)
	return true
}

func (m *appManager) deploy(appID, deviceID string) (map[string]any, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	app, ok := m.apps[appID]
	if !ok {
		return nil, fmt.Errorf("应用 %s 不存在", appID)
	}
	record := map[string]any{
		"app_id": appID, "device_id": deviceID,
		"timestamp": nowISO(), "action": "deploy", "status": "success",
	}
	app.Status = appRunning
	if !contains(app.DeployedDevices, deviceID) {
		app.DeployedDevices = append(app.DeployedDevices, deviceID)
	}
	m.history = append(m.history, record)
	return record, nil
}

func (m *appManager) undeploy(appID, deviceID string) (map[string]any, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	app, ok := m.apps[appID]
	if !ok {
		return nil, fmt.Errorf("应用 %s 不存在", appID)
	}
	record := map[string]any{
		"app_id": appID, "device_id": deviceID,
		"timestamp": nowISO(), "action": "undeploy", "status": "success",
	}
	for i, id := range app.DeployedDevices {
		if id == deviceID {
			app.DeployedDevices = append(app.DeployedDevices[:i], app.DeployedDevices[i+1:]...)
			break
		}
	}
	if len(app.DeployedDevices) == 0 {
		app.Status = appStopped
	}
	m.history = append(m.history, record)
	return record, nil
}

func (m *appManager) historyFor(appID string) []map[string]any {
	m.mu.Lock()
	defer m.mu.Unlock()
	out := []map[string]any{}
	for _, h := range m.history {
		if h["app_id"] == appID {
			out = append(out, h)
		}
	}
	return out
}

func defaultString(v, def string) string {
	if v == "" {
		return def
	}
	return v
}
