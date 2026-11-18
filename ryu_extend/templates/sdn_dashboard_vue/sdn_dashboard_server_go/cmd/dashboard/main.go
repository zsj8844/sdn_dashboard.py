// SDN Dashboard 入口：解析参数后交给 internal/dashboard 启动。
package main

import (
	"flag"

	"sdn-iot/dashboard/internal/dashboard"
)

func main() {
	var (
		host    = flag.String("host", "0.0.0.0", "监听地址")
		port    = flag.Int("port", 5000, "监听端口")
		base    = flag.String("base", "", "本程序所在目录（默认按可执行文件路径推断）")
		dist    = flag.String("dist", "", "Vue dist 目录（默认 ../sdn_dashboard_view/dist）")
		debug   = flag.Bool("debug", false, "Gin debug 模式")
		noBLE   = flag.Bool("no-ble", false, "不监听 UDP 5005")
		noCheck = flag.Bool("no-connectivity", false, "不启动 OVS 连通性轮询")
	)
	flag.Parse()

	dashboard.Run(dashboard.Options{
		Host:           *host,
		Port:           *port,
		Base:           *base,
		Dist:           *dist,
		Debug:          *debug,
		NoBLE:          *noBLE,
		NoConnectivity: *noCheck,
	})
}
