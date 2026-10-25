"""Carteira simulada: banca, aportes/retiradas, extrato e desempenho."""
import io
from datetime import datetime

import pandas as pd
import streamlit as st

from core import paper
from core.profiles import PROFILES
from core.data import get_usdt_brl
from core.ui import cached_ticker, fmt

st.title("💰 Carteira simulada")
st.caption("Defina a sua banca e opere como se fosse real: cada entrada sua ou dos bots usa esta banca, "
           "e o histórico, o extrato e o saldo são atualizados automaticamente com preços reais.")


@st.cache_data(ttl=300, show_spinner=False)
def usdt_brl():
    return get_usdt_brl()


def bot_name(b):
    return PROFILES[b].name if b in PROFILES else "—"


def origin(src):
    return "Você (manual)" if src == "manual" else "Bot (IA)" if src == "ia" else "Bot (regras)"


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

# ------------------------------------------------------------------ resumo
m = st.columns(6)
m[0].metric("Banca", f"{fmt(s['equity'])} USDT", f"{fmt(s['total_pnl'])} ({s['total_pnl_pct']:+.2f}%)",
            help="Saldo livre + margens + resultado das posições abertas.")
m[1].metric("Capital investido", fmt(s["invested"]), f"inicial {fmt(acct['initial'])}", delta_color="off")
m[2].metric("Saldo livre", fmt(s["available"]))
m[3].metric("Alocado em posições", fmt(s["in_margin"]), f"{s['open_positions']} posição(ões)", delta_color="off")
m[4].metric("P&L aberto (líquido)", fmt(s["unrealized_net"]))
m[5].metric("Hoje", fmt(s["pnl_today"]), f"{s['trades_today']} operações", delta_color="off")
if brl:
    st.caption(f"≈ R$ {fmt(s['equity'] * brl)} pela cotação USDT/BRL {fmt(brl, 4)} · modo: "
               f"{'carteira única' if mode == 'única' else 'separada por bot'} · criada em {acct['created'][:10]}")
m = st.columns(5)
m[0].metric("Operações", s["trades"])
m[1].metric("Taxa de acerto", f"{s['win_rate']:.1f}%")
m[2].metric("Fator de lucro", "∞" if s["profit_factor"] == float("inf") else fmt(s["profit_factor"]))
m[3].metric("Ganho médio / perda média", f"{fmt(s['avg_win'])} / {fmt(s['avg_loss'])}")
m[4].metric("Drawdown máximo", f"{s['max_drawdown']:.2f}%")

# ------------------------------------------------------- aporte / retirada
with st.container(border=True):
    st.markdown("**Aporte ou retirada**")
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

# ------------------------------------------------------------------- abas
hist = pd.DataFrame(acct["history"])
ledger = pd.DataFrame(acct["ledger"])
curve = pd.DataFrame(acct["equity_curve"])
tz = "America/Sao_Paulo"
t1, t2, t3, t4, t5 = st.tabs(["📈 Evolução da banca", "📅 Resultado diário", "🧑‍💻 Você × Bots",
                              "📜 Histórico de operações", "🧾 Extrato"])

with t1:
    if len(curve) > 1:
        curve["time"] = pd.to_datetime(curve["time"]).dt.tz_convert(tz)
        curve["Pico"] = curve["equity"].cummax()
        curve["Drawdown (%)"] = (curve["equity"] / curve["Pico"] - 1) * 100
        st.line_chart(curve.set_index("time")[["equity"]].rename(columns={"equity": "Banca (USDT)"}), height=300)
        st.area_chart(curve.set_index("time")[["Drawdown (%)"]], height=150, color="#ef5350")
    else:
        st.caption("A curva aparece conforme a carteira é atualizada (a cada 5 min ou a cada operação).")

daily = pd.DataFrame()
if len(hist):
    hist["closed_dt"] = pd.to_datetime(hist["closed"]).dt.tz_convert(tz)
    hist["Data"] = hist["closed_dt"].dt.date
    daily = hist.groupby("Data").agg(Operações=("pnl", "size"), Ganhos=("pnl", lambda x: int((x > 0).sum())),
                                     Perdas=("pnl", lambda x: int((x <= 0).sum())), Resultado=("pnl", "sum"),
                                     Taxas=("fees_total", "sum")).sort_index()
    daily["Acumulado"] = daily["Resultado"].cumsum()
    daily["Acerto (%)"] = daily["Ganhos"] / daily["Operações"] * 100

