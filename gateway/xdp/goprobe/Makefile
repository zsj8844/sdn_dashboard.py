CC := clang
ARCH := $(shell uname -m)
CFLAGS ?= -O2 -g -Wall -target bpf -I/usr/include/$(ARCH)-linux-gnu

all: gw-xdp-go

SRC := ../gw_filter_probe.c
GO_SRCS := $(shell find cmd internal -name '*.go')

gw_filter_probe.o: $(SRC) ../gw_filter_types.h ../gw_filter_logic.h
	$(CC) $(CFLAGS) -c $(SRC) -o $@

gw-xdp-go: $(GO_SRCS) go.mod go.sum gw_filter_probe.o
	go build -o $@ ./cmd/gw-xdp-go

clean:
	rm -f gw-xdp-go gw_filter_probe.o

.PHONY: all clean
