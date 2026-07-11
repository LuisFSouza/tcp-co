# TCP-CO — TCP Congestion Observatory

Ferramenta em Go + eBPF para observar em tempo real o controle de congestionamento do TCP no kernel Linux (CWND, ssthresh, RTT, retransmissões, etc.), gravando os dados em CSV.

## Pré-requisitos

```bash
sudo apt update
sudo apt install -y clang llvm make libbpf-dev linux-headers-generic gcc-multilib linux-tools-generic
sudo apt install -y iperf3 iproute2
```

- Go 1.25+
- Kernel com suporte a BTF (verifique com `ls /sys/kernel/btf/vmlinux`)

## Compilação

O `Makefile` já cuida de tudo (`go mod tidy`, geração do `vmlinux.h`, `go generate` e `go build`):

```bash
make
```

## Testes simulados

O `test_scenarios.sh` já executa o `tcp_co` internamente para cada cenário (perda de pacotes, delay, comparação Reno/Cubic/BBR) — não é preciso rodar `./tcp_co` manualmente. Leva de 15 a 20 minutos e requer `sudo`:

```bash
sudo bash test_scenarios.sh
```

Os resultados (CSVs por cenário) são salvos em `test_results/`.

## Dashboard (Streamlit)

```bash
pip install streamlit pandas matplotlib numpy
streamlit run dashboard.py
```

Lê os CSVs em `test_results/` e mostra gráficos comparativos por algoritmo/cenário.
