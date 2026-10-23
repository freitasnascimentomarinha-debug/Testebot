"""Plataforma de Bots de Trade — ponto de entrada.

Execute com:  streamlit run app.py
"""
from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="TradeBot · Plataforma de Bots", page_icon="📊", layout="wide",
                   initial_sidebar_state="expanded")

from core.ui import api_key  # noqa: E402  (depois do set_page_config)

st.markdown("""<style>
[data-testid="stMetricValue"] {font-size: 1.35rem;}
[data-testid="stMetricLabel"] p {font-size: .8rem;}
.block-container {padding-top: 2.2rem;}
</style>""", unsafe_allow_html=True)

pages = {
    "Visão geral": [st.Page("views/dashboard.py", title="Painel", icon="📊", default=True)],
    "Bots": [
        st.Page("views/day_trade.py", title="Day Trade · Futuros", icon="⚡", url_path="day-trade"),
        st.Page("views/swing_trade.py", title="Swing Trade · Spot", icon="🌊", url_path="swing-trade"),
        st.Page("views/long_trade.py", title="Long Trade · Spot", icon="🏔️", url_path="long-trade"),
    ],
}
nav = st.navigation(pages, position="sidebar", expanded=True)

with st.sidebar:
    st.divider()
    st.markdown("### 🔑 IA — OpenRouter")
    if api_key() and not st.session_state.get("openrouter_key"):
        st.success("Chave carregada de secrets/variável de ambiente.")
    st.text_input("API Key (somente nesta sessão)", type="password", key="openrouter_key",
                  help="Também pode ser definida em .streamlit/secrets.toml (OPENROUTER_API_KEY) ou na variável de ambiente.")
    st.caption("Modelo padrão: `deepseek/deepseek-v4.1-flash`")
    st.divider()
    st.markdown("### 🏦 Execução")
    st.info("**Conta simulada** com preços reais.\n\nFase 2: Binance API Key (Testnet → Real).")
    st.caption("Dados: Binance (spot/futuros) com fallback OKX. Nenhum dado aqui é recomendação de investimento.")

nav.run()
