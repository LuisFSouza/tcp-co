import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt

CSV_FILE = "tcp_metrics.csv"

st.set_page_config(page_title="TCP-CO Dashboard", layout="wide")
st.title("TCP-CO — TCP Congestion Observatory")

# Carrega o arquivo
try:
    df = pd.read_csv(CSV_FILE)
except Exception as e:
    st.error(f"Erro ao ler o arquivo CSV: {e}")
    st.stop()

# Colunas armazenadas
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

# Conversões e Tratamento de Dados
df["Data_Hora"] = pd.to_datetime(df["Data_Hora"], format="%Y-%m-%d %H:%M:%S.%f", errors="coerce")

numeric_cols = ["CWND", "SSThresh", "SRTT_us", "Retransmissions", "Porta_Origem", "Porta_Destino"]
for col in numeric_cols:
    df[col] = pd.to_numeric(df[col], errors="coerce")

# Trata valor inicial do SSThresh
df.loc[df["SSThresh"] >= 1000000, "SSThresh"] = pd.NA

# Limpa timestamps inválidos
df = df.dropna(subset=["Data_Hora"])

# Remove registros onde as portas são inválidas/zeradas
df = df[(df["Porta_Origem"] > 0) & (df["Porta_Destino"] > 0)].copy()

# Cria o identificador único para cada fluxo físico ANTES de filtrar o estado
df["Conexao"] = (
    df["IP_Origem"].astype(str) + ":" + df["Porta_Origem"].astype(int).astype(str) +
    " → " +
    df["IP_Destino"].astype(str) + ":" + df["Porta_Destino"].astype(int).astype(str)
)

# REQUISITO EXIGIDO: Filtragem estrita para considerar APENAS o estado ESTABLISHED nas análises
df = df[df["TCP_State"] == "ESTABLISHED"].copy()

# Ordenação temporal global garantida para a cronologia do dump
df = df.sort_values("Data_Hora").reset_index(drop=True)

# Cria identificador para a comparação (Algoritmo + Fluxo)
df["Opcao_Comp"] = df["Algoritmo_CA"].astype(str) + " (" + df["Conexao"] + ")"

# Interface em abas do Streamlit
tab1, tab2 = st.tabs(["📊 Análise por Conexão", "🔄 Comparação entre Algoritmos"])

# Checkbox global para otimização de renderização
show_only_changes = st.sidebar.checkbox("Mostrar apenas mudanças relevantes", value=True)

# ---------------------------------------------------------
# ABA 1: GRÁFICOS INDIVIDUAIS POR CONEXÃO (1, 2 e 3)
# ---------------------------------------------------------
with tab1:
    connections = sorted(df["Conexao"].unique())
    if not connections:
        st.warning("Nenhuma conexão TCP no estado ESTABLISHED encontrada no CSV.")
    else:
        selected_connection = st.selectbox("Selecione a conexão TCP para detalhar:", connections)
        
        filtered = df[df["Conexao"] == selected_connection].copy()
        filtered = filtered.sort_values("Data_Hora").reset_index(drop=True)
        
        # Tempo relativo em milissegundos (O zero absoluto agora é o início do ESTABLISHED)
        filtered["Tempo_ms"] = (filtered["Data_Hora"] - filtered["Data_Hora"].min()).dt.total_seconds() * 1000
        
        plot_df = filtered.copy()
        if show_only_changes:
            plot_df = plot_df.loc[
                (plot_df["CWND"].shift() != plot_df["CWND"]) |
                (plot_df["SSThresh"].shift() != plot_df["SSThresh"]) |
                (plot_df["SRTT_us"].shift() != plot_df["SRTT_us"]) |
                (plot_df["Retransmissions"].shift() != plot_df["Retransmissions"])
            ].copy()
            
        st.subheader("1. Janela de Congestionamento (CWND) e SSThresh × Tempo")
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
        
        st.subheader("2. RTT (SRTT_us) × Tempo")
        fig_rtt, ax_rtt = plt.subplots(figsize=(14, 4))
        ax_rtt.plot(plot_df["Tempo_ms"], plot_df["SRTT_us"], marker="o", color="#2ca02c", linewidth=2, markersize=5, label="Smooth RTT")
        ax_rtt.set_xlabel("Tempo (ms)")
        ax_rtt.set_ylabel("RTT (µs)")
        ax_rtt.grid(True, alpha=0.3)
        ax_rtt.legend()
        st.pyplot(fig_rtt)
        
        st.subheader("3. Retransmissões Acumuladas × Tempo")
        fig_retrans, ax_retrans = plt.subplots(figsize=(14, 4))
        ax_retrans.plot(plot_df["Tempo_ms"], plot_df["Retransmissions"], marker="o", linewidth=2, markersize=5, color="#9467bd", label="Retransmissões")
        ax_retrans.set_xlabel("Tempo (ms)")
        ax_retrans.set_ylabel("Total de Pacotes Retransmitidos")
        ax_retrans.grid(True, alpha=0.3)
        ax_retrans.legend()
        st.pyplot(fig_retrans)
        
        st.dataframe(filtered.drop(columns=["Conexao", "Opcao_Comp"], errors="ignore"))

