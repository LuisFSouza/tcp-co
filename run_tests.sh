#!/bin/bash

TESTS_ROOT="tests"
RESULTS_DIR="$TESTS_ROOT/results"
TCP_METRICS_FILE="tcp_metrics.csv"   # gerado pelo próprio tcp_co (main.go) na raiz do repo

mkdir -p "$RESULTS_DIR"

# Pega todos os diretórios exp* dentro de tests/, em ordem
EXPS=$(find "$TESTS_ROOT" -maxdepth 1 -type d -name "exp*" | sort)

for EXP_DIR in $EXPS; do
    EXP_NAME=$(basename "$EXP_DIR")
    RUN_FILE="$EXP_DIR/run.txt"
    CONFIG_FILE="$EXP_DIR/config.txt"

    if [[ ! -f "$RUN_FILE" ]]; then
        echo "[AVISO] run.txt não encontrado em $EXP_DIR, pulando..."
        continue
    fi

    # Ignora comentários (#) e linhas em branco; pega só as linhas de comando.
    # 1ª linha de comando = servidor, 2ª linha de comando = cliente.
    # Cada linha já vem completa com "sudo ip netns exec ns_x ...".
    mapfile -t CMD_LINES < <(grep -vE '^\s*#|^\s*$' "$RUN_FILE" | tr -d '\r')
    SERVER_CMD="${CMD_LINES[0]:-}"
    CLIENT_CMD="${CMD_LINES[1]:-}"

    if [[ -z "$SERVER_CMD" || -z "$CLIENT_CMD" ]]; then
        echo "[AVISO] run.txt incompleto em $EXP_DIR, pulando..."
        continue
    fi

    echo "================================="
    echo "Executando Teste: $EXP_NAME"
    echo "================================="
    echo "  Servidor: $SERVER_CMD"
    echo "  Cliente : $CLIENT_CMD"

    # 0. Limpeza antes de começar
    sudo pkill -f tcp_co 2>/dev/null
    sudo pkill -f iperf3 2>/dev/null
    sudo rm -f "$TCP_METRICS_FILE"
    sleep 1

    # 1. "rodo os comandos do config.txt"
    if [[ -f "$CONFIG_FILE" ]]; then
        echo "[1] Executando config.txt..."
        bash "$CONFIG_FILE"
    fi

    # 2. "abro o servidor" (comando já completo, vindo do run.txt)
    echo "[2] Iniciando Servidor..."
    $SERVER_CMD > /dev/null 2>&1 &
    sleep 1

    # 3. "em outro terminal dou sudo make run...espero ficar pronto (uns 15s)"
    echo "[3] Iniciando make run (tcp_co)..."
    sudo make run > /dev/null 2>&1 &

    echo "    Aguardando 18 segundos para o tcp_co compilar/iniciar de fato..."
    sleep 18
    echo "    tcp_co deve estar pronto agora!"

    # 4. "abro o cliente, depois q esse captura o necessario..." (comando já completo)
    echo "[4] Iniciando Cliente (aguardando transferência finalizar)..."
    $CLIENT_CMD > /dev/null 2>&1

    echo "    Cliente finalizou a conexão!"

    # 5. "deixe o tcp_co ficar pronto e rodar 10 segundos mesmo apos a conexao fechar"
    echo "    Deixando o tcp_co rodar por mais 10 segundos..."
    sleep 10

    # 6. "...eu vou ate o make run e dou ctrl+c"
    echo "[5] Dando Ctrl+C no make run (tcp_co)..."
    sudo pkill -SIGINT -f tcp_co

    # Espera o tcp_co salvar o tcp_metrics.csv e fechar com segurança
    sleep 2

    # 7. Move o CSV real (gerado pelo tcp_co) para tests/results/<exp>.csv
    if [[ -f "$TCP_METRICS_FILE" ]]; then
        sudo mv "$TCP_METRICS_FILE" "$RESULTS_DIR/$EXP_NAME.csv"
        sudo chown "$(id -u):$(id -g)" "$RESULTS_DIR/$EXP_NAME.csv"
        echo "    Resultado salvo em $RESULTS_DIR/$EXP_NAME.csv"
    else
        echo "    [ERRO] $TCP_METRICS_FILE não foi encontrado! Resultado de $EXP_NAME NÃO foi salvo."
    fi

    # Limpeza final
    sudo pkill -f iperf3 2>/dev/null

    echo "Teste $EXP_NAME concluído com sucesso!"
    echo ""
done

echo "================================="
echo "Todos os testes foram concluídos!"
echo "================================="