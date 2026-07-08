.PHONY: all generate build run clean

BINARY_NAME=tcp_co

all: generate build

generate:
	@if [ ! -f go.mod ]; then \
		go mod init $(BINARY_NAME); \
	fi
	go mod tidy
	@if [ ! -f vmlinux.h ] || [ ! -s vmlinux.h ]; then \
		BPFTOOL_PATH=$$(find /usr/lib/linux-tools -name bpftool 2>/dev/null | head -n 1); \
		if [ -n "$$BPFTOOL_PATH" ] && [ -x "$$BPFTOOL_PATH" ]; then \
			$$BPFTOOL_PATH btf dump file /sys/kernel/btf/vmlinux format c > vmlinux.h 2>/dev/null; \
		else \
			if command -v bpftool >/dev/null 2>&1; then \
				bpftool btf dump file /sys/kernel/btf/vmlinux format c > vmlinux.h 2>/dev/null; \
			fi; \
		fi; \
	fi
	go install github.com/cilium/ebpf/cmd/bpf2go@latest
	go generate

build: generate
	go build -o $(BINARY_NAME) .

run: build
	sudo ./$(BINARY_NAME)

clean:
	rm -f $(BINARY_NAME)
	rm -f bpf_bpfel.go bpf_bpfel.o
	rm -f tcp_metrics.csv