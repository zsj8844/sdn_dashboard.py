package dashboard

import (
	"fmt"
	"log"
	"net/http"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
)

type dashboard struct {
	state    *state
	identity *identityManager
	apps     *appManager
	devices  *deviceManager
	paths    paths
}

func registerRoutes(r *gin.Engine, d *dashboard) {
	r.GET("/health", d.health)

	r.POST("/api/logs", d.receiveLogs)
	r.POST("/api/logs/s1", d.receiveS1Logs)
	r.POST("/api/logs/s2", d.receiveS2Logs)

	r.GET("/api/data", d.apiData)
	r.GET("/api/iot-extension", d.getIoTExtension)
	r.POST("/api/iot-extension", d.postIoTExtension)
	r.POST("/api/clear-data", d.clearData)

	r.GET("/api/topology", d.getTopology)
	r.POST("/api/topology", d.postTopology)

	r.GET("/api/stats", d.getStats)
	r.POST("/api/stats", d.postStats)

	r.GET("/api/flows", d.getFlows)
	r.POST("/api/flows", d.postFlow)
	r.DELETE("/api/flows", d.deleteFlows)

	r.GET("/api/apps", d.listApps)
	r.POST("/api/apps", d.createApp)
	r.GET("/api/apps/:app_id", d.getApp)
	r.DELETE("/api/apps/:app_id", d.deleteApp)
	r.POST("/api/apps/:app_id/deploy", d.deployApp)
	r.POST("/api/apps/:app_id/undeploy", d.undeployApp)
	r.GET("/api/apps/:app_id/history", d.appHistory)

	r.GET("/api/devices", d.listDevices)
	r.POST("/api/devices", d.registerDevice)
	r.GET("/api/devices/:device_id", d.getDevice)
	r.DELETE("/api/devices/:device_id", d.deleteDevice)
	r.POST("/api/devices/:device_id/switch-mode", d.switchDeviceMode)
	r.POST("/api/devices/:device_id/identify", d.identifyDeviceMode)
	r.GET("/api/devices/:device_id/history", d.deviceHistory)

	r.GET("/api/device-identity/config", d.getIdentityConfig)
	r.PUT("/api/device-identity/config", d.putIdentityConfig)
	r.POST("/api/device-identity/device", d.addIdentityDevice)
	r.PUT("/api/device-identity/device/:ip", d.updateIdentityDevice)
	r.DELETE("/api/device-identity/device/:ip", d.deleteIdentityDevice)
	r.POST("/api/device-identity/reload", d.reloadIdentity)
}

func (d *dashboard) health(c *gin.Context) {
	d.state.mu.RLock()
	gatewayCount := len(d.state.gatewayLogs)
	s1Count := len(d.state.s1Logs)
	s2Count := len(d.state.s2Logs)
	online := 0
	for _, n := range d.state.bleNodes {
		if n.Status == "在线" {
			online++
		}
	}
	d.state.mu.RUnlock()
	c.JSON(http.StatusOK, gin.H{
		"status":             "healthy",
		"timestamp":          time.Now().Format("2006-01-02 15:04:05"),
		"gateway_logs_count": gatewayCount,
		"s1_logs_count":      s1Count,
		"s2_logs_count":      s2Count,
		"nodes_online":       online,
	})
}

func (d *dashboard) receiveLogs(c *gin.Context) {
	var body map[string]any
	if err := c.ShouldBindJSON(&body); err != nil {
		badRequest(c, "请求体不是 JSON")
		return
	}
	for _, field := range []string{"ble_addr", "type", "value", "src_ip"} {
		if _, ok := body[field]; !ok {
			badRequest(c, "缺少必要字段")
			return
		}
	}
	stamp := time.Now().Format("2006-01-02 15:04:05")
	line := fmt.Sprintf("[%s] %v → %v：%v (来源：%v)", stamp,
		body["ble_addr"], body["type"], body["value"], body["src_ip"])
	d.state.prependGateway(line)
	log.Printf("接收网关日志: %s", line)
	c.JSON(http.StatusOK, gin.H{"status": "success"})
}

