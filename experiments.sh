#!/bin/bash

# TCP-CO experiments runner
# Runs multiple algorithms across predefined scenarios and saves per-run CSVs

set -euo pipefail

EXPERIMENTS_DIR="experiments"
mkdir -p "$EXPERIMENTS_DIR"

# Allow override of network device via env var NET_DEV
NET_DEV=${NET_DEV:-$(ip -o link show | awk -F': ' '{print $2}' | grep -E '^(enp|eth|wlo|wlx|ens|eno|br-|docker|veth)' | head -n 1 || true)}

echo "=================================================="
echo "   TCP-CO: Script de Experimentos Automatizados"
echo "=================================================="
echo "Interface de rede usada: ${NET_DEV:-(não detectada)}"
echo ""

if [ -z "$NET_DEV" ]; then
        echo "ERRO: não foi possível detectar uma interface de rede válida."
        echo "Defina a variável NET_DEV com o nome da interface, por exemplo:"
        echo "  NET_DEV=enp1s0 ./experiments.sh"
        exit 1
fi

# cleanup tc
cleanup_network() {
        echo "[INFO] limpando regras de rede em $NET_DEV"
        sudo tc qdisc del dev "$NET_DEV" root 2>/dev/null || true
}

# run one experiment
run_experiment() {
        local algo=$1
        local scenario=$2
        local delay_ms=${3:-}
        local loss_pct=${4:-}
        local duration=${5:-30}

        local out="$EXPERIMENTS_DIR/${algo}_${scenario}.csv"

        echo
        echo "=========================================="
        echo "Experimento: $algo - $scenario"
        echo "=========================================="
        echo "Algoritmo: $algo | delay=${delay_ms:-none}ms | loss=${loss_pct:-none}%"
        echo "Saída: $out"

        echo "[1/4] set tcp congestion control -> $algo"
        sudo sysctl -q net.ipv4.tcp_congestion_control=$algo

        echo "[2/4] aplicando netem (se necessário)"
        cleanup_network
        if [ -n "$delay_ms" ] || [ -n "$loss_pct" ]; then
                cmd=(sudo tc qdisc add dev "$NET_DEV" root netem)
                [ -n "$delay_ms" ] && cmd+=(delay "${delay_ms}ms")
                [ -n "$loss_pct" ] && cmd+=(loss "${loss_pct}%")
                echo "  Executando: ${cmd[*]}"
                "${cmd[@]}"
        fi

        echo "[3/4] iniciando coleta (tcp_co)"
        sudo timeout $((duration + 10)) ./tcp_co > /dev/null 2>&1 &
        TCP_PID=$!
        sleep 2

        echo "[4/4] gerando tráfego (iperf3 local se disponível)"
        if timeout 2 bash -c 'nc -z localhost 5201' >/dev/null 2>&1; then
                iperf3 -c localhost -t "$duration" -J >/dev/null 2>&1 || true
        else
                echo "  [AVISO] iperf3 server não encontrado em localhost, aguarde ${duration}s"
                sleep "$duration"
        fi

        sleep 3
        kill "$TCP_PID" 2>/dev/null || true

        if [ -f tcp_metrics.csv ]; then
                sudo cp tcp_metrics.csv "$out"
                sudo chown $(id -u):$(id -g) "$out"
                echo "✓ salvo: $out"
        else
                echo "✗ tcp_metrics.csv não encontrado (experimento falhou)"
        fi

        cleanup_network
}

# Algorithms and scenarios
ALGOS=(cubic reno bbr)
# scenarios: name, delay_ms, loss_pct
SCENARIOS=("baseline,," "delay_100ms,100," "loss_1percent,,1")

for algo in "${ALGOS[@]}"; do
        for sc in "${SCENARIOS[@]}"; do
                IFS=',' read -r name delay loss <<< "$sc"
                run_experiment "$algo" "$name" "$delay" "$loss" 30
        done
done

echo
echo "=================================================="
echo "✓ Todos os experimentos concluídos"
echo "Resultados em: $EXPERIMENTS_DIR"
ls -lh "$EXPERIMENTS_DIR" || true
echo
echo "Próximo: copiar um CSV para tcp_metrics.csv e rodar: streamlit run dashboard.py"
