"""Plataforma de Bots de Trade — ponto de entrada.

Execute com:  streamlit run app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

st.set_page_config(page_title="TradeBot · Plataforma de Bots", page_icon="📊", layout="wide",
                   initial_sidebar_state="auto")


def _code_version() -> str:
    """Commit do código no disco (lido direto do .git, sem subprocesso)."""
    git = Path(__file__).resolve().parent / ".git"
    try:
        head = (git / "HEAD").read_text().strip()
        if not head.startswith("ref:"):
            return head
        ref = head.split(" ", 1)[1]
        if (git / ref).exists():
            return (git / ref).read_text().strip()
        for line in (git / "packed-refs").read_text().splitlines():
            if line.endswith(" " + ref):
                return line.split()[0]
    except OSError:
        pass
    return ""


# O Streamlit reexecuta este arquivo a cada atualização do repositório, mas mantém em memória os módulos
# já importados. Se o código no disco mudou (novo commit), descarta os módulos do app para que tudo seja
# recarregado na mesma versão — evita erros de versões misturadas sem precisar reiniciar o servidor.
_disk_version = _code_version()
# Módulo já carregado sem a marcação (versão anterior a esta correção) também conta como desatualizado.
_loaded_version = getattr(sys.modules.get("core"), "LOADED_COMMIT", None)
if "core" in sys.modules and _disk_version and _loaded_version != _disk_version:
    for _name in [n for n in sys.modules if n == "core" or n.startswith(("core.", "views."))]:
        del sys.modules[_name]
    st.cache_data.clear()
    st.cache_resource.clear()

from core.auth import is_authenticated, logout, password_configured, require_login  # noqa: E402  (depois do set_page_config)
import core  # noqa: E402
from core import APP_VERSION  # noqa: E402

core.LOADED_COMMIT = _disk_version
from core.storage import backend, get_secret  # noqa: E402

st.markdown("""<style>
[data-testid="stMetricValue"] {font-size: 1.35rem;}
[data-testid="stMetricLabel"] p {font-size: .8rem;}
.block-container {padding-top: 2.2rem;}
</style>""", unsafe_allow_html=True)

pages = {
    "Visão geral": [st.Page("views/dashboard.py", title="Painel", icon="📊", default=True),
                    st.Page("views/wallet.py", title="Carteira", icon="💰", url_path="carteira"),
                    st.Page("views/bots.py", title="Bots especialistas", icon="🤖", url_path="bots"),
                    st.Page("views/personalities.py", title="Personalidades", icon="🏆", url_path="personalidades")],
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
    if get_secret("OPENROUTER_API_KEY"):
        st.success("Chave configurada nos Secrets ✅")
    else:
        st.text_input("API Key (somente nesta sessão)", type="password", key="openrouter_key",
                      help="Para não precisar digitar, defina OPENROUTER_API_KEY nos Secrets do Streamlit "
                           "(ou em .streamlit/secrets.toml) — este campo some automaticamente.")
        if not st.session_state.get("openrouter_key"):
            st.caption("Sem chave: os bots usam só as habilidades de programação.")
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
