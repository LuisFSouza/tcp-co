#!/bin/bash

# Limpa qualquer coisa residual
sudo ip netns del ns_client 2>/dev/null
sudo ip netns del ns_server 2>/dev/null

# Cria os namespaces
sudo ip netns add ns_client
sudo ip netns add ns_server

# Cria o par veth
sudo ip link add veth-c type veth peer name veth-s

# Move cada ponta pro seu namespace
sudo ip link set veth-c netns ns_client
sudo ip link set veth-s netns ns_server

# Configura IPs
sudo ip netns exec ns_client ip addr add 10.0.0.1/24 dev veth-c
sudo ip netns exec ns_server ip addr add 10.0.0.2/24 dev veth-s

# Sobe as interfaces
sudo ip netns exec ns_client ip link set veth-c up
sudo ip netns exec ns_server ip link set veth-s up
sudo ip netns exec ns_client ip link set lo up
sudo ip netns exec ns_server ip link set lo up

# Desativa o TCP_SACK
sudo ip netns exec ns_client sysctl -w net.ipv4.tcp_sack=0
sudo ip netns exec ns_server sysctl -w net.ipv4.tcp_sack=0

echo "Setup concluído: ns_client (10.0.0.1) <-> ns_server (10.0.0.2)"