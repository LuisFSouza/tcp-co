import os
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt

DEFAULT_CSV = "tcp_metrics.csv"
EXPERIMENTS_DIR = "experiments"

st.set_page_config(page_title="TCP-CO Dashboard", layout="wide")
st.title("TCP-CO — TCP Congestion Observatory")

# --- Data source selection ---
data_source = st.sidebar.selectbox("Fonte de dados:", ["tcp_metrics.csv", "Experiments folder"])

def load_single(csv_path):
    try:
        return pd.read_csv(csv_path)
    except Exception as e:
        st.error(f"Erro ao ler o arquivo CSV: {e}")
        st.stop()

def load_multiple_from_experiments(selected_files):
    frames = []
    for fname in selected_files:
        path = os.path.join(EXPERIMENTS_DIR, fname)
        try:
            df_i = pd.read_csv(path)
        except Exception as e:
            st.error(f"Erro ao ler {path}: {e}")
            st.stop()
        # annotate source
        df_i["_source_file"] = fname
        # try to infer algorithm from filename prefix (algo_scenario.csv)
        parts = fname.split("_")
        if parts:
            df_i["Algoritmo_Experimento"] = parts[0]
        frames.append(df_i)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)

if data_source == "tcp_metrics.csv":
    df = load_single(DEFAULT_CSV)
else:
    files = []
    if os.path.isdir(EXPERIMENTS_DIR):
        files = sorted([f for f in os.listdir(EXPERIMENTS_DIR) if f.endswith('.csv')])
    if not files:
        st.error(f"Pasta {EXPERIMENTS_DIR} vazia ou inexistente. Gere experimentos primeiro.")
        st.stop()
    selected = st.sidebar.multiselect("Selecione CSVs de experiments:", files, default=files)
    df = load_multiple_from_experiments(selected)

