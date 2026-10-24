"""Minha conta: senha, resumo das escolhas pessoais salvas e backup dos dados."""
import json

import pandas as pd
import streamlit as st

from core import accounts, execution, paper, personalities, quota
from core.auth import current_user
from core.binance_ui import render_binance
from core.storage import get_secret
from core.profiles import PAGE_BOTS, PROFILES
from core.settings import load_settings
from core.storage import backend, export_all, import_all

user = current_user()
st.title("👤 Minha conta")
if not user:
    st.info("Sem contas ativas: defina `AUTH_MODE = \"contas\"` nos Secrets para ter usuário e senha.")
    st.stop()
info = accounts.info(user) or {}
st.caption(f"Usuário **{user}**" + (f" · conta criada em {info['created'][:10]}" if info.get("created") else "")
           + f" · dados guardados em: {backend().name}")

st.subheader("🏦 Conta de operação")
st.caption("Onde as ordens dos bots e as suas são executadas. A escolha fica salva na sua conta.")
_modes = list(execution.MODES)
_pick = st.radio("Executar as ordens na", _modes, index=_modes.index(execution.get_mode()), format_func=execution.MODES.get,
                 key="acc_mode", label_visibility="collapsed")
if (_why := execution.key_problem(_pick, user)):
    st.warning(_why)
if _pick != "simulada" and not execution.EXCHANGE_ORDERS_ENABLED:
    st.info("O envio de ordens para a Exchange ainda não está ativo nesta versão: ao escolher esta conta, os bots e a boleta ficam "
            "em espera (nenhuma ordem é enviada nem simulada).")
if st.button("💾 Salvar conta de operação", type="primary", disabled=_pick == execution.get_mode()):
    execution.set_mode(_pick)
    st.success(f"Conta de operação salva: {execution.MODES[_pick]}.")
    st.rerun()
st.caption(f"Conta em uso agora: **{execution.MODES[execution.get_mode()]}**")

st.subheader("💾 Suas escolhas salvas")
st.caption("Tudo abaixo fica salvo na sua conta e volta igual na próxima vez que você entrar, em qualquer aparelho. "
           "Altere em cada bot, em Configurações do bot.")
acct = paper.get_account(paper.account_id("day"))
st.metric("Banca inicial da carteira (USDT)", f"{acct['initial']:,.2f}")
rows = []
for key, p in ((k, PROFILES[k]) for k in PAGE_BOTS):
    c = load_settings(key)
    risk = f"{c['max_loss_pct']:g}% do saldo" if c["risk_mode"] == "% do saldo" else f"{c['max_loss_usdt']:g} USDT"
    rows.append({"Bot": p.name, "Ativo": c["symbol"], "Tempo gráfico": c["interval"], "Perda máxima por trade": risk,
                 "Alavancagem": f"{c['leverage']:g}×" if c["leverage_on"] else "sem", "Personalidade": "automática (ranking)" if c.get("auto_bot", True) else (personalities.get(c["personality"]) or {}).get("name", c["personality"]),
                 "Piloto automático": "ligado" if c["autopilot"] else "desligado"})
st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

st.divider()
render_binance(user, "acc")
if get_secret("OPENROUTER_API_KEY"):
    lim = quota.limit()
    st.caption(f"🤖 A IA é oferecida pela plataforma. Análises de hoje: **{quota.used()}**" + (f" de {lim}" if lim > 0 else " (sem limite)") + ".")

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