# ---------------------------------------------------------
# ABA 2: COMPARAÇÃO ENTRE ALGORITMOS
# ---------------------------------------------------------
with tab2:
    st.subheader("4. Gráfico Comparativo: Algoritmos na Mesma Linha do Tempo")
    opcoes_disponiveis = sorted(df["Opcao_Comp"].unique())
    
    if len(opcoes_disponiveis) == 0:
        st.info("Gere tráfego usando algoritmos diferentes para realizar a comparação.")
    else:
        selecionados = st.multiselect(
            "Selecione os fluxos/algoritmos para sobrepor no gráfico:",
            opcoes_disponiveis,
            default=opcoes_disponiveis[:4] if len(opcoes_disponiveis) >= 4 else opcoes_disponiveis
        )
        
        if selecionados:
            fig_comp, ax_comp = plt.subplots(figsize=(14, 6))
            
            for opcao in selecionados:
                # 1. Isola e ordena cronologicamente os dados desta conexão
                df_comp = df[df["Opcao_Comp"] == opcao].copy()
                df_comp = df_comp.sort_values("Data_Hora").reset_index(drop=True)
                
                # 2. Calcula o tempo relativo (idêntico à Aba 1)
                df_comp["Tempo_ms"] = (df_comp["Data_Hora"] - df_comp["Data_Hora"].min()).dt.total_seconds() * 1000
                
                # 3. CORREÇÃO CRÍTICA: Filtro de mudanças idêntico ao da Aba 1
                # Se filtrarmos menos colunas, os pontos de tempo colapsam e deformam o gráfico
                if show_only_changes:
                    df_comp = df_comp.loc[
                        (df_comp["CWND"].shift() != df_comp["CWND"]) |
                        (df_comp["SSThresh"].shift() != df_comp["SSThresh"]) |
                        (df_comp["SRTT_us"].shift() != df_comp["SRTT_us"]) |
                        (df_comp["Retransmissions"].shift() != df_comp["Retransmissions"])
                    ].copy()
                
                # 4. Plota a linha com os mesmos exatos pontos da Aba 1
                ax_comp.plot(
                    df_comp["Tempo_ms"], 
                    df_comp["CWND"], 
                    label=opcao, 
                    linewidth=2.5,
                    marker="o",
                    markersize=4
                )
                
            ax_comp.set_xlabel("Tempo Relativo desde o início da conexão (ms)")
            ax_comp.set_ylabel("Janela de Congestionamento (CWND) em Segmentos")
            ax_comp.set_title("Comparação de Algoritmos de Controle de Congestionamento")
            ax_comp.grid(True, alpha=0.3, linestyle="--")
            ax_comp.legend()
            
            st.pyplot(fig_comp)
        else:
            st.info("Selecione uma ou mais conexões acima para gerar o gráfico comparativo.")