"""Minha conta: senha, resumo das escolhas pessoais salvas e backup dos dados."""
import json
from pathlib import Path

import streamlit as st

from core import accounts, credentials, exchanges, execution, paper, personalities, quota, wallet_view
from core.auth import current_user
from core.binance_ui import render_keys
from core.storage import get_secret
from core.profiles import PAGE_BOTS, PROFILES
from core.settings import load_settings
from core.storage import backend, export_all, import_all

user = current_user()
st.title("👤 Minha conta")
_DIR = Path(__file__).resolve().parent.parent / "core"


@st.cache_resource(show_spinner=False)
def _component():
    return st.components.v2.component("tb_account", css=(_DIR / "wallet_ui.css").read_text(encoding="utf-8"),
                                      js=(_DIR / "account.js").read_text(encoding="utf-8"))


def _on_exchange(res) -> None:
    ev = getattr(res, "exchange", None)
    if ev and ev.get("uid") != st.session_state.get("_ex_uid") and ev.get("key") in exchanges.EXCHANGES:
        st.session_state["_ex_uid"] = ev["uid"]
        exchanges.select(ev["key"])
        st.cache_data.clear()   # candles e cotações passam a vir da corretora nova
        st.session_state["_acc_msg"] = f"Corretora salva: {exchanges.label(ev['key'])}. Dados, gráficos e chave de API seguem esta escolha."
        st.rerun()


if not user:   # sem contas (uso local): só a escolha da corretora
    if msg := st.session_state.pop("_acc_msg", None):
        st.success(msg)
    _on_exchange(_component()(key="tb-account-ex", on_exchange_change=lambda: None,
                              data={"only_exchange": True, "exchanges": wallet_view.exchanges_view(exchanges.selected()), "user": {"name": ""}}))
    st.info("Sem contas ativas: defina `AUTH_MODE = \"contas\"` nos Secrets para ter usuário, senha e chaves de API guardadas.")
    st.stop()
info = accounts.info(user) or {}


def _warn(mode: str) -> str | None:
    if (why := execution.key_problem(mode, user)):
        return why
    if mode != "simulada" and not execution.EXCHANGE_ORDERS_ENABLED:
        return "Envio de ordens à Exchange ainda não está ativo nesta versão: os bots e a boleta ficam em espera."
    return None


if msg := st.session_state.pop("_acc_msg", None):
    st.success(msg)
bots = [{"name": PROFILES[k].name, "cfg": (c := load_settings(k)),
         "personality": "automático (ranking)" if c.get("auto_bot", True) else (personalities.get(c["personality"]) or {}).get("name", c["personality"])}
        for k in PAGE_BOTS]
lim = quota.limit()
res = _component()(key="tb-account", on_mode_change=lambda: None, on_exchange_change=lambda: None, data=wallet_view.account_data(
    exchanges=wallet_view.exchanges_view(exchanges.selected(), credentials.all_status(user)),
    user=user, admin=accounts.is_admin(user), created=info.get("created", ""), storage=backend().name, mode=execution.get_mode(),
    modes=execution.MODES, warn=_warn, bank=paper.get_account(paper.account_id("day"))["initial"], bots=bots,
    ai={"used": quota.used(), "limit": lim} if get_secret("OPENROUTER_API_KEY") else None))
_on_exchange(res)
ev = getattr(res, "mode", None)
if ev and ev.get("uid") != st.session_state.get("_acc_uid") and ev.get("mode") in execution.MODES:
    st.session_state["_acc_uid"] = ev["uid"]
    execution.set_mode(ev["mode"])
    st.session_state["_acc_msg"] = f"Conta de operação salva: {execution.MODES[ev['mode']]}."
    st.rerun()

st.divider()
render_keys(user, "acc")

st.subheader("🔑 Trocar senha")
with st.form("chg_pw", clear_on_submit=True):
    old = st.text_input("Senha atual", type="password")
    new = st.text_input("Nova senha (mínimo 8 caracteres)", type="password")
    new2 = st.text_input("Repita a nova senha", type="password")
    if st.form_submit_button("Trocar senha", type="primary"):
        if new != new2:
            st.error("As senhas novas não conferem.")
        else:
            try:
                accounts.change_password(user, old, new)
                st.success("Senha alterada. Os links de 'manter conectado' antigos deixaram de valer: entre de novo nos outros aparelhos.")
                st.query_params["s"] = accounts.make_token(user)
            except ValueError as exc:
                st.error(str(exc))

st.subheader("📦 Backup dos seus dados")
st.download_button("⬇️ Baixar meus dados (JSON)", json.dumps(export_all(), ensure_ascii=False, default=str, indent=1),
                   file_name=f"tradebot_{user}.json", mime="application/json")
up = st.file_uploader("Restaurar a partir de um backup (JSON)", type="json")
if up is not None and st.button("Restaurar agora"):
    st.success(f"{import_all(json.load(up))} arquivos restaurados na sua conta.")
