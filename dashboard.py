import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt

CSV_FILE = "tcp_metrics.csv"

st.set_page_config(page_title="TCP-CO Dashboard", layout="wide")
st.title("TCP-CO — CWND e SSThresh × Tempo")

df = pd.read_csv(CSV_FILE)

required_columns = [
    "Data_Hora", "IP_Origem", "IP_Destino",
    "Porta_Origem", "Porta_Destino",
    "CWND", "SSThresh", "Retransmissions", "TCP_State"
]

missing = [col for col in required_columns if col not in df.columns]
if missing:
    st.error(f"Colunas ausentes no CSV: {missing}")
    st.stop()

df["Data_Hora"] = pd.to_datetime(
    df["Data_Hora"],
    format="%Y-%m-%d %H:%M:%S.%f",
    errors="coerce"
)

df["CWND"] = pd.to_numeric(df["CWND"], errors="coerce")
df["SSThresh"] = pd.to_numeric(df["SSThresh"], errors="coerce")
df["Retransmissions"] = pd.to_numeric(df["Retransmissions"], errors="coerce")
df["Porta_Origem"] = pd.to_numeric(df["Porta_Origem"], errors="coerce")
df["Porta_Destino"] = pd.to_numeric(df["Porta_Destino"], errors="coerce")

df.loc[df["SSThresh"] >= 1000000, "SSThresh"] = pd.NA

df = df.dropna(subset=["Data_Hora", "CWND", "TCP_State"])

df = df[
    (df["TCP_State"] == "ESTABLISHED") &
    (df["Porta_Origem"] != 0) &
    (df["Porta_Destino"] != 0)
].copy()

df["Conexao"] = (
    df["IP_Origem"].astype(str)
    + ":"
    + df["Porta_Origem"].astype(int).astype(str)
    + " → "
    + df["IP_Destino"].astype(str)
    + ":"
    + df["Porta_Destino"].astype(int).astype(str)
)

connections = sorted(df["Conexao"].unique())

if not connections:
    st.warning("Nenhuma conexão encontrada no CSV.")
    st.stop()

selected_connection = st.selectbox("Selecione a conexão TCP:", connections)

filtered = df[df["Conexao"] == selected_connection].copy()
filtered = filtered.sort_values("Data_Hora").reset_index(drop=True)

filtered["Tempo_ms"] = (
    filtered["Data_Hora"] - filtered["Data_Hora"].min()
).dt.total_seconds() * 1000

st.subheader(f"Conexão selecionada: {selected_connection}")

show_only_changes = st.checkbox("Mostrar apenas mudanças relevantes", value=True)

plot_df = filtered.copy()

if show_only_changes:
    plot_df = plot_df.loc[
        (plot_df["CWND"].shift() != plot_df["CWND"]) |
        (plot_df["SSThresh"].shift() != plot_df["SSThresh"]) |
        (plot_df["Retransmissions"].shift() != plot_df["Retransmissions"])
    ].copy()

fig, ax = plt.subplots(figsize=(14, 6))

ax.plot(
    plot_df["Tempo_ms"],
    plot_df["CWND"],
    marker="o",
    linewidth=2,
    markersize=5,
    label="CWND"
)

ssthresh_plot = plot_df.dropna(subset=["SSThresh"])

if not ssthresh_plot.empty:
    ax.plot(
        ssthresh_plot["Tempo_ms"],
        ssthresh_plot["SSThresh"],
        marker="x",
        linewidth=2,
        markersize=6,
        color="orange",
        label="SSThresh"
    )

retrans_diff = plot_df["Retransmissions"].diff().fillna(0)
perdas = plot_df[retrans_diff > 0]

if not perdas.empty:
    ax.scatter(
        perdas["Tempo_ms"],
        perdas["CWND"],
        s=90,
        color="red",
        label="Retransmissão/perda",
        zorder=5
    )

ax.set_title("CWND e SSThresh × Tempo")
ax.set_xlabel("Tempo desde o início da conexão (ms)")
ax.set_ylabel("Segmentos TCP")
ax.grid(True)
ax.legend()

plt.tight_layout()
st.pyplot(fig)

st.write("Total de amostras da conexão:", len(filtered))
st.write("Amostras exibidas no gráfico:", len(plot_df))

st.dataframe(filtered)