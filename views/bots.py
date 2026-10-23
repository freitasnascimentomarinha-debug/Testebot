"""Galeria de bots especialistas: um card por bot com especialidade, dica rápida,
desempenho simulado (com % estimada ao mês) e desempenho real."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import indicators as ind, personalities as P, regime
from core.profiles import PROFILES
from core.settings import default_settings, load_settings, save_settings
from core.strategy import SKILLS
from core.ui import cached_klines, cached_symbols

st.title("🤖 Bots especialistas")
st.caption("Cada bot é especialista em um estilo, timeframe, indicador e relação risco:retorno. O desempenho simulado "
           "vem de testes com candles reais (1% da banca arriscado por operação, com taxas); o real vem das operações "
           "feitas pelos bots na carteira simulada. Resultado passado não garante resultado futuro.")

if msg := st.session_state.pop("bots_toast", None):
    st.toast(msg, icon="✅")

SKILL_NAMES = {k: v[0] for k, v in SKILLS.items()}
STYLE = {"day": "⚡ Day trade", "swing": "🌊 Swing", "long": "🏔️ Longo prazo"}


def rr_label(p: dict) -> str:
    sl, tp = float(p.get("sl_atr") or 1), float(p.get("tp_atr") or 1)
    r = tp / sl
    if r >= 1:
        return f"{r:.1f}:1".replace(".0:", ":").replace(".", ",")
    return f"1:{1 / r:.1f}".replace(".0", "").replace(".", ",")


def activate(p: dict, bot: str) -> None:
    cfg = load_settings(bot)
    cfg["personality"] = p["id"]
    st.session_state[f"{bot}__personality"] = p["id"]
    msg = f"{p['name']} ativado no {PROFILES[bot].name}."
    tested = p.get("tested_interval")
    if tested and tested in PROFILES[bot].intervals:
        cfg["interval"] = tested
        st.session_state[f"{bot}__interval"] = tested
        msg += f" Timeframe: {tested}."
    save_settings(bot, cfg)
    st.session_state["bots_toast"] = msg  # exibido após o recarregamento da página


live = {r["id"]: r for r in P.ranking()}
bots = [p for p in P.list_all() if p.get("research", {}).get("monthly_pct") is not None or not p.get("builtin")]

tab_gal, tab_now, tab_ctx = st.tabs(["🃏 Galeria", "🧭 Contexto agora", "📊 Desempenho por contexto"])

with tab_gal:
    # ------------------------------------------------------------------ filtros
    c1, c2, c3, c4 = st.columns([1.2, 1.6, 1.2, 1.2])
    style_f = c1.multiselect("Estilo", list(STYLE), format_func=STYLE.get, placeholder="Todos")
    skills_f = c2.multiselect("Indicador", sorted({k for p in bots for k in p.get("skills", {})}),
                              format_func=lambda k: SKILL_NAMES.get(k, k), placeholder="Todos")
    rr_f = c3.multiselect("Risco:retorno", sorted({rr_label(p) for p in bots}), placeholder="Todos")
    order = c4.selectbox("Ordenar por", ["% ao mês", "Acerto", "Menor queda", "Operações reais"])
    only_ok = st.toggle("Mostrar só os aprovados na prova final (moedas que o teste não viu)", value=False)

    view = []
    for p in bots:
        rs = p.get("research", {})
        if style_f and p.get("bot") not in style_f:
            continue
        if skills_f and not set(skills_f) & set(p.get("skills", {})):
            continue
        if rr_f and rr_label(p) not in rr_f:
            continue
        if only_ok and rs.get("status") != "aprovado":
            continue
        view.append(p)
    key = {"% ao mês": lambda p: -(p.get("research", {}).get("monthly_pct") or -999),
           "Acerto": lambda p: -(p.get("research", {}).get("win_pct") or 0),
           "Menor queda": lambda p: p.get("research", {}).get("dd_pct") or 999,
           "Operações reais": lambda p: -(live.get(p["id"], {}).get("live_trades") or 0)}[order]
    view.sort(key=key)

    ok = sum(1 for p in bots if p.get("research", {}).get("status") == "aprovado")
    st.caption(f"{len(view)} de {len(bots)} bots · {ok} aprovados na prova final")

    # --------------------------------------------------------------------- cards
    in_use = {b: load_settings(b).get("personality") for b in PROFILES}
    cols = st.columns(3)
    for n, p in enumerate(view):
        rs = p.get("research", {})
        lv = live.get(p["id"], {})
        bot = p.get("bot") or ("day" if "futures" in p.get("markets", []) else "swing")
        with cols[n % 3].container(border=True):
            st.markdown(f"#### {p['name']}")
            mk = rs.get("market") or ("futures" if "futures" in p.get("markets", ["futures"])[:1] else "spot")
            market = "Futuros" if mk == "futures" else "Spot"
            badges = [STYLE.get(bot, bot), rs.get("interval") or p.get("tested_interval") or p.get("timeframes", ""), market,
                      f"R:R {rr_label(p)}"]
            st.markdown(" ".join(f"`{b}`" for b in badges if b))
            st.caption(f"**{p.get('specialty', '')}**")
            if p.get("filters", {}).get("contexts"):
                st.caption("🔒 Opera só em: " + ", ".join(regime.label(c) for c in p["filters"]["contexts"])
                           + " — fora disso fica de fora (nos outros contextos a simulação foi negativa).")
            st.markdown(f"💡 {p.get('tip') or p.get('summary', '')}")
            if rs:
                m1, m2 = st.columns(2)
                m1.metric("Ao mês (simulado)", f"{rs['monthly_pct']:+.1f}%",
                          f"{rs['ret_pct']:+.1f}% em {rs['period_label']}",
                          help="Estimativa mensal composta a partir do período simulado: "
                               "(1 + retorno do período)^(30 ÷ dias) − 1, média de 10 moedas, 1% de risco por operação.")
                m2.metric("Acerto", f"{rs['win_pct']:.0f}%", f"pior queda −{rs['dd_pct']:.0f}%", delta_color="off")
                status = {"aprovado": "✅ Aprovado na prova final", "ressalva": "🟡 Aprovado com ressalva",
                          "fraco": "⚠️ Fraco no período"}.get(rs.get("status"), "")
                st.caption(f"{status} · ~{rs['trades_month']:.0f} operações/mês · {rs['pos_coins']} moedas positivas")
                best, filt = rs.get("best_contexts") or [], rs.get("context_filtered")
                if best and filt:
                    better = filt["ret_pct"] > rs["ret_pct"] and filt["status"] == "aprovado"
                    st.caption(f"🎯 **Melhor contexto:** {', '.join(regime.label(c) for c in best)} · só nele(s): "
                               f"≈ {filt['monthly_pct']:+.1f}%/mês, acerto {filt['win_pct']:.0f}% "
                               + ("✅ **recomendado ligar o filtro**" if better else "(sem ganho sobre operar sempre)"))
                elif rs.get("contexts"):
                    st.caption("🎯 Nenhum contexto com resultado positivo consistente.")
            if lv.get("live_trades"):
                st.caption(f"📊 Real: {lv['live_trades']} operações · acerto {lv['live_win_rate']:.0f}% · "
                           f"{(lv['live_avg_r'] or 0):+.2f}R por operação · {lv['live_pnl']:+.2f} USDT")
            else:
                st.caption("📊 Real: ainda sem operações — ative para começar a medir.")
            using = [PROFILES[b].name for b, pid in in_use.items() if pid == p["id"]]
            b1, b2 = st.columns([1.2, 1])
            label = "✅ Em uso" if bot in in_use and in_use[bot] == p["id"] else f"Ativar no {PROFILES[bot].name}"
            if b1.button(label, key=f"act_{p['id']}", type="primary", width="stretch", disabled=label.startswith("✅")):
                activate(p, bot)
                st.rerun()
            with b2.popover("Detalhes", width="stretch"):
                st.markdown(p.get("description", ""))
                st.markdown("**Indicadores (peso):** " + ", ".join(
                    f"{SKILL_NAMES.get(k, k)} ({w:g})" for k, w in sorted(p.get("skills", {}).items(), key=lambda x: -x[1])))
                f = p.get("filters", {})
                filt = [P.FILTERS[k] for k, v in f.items() if v and k in P.FILTERS]
                if f.get("adx_min"):
                    filt.append(f"ADX ≥ {f['adx_min']}")
                if f.get("adx_max"):
                    filt.append(f"ADX ≤ {f['adx_max']}")
                if f.get("vol_mult"):
                    filt.append(f"Volume ≥ {f['vol_mult']:g}× a média")
                st.markdown(f"**Direção:** {P.DIRECTIONS[p.get('direction', 'misto')]} · **Stop/alvo:** "
                            f"{p.get('sl_atr')}× / {p.get('tp_atr')}× ATR · **Filtros:** {', '.join(filt) or 'nenhum'}")
                if rs.get("per_symbol"):
                    st.markdown(f"**Simulação ({rs['period_label']}, até {rs['tested_at']}):**")
                    st.dataframe(pd.DataFrame([{"Moeda": k.replace("USDT", ""), "Retorno": v}
                                               for k, v in rs["per_symbol"].items()]),
                                 hide_index=True, column_config={"Retorno": st.column_config.NumberColumn(format="%+.1f%%")})
                    st.caption(f"Moedas da busca: {rs['ret_seen']:+.1f}% · moedas inéditas (prova final): "
                               f"{rs['ret_new']:+.1f}%.")
                if rs.get("contexts"):
                    st.markdown("**Desempenho por contexto do gráfico** (operando só naquele contexto):")
                    st.dataframe(pd.DataFrame([{
                        "Contexto": regime.label(k), "% do tempo": rs.get("context_share", {}).get(k),
                        "Operações": v["n"], "Acerto": v["win_pct"], "R médio": v["avg_r"], "Retorno": v["ret_pct"]}
                        for k, v in rs["contexts"].items()]).sort_values("R médio", ascending=False),
                        hide_index=True, column_config={
                            "% do tempo": st.column_config.NumberColumn(format="%.0f%%"),
                            "Acerto": st.column_config.NumberColumn(format="%.0f%%"),
                            "R médio": st.column_config.NumberColumn(format="%+.2f"),
                            "Retorno": st.column_config.NumberColumn(format="%+.1f%%")})
                if using:
                    st.caption("Em uso no: " + ", ".join(using))

    if not view:
        st.info("Nenhum bot com esses filtros.")


# --------------------------------------------------------------- contexto agora
TF_SETS = [("futures", "5m", "day"), ("futures", "15m", "day"), ("futures", "1h", "day"),
           ("spot", "4h", "swing"), ("spot", "1d", "long")]

with tab_now:
    st.caption("Contexto atual do gráfico em cada timeframe (último candle fechado) e os bots que tiveram o melhor "
               "resultado operando exatamente nesse contexto na simulação.")
    symbols = cached_symbols("futures")
    sym = st.selectbox("Moeda", symbols, index=symbols.index("BTCUSDT") if "BTCUSDT" in symbols else 0, key="ctx_sym")
    for market, itv, bot_key in TF_SETS:
        cfg = {**default_settings(PROFILES[bot_key]), "interval": itv}
        try:
            df = ind.compute(cached_klines(sym, itv, 400, market), cfg)
        except Exception as exc:  # noqa: BLE001
            st.warning(f"{itv}: sem dados ({exc})")
            continue
        ctx = str(df["regime"].iloc[-2])
        with st.container(border=True):
            c1, c2 = st.columns([1, 2])
            c1.markdown(f"**{itv} · {'Futuros' if market == 'futures' else 'Spot'}**  \n### {regime.label(ctx)}")
            c1.caption(regime.REGIMES[ctx][1])
            recs = P.best_for_context(ctx, market=market, interval=itv) if ctx != "indefinido" else []
            if not recs and ctx != "indefinido":
                recs = P.best_for_context(ctx, market=market)
            if recs:
                c2.markdown("**Melhores bots neste contexto:**")
                for p, c in recs:
                    c2.markdown(f"- {p['name']} ({p['research']['interval']}): **{c['avg_r']:+.2f}R por operação**, "
                                f"acerto {c['win_pct']:.0f}%, {c['n']} operações simuladas")
            else:
                c2.caption("Sem sinal claro ou sem bot com resultado positivo consistente neste contexto: "
                           "melhor ficar de fora.")

# ------------------------------------------------------ desempenho por contexto
with tab_ctx:
    st.caption("Retorno simulado de cada bot operando **somente** em cada contexto do gráfico (1% de risco por "
               "operação, média de 10 moedas, mesmo período do card). Células vazias: menos de 3 operações.")
    metric = st.radio("Mostrar", ["Retorno (%)", "R médio por operação", "Acerto (%)"], horizontal=True)
    field = {"Retorno (%)": "ret_pct", "R médio por operação": "avg_r", "Acerto (%)": "win_pct"}[metric]
    ctx_keys = [k for k in regime.ORDER if k != "indefinido"]
    rows, names = [], []
    for p in sorted(bots, key=lambda p: -(p.get("research", {}).get("monthly_pct") or -99)):
        rs = p.get("research") or {}
        if not rs.get("contexts"):
            continue
        names.append(f"{p['name']} · {rs['interval']}")
        rows.append([rs["contexts"][k][field] if rs["contexts"][k]["n"] >= 3 else None for k in ctx_keys])
    if rows:
        z = pd.DataFrame(rows, index=names, columns=[regime.label(k) for k in ctx_keys])
        mid = 50 if field == "win_pct" else 0
        fig = go.Figure(go.Heatmap(
            z=z.values, x=z.columns, y=z.index, colorscale=[[0, "#ef5350"], [0.5, "#1c2030"], [1, "#26a69a"]],
            zmid=mid, text=[[("" if v is None or v != v else (f"{v:+.1f}" if field != "win_pct" else f"{v:.0f}"))
                             for v in r] for r in z.values], texttemplate="%{text}", hoverongaps=False,
            colorbar=dict(title=metric)))
        fig.update_layout(height=60 + 26 * len(z), template="plotly_dark", margin=dict(l=10, r=10, t=30, b=10),
                          yaxis=dict(autorange="reversed"), xaxis=dict(side="top"))
        st.plotly_chart(fig, config={"displayModeBar": False})
        st.caption("Como ler: verde = o bot ganhou dinheiro operando só naquele contexto; vermelho = perdeu. "
                   "Use junto com a aba 🧭 Contexto agora para escolher o bot certo para o momento do gráfico.")

    st.markdown("#### Resumo: melhores bots em cada contexto")
    resumo = []
    for k in ctx_keys:
        top = P.best_for_context(k, top=3, min_trades=10)
        resumo.append({"Contexto": regime.label(k), "Quando acontece": regime.REGIMES[k][1],
                       "1º": f"{top[0][0]['name']} ({top[0][0]['research']['interval']}) {top[0][1]['avg_r']:+.2f}R" if top else "—",
                       "2º": f"{top[1][0]['name']} ({top[1][0]['research']['interval']}) {top[1][1]['avg_r']:+.2f}R" if len(top) > 1 else "—",
                       "3º": f"{top[2][0]['name']} ({top[2][0]['research']['interval']}) {top[2][1]['avg_r']:+.2f}R" if len(top) > 2 else "—"})
    st.dataframe(pd.DataFrame(resumo), hide_index=True)
    st.caption("R médio por operação quando o bot operou só naquele contexto (mínimo de 10 operações simuladas).")