func (d *dashboard) receiveS1Logs(c *gin.Context) {
	d.receiveSwitchLog(c, "s1", "S1 数据包")
}

func (d *dashboard) receiveS2Logs(c *gin.Context) {
	d.receiveSwitchLog(c, "s2", "S2 数据包")
}

func (d *dashboard) receiveSwitchLog(c *gin.Context, sw, def string) {
	var body map[string]any
	if err := c.ShouldBindJSON(&body); err != nil {
		badRequest(c, "请求体不是 JSON")
		return
	}
	msg := def
	if v, ok := body["message"].(string); ok {
		msg = v
	}
	stamp := time.Now().Format("2006-01-02 15:04:05")
	line := fmt.Sprintf("[%s] %s", stamp, msg)
	if sw == "s1" {
		d.state.prependS1(line)
	} else {
		d.state.prependS2(line)
	}
	log.Printf("接收%s日志: %s", strings.ToUpper(sw), line)
	c.JSON(http.StatusOK, gin.H{"status": "success"})
}

func (d *dashboard) apiData(c *gin.Context) {
	d.state.mu.RLock()
	nodes := append([]bleNode(nil), d.state.bleNodes...)
	switches := make(map[string]switchStatus, len(d.state.switches))
	for k, v := range d.state.switches {
		switches[k] = *v
	}
	iot := deepCopyMap(d.state.iotExtension)
	d.state.mu.RUnlock()

	s1Flows := getSwitchFlows("s1")
	s2Flows := getSwitchFlows("s2")
	if len(s1Flows) > 10 {
		s1Flows = s1Flows[:10]
	}
	if len(s2Flows) > 10 {
		s2Flows = s2Flows[:10]
	}

	c.JSON(http.StatusOK, gin.H{
		"ble_mesh":        gin.H{"nodes": nodes},
		"gateway_logs":    d.state.getGatewayLogsFile(),
		"s1_logs":         d.state.snapshotS1Logs(),
		"s2_logs":         d.state.snapshotS2Logs(),
		"s1_flows":        s1Flows,
		"s2_flows":        s2Flows,
		"switches_status": switches,
		"iot_extension":   iot,
	})
}

func (d *dashboard) getIoTExtension(c *gin.Context) {
	d.state.mu.RLock()
	iot := deepCopyMap(d.state.iotExtension)
	d.state.mu.RUnlock()
	if iot == nil {
		c.JSON(http.StatusOK, gin.H{})
		return
	}
	c.JSON(http.StatusOK, iot)
}

func (d *dashboard) postIoTExtension(c *gin.Context) {
	var body map[string]any
	if err := c.ShouldBindJSON(&body); err != nil {
		badRequest(c, "请求体不是 JSON")
		return
	}
	body["timestamp"] = float64(time.Now().UnixNano()) / 1e9
	d.state.mu.Lock()
	d.state.iotExtension = deepCopyMap(body)
	d.state.mu.Unlock()
	log.Printf("接收IoT扩展字段: %v", body)
	c.JSON(http.StatusOK, gin.H{"status": "success"})
}

func (d *dashboard) clearData(c *gin.Context) {
	d.state.clearData()
	log.Printf("数据已清空")
	c.JSON(http.StatusOK, gin.H{"status": "success", "message": "数据清空完成"})
}

func (d *dashboard) getTopology(c *gin.Context) {
	d.state.mu.RLock()
	topology := deepCopyMap(d.state.topology)
	d.state.mu.RUnlock()
	c.JSON(http.StatusOK, topology)
}

func (d *dashboard) postTopology(c *gin.Context) {
	var body map[string]any
	if err := c.ShouldBindJSON(&body); err != nil {
		badRequest(c, "请求体不是 JSON")
		return
	}
	d.state.mu.Lock()
	d.state.topology = deepCopyMap(body)
	d.state.mu.Unlock()
	log.Printf("接收拓扑数据: %d 交换机, %d 链接, %d 主机",
		lenAny(body["switches"]), lenAny(body["links"]), lenAny(body["hosts"]))
	c.JSON(http.StatusOK, gin.H{"status": "success"})
}

