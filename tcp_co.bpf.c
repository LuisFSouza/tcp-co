//go:build ignore
#include "vmlinux.h"

#include <bpf/bpf_helpers.h>
#include <bpf/bpf_core_read.h>
#include <bpf/bpf_tracing.h>
#include <bpf/bpf_endian.h>

#define AF_INET 2
#define TCP_CLOSE 7

char LICENSE[] SEC("license") = "GPL";

struct flow_key {
    __u32 src_ip;
    __u32 dst_ip;
    __u16 src_port;
    __u16 dst_port;
} __attribute__((packed));

struct tcp_metrics {
    __u32 snd_cwnd;
    __u32 ssthresh;
    __u32 srtt;
    __u32 retransmissions;
    __u32 duplicate_acks;
    __u64 bytes_acked;

    __u32 packets_out;
    __u32 retrans_out;
    __u32 sndbuf;
    __u8 tcp_state;
    __u8 ca_state;
    char ca_name[16];

    __u64 timestamp_ns;
} __attribute__((packed));

struct {
    __uint(type, BPF_MAP_TYPE_HASH);
    __uint(max_entries, 65535);
    __type(key, struct flow_key);
    __type(value, struct tcp_metrics);
} tcp_connections SEC(".maps");

typedef struct tcp_event {
    struct flow_key key;
    struct tcp_metrics metrics;
} __attribute__((packed)) tcp_event;

struct {
    __uint(type, BPF_MAP_TYPE_RINGBUF);
    __uint(max_entries, 1 << 24);
} tcp_events SEC(".maps");

// Extrai a chave (IPs e Portas) do socket
static __always_inline void extract_flow_key(struct sock *sk, struct flow_key *key) {
    key->src_ip = BPF_CORE_READ(sk, __sk_common.skc_rcv_saddr);
    key->dst_ip = BPF_CORE_READ(sk, __sk_common.skc_daddr);
    key->src_port = BPF_CORE_READ(sk, __sk_common.skc_num);
    key->dst_port = bpf_ntohs(BPF_CORE_READ(sk, __sk_common.skc_dport));
}

// Lê o nome do algoritmo de congestionamento
static __always_inline void extract_ca_name(struct inet_connection_sock *icsk, char *name_buf) {
    const struct tcp_congestion_ops *ca_ops = BPF_CORE_READ(icsk, icsk_ca_ops);
    if (ca_ops) {
        bpf_probe_read_kernel_str(name_buf, 16, BPF_CORE_READ(ca_ops, name));
    } else {
        __builtin_memcpy(name_buf, "unknown\0", 8);
    }
}

// Atualiza as métricas gerais do TCP DIRETAMENTE no ponteiro do mapa
static __always_inline void update_tcp_metrics(struct tcp_sock *tp, struct sock *sk, struct inet_connection_sock *icsk, struct tcp_metrics *metrics) {
    metrics->snd_cwnd = BPF_CORE_READ(tp, snd_cwnd);
    metrics->ssthresh = BPF_CORE_READ(tp, snd_ssthresh);
    metrics->srtt = BPF_CORE_READ(tp, srtt_us) >> 3;
    metrics->retransmissions = BPF_CORE_READ(tp, total_retrans);
    metrics->bytes_acked = BPF_CORE_READ(tp, bytes_acked);
    metrics->packets_out = BPF_CORE_READ(tp, packets_out);
    metrics->retrans_out = BPF_CORE_READ(tp, retrans_out);
    metrics->sndbuf = BPF_CORE_READ(sk, sk_sndbuf);
    metrics->tcp_state = BPF_CORE_READ(sk, __sk_common.skc_state);
    metrics->ca_state = BPF_CORE_READ_BITFIELD_PROBED(icsk, icsk_ca_state);
    metrics->timestamp_ns = bpf_ktime_get_boot_ns();
    extract_ca_name(icsk, metrics->ca_name);
}

static __always_inline struct tcp_metrics *get_or_create_metrics(struct flow_key *key) {
    struct tcp_metrics *metrics = bpf_map_lookup_elem(&tcp_connections, key);
    if (!metrics) {
        struct tcp_metrics new_metrics = {};
        bpf_map_update_elem(&tcp_connections, key, &new_metrics, BPF_ANY);
        metrics = bpf_map_lookup_elem(&tcp_connections, key);
    }
    return metrics;
}

