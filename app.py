"""Plataforma de Bots de Trade — ponto de entrada.

Execute com:  streamlit run app.py
"""
from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="TradeBot · Plataforma de Bots", page_icon="📊", layout="wide",
                   initial_sidebar_state="expanded")

from core.auth import is_authenticated, logout, password_configured, require_login  # noqa: E402  (depois do set_page_config)
from core import APP_VERSION  # noqa: E402
from core.storage import backend  # noqa: E402
from core.ui import api_key  # noqa: E402

st.markdown("""<style>
[data-testid="stMetricValue"] {font-size: 1.35rem;}
[data-testid="stMetricLabel"] p {font-size: .8rem;}
.block-container {padding-top: 2.2rem;}
</style>""", unsafe_allow_html=True)

pages = {
    "Visão geral": [st.Page("views/dashboard.py", title="Painel", icon="📊", default=True),
                    st.Page("views/wallet.py", title="Carteira", icon="💰", url_path="carteira")],
    "Bots": [
        st.Page("views/day_trade.py", title="Day Trade · Futuros", icon="⚡", url_path="day-trade"),
        st.Page("views/swing_trade.py", title="Swing Trade · Spot", icon="🌊", url_path="swing-trade"),
        st.Page("views/long_trade.py", title="Long Trade · Spot", icon="🏔️", url_path="long-trade"),
    ],
}
# A navegação é criada antes do login (oculta) para preservar a página pedida na URL.
nav = st.navigation(pages, position="sidebar" if is_authenticated() else "hidden", expanded=True)
require_login()

with st.sidebar:
    st.divider()
    st.markdown("### 🔑 IA — OpenRouter")
    if api_key() and not st.session_state.get("openrouter_key"):
        st.success("Chave carregada de secrets/variável de ambiente.")
    st.text_input("API Key (somente nesta sessão)", type="password", key="openrouter_key",
                  help="Também pode ser definida em .streamlit/secrets.toml (OPENROUTER_API_KEY) ou na variável de ambiente.")
    st.caption("Modelo padrão: `deepseek/deepseek-v4.1-flash`")
    st.divider()
    st.markdown("### 💾 Armazenamento")
    store = backend()
    if store.persistent:
        st.success(f"{store.name} — dados permanentes.")
        if getattr(store, "last_error", None):
            st.error(f"Última gravação falhou (nova tentativa automática): {store.last_error[:200]}")
    else:
        st.warning("Arquivos locais: no Streamlit Community os dados somem quando o app reinicia. "
                   "Configure `GITHUB_DATA_REPO` + `GITHUB_TOKEN` ou `DATABASE_URL` nos secrets.")
        if getattr(store, "error", None):
            st.error(f"Falha ao conectar no banco: {store.error[:200]}")
    st.divider()
    st.markdown("### 🏦 Execução")
    st.info("**Carteira simulada** com preços reais.\n\nFase 2: Binance API Key (Testnet → Real).")
    st.caption("Dados: Binance (spot/futuros) com fallback OKX. Nenhum dado aqui é recomendação de investimento.")
    st.caption(f"Versão {APP_VERSION}")

    st.divider()
    if password_configured():
        if st.button("Sair", icon="🚪", width="stretch"):
            logout()
    else:
        st.caption("⚠️ Sem senha: defina `APP_PASSWORD` nos secrets antes de publicar.")

nav.run()