# If loaded from experiments and Algoritmo_CA missing, try to fill from inferred name
if "Algoritmo_CA" not in df.columns and "Algoritmo_Experimento" in df.columns:
    df["Algoritmo_CA"] = df["Algoritmo_Experimento"]

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
df = df[df["TCP_State"] == "ESTABLISHED"].copy()
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

        # Grafico CWND e SSThresh × Tempo
        st.subheader("CWND e SSThresh × Tempo")
        fig_cwnd, ax_cwnd = plt.subplots(figsize=(14, 4))
        ax_cwnd.plot(plot_df["Tempo_ms"], plot_df["CWND"], linewidth=2, label="CWND", color="#1f77b4")
        ssthresh_plot = plot_df.dropna(subset=["SSThresh"])
        if not ssthresh_plot.empty:
            ax_cwnd.plot(ssthresh_plot["Tempo_ms"], ssthresh_plot["SSThresh"], linewidth=2, color="#ff7f0e", label="SSThresh")
        ax_cwnd.set_xlabel("Tempo (ms)")
        ax_cwnd.set_ylabel("Segmentos TCP")
        ax_cwnd.grid(True, alpha=0.3)
        ax_cwnd.legend()
        st.pyplot(fig_cwnd)

        # Gráfico SRTT x Tempo
        st.subheader("SRTT × Tempo")
        fig_rtt, ax_rtt = plt.subplots(figsize=(14, 4))
        ax_rtt.plot(plot_df["Tempo_ms"], plot_df["SRTT_us"], marker="o", color="#2ca02c", linewidth=2, markersize=5, label="RTT")
        ax_rtt.set_xlabel("Tempo (ms)")
        ax_rtt.set_ylabel("RTT (µs)")
        ax_rtt.grid(True, alpha=0.3)
        ax_rtt.legend()
        st.pyplot(fig_rtt)

        # Gráfico Retransmissions x Tempo
        st.subheader("Retransmissões × Tempo")
        fig_retrans, ax_retrans = plt.subplots(figsize=(14, 4))
        ax_retrans.plot(plot_df["Tempo_ms"], plot_df["Retransmissions"], marker="o", linewidth=2, markersize=5, color="#9467bd", label="Retransmissões")
        ax_retrans.set_xlabel("Tempo (ms)")
        ax_retrans.set_ylabel("Total de Pacotes Retransmitidos")
        ax_retrans.grid(True, alpha=0.3)
        ax_retrans.legend()
        st.pyplot(fig_retrans)

        # Gráfico Bytes Reconhecidos x Tempo
        st.subheader("Bytes Reconhecidos × Tempo")
        fig_bytes, ax_bytes = plt.subplots(figsize=(14, 4))
        ax_bytes.plot(plot_df["Tempo_ms"], plot_df["Bytes_Acked"], marker="o", linewidth=2, markersize=5, color="#8c564b", label="Bytes Reconhecidos")
        ax_bytes.set_xlabel("Tempo (ms)")
        ax_bytes.set_ylabel("Bytes")
        ax_bytes.grid(True, alpha=0.3)
        ax_bytes.legend()
        st.pyplot(fig_bytes)

        # Gráfico Pacotes em Trânsito x Tempo
        st.subheader("Pacotes em Trânsito × Tempo")
        fig_packets, ax_packets = plt.subplots(figsize=(14, 4))
        ax_packets.plot(plot_df["Tempo_ms"], plot_df["Packets_Out"], marker="o", linewidth=2, markersize=5, color="#17becf", label="Pacotes em Trânsito")
        ax_packets.set_xlabel("Tempo (ms)")
        ax_packets.set_ylabel("Pacotes")
        ax_packets.grid(True, alpha=0.3)
        ax_packets.legend()
        st.pyplot(fig_packets)

        # Gráfico Retransmissões em Trânsito x Tempo
        st.subheader("Retransmissões em Trânsito × Tempo")
        fig_retrans_out, ax_retrans_out = plt.subplots(figsize=(14, 4))
        ax_retrans_out.plot(plot_df["Tempo_ms"], plot_df["Retrans_Out"], marker="o", linewidth=2, markersize=5, color="#d62728", label="Retransmissões em Trânsito")
        ax_retrans_out.set_xlabel("Tempo (ms)")
        ax_retrans_out.set_ylabel("Pacotes")
        ax_retrans_out.grid(True, alpha=0.3)
        ax_retrans_out.legend()
        st.pyplot(fig_retrans_out)

        # Gráfico Send Buffer x Tempo
        st.subheader("Send Buffer × Tempo")
        fig_buffer, ax_buffer = plt.subplots(figsize=(14, 4))
        ax_buffer.plot(plot_df["Tempo_ms"], plot_df["Snd_Buffer"], marker="o", linewidth=2, markersize=5, color="#7f7f7f", label="Send Buffer")
        ax_buffer.set_xlabel("Tempo (ms)")
        ax_buffer.set_ylabel("Bytes")
        ax_buffer.grid(True, alpha=0.3)
        ax_buffer.legend()
        st.pyplot(fig_buffer)

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

with tab2:
    st.subheader("Gráfico Comparativo: Algoritmos na Mesma Linha do Tempo")
    opcoes_disponiveis = sorted(df["Opcao_Comp"].unique())
    
    if len(opcoes_disponiveis) == 0:
        st.info("Gere tráfego para realizar a comparação.")
    else:
        selecionados = st.multiselect(
            "Selecione os fluxos/algoritmos para sobrepor no gráfico:",
            opcoes_disponiveis,
            default=[]
        )
        
        if selecionados:
            fig_comp, ax_comp = plt.subplots(figsize=(14, 6))
            
            for opcao in selecionados:
                df_comp = df[df["Opcao_Comp"] == opcao].copy()
                df_comp = df_comp.sort_values("Data_Hora").reset_index(drop=True)
                df_comp["Tempo_ms"] = (df_comp["Data_Hora"] - df_comp["Data_Hora"].min()).dt.total_seconds() * 1000
                ax_comp.plot(df_comp["Tempo_ms"], df_comp["CWND"], label=opcao, linewidth=2.5,marker="o",markersize=4)
                
            ax_comp.set_xlabel("Tempo Relativo desde o início da conexão (ms)")
            ax_comp.set_ylabel("Janela de Congestionamento (CWND) em Segmentos")
            ax_comp.set_title("Comparação de Algoritmos de Controle de Congestionamento")
            ax_comp.grid(True, alpha=0.3, linestyle="--")
            ax_comp.legend()
            
            st.pyplot(fig_comp)
        else:
            st.info("Selecione uma ou mais conexões acima para gerar o gráfico comparativo.")