func (d *dashboard) getStats(c *gin.Context) {
	d.state.mu.RLock()
	port := deepCopyMap(d.state.portStats)
	flow := deepCopyMap(d.state.flowStats)
	table := deepCopyMap(d.state.tableStats)
	d.state.mu.RUnlock()
	if port == nil {
		port = map[string]any{}
	}
	if flow == nil {
		flow = map[string]any{}
	}
	if table == nil {
		table = map[string]any{}
	}
	c.JSON(http.StatusOK, gin.H{
		"port_stats":  port,
		"flow_stats":  flow,
		"table_stats": table,
	})
}

func (d *dashboard) postStats(c *gin.Context) {
	var body map[string]any
	if err := c.ShouldBindJSON(&body); err != nil {
		badRequest(c, "请求体不是 JSON")
		return
	}
	statsType, _ := body["type"].(string)
	dpid := "null"
	if v, ok := body["dpid"]; ok && v != nil {
		dpid = fmt.Sprint(v)
	}
	data := body["data"]
	d.state.mu.Lock()
	switch statsType {
	case "port_stats":
		d.state.portStats[dpid] = data
	case "flow_stats":
		d.state.flowStats[dpid] = data
	case "table_stats":
		d.state.tableStats[dpid] = data
	}
	d.state.mu.Unlock()
	log.Printf("接收%s数据: dpid=%s", statsType, dpid)
	c.JSON(http.StatusOK, gin.H{"status": "success"})
}

func (d *dashboard) getFlows(c *gin.Context) {
	dpid := c.Query("dpid")
	if dpid != "" {
		c.JSON(http.StatusOK, gin.H{
			"flows": getSwitchFlows("s" + dpid),
			"dpid":  dpid,
		})
		return
	}
	c.JSON(http.StatusOK, gin.H{
		"s1_flows": getSwitchFlows("s1"),
		"s2_flows": getSwitchFlows("s2"),
	})
}

func (d *dashboard) postFlow(c *gin.Context) {
	var body map[string]any
	if err := c.ShouldBindJSON(&body); err != nil {
		badRequest(c, "请求体不是 JSON")
		return
	}
	dpid := intFromAny(body["dpid"])
	switchName := fmt.Sprintf("s%d", dpid)
	if switchName != "s1" && switchName != "s2" {
		badRequest(c, "无效的交换机ID")
		return
	}
	priority := 10
	if v, ok := body["priority"]; ok {
		priority = intFromAny(v)
	}
	tableID := 0
	if v, ok := body["table_id"]; ok {
		tableID = intFromAny(v)
	}
	match, _ := body["match"].(string)
	actions := "output:2"
	if v, ok := body["actions"].(string); ok {
		actions = v
	}
	match = convertMatchKeywords(match)
	flow := fmt.Sprintf("table=%d,priority=%d,%s,actions=%s", tableID, priority, match, actions)
	_, stderr, err := runOvs(5*time.Second, "ovs-ofctl", "add-flow", switchName, "-O", "OpenFlow13", flow)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"status": "error", "message": stderr})
		return
	}
	log.Printf("添加流表成功: %s - table=%d, priority=%d", switchName, tableID, priority)
	c.JSON(http.StatusOK, gin.H{"status": "success", "message": "流表添加成功"})
}

func (d *dashboard) deleteFlows(c *gin.Context) {
	var body map[string]any
	if err := c.ShouldBindJSON(&body); err != nil {
		badRequest(c, "请求体不是 JSON")
		return
	}
	dpid := intFromAny(body["dpid"])
	switchName := fmt.Sprintf("s%d", dpid)
	if switchName != "s1" && switchName != "s2" {
		badRequest(c, "无效的交换机ID")
		return
	}
	args := []string{"ovs-ofctl", "del-flows", switchName, "-O", "OpenFlow13"}
	if v, ok := body["table_id"]; ok && v != nil {
		args = append(args, fmt.Sprintf("table=%d", intFromAny(v)))
	}
	_, stderr, err := runOvs(5*time.Second, args...)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"status": "error", "message": stderr})
		return
	}
	log.Printf("清空流表成功: %s", switchName)
	c.JSON(http.StatusOK, gin.H{"status": "success", "message": "流表清空成功"})
}

