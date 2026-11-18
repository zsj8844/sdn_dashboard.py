CC := clang
ARCH := $(shell uname -m)
CFLAGS ?= -O2 -g -Wall -target bpf -I/usr/include/$(ARCH)-linux-gnu

all: gw-xdp-go

gw_filter_probe.o: bpf/gw_filter_probe.c
	$(CC) $(CFLAGS) -c $< -o $@

gw-xdp-go: main.go go.mod gw_filter_probe.o
	go build -o $@ .

clean:
	rm -f gw-xdp-go gw_filter_probe.o

.PHONY: all clean
