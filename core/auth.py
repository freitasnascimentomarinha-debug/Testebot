"""Senha de acesso à plataforma.

Defina ``APP_PASSWORD`` nos secrets do Streamlit (ou variável de ambiente).
Sem senha definida, o app fica aberto (uso local) e mostra um aviso.
"""
from __future__ import annotations

import hashlib
import hmac
import time

import streamlit as st

from core.storage import get_secret

MAX_ATTEMPTS = 5
LOCK_SECONDS = 60


def _token(password: str) -> str:
    """Token derivado da senha, guardado na URL para não pedir login a cada
    recarregamento. Trocar a senha invalida todos os tokens."""
    return hmac.new(password.encode(), b"tradebot-session-v1", hashlib.sha256).hexdigest()[:32]


def password_configured() -> bool:
    return bool(get_secret("APP_PASSWORD"))


def is_authenticated() -> bool:
    password = get_secret("APP_PASSWORD")
    if not password or st.session_state.get("auth_ok"):
        return True
    token = st.query_params.get("s")
    if token and hmac.compare_digest(token, _token(password)):
        st.session_state["auth_ok"] = True
        return True
    return False


def require_login() -> None:
    """Interrompe a página até o usuário informar a senha correta."""
    if is_authenticated():
        return
    password = get_secret("APP_PASSWORD")

    _, col, _ = st.columns([1, 1.2, 1])
    with col:
        st.markdown("## 🔒 TradeBot")
        st.caption("Plataforma de bots de trade — acesso restrito.")
        locked_until = st.session_state.get("auth_locked_until", 0)
        if time.time() < locked_until:
            st.error(f"Muitas tentativas. Aguarde {int(locked_until - time.time())} s.")
            st.stop()
        with st.form("login"):
            typed = st.text_input("Senha", type="password")
            remember = st.checkbox("Manter conectado neste navegador (link com acesso salvo)", value=True)
            ok = st.form_submit_button("Entrar", type="primary", width="stretch")
        if ok:
            if hmac.compare_digest(typed.encode(), password.encode()):
                st.session_state["auth_ok"] = True
                st.session_state.pop("auth_fails", None)
                if remember:
                    st.query_params["s"] = _token(password)
                st.rerun()
            fails = st.session_state.get("auth_fails", 0) + 1
            st.session_state["auth_fails"] = fails
            time.sleep(1.5)  # desestimula tentativa e erro
            if fails >= MAX_ATTEMPTS:
                st.session_state["auth_locked_until"] = time.time() + LOCK_SECONDS
                st.session_state["auth_fails"] = 0
            st.error("Senha incorreta.")
    st.stop()


def logout() -> None:
    st.session_state.pop("auth_ok", None)
    st.query_params.pop("s", None)
    st.rerun()
