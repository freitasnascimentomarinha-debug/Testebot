"""Painel geral: resumo das três subcontas simuladas."""
import pandas as pd
import streamlit as st

from core import paper
from core.profiles import PROFILES
from core.settings import load_settings
import json
from datetime import datetime

from core.storage import backend, export_all, import_all, load_json
from core.ui import cached_ticker, fmt

st.title("📊 Plataforma de Bots de Trade")
mode = paper.wallet_config()["mode"]
st.caption("Três bots operando com cotações reais — "
           + ("todos na mesma **carteira única**, junto com as suas ordens manuais." if mode == "única"
              else "cada um com a sua **banca separada**."))
st.page_link("views/wallet.py", label="Abrir Carteira (banca, aportes, extrato e histórico completo)", icon="💰")

cols = st.columns(3)
curves = []
for col, (key, profile) in zip(cols, PROFILES.items()):
    cfg = load_settings(key)
    acct = paper.get_account(paper.account_id(key))
    prices = {}
    for sym in {p["symbol"] for p in acct["positions"]} | {cfg["symbol"]}:
        try:
            prices[sym] = cached_ticker(sym, profile.market).last
        except Exception:  # noqa: BLE001
            pass
    s = paper.stats(acct, prices, bot=key)
    with col.container(border=True):
        st.markdown(f"### {profile.icon} {profile.name}")
        st.caption(f"{profile.market_label} · {cfg['symbol']} {cfg['interval']} · "
                   f"{'alavancado ' + str(cfg['leverage']) + '×' if cfg['leverage_on'] else 'sem alavancagem'}")
        a, b = st.columns(2)
        a.metric("Banca" + (" (única)" if mode == "única" else ""), fmt(s["equity"]), f"{s['total_pnl_pct']:+.2f}%")
        b.metric("Hoje", fmt(s["pnl_today"]), f"{s['trades_today']}/{cfg['max_trades_day']} operações", delta_color="off")
        a.metric("Posições abertas", s["open_positions"])
        b.metric("Acerto", f"{s['win_rate']:.0f}%", f"{s['trades']} trades", delta_color="off")
        st.caption(f"Piloto automático: {'🟢 ligado' if cfg['autopilot'] else '⚪ desligado'} · "
                   f"Perda máx./trade: {fmt(cfg['max_loss_usdt']) + ' USDT' if cfg['risk_mode'] == 'USDT' else str(cfg['max_loss_pct']) + '%'}")
        st.page_link(f"views/{ {'day': 'day_trade', 'swing': 'swing_trade', 'long': 'long_trade'}[key] }.py",
                     label="Abrir bot", icon="➡️")
    curve = pd.DataFrame(acct["equity_curve"])
    if len(curve) and (mode == "separada" or not curves):
        curve["time"] = pd.to_datetime(curve["time"])
        curves.append(curve.set_index("time")["equity"].rename(profile.name if mode == "separada" else "Carteira"))

if curves:
    st.subheader("Evolução da banca")
    st.line_chart(pd.concat(curves, axis=1).sort_index().ffill(), height=300)

st.subheader("Últimas decisões dos bots")
logs = load_json("decisions.json", {}) or {}
rows = [{"bot": PROFILES[k].name, **e} for k, v in logs.items() if k in PROFILES for e in v]
if rows:
    df = pd.DataFrame(rows).sort_values("time", ascending=False).head(30)
    st.dataframe(df[["time", "bot", "symbol", "interval", "decision", "source", "confidence", "approved", "executed", "reasoning"]],
                 hide_index=True)
else:
    st.caption("Nenhuma análise ainda. Abra um bot e clique em **Analisar mercado e programar ordem**.")

with st.expander("Como funciona o fluxo de decisão"):
    st.markdown("""
1. **Dados reais** — candles e cotação da Binance (futuros USDⓈ-M ou spot), com fallback para a OKX.
2. **Habilidades de programação** — 9 regras determinísticas (tendência, momentum, MACD, Bollinger, SuperTrend,
   VWAP, volume/OBV, estrutura de topos/fundos e suportes/resistências) votam de −1 a +1 com pesos por estilo.
3. **IA (via OpenRouter)** — recebe o contexto completo e devolve um JSON com decisão,
   entrada, stop, alvo, confiança, riscos e condução.
4. **Gestor de risco** — dimensiona a posição pela sua *perda máxima por trade*, valida R:R mínimo, metas diárias,
   limite de perda, posições simultâneas, alavancagem e liquidação.
5. **Execução** — ordem enviada à conta simulada (fase 2: Binance). Stops e alvos são monitorados com as máximas e
   mínimas reais de cada candle.
""")

with st.expander("💾 Backup e restauração dos dados"):
    st.caption(f"Armazenamento atual: **{backend().name}**. O backup inclui contas simuladas, configurações e logs.")
    c1, c2 = st.columns(2)
    c1.download_button("⬇️ Baixar backup (JSON)", json.dumps(export_all(), ensure_ascii=False, default=str, indent=1),
                       file_name=f"tradebot_backup_{datetime.now():%Y%m%d_%H%M}.json", mime="application/json")
    up = c2.file_uploader("Restaurar backup", type="json")
    if up and c2.button("Restaurar (substitui os dados atuais)", type="primary"):
        n = import_all(json.load(up))
        st.success(f"{n} conjuntos de dados restaurados.")
        st.rerun()
