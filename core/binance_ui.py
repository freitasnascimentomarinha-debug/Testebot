"""Tela da chave da Binance de cada usuário (usada em Minha conta e na tela de configuração inicial obrigatória)."""
import streamlit as st

from core import credentials


def render_binance(user: str, key_prefix: str = "bn") -> None:
    st.markdown("#### 🔗 Conexão com a Binance")
    st.caption("Hoje as ordens do app são **simuladas**; a sua chave fica guardada **criptografada** na sua conta, pronta para quando a "
               "execução real for ativada. Só você a cadastra, e o Secret nunca é mostrado de volta.")
    if not credentials.configured():
        st.warning("O administrador da plataforma ainda não definiu a chave de criptografia (SECRETS_KEY nos Secrets). "
                   "Enquanto isso não é possível guardar chaves da Binance.")
        return
    stt = credentials.status(user)
    if stt:
        valid = {True: "✅ validada na Binance", False: "⚠️ recusada", None: "🟡 salva sem validação"}[stt["validated"]]
        st.success(f"Chave conectada: ••••{stt['last4']} · {'conta de testes (testnet)' if stt['testnet'] else 'conta real'} · {valid} · "
                   f"salva em {stt['saved_at'][:16].replace('T', ' ')} UTC")
        if stt["perms"] and not stt["testnet"]:
            p = stt["perms"]
            st.caption(f"Permissões: leitura {'sim' if p.get('enableReading') else 'não'} · trade à vista {'sim' if p.get('enableSpotAndMarginTrading') else 'não'}"
                       f" · futuros {'sim' if p.get('enableFutures') else 'não'} · saque {'SIM' if p.get('enableWithdrawals') else 'não'} · "
                       f"restrita a IP {'sim' if p.get('ipRestrict') else 'não'}")
        if st.button("🗑️ Remover a chave da minha conta", key=f"{key_prefix}_del"):
            credentials.delete(user)
            st.rerun()
        st.caption("Para trocar, remova e cadastre de novo.")
        return
    with st.expander("Como criar a chave com segurança", expanded=False):
        st.markdown("1. Na Binance: **Gerenciamento de API → Criar API**.\n"
                    "2. Marque só **Leitura** e **Trade** (futuros, se for usar o Day Trade). **Nunca ative Saque**: chaves com saque são recusadas.\n"
                    "3. Se puder, restrinja a chave a **IPs confiáveis**.\n"
                    "4. Para treinar sem risco, use uma chave da **conta de testes (testnet)** e marque a opção abaixo.\n"
                    "5. Copie a API Key e o Secret (o Secret aparece uma só vez).")
    with st.form(f"{key_prefix}_form", clear_on_submit=False):
        api_key = st.text_input("API Key", autocomplete="off")
        secret = st.text_input("Secret", type="password", autocomplete="off")
        testnet = st.checkbox("É uma chave da conta de testes (testnet)", value=False)
        force = st.checkbox("Salvar mesmo se não for possível validar agora (a Binance bloqueia alguns servidores)", value=False)
        go = st.form_submit_button("Validar e salvar", type="primary")
    if go:
        with st.spinner("Conferindo a chave na Binance…"):
            check = credentials.validate(api_key.strip(), secret.strip(), testnet)
        if check["ok"] is False:
            st.error(check["message"])
        elif check["ok"] is None and not force:
            st.warning(check["message"] + " Marque 'Salvar mesmo se não for possível validar' se quiser guardar assim.")
        else:
            try:
                credentials.save(user, api_key, secret, testnet, check)
                st.success(check["message"] if check["ok"] else "Chave salva sem validação.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
