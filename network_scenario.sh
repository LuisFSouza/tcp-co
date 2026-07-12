#!/usr/bin/env bash
#
# network_scenario.sh — Aplica uma configuração de rede (delay, jitter, loss,
# corrupt, duplicate, reorder, limite de banda) na topologia criada pelo
# setup.sh (namespaces ns_client/ns_server, veth-c/veth-s).
#
# Por padrão aplica no veth-c (saída do cliente, dev usado pelo iperf3 -c).
# Use -b para espelhar a mesma config no veth-s também (delay simétrico/RTT).
#
# Uso:
#   sudo ./network_scenario.sh -d 40 -l 0.01
#   sudo ./network_scenario.sh -d 100 -l 1 -r 10
#   sudo ./network_scenario.sh --clean
#
# Opções:
#   -d  delay em ms                                    [default: 0]
#   -j  jitter em ms (variação do delay)                [default: 0]
#   -l  perda de pacotes em %% (aceita decimais: 0.01)   [default: 0]
#   -c  corrupção em %%                                  [default: 0]
#   -u  duplicação em %%                                 [default: 0]
#   -e  reordenação, formato "PCT[/CORR]" ex: 25/50      [default: vazio]
#   -r  limite de banda em mbit (tbf)                    [default: 0 = sem limite]
#   -b  também espelha a config no lado do servidor (veth-s)
#   --clean  remove toda configuração de rede (equivale a "sem cenário")
#   -h  ajuda

set -euo pipefail

DELAY=0
JITTER=0
LOSS=0
CORRUPT=0
DUPLICATE=0
REORDER=""
RATE=0
BOTH_SIDES=0
CLEAN_ONLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    -d) DELAY="$2"; shift 2 ;;
    -j) JITTER="$2"; shift 2 ;;
    -l) LOSS="$2"; shift 2 ;;
    -c) CORRUPT="$2"; shift 2 ;;
    -u) DUPLICATE="$2"; shift 2 ;;
    -e) REORDER="$2"; shift 2 ;;
    -r) RATE="$2"; shift 2 ;;
    -b) BOTH_SIDES=1; shift ;;
    --clean) CLEAN_ONLY=1; shift ;;
    -h)
      grep '^#' "$0" | sed 's/^#//'
      exit 0
      ;;
    *) echo "Opção inválida: $1"; exit 1 ;;
  esac
done

if [[ $EUID -ne 0 ]]; then
  echo "Erro: rode este script com sudo."
  exit 1
fi

if ! sudo ip netns list | grep -q ns_client; then
  echo "Erro: namespace ns_client não existe. Rode ./setup.sh primeiro."
  exit 1
fi

apply_to() {
  local ns="$1"
  local dev="$2"

  # sempre limpa antes, pra evitar erro de "add" duplicado
  sudo ip netns exec "$ns" tc qdisc del dev "$dev" root 2>/dev/null || true

  if [[ $CLEAN_ONLY -eq 1 ]]; then
    echo "  [$ns/$dev] configuração de rede removida."
    return
  fi

  local netem_args=""
  [[ "$DELAY" != "0" ]] && netem_args="$netem_args delay ${DELAY}ms${JITTER:+ ${JITTER}ms}"
  [[ "$LOSS" != "0" ]] && netem_args="$netem_args loss ${LOSS}%"
  [[ "$CORRUPT" != "0" ]] && netem_args="$netem_args corrupt ${CORRUPT}%"
  [[ "$DUPLICATE" != "0" ]] && netem_args="$netem_args duplicate ${DUPLICATE}%"
  if [[ -n "$REORDER" ]]; then
    PCT="${REORDER%%/*}"
    CORR="${REORDER##*/}"
    if [[ "$PCT" == "$REORDER" ]]; then
      netem_args="$netem_args reorder ${PCT}%"
    else
      netem_args="$netem_args reorder ${PCT}% ${CORR}%"
    fi
  fi

  if [[ -z "$netem_args" && "$RATE" == "0" ]]; then
    echo "  [$ns/$dev] nenhuma perturbação aplicada (rede limpa)."
    return
  fi

  if [[ -n "$netem_args" && "$RATE" != "0" ]]; then
    sudo ip netns exec "$ns" tc qdisc add dev "$dev" root handle 1: netem $netem_args
    sudo ip netns exec "$ns" tc qdisc add dev "$dev" parent 1:1 handle 10: tbf rate "${RATE}mbit" burst 32k latency 400ms
  elif [[ -n "$netem_args" ]]; then
    sudo ip netns exec "$ns" tc qdisc add dev "$dev" root netem $netem_args
  else
    sudo ip netns exec "$ns" tc qdisc add dev "$dev" root tbf rate "${RATE}mbit" burst 32k latency 400ms
  fi

  echo "  [$ns/$dev] aplicado:${netem_args:+ netem$netem_args}${RATE:+ tbf rate ${RATE}mbit}"
}

echo "==> Configurando rede em ns_client/veth-c..."
apply_to ns_client veth-c

if [[ $BOTH_SIDES -eq 1 ]]; then
  echo "==> Espelhando em ns_server/veth-s..."
  apply_to ns_server veth-s
fi

echo ""
echo "==> Estado atual dos qdiscs:"
sudo ip netns exec ns_client tc qdisc show dev veth-c
sudo ip netns exec ns_server tc qdisc show dev veth-s

echo ""
echo "Pronto. Agora rode, em terminais separados:"
echo "  make run OUT=results/<nome_do_teste>.csv"
echo "  sudo ip netns exec ns_client iperf3 -c 10.0.0.2 -C <algoritmo> -k 10000"