// Envia o estado atual da conexão para o user space via Ring Buffer
static __always_inline void emit_tcp_event(struct flow_key *key, struct tcp_metrics *metrics) {
    struct tcp_event *event;
    event = bpf_ringbuf_reserve(&tcp_events, sizeof(*event), 0);
    if (!event) {
        return; 
    }
    event->key = *key;
    event->metrics = *metrics;
    bpf_ringbuf_submit(event, 0);
}

SEC("tracepoint/tcp/tcp_probe")
int handle_tcp_probe(struct trace_event_raw_tcp_probe *ctx)
{
    // No tcp_probe, a estrutura 'skaddr' guarda o endereço do socket de forma genérica
    struct sock *sk = (struct sock *)ctx->skaddr;
    if (!sk) return 0;
    
    // Filtra apenas tráfego IPv4
    if (BPF_CORE_READ(sk, __sk_common.skc_family) != AF_INET) 
        return 0;

    struct flow_key key = {};
    extract_flow_key(sk, &key);

    struct tcp_metrics *metrics = get_or_create_metrics(&key);
    if (!metrics) return 0;
    
    struct tcp_sock *tp = (struct tcp_sock *)sk;
    struct inet_connection_sock *icsk = (struct inet_connection_sock *)sk;

    // Atualiza com os valores reais no exato momento da transmissão do pacote
    update_tcp_metrics(tp, sk, icsk, metrics);

    emit_tcp_event(&key, metrics);

    return 0;
}

// SEC("fexit/tcp_ack")
// int BPF_PROG(handle_tcp_ack_exit, struct sock *sk, struct sk_buff *skb, int flag, int ret)
// {
//     if (!sk) return 0;
    
//     // Filtra apenas IPv4 para manter a paridade com seu código original
//     if (BPF_CORE_READ(sk, __sk_common.skc_family) != AF_INET) 
//         return 0;

//     struct flow_key key = {};
//     extract_flow_key(sk, &key);

//     struct tcp_metrics *metrics = get_or_create_metrics(&key);
//     if (!metrics) return 0;
    
//     struct tcp_sock *tp = (struct tcp_sock *)sk;
//     struct inet_connection_sock *icsk = (struct inet_connection_sock *)sk;

//     // Atualiza tudo de uma vez com o estado fresco pós-ACK
//     update_tcp_metrics(tp, sk, icsk, metrics);

//     emit_tcp_event(&key, metrics);

//     return 0;
// }

SEC("tracepoint/sock/inet_sock_set_state")
int handle_tcp_state_change(struct trace_event_raw_inet_sock_set_state *ctx)
{
    if (ctx->protocol != 6) return 0; // Protocolo TCP

    struct sock *sk = (struct sock *)ctx->skaddr;
    if (!sk) return 0;

    struct flow_key key = {};
    extract_flow_key(sk, &key);

    struct tcp_sock *tp = (struct tcp_sock *)sk;
    struct inet_connection_sock *icsk = (struct inet_connection_sock *)sk;

    struct tcp_metrics *metrics = get_or_create_metrics(&key);
    if (!metrics) return 0;

    update_tcp_metrics(tp, sk, icsk, metrics);
    metrics->tcp_state = ctx->newstate;

    emit_tcp_event(&key, metrics);
    return 0;
}

SEC("kprobe/tcp_set_ca_state")
int BPF_KPROBE(trace_tcp_set_ca_state, struct sock *sk, const u8 ca_state)
{
    if (!sk) return 0;

    struct flow_key key = {};
    extract_flow_key(sk, &key);

    struct tcp_sock *tp = (struct tcp_sock *)sk;
    struct inet_connection_sock *icsk = (struct inet_connection_sock *)sk;

    struct tcp_metrics *metrics = get_or_create_metrics(&key);
    if (!metrics) return 0;

    update_tcp_metrics(tp, sk, icsk, metrics);
    metrics->ca_state = ca_state;

    emit_tcp_event(&key, metrics);
    return 0;
}

SEC("tracepoint/tcp/tcp_retransmit_skb")
int handle_tcp_retransmit_skb(struct trace_event_raw_tcp_retransmit_skb *ctx)
{
    struct sock *sk = (struct sock *)ctx->skaddr;
    if (!sk) return 0;

    struct flow_key key = {};
    extract_flow_key(sk, &key);

    struct tcp_metrics *metrics = bpf_map_lookup_elem(&tcp_connections, &key);
    if (metrics) {
        struct tcp_sock *tp = (struct tcp_sock *)sk;
        struct inet_connection_sock *icsk = (struct inet_connection_sock *)sk;
        update_tcp_metrics(tp, sk, icsk, metrics);
        emit_tcp_event(&key, metrics);
    }
    return 0;
}