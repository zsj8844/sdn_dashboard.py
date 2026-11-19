package main

import (
	"bytes"
	"encoding/binary"
	"log"

	"github.com/cilium/ebpf/ringbuf"

	"sdn-iot/gateway/xdp/goprobe/internal/model"
	"sdn-iot/gateway/xdp/goprobe/internal/probe"
)

// consumeRingbuf 持续读取 miss 事件；p 为 nil 时只打日志（--no-probe）。
func consumeRingbuf(rd *ringbuf.Reader, p *probe.Probe) {
	for {
		rec, err := rd.Read()
		if err != nil {
			return
		}
		var evt model.MissEvt
		if err := binary.Read(bytes.NewReader(rec.RawSample), binary.LittleEndian, &evt); err != nil {
			log.Printf("[MISS] 解析事件失败: %v", err)
			continue
		}
		if p != nil {
			p.OnMiss(evt)
		} else {
			log.Printf("[MISS] %s preview=%q", model.FmtKey(evt.Key),
				bytes.TrimRight(evt.Preview[:], "\x00"))
		}
	}
}
