"""Administração de contas: autorizar pedidos, bloquear, reativar, excluir e redefinir senhas (só admins)."""
import pandas as pd
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

rows = accounts.list_accounts()
pend = [r for r in rows if r["estado"] == accounts.PENDING]
act = [r for r in rows if r["estado"] == accounts.ACTIVE]
blk = [r for r in rows if r["estado"] == accounts.BLOCKED]
c = st.columns(3)
c[0].metric("Pedidos pendentes", len(pend))
c[1].metric("Contas ativas", len(act))
c[2].metric("Bloqueadas", len(blk))
st.caption("Ninguém entra sem a sua autorização. O admin principal é definido nos Secrets (ADMIN_USER / ADMIN_PASSWORD) e não pode ser "
           "bloqueado nem excluído por aqui. Bloqueio e exclusão passam a valer em até 1 minuto, mesmo para quem está conectado.")

st.subheader(f"⏳ Pedidos aguardando autorização ({len(pend)})")
if not pend:
    st.caption("Nenhum pedido pendente.")
for r in pend:
    with st.container(border=True):
        a, b, d = st.columns([3, 1, 1])
        a.markdown(f"**{r['usuario']}** · pedido em {r['criado'][:16].replace('T', ' ')} UTC")
        a.caption(f"Quem é: {r['nota'] or '— (não informado)'}")
        if b.button("✅ Autorizar", key=f"ap_{r['usuario']}", type="primary", width="stretch"):
            run(accounts.approve, r["usuario"], ok=f"{r['usuario']} autorizado.")
        if d.button("🚫 Recusar", key=f"rj_{r['usuario']}", width="stretch"):
            run(accounts.delete, r["usuario"], ok=f"Pedido de {r['usuario']} recusado e apagado.")

st.subheader(f"✅ Contas ativas ({len(act)})")
for r in act:
    with st.container(border=True):
        a, b = st.columns([3, 2])
        a.markdown(f"**{r['usuario']}** · {r['papel']}{' · principal (Secrets)' if r['principal'] else ''}")
        a.caption(f"Criada: {r['criado'][:10] or '—'} · último acesso: {r['ultimo_acesso'][:16].replace('T', ' ') or '—'}"
                  + (f" · {r['nota']}" if r["nota"] else ""))
        if r["principal"] or r["usuario"] == me:
            b.caption("Esta é a sua conta." if r["usuario"] == me else "")
            continue
        c1, c2, c3 = b.columns(3)
        if c1.button("⛔ Bloquear", key=f"bl_{r['usuario']}", width="stretch"):
            run(accounts.block, r["usuario"], ok=f"{r['usuario']} bloqueado.")
        with c2.popover("🔑 Senha", width="stretch"):
            pw = st.text_input("Nova senha provisória (mín. 8)", type="password", key=f"pw_{r['usuario']}")
            if st.button("Definir senha", key=f"pwb_{r['usuario']}"):
                run(accounts.reset_password, r["usuario"], pw, ok=f"Senha de {r['usuario']} redefinida. Informe a ela(e) por um canal seguro.")
        with c3.popover("⋯", width="stretch"):
            is_adm = r["papel"] == "admin"
            if st.button("Remover admin" if is_adm else "Tornar admin", key=f"ad_{r['usuario']}", width="stretch"):
                run(accounts.set_admin, r["usuario"], not is_adm, ok=f"{r['usuario']} agora é {'usuário' if is_adm else 'admin'}.")
            st.divider()
            wipe = st.checkbox("Apagar também os dados (carteira, extrato, configurações)", value=True, key=f"wp_{r['usuario']}")
            if st.button("🗑️ Excluir conta", key=f"dl_{r['usuario']}", type="primary", width="stretch"):
                run(accounts.delete, r["usuario"], wipe, ok=f"Conta {r['usuario']} excluída.")

st.subheader(f"⛔ Contas bloqueadas ({len(blk)})")
if not blk:
    st.caption("Nenhuma conta bloqueada.")
for r in blk:
    with st.container(border=True):
        a, b, d = st.columns([3, 1, 1])
        a.markdown(f"**{r['usuario']}** · bloqueada")
        if b.button("↩️ Reativar", key=f"ub_{r['usuario']}", width="stretch"):
            run(accounts.unblock, r["usuario"], ok=f"{r['usuario']} reativado.")
        with d.popover("🗑️ Excluir", width="stretch"):
            wipe = st.checkbox("Apagar também os dados", value=True, key=f"wpb_{r['usuario']}")
            if st.button("Confirmar exclusão", key=f"dlb_{r['usuario']}", type="primary"):
                run(accounts.delete, r["usuario"], wipe, ok=f"Conta {r['usuario']} excluída.")

with st.expander("📋 Todas as contas (tabela)"):
    st.dataframe(pd.DataFrame(rows).rename(columns={"usuario": "Usuário", "estado": "Estado", "papel": "Papel", "principal": "Principal",
                                                    "criado": "Criada em", "ultimo_acesso": "Último acesso", "nota": "Nome informado"}),
                 hide_index=True, width="stretch")
