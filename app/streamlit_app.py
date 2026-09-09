import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

DB = Path(__file__).resolve().parent.parent / "data" / "real_madrid.db"

st.set_page_config(page_title="Real Madrid Analytics", page_icon="⚪", layout="wide")


@st.cache_data(ttl=3600)
def tables():
    with sqlite3.connect(DB) as c:
        return pd.read_sql(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name", c
        )["name"].tolist()


@st.cache_data(ttl=3600)
def load(table):
    with sqlite3.connect(DB) as c:
        return pd.read_sql(f'SELECT * FROM "{table}"', c)


if not DB.exists():
    st.error("Banco ainda não gerado. Rode `python src/etl.py` primeiro.")
    st.stop()

st.title("⚪ Real Madrid — Analytics")

try:
    runs = load("_etl_runs")
    st.caption(f"Última atualização: {runs['run_at'].max()}")
except Exception:
    pass

tabs = tables()

col1, col2 = st.columns([1, 3])
with col1:
    table = st.selectbox("Tabela", [t for t in tabs if not t.startswith("_")])

df = load(table)

# Filtro de temporada, quando existir
season_col = next((c for c in df.columns if "season" in c), None)
if season_col:
    seasons = sorted(df[season_col].dropna().unique(), reverse=True)
    sel = st.multiselect("Temporada", seasons, default=seasons[:1])
    if sel:
        df = df[df[season_col].isin(sel)]

st.metric("Registros", len(df))
st.dataframe(df, use_container_width=True, height=520)

# Gráfico rápido
num_cols = df.select_dtypes("number").columns.tolist()
name_col = next((c for c in df.columns if c in ("player", "player_name")), None)

if name_col and num_cols:
    st.subheader("Ranking rápido")
    metric = st.selectbox("Métrica", num_cols)
    top = (
        df.groupby(name_col)[metric]
        .sum()
        .sort_values(ascending=False)
        .head(15)
    )
    st.bar_chart(top)

st.download_button(
    "Baixar CSV",
    df.to_csv(index=False).encode("utf-8"),
    file_name=f"{table}.csv",
    mime="text/csv",
)
