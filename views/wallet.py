"""Carteira simulada: banca, aportes/retiradas, extrato e desempenho."""
import io
from datetime import datetime

from pathlib import Path

import pandas as pd
import streamlit as st

from core import paper, wallet_view
from core.profiles import PROFILES
from core.data import get_usdt_brl
from core.ui import cached_ticker, fmt

st.title("💰 Carteira simulada")
st.caption("Defina a sua banca e opere como se fosse real: cada entrada sua ou dos bots usa esta banca, "
           "e o histórico, o extrato e o saldo são atualizados automaticamente com preços reais.")


@st.cache_data(ttl=300, show_spinner=False)
def usdt_brl():
    return get_usdt_brl()


mode = paper.wallet_config()["mode"]
accounts = [paper.SHARED_ACCOUNT] if mode == "única" else list(PROFILES)
labels = {paper.SHARED_ACCOUNT: "Carteira única", **{k: f"{p.icon} {p.name}" for k, p in PROFILES.items()}}

# ----------------------------------------------------------- configuração
with st.expander("⚙️ Configurar carteira (valor inicial e modo)", expanded=False):
    c1, c2 = st.columns(2)
    new_mode = c1.radio("Modo", ["única", "separada"], index=0 if mode == "única" else 1, horizontal=True,
                        format_func=lambda m: "Carteira única (bots + você na mesma banca)" if m == "única"
                        else "Separada por bot (uma banca para cada)")
    initial = c2.number_input("Valor inicial da banca (USDT)", min_value=10.0, max_value=1e8, value=100.0, step=10.0)
    brl = usdt_brl()
    if brl:
        c2.caption(f"≈ R$ {fmt(initial * brl)} (USDT/BRL {fmt(brl, 4)})")
    target = paper.SHARED_ACCOUNT if new_mode == "única" else c1.selectbox(
        "Banca a criar/reiniciar", list(PROFILES), format_func=lambda a: labels[a])
    ok = st.checkbox("Entendo que isso zera a banca escolhida: posições, ordens, histórico e extrato.")
    if st.button("Criar / reiniciar carteira", type="primary", disabled=not ok):
        paper.set_wallet_mode(new_mode)
        paper.reset_account(target, initial)
        st.success(f"Carteira criada com {fmt(initial)} USDT.")
        st.rerun()
    if new_mode != mode and not ok:
        st.info("Para trocar o modo, marque a confirmação e clique em Criar / reiniciar carteira.")

acc = paper.SHARED_ACCOUNT if mode == "única" else st.segmented_control(
    "Banca", list(PROFILES), default="day", format_func=lambda a: labels[a]) or "day"
acct = paper.get_account(acc)

prices = {}
for p in acct["positions"]:
    try:
        prices[p["symbol"]] = cached_ticker(p["symbol"], p["market"]).last
    except Exception:  # noqa: BLE001
        pass
s = paper.stats(acct, prices)
brl = usdt_brl()

# ------------------------------------------------------- resumo, gráficos e abas (componente)
_DIR = Path(__file__).resolve().parent.parent / "core"


@st.cache_resource(show_spinner=False)
def _component():
    return st.components.v2.component("tb_wallet", css=(_DIR / "wallet_ui.css").read_text(encoding="utf-8"),
                                      js=(_DIR / "wallet.js").read_text(encoding="utf-8"))


_component()(key=f"tb-wallet-{acc}", data=wallet_view.wallet_data(acct, s, brl=brl, mode=mode, label=labels[acc]))

# ------------------------------------------------------- aporte / retirada
with st.expander("💵 Aporte ou retirada"):
    c = st.columns([1, 1, 2, 1])
    kind = c[0].radio("Tipo", ["Aporte", "Retirada"], horizontal=True, label_visibility="collapsed")
    amount = c[1].number_input("Valor (USDT)", min_value=0.0, value=100.0, step=50.0, label_visibility="collapsed")
    note = c[2].text_input("Observação", placeholder="Ex.: aporte mensal", label_visibility="collapsed")
    if c[3].button("Registrar", width="stretch"):
        try:
            paper.cash_movement(acc, amount if kind == "Aporte" else -amount, note)
            st.success(f"{kind} de {fmt(amount)} USDT registrado.")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

# --------------------------------------------------- tabelas para o Excel
hist = pd.DataFrame(acct["history"])
ledger = pd.DataFrame(acct["ledger"])
daily = pd.DataFrame()
if len(hist):
    hist["closed_dt"] = pd.to_datetime(hist["closed"]).dt.tz_convert("America/Sao_Paulo")
    daily = hist.assign(Data=hist["closed_dt"].dt.date).groupby("Data").agg(
        Operações=("pnl", "size"), Ganhos=("pnl", lambda x: int((x > 0).sum())), Perdas=("pnl", lambda x: int((x <= 0).sum())),
        Resultado=("pnl", "sum"), Taxas=("fees_total", "sum")).sort_index()
    daily["Acumulado"] = daily["Resultado"].cumsum()

# ----------------------------------------------------------------- Excel
def excel() -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        pd.DataFrame([{"Indicador": k, "Valor": v} for k, v in {
            "Banca (USDT)": s["equity"], "Capital investido": s["invested"], "Resultado total": s["total_pnl"],
            "Resultado total (%)": s["total_pnl_pct"], "Saldo livre": s["available"], "Em margem": s["in_margin"],
            "P&L aberto (líquido)": s["unrealized_net"], "Operações": s["trades"], "Taxa de acerto (%)": s["win_rate"],
            "Fator de lucro": s["profit_factor"], "Drawdown máximo (%)": s["max_drawdown"],
            "Gerado em": datetime.now().strftime("%d/%m/%Y %H:%M")}.items()]).to_excel(xw, sheet_name="Resumo", index=False)
        if len(hist):
            out = hist.drop(columns=["closed_dt"], errors="ignore").copy()
            for col in out.select_dtypes(include=["datetimetz"]).columns:
                out[col] = out[col].dt.tz_localize(None)
            out.to_excel(xw, sheet_name="Operações", index=False)
        if len(daily):
            daily.to_excel(xw, sheet_name="Resultado diário")
        if len(ledger):
            ledger.to_excel(xw, sheet_name="Extrato", index=False)
        if len(acct["equity_curve"]):
            pd.DataFrame(acct["equity_curve"]).to_excel(xw, sheet_name="Evolução da banca", index=False)
    return buf.getvalue()


st.download_button("⬇️ Exportar carteira para Excel", excel(), file_name=f"carteira_{datetime.now():%Y%m%d_%H%M}.xlsx",
                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
