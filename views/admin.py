"""Administração de contas: autorizar pedidos, bloquear, reativar, excluir e redefinir senhas (só admins)."""
from pathlib import Path

import streamlit as st

from core import accounts
from core.auth import current_user

me = current_user()
st.title("🛡️ Administração de contas")
if not accounts.is_admin(me):
    st.error("Acesso restrito a administradores.")
    st.stop()


def run(action, *args, ok="Feito.", **kw):
    try:
        action(me, *args, **kw)
        st.session_state["_admin_msg"] = ok
    except (ValueError, PermissionError) as exc:
        st.session_state["_admin_msg"] = "⚠️ " + str(exc)
    st.rerun()


if msg := st.session_state.pop("_admin_msg", None):
    st.info(msg)

st.caption("Ninguém entra sem a sua autorização. O admin principal é definido nos Secrets (ADMIN_USER / ADMIN_PASSWORD) e não pode ser "
           "bloqueado nem excluído por aqui. Bloqueio e exclusão passam a valer em até 1 minuto, mesmo para quem está conectado.")

_DIR = Path(__file__).resolve().parent.parent / "core"


@st.cache_resource(show_spinner=False)
def _component():
    return st.components.v2.component("tb_admin", css=(_DIR / "wallet_ui.css").read_text(encoding="utf-8"),
                                      js=(_DIR / "admin.js").read_text(encoding="utf-8"))


ACTIONS = {
    "approve": lambda u, ev: run(accounts.approve, u, ok=f"{u} autorizado."),
    "reject": lambda u, ev: run(accounts.delete, u, ok=f"Pedido de {u} recusado e apagado."),
    "block": lambda u, ev: run(accounts.block, u, ok=f"{u} bloqueado."),
    "unblock": lambda u, ev: run(accounts.unblock, u, ok=f"{u} reativado."),
    "admin": lambda u, ev: run(accounts.set_admin, u, not accounts.is_admin(u), ok=f"{u} agora é {'usuário' if accounts.is_admin(u) else 'admin'}."),
    "password": lambda u, ev: run(accounts.reset_password, u, str(ev.get("password") or ""), ok=f"Senha de {u} redefinida. Informe a pessoa por um canal seguro."),
    "delete": lambda u, ev: run(accounts.delete, u, bool(ev.get("wipe", True)), ok=f"Conta {u} excluída."),
}
res = _component()(key="tb-admin", on_action_change=lambda: None,
                   data={"rows": accounts.list_accounts(), "me": me, "PENDING": accounts.PENDING, "ACTIVE": accounts.ACTIVE, "BLOCKED": accounts.BLOCKED})
ev = getattr(res, "action", None)
if ev and ev.get("uid") != st.session_state.get("_adm_uid") and ev.get("kind") in ACTIONS and ev.get("user"):
    st.session_state["_adm_uid"] = ev["uid"]
    ACTIONS[ev["kind"]](str(ev["user"]), ev)   # cada função do core/accounts confere de novo se quem pede é admin
