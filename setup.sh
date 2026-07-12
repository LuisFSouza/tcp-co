#!/usr/bin/env bash
#
# setup.sh — Cria a topologia de rede (2 network namespaces + par veth)
# usada para os testes do TCP-CO. Rode uma vez antes de começar os testes.
#
# Uso: sudo ./setup.sh

set -e

echo "==> Limpando qualquer coisa residual de execuções anteriores..."
sudo ip netns del ns_client 2>/dev/null
sudo ip netns del ns_server 2>/dev/null

echo "==> Criando os namespaces..."
sudo ip netns add ns_client
sudo ip netns add ns_server

echo "==> Criando o par veth..."
sudo ip link add veth-c type veth peer name veth-s

echo "==> Movendo cada ponta para o seu namespace..."
sudo ip link set veth-c netns ns_client
sudo ip link set veth-s netns ns_server

echo "==> Configurando IPs..."
sudo ip netns exec ns_client ip addr add 10.0.0.1/24 dev veth-c
sudo ip netns exec ns_server ip addr add 10.0.0.2/24 dev veth-s

echo "==> Subindo as interfaces..."
sudo ip netns exec ns_client ip link set veth-c up
sudo ip netns exec ns_server ip link set veth-s up
sudo ip netns exec ns_client ip link set lo up
sudo ip netns exec ns_server ip link set lo up

echo "==> Desativando o TCP_SACK..."
sudo ip netns exec ns_client sysctl -w net.ipv4.tcp_sack=0
sudo ip netns exec ns_server sysctl -w net.ipv4.tcp_sack=0

echo "==> Testando conectividade..."
sudo ip netns exec ns_client ping -c 2 10.0.0.2

echo ""
echo "Topologia pronta:"
echo "  ns_client (veth-c, 10.0.0.1) <----> ns_server (veth-s, 10.0.0.2)"
echo ""
echo "Próximos passos (3 terminais):"
echo "  1) sudo ip netns exec ns_server iperf3 -s"
echo "  2) sudo ./network_scenario.sh -d 40 -l 0.01           (aplica o cenário de rede)"
echo "  3) make run OUT=results/<nome_do_teste>.csv           (inicia a coleta)"
echo "  4) sudo ip netns exec ns_client iperf3 -c 10.0.0.2 -C cubic -k 10000"