"""Minha conta: senha, resumo das escolhas pessoais salvas e backup dos dados."""
import json

import pandas as pd
import streamlit as st

from core import accounts, paper, personalities
from core.auth import current_user
from core.profiles import PROFILES
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

st.subheader("💾 Suas escolhas salvas")
st.caption("Tudo abaixo fica salvo na sua conta e volta igual na próxima vez que você entrar, em qualquer aparelho. "
           "Altere em cada bot, em Configurações do bot.")
acct = paper.get_account(paper.account_id("day"))
st.metric("Banca inicial da carteira (USDT)", f"{acct['initial']:,.2f}")
rows = []
for key, p in PROFILES.items():
    c = load_settings(key)
    risk = f"{c['max_loss_pct']:g}% do saldo" if c["risk_mode"] == "% do saldo" else f"{c['max_loss_usdt']:g} USDT"
    rows.append({"Bot": p.name, "Ativo": c["symbol"], "Tempo gráfico": c["interval"], "Perda máxima por trade": risk,
                 "Meta de lucro/dia": c["daily_profit_target"], "Limite de perda/dia": c["daily_max_loss"],
                 "Alavancagem": f"{c['leverage']:g}×" if c["leverage_on"] else "sem", "Personalidade": (personalities.get(c["personality"]) or {}).get("name", c["personality"]),
                 "Piloto automático": "ligado" if c["autopilot"] else "desligado"})
st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

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
