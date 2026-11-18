// SDN Dashboard API 服务器（Gin 版）。
//
// 保持原有 HTTP API 路径与 JSON 形状不变，Vue 前端和 Vite 代理无需修改。
package dashboard

import (
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"path"
	"path/filepath"
	"strings"

	"github.com/gin-gonic/gin"
)

type paths struct {
	base          string
	vueDist       string
	logsDir       string
	gatewayLog    string
	controllerLog string
	identity      string
}

// Options 是 cmd/dashboard 传入的运行参数。
type Options struct {
	Host           string
	Port           int
	Base           string
	Dist           string
	Debug          bool
	NoBLE          bool
	NoConnectivity bool
}

func resolvePaths(base string) paths {
	return paths{
		base:          base,
		vueDist:       filepath.Join(base, "..", "sdn_dashboard_view", "dist"),
		logsDir:       filepath.Join(base, "..", "..", "..", "logs"),
		gatewayLog:    filepath.Join(base, "..", "..", "..", "logs", "gateway.log"),
		controllerLog: filepath.Join(base, "..", "..", "..", "logs", "controller.log"),
		identity:      filepath.Join(base, "..", "..", "..", "switch", "config", "device_identity.json"),
	}
}

func defaultBase() string {
	if exe, err := os.Executable(); err == nil {
		dir := filepath.Dir(exe)
		if filepath.Base(dir) == "bin" {
			dir = filepath.Dir(dir)
		}
		if _, err := os.Stat(filepath.Join(dir, "..", "sdn_dashboard_view")); err == nil {
			return dir
		}
	}
	if wd, err := os.Getwd(); err == nil {
		return wd
	}
	return "."
}

// Run 启动 HTTP 服务，阻塞直到退出。
func Run(opts Options) {
	if opts.Base == "" {
		opts.Base = defaultBase()
	}
	p := resolvePaths(opts.Base)
	if opts.Dist != "" {
		p.vueDist = opts.Dist
	}
	if err := os.MkdirAll(p.logsDir, 0o755); err != nil {
		fmt.Fprintf(os.Stderr, "创建日志目录失败: %v\n", err)
	}
	logFile, err := os.OpenFile(p.controllerLog, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
	if err != nil {
		fmt.Fprintf(os.Stderr, "打开日志文件失败: %v\n", err)
		logFile = nil
	}
	if logFile != nil {
		log.SetOutput(io.MultiWriter(os.Stdout, logFile))
	}
	log.SetFlags(log.LstdFlags)

	st := newState()
	st.gatewayLogFile = p.gatewayLog
	identity := newIdentityManager(p.identity)
	apps := newAppManager()
	devices := newDeviceManager()
	dash := &dashboard{
		state:    st,
		identity: identity,
		apps:     apps,
		devices:  devices,
		paths:    p,
	}

	if !opts.NoBLE {
		go st.listenBLE()
	}
	if !opts.NoConnectivity {
		go st.connectivityLoop()
	}

	if !opts.Debug {
		gin.SetMode(gin.ReleaseMode)
	}
	r := gin.New()
	r.Use(gin.Logger(), gin.Recovery(), corsMiddleware())

	registerRoutes(r, dash)
	registerStatic(r, p)

	if _, err := os.Stat(p.vueDist); err == nil {
		log.Printf("SDN Dashboard（Gin）启动：http://%s:%d（生产模式，托管 %s）",
			opts.Host, opts.Port, p.vueDist)
	} else {
		log.Printf("SDN Dashboard（Gin）启动：http://%s:%d（开发模式，dist 不存在）",
			opts.Host, opts.Port)
	}
	if err := r.Run(fmt.Sprintf("%s:%d", opts.Host, opts.Port)); err != nil {
		log.Fatalf("HTTP 服务退出: %v", err)
	}
}

func corsMiddleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		c.Header("Access-Control-Allow-Origin", "*")
		c.Header("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
		c.Header("Access-Control-Allow-Headers", "Content-Type")
		if c.Request.Method == http.MethodOptions {
			c.AbortWithStatus(http.StatusNoContent)
			return
		}
		c.Next()
	}
}

func registerStatic(r *gin.Engine, p paths) {
	assets := filepath.Join(p.vueDist, "assets")
	if _, err := os.Stat(assets); err == nil {
		r.Static("/assets", assets)
	}
	index := filepath.Join(p.vueDist, "index.html")

	r.GET("/", func(c *gin.Context) {
		if _, err := os.Stat(index); err == nil {
			c.File(index)
			return
		}
		c.JSON(http.StatusOK, gin.H{
			"message": "SDN Dashboard API Server",
			"mode":    "development",
			"tip":     "请启动 Vue 开发服务器: cd sdn_dashboard_view && npm run dev",
		})
	})

	r.NoRoute(func(c *gin.Context) {
		reqPath := c.Request.URL.Path
		if strings.HasPrefix(reqPath, "/api/") || reqPath == "/api" {
			c.JSON(http.StatusNotFound, gin.H{"error": "Not found", "path": reqPath})
			return
		}
		clean := path.Clean("/" + reqPath)
		if clean == "/" {
			clean = "/index.html"
		}
		file := filepath.Join(p.vueDist, filepath.FromSlash(strings.TrimPrefix(clean, "/")))
		if rel, err := filepath.Rel(p.vueDist, file); err == nil && !strings.HasPrefix(rel, "..") {
			if info, err := os.Stat(file); err == nil && !info.IsDir() {
				c.File(file)
				return
			}
		}
		if _, err := os.Stat(index); err == nil {
			c.File(index)
			return
		}
		c.JSON(http.StatusNotFound, gin.H{"error": "Not found", "path": reqPath})
	})
}