with t2:
    if len(daily):
        st.bar_chart(daily["Resultado"], height=220, color="#26a69a")
        st.dataframe(daily.iloc[::-1], column_config={
            "Resultado": st.column_config.NumberColumn(format="%.2f"), "Taxas": st.column_config.NumberColumn(format="%.2f"),
            "Acumulado": st.column_config.NumberColumn(format="%.2f"),
            "Acerto (%)": st.column_config.NumberColumn(format="%.0f%%")})
    else:
        st.caption("Sem operações encerradas ainda.")

with t3:
    if len(hist):
        hist["Origem"] = hist["source"].map(origin)
        hist["Bot"] = hist.get("bot", pd.Series([""] * len(hist))).map(bot_name)

        def summary(g):
            wins, losses = g[g["pnl"] > 0]["pnl"], g[g["pnl"] <= 0]["pnl"]
            return pd.Series({"Operações": len(g), "Acerto (%)": len(wins) / len(g) * 100, "Resultado": g["pnl"].sum(),
                              "Ganho médio": wins.mean() if len(wins) else 0.0,
                              "Perda média": losses.mean() if len(losses) else 0.0,
                              "Fator de lucro": wins.sum() / abs(losses.sum()) if losses.sum() else float("nan")})

        fmtcfg = {k: st.column_config.NumberColumn(format="%.2f") for k in ("Resultado", "Ganho médio", "Perda média", "Fator de lucro")}
        fmtcfg["Acerto (%)"] = st.column_config.NumberColumn(format="%.0f%%")
        st.markdown("**Por origem da decisão**")
        st.dataframe(hist.groupby("Origem").apply(summary, include_groups=False), column_config=fmtcfg)
        st.markdown("**Por bot**")
        st.dataframe(hist.groupby("Bot").apply(summary, include_groups=False), column_config=fmtcfg)
    else:
        st.caption("Quando houver operações encerradas, aqui aparece a comparação entre as suas entradas e as do bot.")

with t4:
    if len(hist):
        view = hist.copy()
        f1, f2, f3 = st.columns(3)
        bots = f1.multiselect("Bot", sorted(view["Bot"].unique()))
        origins = f2.multiselect("Origem", sorted(view["Origem"].unique()))
        symbols = f3.multiselect("Ativo", sorted(view["symbol"].unique()))
        if bots:
            view = view[view["Bot"].isin(bots)]
        if origins:
            view = view[view["Origem"].isin(origins)]
        if symbols:
            view = view[view["symbol"].isin(symbols)]
        view["Abertura"] = pd.to_datetime(view["opened"]).dt.tz_convert(tz).dt.strftime("%d/%m/%Y %H:%M")
        view["Encerramento"] = view["closed_dt"].dt.strftime("%d/%m/%Y %H:%M")
        view["Lado"] = view["side"].map({"BUY": "Compra", "SELL": "Venda"})
        cols = {"Abertura": "Abertura", "Encerramento": "Encerramento", "Bot": "Bot", "Origem": "Origem",
                "symbol": "Ativo", "Lado": "Lado", "qty": "Qtd.", "entry": "Entrada", "exit": "Saída",
                "leverage": "Alav.", "reason": "Motivo", "fees_total": "Taxas", "pnl": "Resultado (USDT)",
                "pnl_pct_margin": "% s/ margem"}
        table = view.reindex(columns=list(cols)).rename(columns=cols).iloc[::-1]
        st.dataframe(table, hide_index=True, column_config={
            "Resultado (USDT)": st.column_config.NumberColumn(format="%.2f"),
            "Taxas": st.column_config.NumberColumn(format="%.2f"),
            "% s/ margem": st.column_config.NumberColumn(format="%.1f%%")})
        st.caption(f"{len(table)} operações · resultado do filtro: {fmt(view['pnl'].sum())} USDT")
    else:
        st.caption("Nenhuma operação encerrada ainda.")

with t5:
    if len(ledger):
        lg = ledger.copy()
        lg["Data/hora"] = pd.to_datetime(lg["time"]).dt.tz_convert(tz).dt.strftime("%d/%m/%Y %H:%M:%S")
        lg["Bot"] = lg["bot"].map(bot_name)
        lg = lg.rename(columns={"type": "Lançamento", "symbol": "Ativo", "amount": "Valor (USDT)",
                                "bank": "Banca realizada", "detail": "Detalhe"})
        lg = lg[["Data/hora", "Lançamento", "Bot", "Ativo", "Valor (USDT)", "Banca realizada", "Detalhe"]].iloc[::-1]
        st.dataframe(lg, hide_index=True, column_config={
            "Valor (USDT)": st.column_config.NumberColumn(format="%+.2f"),
            "Banca realizada": st.column_config.NumberColumn(format="%.2f")})
        st.caption("Banca realizada = saldo livre + margens em uso (sem o resultado das posições ainda abertas).")
    else:
        st.caption("Sem lançamentos.")

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
