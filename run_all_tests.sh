#!/usr/bin/env bash
#
# run_all_tests.sh — Automatiza TUDO: sobe a topologia (se preciso), builda o
# binário, sobe o servidor iperf3, e roda a bateria de cenários definida no
# array SCENARIOS abaixo, cada um aplicando o cenário de rede (network_scenario.sh),
# coletando com "make run OUT=... DURATION=..." e gerando tráfego com iperf3 -
# tudo em sequência, sem precisar de 3 terminais manuais.
#
# Uso:
#   sudo ./run_all_tests.sh
#
# Os resultados vão para results/<label>.csv — depois é só rodar:
#   streamlit run dashboard.py

set -euo pipefail
cd "$(dirname "$0")"

if [[ $EUID -ne 0 ]]; then
  echo "Erro: rode este script com sudo."
  exit 1
fi

# label|algoritmo|delay_ms|loss_pct|rate_mbit|duracao_s
SCENARIOS=(
  "exp1_cwnd_cubic|cubic|0|0|0|20"
  "exp2_loss1pct_cubic|cubic|0|1|0|30"
  "exp3_rtt100_cubic|cubic|100|0|0|30"
  "exp3_rtt200_cubic|cubic|200|0|0|30"
  "exp3_rtt500_cubic|cubic|500|0|0|30"
  "exp4_cubic|cubic|50|1|5|30"
  "exp4_bbr|bbr|50|1|5|30"
)

IPERF_SERVER_PID=""

cleanup() {
  echo ""
  echo "==> Limpando..."
  ./network_scenario.sh --clean >/dev/null 2>&1 || true
  if [[ -n "$IPERF_SERVER_PID" ]]; then
    kill "$IPERF_SERVER_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

echo "=============================================="
echo " TCP-CO — Bateria automática de experimentos"
echo "=============================================="

# 1) Garante que a topologia existe
if ! ip netns list | grep -q ns_client; then
  echo "==> Topologia não encontrada, rodando setup.sh..."
  ./setup.sh
else
  echo "==> Topologia já existe, seguindo em frente."
fi

# 2) Builda o binário uma vez
echo "==> Compilando (make build)..."
make build

mkdir -p results

# 3) Sobe o servidor iperf3 dentro do ns_server
echo "==> Subindo iperf3 -s em ns_server..."
ip netns exec ns_server iperf3 -s -D -p 5201 >/tmp/iperf3_server.log 2>&1
IPERF_SERVER_PID=$(pgrep -f "iperf3 -s" | head -n1)
sleep 1

# 4) Roda cada cenário da lista
for entry in "${SCENARIOS[@]}"; do
  IFS='|' read -r LABEL ALGO DELAY LOSS RATE DURATION <<< "$entry"

  echo ""
  echo "----------------------------------------------"
  echo " Cenário: $LABEL"
  echo " algo=$ALGO delay=${DELAY}ms loss=${LOSS}% rate=${RATE}mbit duracao=${DURATION}s"
  echo "----------------------------------------------"

  # Prepara o BBR se for o caso (módulo + fq)
  if [[ "$ALGO" == "bbr" ]]; then
    modprobe tcp_bbr 2>/dev/null || true
    sysctl -w net.core.default_qdisc=fq >/dev/null
  fi

  # Define o algoritmo de congestionamento no lado que envia dados (ns_client)
  ip netns exec ns_client sysctl -w net.ipv4.tcp_congestion_control="$ALGO" >/dev/null

  # Aplica o cenário de rede (ou limpa, se for tudo zero)
  if [[ "$DELAY" == "0" && "$LOSS" == "0" && "$RATE" == "0" ]]; then
    ./network_scenario.sh --clean
  else
    ./network_scenario.sh -d "$DELAY" -l "$LOSS" -r "$RATE"
  fi

  OUTFILE="results/${LABEL}.csv"

  # Sobe o coletor com parada automática (duração + margem)
  make run OUT="$OUTFILE" DURATION=$((DURATION + 5)) &
  TCPCO_PID=$!
  sleep 2   # tempo para os hooks eBPF anexarem

  # Gera tráfego real
  ip netns exec ns_client iperf3 -c 10.0.0.2 -p 5201 -C "$ALGO" -t "$DURATION" || true

  # Aguarda o coletor encerrar sozinho
  wait "$TCPCO_PID" 2>/dev/null || true

  echo "==> Cenário $LABEL concluído -> $OUTFILE"
done

echo ""
echo "=============================================="
echo " Todos os cenários concluídos. CSVs em results/"
echo " Rode: streamlit run dashboard.py"
echo "=============================================="