// ============ 边缘应用 ============

func (d *dashboard) listApps(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"apps": d.apps.list()})
}

func (d *dashboard) createApp(c *gin.Context) {
	var body map[string]any
	if err := c.ShouldBindJSON(&body); err != nil {
		badRequest(c, "请求体不是 JSON")
		return
	}
	appID := stringFromAny(body["app_id"])
	appName := stringFromAny(body["app_name"])
	appType := intFromAny(body["app_type"])
	appCode := stringFromAny(body["app_code"])
	version := stringFromAny(body["version"])
	description := stringFromAny(body["description"])
	app, err := d.apps.create(appID, appName, appType, appCode, version, description)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"status": "error", "message": err.Error()})
		return
	}
	log.Printf("创建应用成功: %s - %s", appID, appName)
	c.JSON(http.StatusOK, gin.H{"status": "success", "app": app})
}

func (d *dashboard) getApp(c *gin.Context) {
	app := d.apps.get(c.Param("app_id"))
	if app == nil {
		c.JSON(http.StatusNotFound, gin.H{"status": "error", "message": "应用不存在"})
		return
	}
	c.JSON(http.StatusOK, app)
}

func (d *dashboard) deleteApp(c *gin.Context) {
	id := c.Param("app_id")
	if !d.apps.remove(id) {
		c.JSON(http.StatusNotFound, gin.H{"status": "error", "message": fmt.Sprintf("应用 %s 不存在", id)})
		return
	}
	log.Printf("删除应用成功: %s", id)
	c.JSON(http.StatusOK, gin.H{"status": "success", "message": "应用已删除"})
}

func (d *dashboard) deployApp(c *gin.Context) {
	d.changeAppDeployment(c, true)
}

func (d *dashboard) undeployApp(c *gin.Context) {
	d.changeAppDeployment(c, false)
}

func (d *dashboard) changeAppDeployment(c *gin.Context, deploy bool) {
	var body map[string]any
	if err := c.ShouldBindJSON(&body); err != nil {
		badRequest(c, "请求体不是 JSON")
		return
	}
	deviceID := stringFromAny(body["device_id"])
	if deviceID == "" {
		badRequest(c, "缺少设备ID")
		return
	}
	id := c.Param("app_id")
	var (
		record map[string]any
		err    error
	)
	if deploy {
		record, err = d.apps.deploy(id, deviceID)
	} else {
		record, err = d.apps.undeploy(id, deviceID)
	}
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"status": "error", "message": err.Error()})
		return
	}
	action := "部署"
	if !deploy {
		action = "卸载"
	}
	log.Printf("%s应用成功: %s -> %s", action, id, deviceID)
	c.JSON(http.StatusOK, gin.H{"status": "success", "record": record})
}

func (d *dashboard) appHistory(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"history": d.apps.historyFor(c.Param("app_id"))})
}

// ============ 设备角色 ============

func (d *dashboard) listDevices(c *gin.Context) {
	list := d.devices.list()
	out := make([]map[string]any, 0, len(list))
	for _, dev := range list {
		out = append(out, deviceToDict(dev))
	}
	c.JSON(http.StatusOK, gin.H{"devices": out})
}

func (d *dashboard) registerDevice(c *gin.Context) {
	var body map[string]any
	if err := c.ShouldBindJSON(&body); err != nil {
		badRequest(c, "请求体不是 JSON")
		return
	}
	id := stringFromAny(body["device_id"])
	name := stringFromAny(body["device_name"])
	mode := 1
	if v, ok := body["initial_mode"]; ok {
		mode = intFromAny(v)
	}
	caps := deviceCapabilities{
		CPUCores: 1, MemoryMB: 512, StorageMB: 1024, NetworkPorts: 2,
	}
	if raw, ok := body["capabilities"].(map[string]any); ok {
		if v, ok := raw["cpu_cores"]; ok {
			caps.CPUCores = intFromAny(v)
		}
		if v, ok := raw["memory_mb"]; ok {
			caps.MemoryMB = intFromAny(v)
		}
		if v, ok := raw["storage_mb"]; ok {
			caps.StorageMB = intFromAny(v)
		}
		if v, ok := raw["network_ports"]; ok {
			caps.NetworkPorts = intFromAny(v)
		}
		if v, ok := raw["supports_nat"]; ok {
			caps.SupportsNAT = boolFromAny(v)
		}
		if v, ok := raw["supports_container"]; ok {
			caps.SupportsContainer = boolFromAny(v)
		}
		if v, ok := raw["supports_ble"]; ok {
			caps.SupportsBLE = boolFromAny(v)
		}
	}
	dev, err := d.devices.register(id, name, mode, caps)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"status": "error", "message": err.Error()})
		return
	}
	log.Printf("注册设备成功: %s - %s", id, name)
	c.JSON(http.StatusOK, gin.H{"status": "success", "device": deviceToDict(dev)})
}

