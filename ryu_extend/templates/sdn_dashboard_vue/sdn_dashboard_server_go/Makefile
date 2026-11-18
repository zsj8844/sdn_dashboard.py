GO ?= go
BIN := bin/dashboard-go
SRC := $(wildcard internal/dashboard/*.go) cmd/dashboard/main.go go.mod

all: $(BIN)

$(BIN): $(SRC)
	mkdir -p bin
	$(GO) build -o $(BIN) ./cmd/dashboard

clean:
	rm -f $(BIN)
	rmdir bin 2>/dev/null || true

.PHONY: all clean
