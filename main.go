package main

import (
	"bufio"
	"bytes"
	"encoding/binary"
	"encoding/csv"
	"flag"
	"fmt"
	"log"
	"net"
	"net/smtp"
	"os"
	"os/signal"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/cilium/ebpf/link"
	"github.com/cilium/ebpf/ringbuf"
	"github.com/cilium/ebpf/rlimit"
)

//go:generate go run github.com/cilium/ebpf/cmd/bpf2go -target amd64 -type flow_key -type tcp_metrics bpf tcp_co.bpf.c

// Estrutura para armazenar os eventos de TCP recebidos do eBPF
type tcpEvent struct {
	Key     bpfFlowKey
	Metrics bpfTcpMetrics
}

// Estutura para guardar o último estado conhecido de cada conexão
type tcpHistory struct {
	lastCwnd            uint32
	lastRetransmissions uint32
}

// Limiar de notificação para queda de CWND com aumento de retransmissão (50%)
const dropPercentage = 0.50

func main() {
	outputPath := flag.String("o", "tcp_metrics.csv", "Caminho do arquivo CSV de saída")
	durationSec := flag.Int("duration", 0, "Encerra automaticamente após N segundos (0 = roda até Ctrl+C)")
	intervalMs := flag.Int("interval", 50, "Intervalo mínimo em ms entre amostras gravadas no CSV por conexão (0 = grava tudo, sem limite)")
	flag.Parse()

	sampleInterval := time.Duration(*intervalMs) * time.Millisecond

	if err := rlimit.RemoveMemlock(); err != nil {
		log.Fatalf("Falha ao remover memlock rlimit: %v", err)
	}

	var objs bpfObjects
	if err := loadBpfObjects(&objs, nil); err != nil {
		log.Fatalf("Falha ao carregar objetos eBPF: %v", err)
	}
	defer objs.Close()

	linkAck, err := link.AttachTracing(link.TracingOptions{
		Program: objs.HandleTcpAckExit,
	})
	if err != nil {
		log.Fatalf("Falha ao anexar fexit/tcp_ack: %v", err)
	}
	defer linkAck.Close()

	linkFastretrans, err := link.AttachTracing(link.TracingOptions{
		Program: objs.HandleFastretransAlert,
	})
	if err != nil {
		log.Fatalf("Falha ao anexar fentry/tcp_fastretrans_alert: %v", err)
	}
	defer linkFastretrans.Close()

	linkState, err := link.Tracepoint("sock", "inet_sock_set_state", objs.HandleTcpStateChange, nil)
	if err != nil {
		log.Fatalf("Falha ao anexar tracepoint sock/inet_sock_set_state: %v", err)
	}
	defer linkState.Close()

	linkCa, err := link.Kprobe("tcp_set_ca_state", objs.TraceTcpSetCaState, nil)
	if err != nil {
		log.Fatalf("Falha ao anexar kprobe tcp_set_ca_state: %v", err)
	}
	defer linkCa.Close()

	linkRetrans, err := link.Tracepoint("tcp", "tcp_retransmit_skb", objs.HandleTcpRetransmitSkb, nil)
	if err != nil {
		log.Fatalf("Falha ao anexar tracepoint tcp_retransmit_skb: %v", err)
	}
	defer linkRetrans.Close()

	linkProbe, err := link.Tracepoint("tcp", "tcp_probe", objs.HandleTcpProbe, nil)
	if err != nil {
		log.Fatalf("Falha ao anexar tracepoint tcp/tcp_probe: %v", err)
	}
	defer linkProbe.Close()

	fmt.Println("Hooks anexados: fexit/tcp_ack, fentry/tcp_fastretrans_alert, tracepoint sock/inet_sock_set_state, kprobe tcp_set_ca_state, tracepoint tcp_retransmit_skb, tracepoint tcp/tcp_probe")

	rd, err := ringbuf.NewReader(objs.TcpEvents)
	if err != nil {
		log.Fatalf("Falha ao abrir ringbuf: %v", err)
	}
	defer rd.Close()

	if dir := filepath.Dir(*outputPath); dir != "." && dir != "" {
		if err := os.MkdirAll(dir, 0755); err != nil {
			log.Fatalf("Falha ao criar diretório de saída %s: %v", dir, err)
		}
	}

	csvFile, err := os.Create(*outputPath)
	if err != nil {
		log.Fatalf("Falha ao criar CSV: %v", err)
	}
	defer csvFile.Close()

	writer := csv.NewWriter(csvFile)
	defer writer.Flush()

	headers := []string{
		"Data_Hora", "IP_Origem", "IP_Destino", "Porta_Origem",
		"Porta_Destino", "CWND", "SSThresh", "SRTT_us", "Retransmissions",
		"Duplicate_ACKs", "Bytes_Acked", "Packets_Out", "Retrans_Out",
		"Snd_Buffer", "TCP_State", "CA_State", "Algoritmo_CA",
	}

	if err := writer.Write(headers); err != nil {
		log.Fatalf("Falha ao escrever cabeçalho: %v", err)
	}

	writer.Flush()
	if err := writer.Error(); err != nil {
		log.Fatalf("Erro ao gravar cabeçalho no CSV: %v", err)
	}

	bootTime, err := getBootTime()
	if err != nil {
		log.Fatalf("Falha ao obter boot time: %v", err)
	}

	loc, err := time.LoadLocation("America/Sao_Paulo")
	if err != nil {
		loc = time.Local
	}

	fmt.Printf("📊 Gravando histórico em %s\n", *outputPath)
	intervalNs := uint64(sampleInterval.Nanoseconds())
	if intervalNs > 0 {
		fmt.Printf("⏱️  Intervalo mínimo entre amostras por conexão: %dms\n", *intervalMs)
	} else {
		fmt.Println("⏱️  Throttling desativado (gravando todos os eventos, CSV pode ficar grande)")
	}
	fmt.Println("Pressione Ctrl+C para encerrar.")

	stopChan := make(chan os.Signal, 1)
	signal.Notify(stopChan, os.Interrupt, syscall.SIGTERM)

	if *durationSec > 0 {
		go func() {
			time.Sleep(time.Duration(*durationSec) * time.Second)
			stopChan <- syscall.SIGTERM
		}()
	}

	go func() {
		<-stopChan
		fmt.Printf("\n💾 Finalizando %s...\n", *outputPath)
		rd.Close()
	}()

	// Mapa para armazenar o último estado conhecido de cada conexão TCP
	historyMap := make(map[string]tcpHistory)
	lastWrittenNs := make(map[string]uint64)
	count := 0
	skipped := 0

	for {
		record, err := rd.Read()
		if err != nil {
			break
		}

		var event tcpEvent
		if err := binary.Read(bytes.NewBuffer(record.RawSample), binary.LittleEndian, &event); err != nil {
			log.Printf("Erro ao decodificar evento: %v", err)
			continue
		}

		// ID da conexão TCP
		connKey := fmt.Sprintf("%s:%d -> %s:%d",
			intToIP(event.Key.SrcIp).String(), event.Key.SrcPort,
			intToIP(event.Key.DstIp).String(), event.Key.DstPort,
		)

		// CWND e retransmissões no momento
		currentCwnd := event.Metrics.SndCwnd
		currentRetrans := uint32(event.Metrics.Retransmissions)

		// Verificação de queda de CWND com aumento de retransmissões
		// (roda em TODO evento, independente da amostra ser gravada ou não,
		// pra não perder detecção de anomalias por causa do throttling)
		if history, exists := historyMap[connKey]; exists {
			// Se as retransmissões subiram e a cwnd atual diminuiu
			if currentRetrans > history.lastRetransmissions && currentCwnd < history.lastCwnd {
				// Porcentagem da queda
				drop := float64(history.lastCwnd-currentCwnd) / float64(history.lastCwnd)

				if drop >= dropPercentage {
					fmt.Printf("\n⚠️ Queda de CWND > 50%% com retransmissão!\n")
					fmt.Printf("Conexão: %s\n", connKey)
					fmt.Printf("CWND: %d -> %d (Queda de %.2f%%)\n", history.lastCwnd, currentCwnd, drop*100)
					fmt.Printf("Retransmissões: %d -> %d\n\n", history.lastRetransmissions, currentRetrans)

					// Notificação via email
					sendEmailAlert(connKey, history.lastCwnd, currentCwnd, drop, history.lastRetransmissions, currentRetrans)
				}
			}
		}

		// Atualiza o mapa de histórico de conexão
		historyMap[connKey] = tcpHistory{
			lastCwnd:            currentCwnd,
			lastRetransmissions: currentRetrans,
		}

		// Throttling: só grava uma amostra por conexão a cada "intervalNs".
		// Isso reduz drasticamente o tamanho do CSV sem perder a forma da curva.
		if intervalNs > 0 {
			last, seen := lastWrittenNs[connKey]
			if seen && event.Metrics.TimestampNs-last < intervalNs {
				skipped++
				continue
			}
		}
		lastWrittenNs[connKey] = event.Metrics.TimestampNs

		row := eventToCSVRow(event, bootTime, loc)

		if err := writer.Write(row); err != nil {
			log.Printf("Erro ao escrever CSV: %v", err)
			continue
		}

		writer.Flush()
		if err := writer.Error(); err != nil {
			log.Printf("Erro ao gravar CSV: %v", err)
			continue
		}

		count++
		if count%20 == 0 {
			fmt.Printf("Amostras gravadas: %d (descartadas por throttling: %d)\n", count, skipped)
		}
	}

	writer.Flush()
	fmt.Printf("\n✅ Total de amostras gravadas: %d | descartadas por throttling: %d\n", count, skipped)
}