func (d *dashboard) getDevice(c *gin.Context) {
	dev := d.devices.get(c.Param("device_id"))
	if dev == nil {
		c.JSON(http.StatusNotFound, gin.H{"status": "error", "message": "设备不存在"})
		return
	}
	c.JSON(http.StatusOK, deviceToDict(dev))
}

func (d *dashboard) deleteDevice(c *gin.Context) {
	id := c.Param("device_id")
	if !d.devices.remove(id) {
		c.JSON(http.StatusNotFound, gin.H{"status": "error", "message": fmt.Sprintf("设备 %s 不存在", id)})
		return
	}
	log.Printf("删除设备成功: %s", id)
	c.JSON(http.StatusOK, gin.H{"status": "success", "message": "设备已删除"})
}

func (d *dashboard) switchDeviceMode(c *gin.Context) {
	var body map[string]any
	if err := c.ShouldBindJSON(&body); err != nil {
		badRequest(c, "请求体不是 JSON")
		return
	}
	target := intFromAny(body["target_mode"])
	force := boolFromAny(body["force"])
	record, err := d.devices.switchMode(c.Param("device_id"), target, force)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"status": "error", "message": err.Error()})
		return
	}
	log.Printf("切换设备模式成功: %s -> %s", c.Param("device_id"), modeName(target))
	c.JSON(http.StatusOK, gin.H{"status": "success", "record": record})
}

func (d *dashboard) identifyDeviceMode(c *gin.Context) {
	var body map[string]any
	if err := c.ShouldBindJSON(&body); err != nil {
		body = map[string]any{}
	}
	var traffic, resource map[string]any
	if v, ok := body["traffic_pattern"].(map[string]any); ok {
		traffic = v
	}
	if v, ok := body["resource_usage"].(map[string]any); ok {
		resource = v
	}
	id := c.Param("device_id")
	mode, err := d.devices.identify(id, traffic, resource)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"status": "error", "message": err.Error()})
		return
	}
	available := d.devices.availableModes(id)
	names := make([]string, 0, len(available))
	for _, m := range available {
		names = append(names, modeName(m))
	}
	c.JSON(http.StatusOK, gin.H{
		"status":               "success",
		"identified_mode":      mode,
		"identified_mode_name": modeName(mode),
		"available_modes":      available,
		"available_mode_names": names,
	})
}

func (d *dashboard) deviceHistory(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"history": d.devices.historyFor(c.Param("device_id"))})
}

// ============ 设备身份配置 ============

func (d *dashboard) getIdentityConfig(c *gin.Context) {
	c.JSON(http.StatusOK, d.identity.get())
}

func (d *dashboard) putIdentityConfig(c *gin.Context) {
	var body map[string]any
	if err := c.ShouldBindJSON(&body); err != nil {
		badRequest(c, "请求体不是 JSON")
		return
	}
	if _, ok := body["devices"]; !ok {
		badRequest(c, "缺少devices字段")
		return
	}
	d.identity.save(body)
	log.Printf("设备身份配置已全局更新")
	c.JSON(http.StatusOK, gin.H{"status": "success"})
}

