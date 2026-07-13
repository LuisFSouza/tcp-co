import argparse
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import LineCollection


def parse_args():
    parser = argparse.ArgumentParser(description="TCP-CO Dashboard")
    parser.add_argument(
        "--csv",
        dest="csv_file",
        default="./tcp_metrics.csv",
        help="Caminho para o arquivo CSV de métricas TCP (padrão: ./tcp_metrics.csv)",
    )
    # parse_known_args evita erro caso o Streamlit injete argumentos extras
    args, _ = parser.parse_known_args()
    return args


args = parse_args()
CSV_FILE = args.csv_file

st.set_page_config(page_title="TCP-CO Dashboard", layout="wide")
st.title("TCP-CO — TCP Congestion Observatory")
st.caption(f"Arquivo carregado: `{CSV_FILE}`")

try:
    df = pd.read_csv(CSV_FILE)
except Exception as e:
    st.error(f"Erro ao ler o arquivo CSV: {e}")
    st.stop()

required_columns = [
    "Data_Hora", "IP_Origem", "IP_Destino", "Porta_Origem", "Porta_Destino",
    "CWND", "SSThresh", "SRTT_us", "Retransmissions", "Duplicate_ACKs", 
    "Bytes_Acked", "Packets_Out", "Retrans_Out", "Snd_Buffer", "TCP_State", 
    "CA_State", "Algoritmo_CA"
]

missing = [col for col in required_columns if col not in df.columns]
if missing:
    st.error(f"Colunas ausentes no CSV: {missing}")
    st.stop()

df["Data_Hora"] = pd.to_datetime(df["Data_Hora"], format="%Y-%m-%d %H:%M:%S.%f", errors="coerce")

numeric_cols = [
    "CWND", "SSThresh", "SRTT_us", "Retransmissions", "Duplicate_ACKs", "Bytes_Acked",
    "Packets_Out", "Retrans_Out", "Snd_Buffer", "Porta_Origem", "Porta_Destino"
]
for col in numeric_cols:
    df[col] = pd.to_numeric(df[col], errors="coerce")

df.loc[df["SSThresh"] == 2147483647, "SSThresh"] = pd.NA
df = df.dropna(subset=["Data_Hora"])
df = df[(df["Porta_Origem"] > 0) & (df["Porta_Destino"] > 0)].copy()
df["Origem"] = df["IP_Origem"].astype(str) + ":" + df["Porta_Origem"].astype(int).astype(str)
df["Destino"] = df["IP_Destino"].astype(str) + ":" + df["Porta_Destino"].astype(int).astype(str)
df["Conexao"] = df["Origem"] + " → " + df["Destino"]
df = df.sort_values("Data_Hora").reset_index(drop=True)
df["Opcao_Comp"] = df["Algoritmo_CA"].astype(str) + " (" + df["Conexao"] + ")"

tab1, tab2 = st.tabs(["📊 Análise por Conexão", "🔄 Comparação entre Algoritmos"])

