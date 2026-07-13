# TCP-CO: TCP Congestion Observatory

O **TCP-CO** é uma ferramenta desenvolvida em **Go** e **eBPF** projetada para observar o comportamento de conexões TCP diretamente no espaço do kernel Linux. A ferramenta monitora métricas críticas de controle de congestionamento, como Janela de Congestionamento (CWND), Slow Start Threshold (ssthresh), Round-Trip Time (RTT) e retransmissões.

## 🚀 Funcionalidades
*   **Monitoramento via eBPF:** Coleta de métricas direto do subsistema de rede do kernel.
*   **Análise de Algoritmos:** Comparação visual do comportamento de algoritmos como **Reno** e **Cubic**.
*   **Dashboard Interativo:** Visualização dos dados coletados via Streamlit.
*   **Suíte de Testes Automatizada:** Cenários simulados de perda de pacotes, latência e variação de banda.

---

## 🛠️ Pré-requisitos e Dependências

Antes de começar, certifique-se de que seu kernel possui suporte a **BTF (BPF Type Format)**:
```bash
ls /sys/kernel/btf/vmlinux || echo "Erro: Seu kernel não suporta BTF."
```

### 1. Pacotes do Sistema

Instale o compilador, as ferramentas do eBPF e utilitários de teste:

```bash
sudo apt update
sudo apt install -y clang llvm make libbpf-dev linux-headers-generic gcc-multilib golang-go
```

*Nota: O projeto requer **Go 1.25+**.

### 2. Ferramentas de Alerta (Opcional)
Para testar a simulação de e-mails localmente, instale o Mailpit. No Linux, você pode instalar rapidamente com o comando:
```bash
sudo sh < <(curl -sL https://raw.githubusercontent.com/axllent/mailpit/develop/install.sh)
```
Mais informações em: [MailPit](https://github.com/axllent/mailpit)

---

## ⚙️ Compilação e Execução

O processo de build é totalmente automatizado via `Makefile`, que gerencia desde a extração do `vmlinux.h` até o `go generate` (via `bpf2go`) e a compilação final.

### Modo Observador (Tempo Real)

Para compilar e rodar o coletor imediatamente:

```bash
sudo make run
```

> 💡 **Nota de Execução:** A execução requer privilégios de `root` (`sudo`).

Por padrão, os dados coletados serão salvos continuamente no arquivo `tcp_metrics.csv`.

### Inicializando o Dashboard

Em outro terminal, instale as dependências do Python e inicie a interface de análise (aponte para o arquivo `.csv` que deseja visualizar):

```bash
pip install -r requirements.txt
streamlit run dashboard.py -- --csv 'tcp_metrics.csv'
```

---

##  Simulação de Alertas com Mailpit

A ferramenta possui um mecanismo interno para disparar notificações por e-mail sempre que uma degradação severa na performance do TCP for detectada.

Para interceptar e visualizar esses alertas localmente sem precisar de credenciais SMTP reais, você pode utilizar o **Mailpit**:

#### 1. Suba o servidor do Mailpit (ele iniciará o servidor SMTP na porta `1025` e a interface web na porta `8025` por padrão):
```bash
mailpit --listen 127.0.0.1:8025
```

#### 2. Abra o painel do Mailpit no seu navegador em [http://127.0.0.1:8025](http://127.0.0.1:8025) para visualizar os e-mails recebidos em tempo real com o layout de degradação estruturado.

---

## 🧪 Cenários de Testes Simulados

O projeto acompanha um script automatizado (`run_tests.sh`) que aplica condições adversas de rede usando `tc` (Traffic Control) e injeta tráfego com `iperf3`.

O script gerencia o ciclo de vida do `tcp_co` internamente para cada cenário (Reno vs Cubic, perda de pacotes, introdução de delay).

```bash
sudo ./setup.sh
sudo bash run_tests.sh
```
📂 **Saída:** Os relatórios consolidados de cada cenário serão gerados na pasta `tests/results/`. Na hora de gerar o gráfico, especifique o caminho do arquivo `.csv` gerado pelo teste.

**Exemplo de execução do dashboard:**

```bash
streamlit run dashboard.py -- --csv 'tests/results/exp01.csv'
```

---

## 👥 Integrantes

* **Luis Felipi Cruz de Souza** — [@LuisFSouza](https://github.com/LuisFSouza)
* **Felipe Bonadia de Oliveira Bravo** — [@FelipeBonadia](https://github.com/FelipeBonadia)
