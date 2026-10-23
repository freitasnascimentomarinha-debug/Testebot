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

from core import accounts, credentials  # noqa: E402
from core.auth import current_user, is_authenticated, logout, password_configured, require_login  # noqa: E402  (depois do set_page_config)
import core  # noqa: E402
from core import APP_VERSION  # noqa: E402

core.LOADED_COMMIT = _disk_version
from core.storage import backend, get_secret  # noqa: E402

st.markdown("""<style>
[data-testid="stMetricValue"] {font-size: 1.35rem;}
[data-testid="stMetricLabel"] p {font-size: .8rem;}
.block-container {padding-top: 2.2rem;}
</style>""", unsafe_allow_html=True)

_acct_pages = ([st.Page("views/account.py", title="Minha conta", icon="👤", url_path="conta")] if accounts.enabled() else []) + \
    ([st.Page("views/admin.py", title="Administração", icon="🛡️", url_path="admin")]
     if accounts.enabled() and accounts.is_admin(st.session_state.get("_user")) else [])
# Ordem do menu: conta e administração primeiro, depois o painel geral, a cripto e os demais mercados.
pages = {
    **({"Conta": _acct_pages} if _acct_pages else {}),
    "Visão geral": [st.Page("views/dashboard.py", title="Painel", icon="📊", default=True),
                    st.Page("views/wallet.py", title="Carteira", icon="💰", url_path="carteira"),
                    st.Page("views/bots.py", title="Bots especialistas", icon="🤖", url_path="bots"),
                    st.Page("views/personalities.py", title="Personalidades", icon="🏆", url_path="personalidades"),
                    st.Page("views/learning.py", title="Aprendendo", icon="🎓", url_path="aprendendo")],
    "Mercado Cripto": [
        st.Page("views/day_trade.py", title="Day Trade · Futuros", icon="⚡", url_path="day-trade"),
        st.Page("views/swing_trade.py", title="Swing Trade · Spot", icon="🌊", url_path="swing-trade"),
        st.Page("views/long_trade.py", title="Long Trade · Spot", icon="🏔️", url_path="long-trade"),
    ],
    "Outros mercados": [
        st.Page("views/forex.py", title="Forex", icon="💱", url_path="forex"),
        st.Page("views/commodities.py", title="Commodities", icon="🛢️", url_path="commodities"),
        st.Page("views/indices.py", title="Índices", icon="📈", url_path="indices"),
        st.Page("views/acoes.py", title="Ações Brasil (B3)", icon="🇧🇷", url_path="acoes-brasil"),
    ],
}


def _binance_required() -> bool:
    """Chave da Binance obrigatória no primeiro acesso (REQUIRE_BINANCE_KEYS = "true" nos Secrets; admins ficam de fora)."""
    user = current_user()
    return bool(accounts.enabled() and user and (get_secret("REQUIRE_BINANCE_KEYS") or "").strip().lower() in ("1", "true", "sim", "yes")
                and credentials.configured() and not accounts.is_admin(user) and not credentials.status(user))


# A navegação é criada antes do login (oculta) para preservar a página pedida na URL.
_authed = is_authenticated()
_gated = _authed and _binance_required()
nav = st.navigation(pages, position="sidebar" if _authed and not _gated else "hidden", expanded=True)
require_login()

with st.sidebar:
    st.divider()
    store = backend()
    if getattr(store, "last_error", None):  # só avisa quando uma gravação realmente falhou
        st.error(f"Última gravação falhou (nova tentativa automática): {store.last_error[:200]}")
    st.caption(f"Versão {APP_VERSION}")
    if current_user():
        st.caption(f"👤 {current_user()}" + (" · admin" if accounts.is_admin(current_user()) else ""))
        if accounts.is_admin(current_user()) and (n_pending := accounts.pending_count()):
            st.warning(f"⏳ {n_pending} pedido(s) de conta aguardando você em **Administração**.")
    if password_configured():
        if st.button("Sair", icon="🚪", width="stretch"):
            logout()

if _gated:
    from core.binance_ui import render_binance

    st.title("🔗 Conecte a sua Binance")
    st.caption("Para usar a plataforma, cadastre a chave de API da sua conta Binance. Ela fica criptografada na sua conta.")
    render_binance(current_user(), "gate")
    st.stop()

nav.run()