with tab1:
    connections = sorted(df["Conexao"].unique())
    if not connections:
        st.warning("Nenhuma conexão TCP encontrada no CSV.")
    else:
        selected_connection = st.selectbox("Selecione a conexão TCP para detalhar:", connections)
        
        filtered = df[df["Conexao"] == selected_connection].copy()
        filtered = filtered.sort_values("Data_Hora").reset_index(drop=True)
        filtered["Tempo_ms"] = (filtered["Data_Hora"] - filtered["Data_Hora"].min()).dt.total_seconds() * 1000
        
        plot_df = filtered.copy()

        # Grafico CWND x Tempo com cores baseadas no estado de congestionamento
        cores_ca = {
            "Open": "#2ca02c",      # Verde (Estável)
            "Disorder": "#9467bd",  # Roxo (Disorder)
            "CWR": "#bcbd22",       # Amarelo (CWR)
            "Recovery": "#e377c2",  # Rosa (Recovery)
            "Loss": "#d62728"       # Vermelho (Loss)
        }
        labels_ca = {
            "Open": "Open (Normal)",
            "Disorder": "Disorder (ACK Duplicado)",
            "CWR": "CWR (Redução Preventiva)",
            "Recovery": "Recovery (Fast Retransmit)",
            "Loss": "Loss (Timeout RTO)"
        }

        st.subheader("CWND e SSThresh × Tempo")
        fig_cwnd, ax_cwnd = plt.subplots(figsize=(14, 8)) 
        x = plot_df["Tempo_ms"].values
        y = plot_df["CWND"].values
        states = plot_df["CA_State"].fillna("Open").astype(str).values
        points = np.array([x, y]).T.reshape(-1, 1, 2)
        segments = np.concatenate([points[:-1], points[1:]], axis=1)
        segment_colors = [cores_ca.get(st, "#7f7f7f") for st in states[:-1]]
        
        lc = LineCollection(segments, colors=segment_colors, linewidths=1.0) 
        ax_cwnd.add_collection(lc)
        ax_cwnd.autoscale_view()

        ssthresh_plot = plot_df.dropna(subset=["SSThresh"])
        if not ssthresh_plot.empty:
            ax_cwnd.plot(ssthresh_plot["Tempo_ms"], ssthresh_plot["SSThresh"], linewidth=1.2, color="#ff7f0e", label="SSThresh")
            ax_cwnd.legend(loc="upper right")
        ax_cwnd.set_xlabel("Tempo (ms)")
        ax_cwnd.set_ylabel("Segmentos TCP")
        ax_cwnd.grid(True, alpha=0.3)
        st.pyplot(fig_cwnd)

        st.markdown("**Legenda de Cores da Janela (CWND) pelo Estado de Congestionamento (CA State):**")
        cols_legenda = st.columns(5)
        for idx, (cod, cor) in enumerate(cores_ca.items()):
            with cols_legenda[idx]:
                st.markdown(f"<span style='color:{cor}; font-weight:bold;'>■</span> {labels_ca[cod]}", unsafe_allow_html=True)

        # Gráfico SRTT x Tempo
        st.subheader("SRTT × Tempo")
        fig_rtt, ax_rtt = plt.subplots(figsize=(14, 4))
        ax_rtt.plot(plot_df["Tempo_ms"], plot_df["SRTT_us"], color="#2ca02c", linewidth=1.2, label="RTT")
        ax_rtt.set_xlabel("Tempo (ms)")
        ax_rtt.set_ylabel("RTT (µs)")
        ax_rtt.grid(True, alpha=0.3)
        ax_rtt.legend()
        st.pyplot(fig_rtt)

        # Gráfico Retransmissions x Tempo
        st.subheader("Retransmissões × Tempo")
        fig_retrans, ax_retrans = plt.subplots(figsize=(14, 4))
        ax_retrans.plot(plot_df["Tempo_ms"], plot_df["Retransmissions"], linewidth=1.2, color="#9467bd", label="Retransmissões")
        ax_retrans.set_xlabel("Tempo (ms)")
        ax_retrans.set_ylabel("Total de Pacotes Retransmitidos")
        ax_retrans.grid(True, alpha=0.3)
        ax_retrans.legend()
        st.pyplot(fig_retrans)

        # Gráfico Bytes Reconhecidos x Tempo
        st.subheader("Bytes Reconhecidos × Tempo")
        fig_bytes, ax_bytes = plt.subplots(figsize=(14, 4))
        ax_bytes.plot(plot_df["Tempo_ms"], plot_df["Bytes_Acked"], linewidth=1.2, color="#8c564b", label="Bytes Reconhecidos")
        ax_bytes.set_xlabel("Tempo (ms)")
        ax_bytes.set_ylabel("Bytes")
        ax_bytes.grid(True, alpha=0.3)
        ax_bytes.legend()
        st.pyplot(fig_bytes)

        # Gráfico Pacotes em Trânsito x Tempo
        st.subheader("Pacotes em Trânsito × Tempo")
        fig_packets, ax_packets = plt.subplots(figsize=(14, 4))
        ax_packets.plot(plot_df["Tempo_ms"], plot_df["Packets_Out"], linewidth=1.2, color="#17becf", label="Pacotes em Trânsito")
        ax_packets.set_xlabel("Tempo (ms)")
        ax_packets.set_ylabel("Pacotes")
        ax_packets.grid(True, alpha=0.3)
        ax_packets.legend()
        st.pyplot(fig_packets)

        # Gráfico Retransmissões em Trânsito x Tempo
        st.subheader("Retransmissões em Trânsito × Tempo")
        fig_retrans_out, ax_retrans_out = plt.subplots(figsize=(14, 4))
        ax_retrans_out.plot(plot_df["Tempo_ms"], plot_df["Retrans_Out"], linewidth=1.2, color="#d62728", label="Retransmissões em Trânsito")
        ax_retrans_out.set_xlabel("Tempo (ms)")
        ax_retrans_out.set_ylabel("Pacotes")
        ax_retrans_out.grid(True, alpha=0.3)
        ax_retrans_out.legend()
        st.pyplot(fig_retrans_out)

        # Gráfico Send Buffer x Tempo
        st.subheader("Send Buffer × Tempo")
        fig_buffer, ax_buffer = plt.subplots(figsize=(14, 4))
        ax_buffer.plot(plot_df["Tempo_ms"], plot_df["Snd_Buffer"], linewidth=1.2, color="#7f7f7f", label="Send Buffer")
        ax_buffer.set_xlabel("Tempo (ms)")
        ax_buffer.set_ylabel("Bytes")
        ax_buffer.grid(True, alpha=0.3)
        ax_buffer.legend()
        st.pyplot(fig_buffer)
        
        # Gráfico Throughput x Tempo
        st.subheader("Throughput × Tempo")

        try:
            df_thr_calc = plot_df[['Data_Hora', 'Bytes_Acked']].copy()
            df_thr_calc.set_index('Data_Hora', inplace=True)
            df_thr_calc['Bytes_Novos'] = df_thr_calc['Bytes_Acked'].diff().fillna(0)
            
            df_resampled = df_thr_calc['Bytes_Novos'].resample('1s').sum().to_frame()

            duracao_janela_segundos = 1.0
            
            df_resampled['Throughput_Mbps'] = (df_resampled['Bytes_Novos'] * 8) / (duracao_janela_segundos * 1_000_000)
            
            df_resampled['Tempo_ms'] = (df_resampled.index - df_resampled.index.min()).total_seconds() * 1000

            fig_thr, ax_thr = plt.subplots(figsize=(14, 4))
            ax_thr.plot(df_resampled["Tempo_ms"], df_resampled["Throughput_Mbps"], 
                        linewidth=2, color="#1f77b4", marker='o', label="Vazão (Janela de 1s)")
            
            ax_thr.set_xlabel("Tempo (ms)")
            ax_thr.set_ylabel("Vazão (Mbps)")
            ax_thr.grid(True, alpha=0.3, linestyle="--")
            ax_thr.legend()
            
            st.pyplot(fig_thr)

        except Exception as e:
            st.error(f"Erro ao calcular Throughput por segundo: {e}")
        tabela = filtered.drop(columns=["Conexao", "Opcao_Comp"], errors="ignore").rename(columns={
            "Data_Hora": "Horário",
            "Origem": "Origem",
            "Destino": "Destino",
            "CWND": "Janela de Congestionamento",
            "SSThresh": "Limiar de Congestionamento",
            "SRTT_us": "RTT suavizado",
            "Retransmissions": "Retransmissões",
            "Duplicate_ACKs": "Acks duplicados",
            "Bytes_Acked": "Bytes reconhecidos",
            "Packets_Out": "Pacotes em trânsito",
            "Retrans_Out": "Retransmissões em trânsito",
            "Snd_Buffer": "Buffer de envio",
            "TCP_State": "Estado TCP",
            "CA_State": "Estado de Controle de Congestionamento",
            "Algoritmo_CA": "Algoritmo de Controle de Congestionamento",
        })

        ordem_colunas = ["Horário", "Origem", "Destino", "Janela de Congestionamento",
                        "Limiar de Congestionamento", "RTT suavizado", "Retransmissões",
                        "Acks duplicados", "Bytes reconhecidos", "Pacotes em trânsito",
                        "Retransmissões em trânsito", "Buffer de envio", "Estado TCP",
                        "Estado de Controle de Congestionamento",
                        "Algoritmo de Controle de Congestionamento"]
        
        tabela = tabela[[col for col in ordem_colunas if col in tabela.columns]]

        st.dataframe(tabela)
        
        st.subheader("Linha do Tempo de Transições de Estados TCP")

        try:
            filtered["Estado_Mudou"] = filtered["TCP_State"] != filtered["TCP_State"].shift(1)
            df_changes = filtered[filtered["Estado_Mudou"]].copy().reset_index(drop=True)
            
            df_changes["Fim_ms"] = df_changes["Tempo_ms"].shift(-1)
            df_changes["Fim_ms"] = df_changes["Fim_ms"].fillna(filtered["Tempo_ms"].max())
            df_changes["Duracao_ms"] = df_changes["Fim_ms"] - df_changes["Tempo_ms"]
            
            total_estados = len(df_changes)
            
            largura_bloco_fixo = 1.0
            
            fig_timeline, ax_timeline = plt.subplots(figsize=(14, 3.5))
            
            cores_estados = {
                "ESTABLISHED": "#2ca02c",
                "SYN_SENT": "#1f77b4",
                "SYN_RECV": "#aec7e8",
                "FIN_WAIT1": "#ff7f0e",
                "FIN_WAIT2": "#ffbb78",
                "TIME_WAIT": "#98df8a",
                "CLOSE": "#d62728",
                "CLOSE_WAIT": "#ff9896",
                "LAST_ACK": "#9467bd",
                "CLOSING": "#c5b0d5",
                "LISTEN": "#17becf",
                "NEW_SYN_RECV": "#bcbd22"
            }

            for i, row in df_changes.iterrows():
                estado = str(row["TCP_State"])
                cor = cores_estados.get(estado, "#7f7f7f")
                
                ax_timeline.barh(y=0, width=largura_bloco_fixo, left=i, 
                                 color=cor, edgecolor="black", height=0.5, label=estado)
                
                ax_timeline.text(i + 0.5, 0.08, estado, ha="center", va="center", 
                                 color="white", fontweight="bold", fontsize=10)
                
                ax_timeline.text(i + 0.5, -0.08, f"{int(row['Tempo_ms'])} ms", ha="center", va="center", 
                                 color="white", fontsize=8, style="italic")

            ax_timeline.set_title("Diagrama de Sequência e Transição de Estados TCP", fontsize=12, pad=35)
            ax_timeline.set_yticks([])
            ax_timeline.set_xticks([])
            ax_timeline.set_ylim(-0.5, 0.5)
            ax_timeline.set_xlim(-0.2, total_estados + 0.2)
            
            handles, labels = ax_timeline.get_legend_handles_labels()
            by_label = dict(zip(labels, handles))
            
            ax_timeline.legend(by_label.values(), by_label.keys(), 
                               loc='lower center', 
                               bbox_to_anchor=(0.5, 1.02), 
                               ncol=6, 
                               fontsize=9, 
                               frameon=False)
            
            fig_timeline.tight_layout()
            st.pyplot(fig_timeline)

            st.markdown("**Sequência Temporal Provida (Fluxo de Estados):**")
            sequencia_str = " ➔ ".join([f"`{row['TCP_State']}` ({int(row['Tempo_ms'])} ms)" for _, row in df_changes.iterrows()])
            st.write(sequencia_str)

        except Exception as e:
            st.error(f"Erro ao processar linha do tempo de estados: {e}")

