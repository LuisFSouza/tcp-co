//go:build ignore
#include "vmlinux.h"

#include <bpf/bpf_helpers.h>
#include <bpf/bpf_core_read.h>
#include <bpf/bpf_tracing.h>
#include <bpf/bpf_endian.h>

#define AF_INET 2

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


typedef struct tcp_event {
    struct flow_key key;
    struct tcp_metrics metrics;
} __attribute__((packed)) tcp_event;

struct {
    __uint(type, BPF_MAP_TYPE_HASH);
    __uint(max_entries, 65535);
    __type(key, struct flow_key);
    __type(value, struct tcp_metrics);
} tcp_connections SEC(".maps");

struct {
    __uint(type, BPF_MAP_TYPE_RINGBUF);
    __uint(max_entries, 1 << 24);
} tcp_events SEC(".maps");

SEC("tracepoint/tcp/tcp_probe")
int handle_tcp_probe(struct trace_event_raw_tcp_probe *ctx)
{
    if (ctx->family != AF_INET)
        return 0;

    struct sock *sk = (struct sock *)ctx->skaddr;
    if (!sk)
        return 0;

    struct tcp_sock *tp = (struct tcp_sock *)sk;
    struct inet_connection_sock *icsk = (struct inet_connection_sock *)sk;

    struct flow_key key;

    key.src_ip = BPF_CORE_READ(sk, __sk_common.skc_rcv_saddr);
    key.dst_ip = BPF_CORE_READ(sk, __sk_common.skc_daddr);

    key.src_port = BPF_CORE_READ(sk, __sk_common.skc_num);
    key.dst_port = bpf_ntohs(BPF_CORE_READ(sk, __sk_common.skc_dport));
    
    struct tcp_metrics metrics;

    metrics.snd_cwnd = ctx->snd_cwnd;
    metrics.ssthresh = ctx->ssthresh;
    metrics.srtt = ctx->srtt;

    metrics.retransmissions = BPF_CORE_READ(tp, total_retrans);
    metrics.duplicate_acks = 0;
    metrics.bytes_acked = BPF_CORE_READ(tp, bytes_acked);

    metrics.packets_out = BPF_CORE_READ(tp, packets_out);
    metrics.retrans_out = BPF_CORE_READ(tp, retrans_out);
    metrics.sndbuf = BPF_CORE_READ(sk, sk_sndbuf);

    metrics.tcp_state = BPF_CORE_READ(sk, __sk_common.skc_state);
    metrics.ca_state = BPF_CORE_READ_BITFIELD_PROBED(icsk, icsk_ca_state);

    metrics.timestamp_ns = bpf_ktime_get_boot_ns();

    const struct tcp_congestion_ops *ca_ops;
    ca_ops = BPF_CORE_READ(icsk, icsk_ca_ops);

    if (ca_ops) {
        bpf_probe_read_kernel_str(
            metrics.ca_name,
            sizeof(metrics.ca_name),
            BPF_CORE_READ(ca_ops, name)
        );
    } else {
        metrics.ca_name[0] = 'u';
        metrics.ca_name[1] = 'n';
        metrics.ca_name[2] = 'k';
        metrics.ca_name[3] = 'n';
        metrics.ca_name[4] = 'o';
        metrics.ca_name[5] = 'w';
        metrics.ca_name[6] = 'n';
        metrics.ca_name[7] = '\0';
        metrics.ca_name[8] = '\0';
        metrics.ca_name[9] = '\0';
        metrics.ca_name[10] = '\0';
        metrics.ca_name[11] = '\0';
        metrics.ca_name[12] = '\0';
        metrics.ca_name[13] = '\0';
        metrics.ca_name[14] = '\0';
        metrics.ca_name[15] = '\0';
    }

    bpf_map_update_elem(&tcp_connections, &key, &metrics, BPF_ANY);

    struct tcp_event *event;
    event = bpf_ringbuf_reserve(&tcp_events, sizeof(*event), 0);
    if (!event)
        return 0;

    event->key = key;
    event->metrics = metrics;

    bpf_ringbuf_submit(event, 0);

    return 0;
}

SEC("tracepoint/sock/inet_sock_set_state")
int handle_tcp_state_change(struct trace_event_raw_inet_sock_set_state *ctx)
{
    if (ctx->protocol != 6)
        return 0;

    struct sock *sk = (struct sock *)ctx->skaddr;
    if (!sk)
        return 0;

    struct tcp_sock *tp = (struct tcp_sock *)sk;
    struct inet_connection_sock *icsk = (struct inet_connection_sock *)sk;

    struct tcp_event *event;
    event = bpf_ringbuf_reserve(&tcp_events, sizeof(*event), 0);
    if (!event)
        return 0;

    event->key.src_ip = BPF_CORE_READ(sk, __sk_common.skc_rcv_saddr);
    event->key.dst_ip = BPF_CORE_READ(sk, __sk_common.skc_daddr);
    event->key.src_port = BPF_CORE_READ(sk, __sk_common.skc_num);
    event->key.dst_port = bpf_ntohs(BPF_CORE_READ(sk, __sk_common.skc_dport));

    event->metrics.snd_cwnd = BPF_CORE_READ(tp, snd_cwnd);
    event->metrics.ssthresh = BPF_CORE_READ(tp, snd_ssthresh);
    event->metrics.srtt = BPF_CORE_READ(tp, srtt_us);
    event->metrics.retransmissions = BPF_CORE_READ(tp, total_retrans);
    event->metrics.duplicate_acks = 0;
    event->metrics.bytes_acked = BPF_CORE_READ(tp, bytes_acked);

    event->metrics.packets_out = BPF_CORE_READ(tp, packets_out);
    event->metrics.retrans_out = BPF_CORE_READ(tp, retrans_out);
    event->metrics.sndbuf = BPF_CORE_READ(sk, sk_sndbuf);

    event->metrics.tcp_state = ctx->newstate;
    event->metrics.ca_state = BPF_CORE_READ_BITFIELD_PROBED(icsk, icsk_ca_state);
    event->metrics.timestamp_ns = bpf_ktime_get_boot_ns();

    const struct tcp_congestion_ops *ca_ops;
    ca_ops = BPF_CORE_READ(icsk, icsk_ca_ops);

    if (ca_ops) {
        bpf_probe_read_kernel_str(
            event->metrics.ca_name,
            sizeof(event->metrics.ca_name),
            BPF_CORE_READ(ca_ops, name)
        );
    } else {
        event->metrics.ca_name[0] = 'u';
        event->metrics.ca_name[1] = 'n';
        event->metrics.ca_name[2] = 'k';
        event->metrics.ca_name[3] = 'n';
        event->metrics.ca_name[4] = 'o';
        event->metrics.ca_name[5] = 'w';
        event->metrics.ca_name[6] = 'n';
        event->metrics.ca_name[7] = '\0';
    }

    bpf_ringbuf_submit(event, 0);

    return 0;
}