func eventToCSVRow(event tcpEvent, bootTime time.Time, loc *time.Location) []string {
	metrics := event.Metrics
	key := event.Key

	eventTime := bootTime.Add(time.Duration(metrics.TimestampNs)).In(loc)
	dataHora := eventTime.Format("2006-01-02 15:04:05.000000000")

	return []string{
		dataHora,
		intToIP(key.SrcIp).String(),
		intToIP(key.DstIp).String(),
		strconv.Itoa(int(key.SrcPort)),
		strconv.Itoa(int(key.DstPort)),
		strconv.FormatUint(uint64(metrics.SndCwnd), 10),
		strconv.FormatUint(uint64(metrics.Ssthresh), 10),
		strconv.FormatUint(uint64(metrics.Srtt), 10),
		strconv.FormatUint(uint64(metrics.Retransmissions), 10),
		strconv.FormatUint(uint64(metrics.DuplicateAcks), 10),
		strconv.FormatUint(metrics.BytesAcked, 10),
		strconv.FormatUint(uint64(metrics.PacketsOut), 10),
		strconv.FormatUint(uint64(metrics.RetransOut), 10),
		strconv.FormatUint(uint64(metrics.Sndbuf), 10),
		parseTCPState(metrics.TcpState),
		parseCAState(metrics.CaState),
		parseCaName(metrics.CaName),
	}
}

