"""Tela das chaves de API das corretoras (usada em Minha conta e na tela de configuração inicial obrigatória).

A corretora é a escolhida em Minha conta (a mesma dos dados de mercado). Cada corretora guarda a sua própria chave."""
import streamlit as st

from core import credentials, exchanges

HELP = {
    "binance": "Na Binance: **Gerenciamento de API → Criar API**. Marque só **Leitura** e **Trade** (e Futuros, se for usar). Nunca ative **Saque**.",
    "bybit": "Na Bybit: **Perfil → API → Criar nova chave → Gerada pelo sistema**. Permissões de leitura e trade; sem saque.",
    "okx": "Na OKX: **Perfil → API → Criar chave V5**. Escolha *Ler* e *Negociar* (sem *Sacar*) e anote a **passphrase** que você definir.",
    "coinbase": "Na Coinbase: **Configurações → API → Nova chave (Advanced Trade)**. Copie o nome da chave (API Key) e a chave privada (Secret).",
    "kraken": "Na Kraken: **Configurações → API → Gerar nova chave**. Marque consulta de fundos e trade; sem saque.",
    "kucoin": "Na KuCoin: **Gerenciamento de API → Criar API**. Permissões *Geral* e *Trade* e anote a **passphrase** da chave.",
    "bitget": "Na Bitget: **Gerenciamento de API → Criar API**. Leitura e trade (sem saque) e anote a **passphrase**.",
    "gate": "No Gate: **Gerenciamento de API → Criar chave**. Permissões de leitura e trade (spot/futuros); sem saque.",
    "mexc": "Na MEXC: **Gerenciamento de API → Criar API**. Leitura e trade; sem saque.",
    "htx": "Na HTX: **Gerenciamento de API → Criar API**. Leitura e trade; sem saque.",
    "bingx": "Na BingX: **Gerenciamento de API → Criar API**. Leitura e trade (spot/perpétuos); sem saque.",
}


def render_keys(user: str, key_prefix: str = "bn") -> None:
    ex = exchanges.selected()
    name = exchanges.label(ex)
    st.markdown(f"#### 🔗 Chave de API · {name}")
    st.caption(f"Corretora escolhida acima: **{name}**. Hoje as ordens do app são **simuladas**; a chave fica guardada **criptografada** na sua "
               "conta, pronta para quando a execução real for ativada. Cada corretora tem a sua chave, e o Secret nunca é mostrado de volta.")
    if not credentials.configured():
        st.warning("O administrador da plataforma ainda não definiu a chave de criptografia (SECRETS_KEY nos Secrets). "
                   "Enquanto isso não é possível guardar chaves de API.")
        return
    stt = credentials.status(user, ex)
    if stt:
        valid = {True: f"✅ validada na {name}", False: "⚠️ recusada", None: "🟡 salva sem validação"}[stt["validated"]]
        st.success(f"Chave conectada: ••••{stt['last4']} · {'conta de testes (testnet)' if stt['testnet'] else 'conta real'} · {valid} · "
                   f"salva em {stt['saved_at'][:16].replace('T', ' ')} UTC")
        if stt["perms"] and not stt["testnet"]:
            p = stt["perms"]
            st.caption(f"Permissões: leitura {'sim' if p.get('enableReading') else 'não'} · trade à vista {'sim' if p.get('enableSpotAndMarginTrading') else 'não'}"
                       f" · futuros {'sim' if p.get('enableFutures') else 'não'} · saque {'SIM' if p.get('enableWithdrawals') else 'não'} · "
                       f"restrita a IP {'sim' if p.get('ipRestrict') else 'não'}")
        if st.button(f"🗑️ Remover a chave da {name}", key=f"{key_prefix}_del_{ex}"):
            credentials.delete(user, ex)
            st.rerun()
        st.caption("Para trocar, remova e cadastre de novo.")
        return
    with st.expander("Como criar a chave com segurança", expanded=False):
        st.markdown(f"1. {HELP.get(ex, 'Crie a chave na área de API da corretora, só com leitura e trade.')}\n"
                    "2. **Nunca ative Saque.**\n3. Se puder, restrinja a chave a **IPs confiáveis**.\n"
                    "4. Copie a API Key e o Secret (o Secret aparece uma só vez).")
    with st.form(f"{key_prefix}_form_{ex}", clear_on_submit=False):
        api_key = st.text_input("API Key", autocomplete="off")
        secret = st.text_input("Secret", type="password", autocomplete="off")
        pp = st.text_input("Passphrase", type="password", autocomplete="off") if ex in credentials.NEEDS_PASSPHRASE else None
        testnet = st.checkbox("É uma chave da conta de testes (testnet)", value=False) if ex in credentials.HAS_TESTNET else False
        force = st.checkbox("Salvar mesmo se não for possível validar agora (algumas corretoras bloqueiam servidores)", value=False)
        go = st.form_submit_button("Validar e salvar", type="primary")
    if go:
        with st.spinner(f"Conferindo a chave na {name}…"):
            check = credentials.validate_any(ex, api_key.strip(), secret.strip(), testnet, pp)
        if check["ok"] is False:
            st.error(check["message"])
        elif check["ok"] is None and not force:
            st.warning(check["message"] + " Marque 'Salvar mesmo se não for possível validar' se quiser guardar assim.")
        else:
            try:
                credentials.save(user, api_key, secret, testnet, check, exchange=ex, passphrase=pp)
                st.success(check["message"] if check["ok"] else "Chave salva sem validação.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))


render_binance = render_keys   # nome antigo (tela de configuração inicial)
