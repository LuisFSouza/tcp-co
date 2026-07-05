.PHONY: all generate build run clean

BINARY_NAME=tcp_co

all: generate build

generate:
	@echo "🔄 Verificando módulo do Go..."
	@if [ ! -f go.mod ]; then \
		echo "📦 Inicializando módulo go.mod..."; \
		go mod init $(BINARY_NAME); \
	fi
	@echo "📥 Baixando e atualizando dependências..."
	go mod tidy
	@echo "🩺 Verificando se vmlinux.h existe..."
	@if [ ! -f vmlinux.h ] || [ ! -s vmlinux.h ]; then \
		echo "🧬 Buscando bpftool em /usr/lib/linux-tools..."; \
		BPFTOOL_PATH=$$(find /usr/lib/linux-tools -name bpftool 2>/dev/null | head -n 1); \
		if [ -n "$$BPFTOOL_PATH" ] && [ -x "$$BPFTOOL_PATH" ]; then \
			echo "⚙️ bpftool encontrado em: $$BPFTOOL_PATH"; \
			echo "🧬 Gerando vmlinux.h com o bpftool localizado..."; \
			$$BPFTOOL_PATH btf dump file /sys/kernel/btf/vmlinux format c > vmlinux.h 2>/dev/null; \
		else \
			echo "🔍 bpftool não encontrado em linux-tools. Tentando comando global..."; \
			if command -v bpftool >/dev/null 2>&1; then \
				bpftool btf dump file /sys/kernel/btf/vmlinux format c > vmlinux.h 2>/dev/null; \
			fi; \
		fi; \
	fi
	@echo "🛠️ Gerando ferramentas e compilando código eBPF..."
	go install github.com/cilium/ebpf/cmd/bpf2go@latest
	go generate

build: generate
	@echo "🦀 Compilando o binário Go..."
	go build -o $(BINARY_NAME) .
run: build
	@echo "🚀 Executando o rastreador TCP (requer sudo)..."
	sudo ./$(BINARY_NAME)

clean:
	@echo "🧹 Limpando arquivos gerados..."
	rm -f $(BINARY_NAME)
	rm -f bpf_bpfel.go bpf_bpfel.o
	rm -f tcp_metrics.csv