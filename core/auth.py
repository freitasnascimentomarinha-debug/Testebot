"""Senha de acesso à plataforma.

Dois modos:

* **Contas de usuário** (``AUTH_MODE = "contas"``): cada pessoa cria o seu usuário e senha e tem os próprios dados
  (ver ``core/accounts.py``).
* **Senha única** (``APP_PASSWORD``): quem sabe a senha entra. Sem nenhuma das duas, o app fica aberto (uso local).
"""
from __future__ import annotations

import hashlib
import hmac
import time

import streamlit as st

from core import accounts
from core.storage import get_secret

MAX_ATTEMPTS = 5
LOCK_SECONDS = 60


def _token(password: str) -> str:
    """Token derivado da senha, guardado na URL para não pedir login a cada
    recarregamento. Trocar a senha invalida todos os tokens."""
    return hmac.new(password.encode(), b"tradebot-session-v1", hashlib.sha256).hexdigest()[:32]


def password_configured() -> bool:
    return accounts.enabled() or bool(get_secret("APP_PASSWORD"))


def current_user() -> str | None:
    return st.session_state.get("_user")


def is_authenticated() -> bool:
    if accounts.enabled():
        if st.session_state.get("_user"):
            return True
        user = accounts.verify_token(st.query_params.get("s"))
        if user:
            st.session_state["_user"] = user
            return True
        return False
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
    if accounts.enabled():
        _accounts_login()
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


def _start_session(user: str, remember: bool) -> None:
    st.session_state.clear()  # nada da sessão anterior (outro usuário) pode vazar para esta
    st.session_state["_user"] = user
    if remember:
        st.query_params["s"] = accounts.make_token(user)
    st.rerun()


def _accounts_login() -> None:
    problem = accounts.storage_problem()
    _, col, _ = st.columns([1, 1.3, 1])
    with col:
        if problem and problem[1]:
            st.error(problem[0])
            st.stop()
        if problem:
            st.warning(problem[0])
        st.markdown("## 🔒 TradeBot")
        st.caption("Plataforma de bots de trade — entre com o seu usuário ou crie uma conta.")
        locked_until = st.session_state.get("auth_locked_until", 0)
        t_in, t_new = st.tabs(["Entrar", "Criar conta"])
        with t_in:
            with st.form("login_user"):
                user = st.text_input("Usuário")
                pw = st.text_input("Senha", type="password")
                remember = st.checkbox("Manter conectado neste navegador (link com acesso salvo, vale 14 dias)", value=True)
                ok = st.form_submit_button("Entrar", type="primary", width="stretch")
            if ok:
                if time.time() < locked_until:
                    st.error(f"Muitas tentativas. Aguarde {int(locked_until - time.time())} s.")
                else:
                    try:
                        _start_session(accounts.authenticate(user, pw), remember)
                    except ValueError as exc:
                        fails = st.session_state.get("auth_fails", 0) + 1
                        st.session_state["auth_fails"] = fails
                        time.sleep(1.0)
                        if fails >= 5:
                            st.session_state["auth_locked_until"] = time.time() + 60
                            st.session_state["auth_fails"] = 0
                        st.error(str(exc))
        with t_new:
            if not accounts.signup_open():
                st.info("O cadastro de novas contas está fechado.")
            else:
                with st.form("signup_user"):
                    user = st.text_input("Escolha um usuário", help="3 a 20 caracteres: letras minúsculas, números, ponto, hífen e sublinhado.")
                    pw = st.text_input("Senha (mínimo 8 caracteres)", type="password")
                    pw2 = st.text_input("Repita a senha", type="password")
                    code = st.text_input("Código de convite", type="password") if accounts.needs_code() else None
                    ok = st.form_submit_button("Criar conta", type="primary", width="stretch")
                if ok:
                    if pw != pw2:
                        st.error("As senhas não conferem.")
                    else:
                        try:
                            created = accounts.register(user, pw, code)
                            _start_session(created, True)
                        except ValueError as exc:
                            st.error(str(exc))
    st.stop()


def logout() -> None:
    st.session_state.clear()
    st.query_params.pop("s", None)
    st.rerun()