func getBootTime() (time.Time, error) {
	file, err := os.Open("/proc/stat")
	if err != nil {
		return time.Time{}, err
	}
	defer file.Close()

	scanner := bufio.NewScanner(file)

	for scanner.Scan() {
		line := scanner.Text()

		if strings.HasPrefix(line, "btime ") {
			parts := strings.Fields(line)
			if len(parts) != 2 {
				return time.Time{}, fmt.Errorf("formato inválido de btime")
			}

			bootUnix, err := strconv.ParseInt(parts[1], 10, 64)
			if err != nil {
				return time.Time{}, err
			}

			return time.Unix(bootUnix, 0), nil
		}
	}

	if err := scanner.Err(); err != nil {
		return time.Time{}, err
	}

	return time.Time{}, fmt.Errorf("btime não encontrado em /proc/stat")
}

func intToIP(nn uint32) net.IP {
	ip := make(net.IP, 4)
	ip[0] = byte(nn & 0xFF)
	ip[1] = byte((nn >> 8) & 0xFF)
	ip[2] = byte((nn >> 16) & 0xFF)
	ip[3] = byte((nn >> 24) & 0xFF)
	return ip
}

func parseCaName(caName [16]int8) string {
	var buf []byte
	for _, b := range caName {
		if b == 0 {
			break
		}
		buf = append(buf, byte(b))
	}
	return string(buf)
}

func parseTCPState(state uint8) string {
	switch state {
	case 1:
		return "ESTABLISHED"
	case 2:
		return "SYN_SENT"
	case 3:
		return "SYN_RECV"
	case 4:
		return "FIN_WAIT1"
	case 5:
		return "FIN_WAIT2"
	case 6:
		return "TIME_WAIT"
	case 7:
		return "CLOSE"
	case 8:
		return "CLOSE_WAIT"
	case 9:
		return "LAST_ACK"
	case 10:
		return "LISTEN"
	case 11:
		return "CLOSING"
	case 12:
		return "NEW_SYN_RECV"
	default:
		return fmt.Sprintf("UNKNOWN(%d)", state)
	}
}

func parseCAState(state uint8) string {
	switch state {
	case 0:
		return "Open"
	case 1:
		return "Disorder"
	case 2:
		return "CWR"
	case 3:
		return "Recovery"
	case 4:
		return "Loss"
	default:
		return fmt.Sprintf("UNKNOWN(%d)", state)
	}
}

func sendEmailAlert(connKey string, lastCwnd, currentCwnd uint32, drop float64, lastRetrans, currentRetrans uint32) {
	smtpHost := "127.0.0.1"
	smtpPort := "1025"

	from := "ebpf-monitor@network.local"
	to := []string{"exemplo-email@network.local"}
	subject := "Subject: ⚠️ Degradação de Performance TCP\n"
	mime := "MIME-version: 1.0;\nContent-Type: text/html; charset=\"UTF-8\";\n\n"

	body := fmt.Sprintf(`
		<div style="font-family: sans-serif; padding: 15px; border: 1px solid #ddd; border-radius: 5px;">
			<h2 style="color: #d9534f; margin-top: 0;">Degradação de Performance Detectada</h2>
			<p>O monitoramento eBPF identificou um comportamento anômalo na rede.</p>
			<hr style="border: 0; border-top: 1px solid #eee;">
			<p><strong>Conexão Afetada:</strong> <code style="background: #f4f4f4; padding: 2px 5px; border-radius: 3px;">%s</code></p>
			<ul>
				<li><strong>Janela de Congestionamento (CWND):</strong> de %d para %d (<span style="color: #d9534f; font-weight: bold;">Queda de %.2f%%</span>)</li>
				<li><strong>Retransmissões no Intervalo:</strong> de %d para %d</li>
			</ul>
			<br>
			<small style="color: #777;">Alerta gerado via monitoramento eBPF.</small>
		</div>
	`, connKey, lastCwnd, currentCwnd, drop*100, lastRetrans, currentRetrans)

	msg := []byte(subject + mime + body)

	err := smtp.SendMail(smtpHost+":"+smtpPort, nil, from, to, msg)
	if err != nil {
		log.Printf("Falha ao disparar e-mail de alerta: %v", err)
		return
	}
	log.Println("Notificação de alerta enviada para a caixa de testes SMTP local.")
}