with tab2:
    st.subheader("Gráfico Comparativo: Algoritmos na Mesma Linha do Tempo")
    opcoes_disponiveis = sorted(df["Opcao_Comp"].unique())
    
    if len(opcoes_disponiveis) == 0:
        st.info("Gere tráfego para realizar a comparação.")
    else:
        selecionados = st.multiselect(
            "Selecione os fluxos/algoritmos para sobrepor nos gráficos:",
            opcoes_disponiveis,
            default=[]
        )
        
        if selecionados:
            dados_fluxos = {}
            dados_throughput = {}

            for opcao in selecionados:
                df_comp = df[df["Opcao_Comp"] == opcao].copy()
                df_comp = df_comp.sort_values("Data_Hora").reset_index(drop=True)
                df_comp["Tempo_ms"] = (df_comp["Data_Hora"] - df_comp["Data_Hora"].min()).dt.total_seconds() * 1000
                dados_fluxos[opcao] = df_comp

                try:
                    df_thr_calc = df_comp[['Data_Hora', 'Bytes_Acked']].copy()
                    df_thr_calc.set_index('Data_Hora', inplace=True)
                    df_thr_calc['Bytes_Novos'] = df_thr_calc['Bytes_Acked'].diff().fillna(0)
                    
                    df_resampled = df_thr_calc['Bytes_Novos'].resample('1s').sum().to_frame()
                    duracao_janela_segundos = 1.0
                    df_resampled['Throughput_Mbps'] = (df_resampled['Bytes_Novos'] * 8) / (duracao_janela_segundos * 1_000_000)
                    df_resampled['Tempo_ms'] = (df_resampled.index - df_resampled.index.min()).total_seconds() * 1000
                    
                    dados_throughput[opcao] = df_resampled
                except Exception as e:
                    dados_throughput[opcao] = None

            # 1. Comparativo de CWND
            st.markdown("### Comparação de Janela de Congestionamento (CWND)")
            fig_comp_cwnd, ax_comp_cwnd = plt.subplots(figsize=(14, 5))
            for opcao in selecionados:
                df_c = dados_fluxos[opcao]
                ax_comp_cwnd.plot(df_c["Tempo_ms"], df_c["CWND"], label=opcao, linewidth=1.2)
            ax_comp_cwnd.set_xlabel("Tempo (ms)")
            ax_comp_cwnd.set_ylabel("Janela de Congestionamento (CWND) em Segmentos")
            ax_comp_cwnd.grid(True, alpha=0.3, linestyle="--")
            ax_comp_cwnd.legend()
            st.pyplot(fig_comp_cwnd)

            # 2. Comparativo de RTT
            st.markdown("### Comparação de RTT (SRTT)")
            fig_comp_rtt, ax_comp_rtt = plt.subplots(figsize=(14, 5))
            for opcao in selecionados:
                df_c = dados_fluxos[opcao]
                ax_comp_rtt.plot(df_c["Tempo_ms"], df_c["SRTT_us"], label=opcao, linewidth=1.2)
            ax_comp_rtt.set_xlabel("Tempo (ms)")
            ax_comp_rtt.set_ylabel("RTT (µs)")
            ax_comp_rtt.grid(True, alpha=0.3, linestyle="--")
            ax_comp_rtt.legend()
            st.pyplot(fig_comp_rtt)

            # 3. Comparativo de Throughput
            st.markdown("### Comparação de Throughput (Vazão)")
            fig_comp_thr, ax_comp_thr = plt.subplots(figsize=(14, 5))
            erro_thr = False
            for opcao in selecionados:
                df_t = dados_throughput.get(opcao)
                if df_t is not None and not df_t.empty:
                    ax_comp_thr.plot(df_t["Tempo_ms"], df_t["Throughput_Mbps"], label=opcao, linewidth=2, marker='o')
                else:
                    erro_thr = True
            if erro_thr:
                st.warning("Não foi possível calcular o Throughput para uma ou mais conexões nesta janela temporal.")
            ax_comp_thr.set_xlabel("Tempo (ms)")
            ax_comp_thr.set_ylabel("Vazão (Mbps)")
            ax_comp_thr.grid(True, alpha=0.3, linestyle="--")
            ax_comp_thr.legend()
            st.pyplot(fig_comp_thr)

            # 4. Comparativo de Retransmissões
            st.markdown("### Comparação de Retransmissões Totais")
            fig_comp_ret, ax_comp_ret = plt.subplots(figsize=(14, 5))
            for opcao in selecionados:
                df_c = dados_fluxos[opcao]
                ax_comp_ret.plot(df_c["Tempo_ms"], df_c["Retransmissions"], label=opcao, linewidth=1.2)
            ax_comp_ret.set_xlabel("Tempo (ms)")
            ax_comp_ret.set_ylabel("Total de Pacotes Retransmitidos")
            ax_comp_ret.grid(True, alpha=0.3, linestyle="--")
            ax_comp_ret.legend()
            st.pyplot(fig_comp_ret)

        else:
            st.info("Selecione uma ou mais conexões acima para gerar os gráficos comparativos.")