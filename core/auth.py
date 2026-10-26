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
from pathlib import Path

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
        user = st.session_state.get("_user")
        if user:
            if time.time() - st.session_state.get("_chk", 0) > 45:  # um bloqueio/exclusão feito pelo admin vale em até 45 s
                st.session_state["_chk"] = time.time()
                if not accounts.is_active(user):
                    st.session_state.clear()
                    st.query_params.pop("s", None)
                    st.session_state["_msg"] = "O seu acesso foi encerrado pelo administrador."
                    return False
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
    """Interrompe a página até o usuário entrar (tela de login em JavaScript, com o mascote do Cripto Robô)."""
    if is_authenticated():
        return
    if accounts.enabled():
        problem = accounts.storage_problem()
        if problem and problem[1]:
            st.error(problem[0])
            st.stop()
        if problem and "_login_msg" not in st.session_state:
            _say("warn", problem[0])
    if msg := st.session_state.pop("_msg", None):
        _say("warn", msg)
    _login_screen("contas" if accounts.enabled() else "senha")
    st.stop()


_DIR = Path(__file__).resolve().parent


@st.cache_resource(show_spinner=False)
def _login_component():
    return st.components.v2.component("tb_login", css=(_DIR / "login.css").read_text(encoding="utf-8"),
                                      js=(_DIR / "login.js").read_text(encoding="utf-8"))


def _say(kind: str, text: str) -> None:
    st.session_state["_login_msg"] = {"kind": kind, "text": str(text).replace("**", "")}


def _new(res, name: str) -> dict | None:
    ev = getattr(res, name, None)
    if ev and ev.get("uid") != st.session_state.get(f"_login_{name}_uid"):
        st.session_state[f"_login_{name}_uid"] = ev.get("uid")
        return ev
    return None


def _failed(text: str) -> None:
    fails = st.session_state.get("auth_fails", 0) + 1
    st.session_state["auth_fails"] = fails
    time.sleep(1.0)  # desestimula tentativa e erro
    if fails >= MAX_ATTEMPTS:
        st.session_state["auth_locked_until"] = time.time() + LOCK_SECONDS
        st.session_state["auth_fails"] = 0
    _say("err", text)


def _login_screen(mode: str) -> None:
    from core import mascot

    data = {"mode": mode, "name": mascot.NAME, "mascot": mascot.svg(190, uid="crlg"), "message": st.session_state.get("_login_msg"),
            "signup_open": mode == "contas" and accounts.signup_open(), "needs_code": mode == "contas" and accounts.needs_code(),
            "last_user": st.session_state.get("_login_user", ""), "tab": st.session_state.get("_login_tab"), "tabNonce": st.session_state.get("_login_nonce")}
    res = _login_component()(key="tb-login", data=data, on_login_change=lambda: None, on_signup_change=lambda: None)
    if ev := _new(res, "login"):
        st.session_state.pop("_login_msg", None)
        locked = st.session_state.get("auth_locked_until", 0)
        if time.time() < locked:
            _say("err", f"Muitas tentativas. Aguarde {int(locked - time.time())} s.")
        elif mode == "contas":
            st.session_state["_login_user"] = str(ev.get("user", ""))[:40]
            try:
                _start_session(accounts.authenticate(str(ev.get("user", "")), str(ev.get("pw", ""))), bool(ev.get("remember")))
            except ValueError as exc:
                _failed(str(exc))
        else:
            password = get_secret("APP_PASSWORD") or ""
            if hmac.compare_digest(str(ev.get("pw", "")).encode(), password.encode()):
                st.session_state["auth_ok"] = True
                st.session_state.pop("auth_fails", None)
                if ev.get("remember"):
                    st.query_params["s"] = _token(password)
            else:
                _failed("Senha incorreta.")
        st.rerun()
    if (ev := _new(res, "signup")) and mode == "contas":
        st.session_state.pop("_login_msg", None)
        if ev.get("pw") != ev.get("pw2"):
            _say("err", "As senhas não conferem.")
            st.session_state.update(_login_tab="up", _login_nonce=time.time())
        else:
            try:
                created = accounts.register(str(ev.get("user", "")), str(ev.get("pw", "")), ev.get("code") or None, str(ev.get("note", ""))[:80])
                _say("ok", f"Pedido enviado para {created}. O administrador precisa autorizar a conta; depois disso entre aqui com o usuário e a senha escolhidos.")
                st.session_state.update(_login_tab="in", _login_nonce=time.time(), _login_user=created)
            except ValueError as exc:
                _say("err", str(exc))
                st.session_state.update(_login_tab="up", _login_nonce=time.time())
        st.rerun()


def _start_session(user: str, remember: bool) -> None:
    st.session_state.clear()  # nada da sessão anterior (outro usuário) pode vazar para esta
    st.session_state["_user"] = user
    if remember:
        st.query_params["s"] = accounts.make_token(user)
    st.rerun()


def logout() -> None:
    st.session_state.clear()
    st.query_params.pop("s", None)
    st.rerun()