func (d *dashboard) addIdentityDevice(c *gin.Context) {
	var body map[string]any
	if err := c.ShouldBindJSON(&body); err != nil {
		badRequest(c, "请求体不是 JSON")
		return
	}
	ip := strings.TrimSpace(stringFromAny(body["ip"]))
	if ip == "" {
		badRequest(c, "缺少IP地址")
		return
	}
	cfg := d.identity.get()
	devices := devicesMap(cfg)
	devices[ip] = map[string]any{
		"device_id":   stringFromAny(body["device_id"]),
		"device_name": stringFromAny(body["device_name"]),
		"device_type": defaultString(stringFromAny(body["device_type"]), "host"),
		"role":        defaultString(stringFromAny(body["role"]), "host"),
		"description": stringFromAny(body["description"]),
	}
	cfg["devices"] = devices
	d.identity.save(cfg)
	log.Printf("添加设备身份映射: %s -> %s", ip, stringFromAny(body["device_id"]))
	c.JSON(http.StatusOK, gin.H{"status": "success"})
}

func (d *dashboard) updateIdentityDevice(c *gin.Context) {
	ip := c.Param("ip")
	var body map[string]any
	if err := c.ShouldBindJSON(&body); err != nil {
		badRequest(c, "请求体不是 JSON")
		return
	}
	cfg := d.identity.get()
	devices := devicesMap(cfg)
	entry, ok := devices[ip].(map[string]any)
	if !ok {
		c.JSON(http.StatusNotFound, gin.H{"status": "error", "message": fmt.Sprintf("IP %s 不存在", ip)})
		return
	}
	for _, field := range []string{"device_id", "device_name", "device_type", "role", "description"} {
		if v, exists := body[field]; exists {
			entry[field] = v
		}
	}
	devices[ip] = entry
	cfg["devices"] = devices
	d.identity.save(cfg)
	log.Printf("更新设备身份映射: %s", ip)
	c.JSON(http.StatusOK, gin.H{"status": "success"})
}

func (d *dashboard) deleteIdentityDevice(c *gin.Context) {
	ip := c.Param("ip")
	cfg := d.identity.get()
	devices := devicesMap(cfg)
	if _, ok := devices[ip]; !ok {
		c.JSON(http.StatusNotFound, gin.H{"status": "error", "message": fmt.Sprintf("IP %s 不存在", ip)})
		return
	}
	delete(devices, ip)
	cfg["devices"] = devices
	d.identity.save(cfg)
	log.Printf("删除设备身份映射: %s", ip)
	c.JSON(http.StatusOK, gin.H{"status": "success"})
}

func (d *dashboard) reloadIdentity(c *gin.Context) {
	cfg := d.identity.get()
	cfg["updated_at"] = nowISO()
	d.identity.save(cfg)
	log.Printf("已触发控制器配置重载")
	c.JSON(http.StatusOK, gin.H{"status": "success", "message": "重载信号已发出"})
}

// ============ helpers ============

func badRequest(c *gin.Context, msg string) {
	c.JSON(http.StatusBadRequest, gin.H{"status": "error", "message": msg})
}

func convertMatchKeywords(match string) string {
	return strings.NewReplacer(
		"ipv4_src", "nw_src",
		"ipv4_dst", "nw_dst",
		"tcp_src", "tp_src",
		"tcp_dst", "tp_dst",
		"udp_src", "tp_src",
		"udp_dst", "tp_dst",
	).Replace(match)
}

func stringFromAny(v any) string {
	if s, ok := v.(string); ok {
		return s
	}
	if v == nil {
		return ""
	}
	return fmt.Sprint(v)
}

func intFromAny(v any) int {
	switch n := v.(type) {
	case int:
		return n
	case int32:
		return int(n)
	case int64:
		return int(n)
	case float64:
		return int(n)
	case float32:
		return int(n)
	case string:
		var out int
		fmt.Sscanf(n, "%d", &out)
		return out
	default:
		return 0
	}
}

func boolFromAny(v any) bool {
	switch b := v.(type) {
	case bool:
		return b
	case string:
		return b == "true" || b == "1"
	case float64:
		return b != 0
	case int:
		return b != 0
	default:
		return false
	}
}

func lenAny(v any) int {
	switch list := v.(type) {
	case []any:
		return len(list)
	case []map[string]any:
		return len(list)
	case map[string]any:
		return len(list)
	default:
		return 0
	}
}
