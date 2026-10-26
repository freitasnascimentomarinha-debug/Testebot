"""Bots: ranking diário (dia, semana e mês), calculadora, backtest sob demanda, criação, biblioteca e contextos — tudo numa página."""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import accounts, bot_performance, fastsim, indicators as ind, personalities as P, regime
from core.ai import strategy_from_text
from core.paper import account_id, get_account, stats
from core.profiles import PROFILES
from core.settings import DEFAULT_MODEL, default_settings
from core.storage import current_user
from core.strategy import SKILLS
from core.ui import api_key, cached_klines, cached_symbols, cached_votes, fmt

st.title("🤖 Bots")
st.caption("Cada bot é uma estratégia (indicadores, entrada, direção e stop/alvo) treinada num mercado e tempo gráfico. O ranking é refeito "
           "sozinho uma vez por dia com os candles mais recentes; a calculadora e o backtest mostram quanto cada um teria rendido. "
           "Resultado passado não garante resultado futuro. No fechamento de cada candle o sistema escolhe sozinho o melhor bot para o contexto.")

SKILL_NAMES = {k: v[0] for k, v in SKILLS.items()}
STYLE = {"day": "⚡ Day trade", "swing": "🌊 Swing", "long": "🏔️ Longo prazo"}
MARKET_LABEL = {"futures": "Futuros", "spot": "Spot (só compra)"}


def mlabel(m: str) -> str:
    return MARKET_LABEL.get(m, m)


def rr_label(p: dict) -> str:
    if p.get("trail_atr"):
        return "sem alvo (surfa)"
    sl, tp = float(p.get("sl_atr") or 1), float(p.get("tp_atr") or 1)
    r = tp / sl
    if r >= 1:
        return f"{r:.1f}:1".replace(".0:", ":").replace(".", ",")
    return f"1:{1 / r:.1f}".replace(".0", "").replace(".", ",")



live = {r["id"]: r for r in P.ranking()}
bots = [p for p in P.list_all() if p.get("research", {}).get("monthly_pct") is not None or not p.get("builtin")]
if msg := st.session_state.pop("bots_msg", None):
    st.info(msg)

tab_rank, tab_calc, tab_bt, tab_new, tab_lib, tab_ctx = st.tabs(["🏆 Ranking", "🧮 Calculadora", "🔁 Backtest", "✍️ Criar bot", "📚 Biblioteca",
                                                                 "🧭 Contextos"])

# ------------------------------------------------------------------ ranking diário
bot_performance.refresh_if_due()   # 1x por dia, em segundo plano (o worker 24/7 também dispara)


@st.fragment(run_every=30)
def _ranking():
    upd, busy = bot_performance.last_update(), bot_performance.running()
    st.caption(("🔄 Atualizando o ranking de hoje em segundo plano… a tabela muda sozinha quando terminar. " if busy else "")
               + (f"Atualizado em {upd:%d/%m %H:%M} UTC · próxima atualização automática amanhã." if upd else "Ainda não calculado."))
    c1, c2, c3 = st.columns([1, 1, 1.2])
    m = c1.selectbox("Mercado", ["", "futures", "spot"], format_func=lambda x: "Todos" if not x else mlabel(x), key="rk_m")
    itvs = sorted({r["interval"] for r in bot_performance.rows(m or None)}, key=lambda i: -fastsim.PER_DAY.get(i, 0))
    i = c2.selectbox("Tempo gráfico", [""] + itvs, format_func=lambda x: x or "Todos", key="rk_i")
    order = c3.selectbox("Ordenar por", list(bot_performance.LABELS), index=2, format_func=lambda k: f"Retorno no {bot_performance.LABELS[k].lower()}", key="rk_o")
    rows = bot_performance.rows(m or None, i or None)
    pct = lambda r, k, f="ret_pct": (r[k] or {}).get(f)  # noqa: E731
    rows.sort(key=lambda r: (pct(r, order) is None, -(pct(r, order) or 0)))
    if not rows or all(pct(r, "d30") is None for r in rows):
        st.info("O ranking diário ainda não foi calculado. Ele roda sozinho em segundo plano; para um bot específico agora, use a aba 🔁 Backtest.")
        return
    tag = {"aprovado": "✅", "ressalva": "🟡", "fraco": "⚠️"}
    table = pd.DataFrame([{
        "#": n + 1, "Bot": f"{tag.get(r['status'], '·')} {r['name']}", "Mercado": "Futuros" if r["market"] == "futures" else "Spot",
        "Tempo": r["interval"], "Dia": pct(r, "d1"), "Semana": pct(r, "d7"), "Mês": pct(r, "d30"),
        "Operações no mês": pct(r, "d30", "trades"), "Acerto no mês": pct(r, "d30", "win_pct"), "Pior queda no mês": pct(r, "d30", "dd_pct"),
        "Moedas positivas (mês)": f"{pct(r, 'd30', 'positive')}/{pct(r, 'd30', 'symbols')}" if r["d30"] else None,
        "Real (USDT)": r["live_pnl"] if r["live_trades"] else None,
    } for n, r in enumerate(rows)])
    pc = lambda h: st.column_config.NumberColumn(format="%+.2f%%", help=h)  # noqa: E731
    st.dataframe(table, hide_index=True, placeholder="—", height=min(38 + 35 * len(table), 640), column_config={
        "Dia": pc("Retorno nas últimas 24 h (média das 5 moedas, 1% de risco por operação, com taxas)"), "Semana": pc("Últimos 7 dias"),
        "Mês": pc("Últimos 30 dias"), "Acerto no mês": st.column_config.NumberColumn(format="%.0f%%"),
        "Pior queda no mês": st.column_config.NumberColumn(format="−%.1f%%"), "Real (USDT)": st.column_config.NumberColumn(format="%+.2f",
                                                                                                                       help="Resultado das operações reais do bot na carteira simulada")})
    st.caption(f"Simulado em {', '.join(s.replace('USDT', '') for s in P.PERIOD_SYMBOLS)} (cada moeda com a própria banca; a coluna é a média), "
               "só com as regras do bot, entrada no candle seguinte ao sinal e taxas incluídas.")

    st.markdown("##### 📈 Evolução diária")
    pick = st.selectbox("Bot", [r["id"] for r in rows], format_func=lambda pid: next(r["name"] for r in rows if r["id"] == pid), key="rk_hist")
    hist = bot_performance.history(pick)
    if len(hist) < 2:
        st.caption("A evolução aparece a partir do segundo dia de atualizações (o histórico guarda até 90 dias).")
    else:
        df = pd.DataFrame(hist)
        fig = go.Figure([go.Scatter(x=df["date"], y=df[k], mode="lines+markers", name=bot_performance.LABELS[k]) for k in ("d1", "d7", "d30") if k in df])
        fig.update_layout(height=260, template="plotly_dark", margin=dict(l=10, r=10, t=10, b=10), yaxis_title="Retorno (%)", legend=dict(orientation="h"))
        st.plotly_chart(fig, config={"displayModeBar": False})


with tab_rank:
    _ranking()

# ------------------------------------------------------------------ backtest sob demanda
with tab_bt:
    st.caption("Força agora a atualização de um bot: refaz a simulação de 1, 7 e 30 dias com os candles mais recentes no mercado e tempo gráfico "
               "dele, salva no ranking e mostra o resultado por moeda. A atualização automática de todos continua 1x por dia.")
    allp = bot_performance.tracked()
    c1, c2 = st.columns([2.4, 1])
    bt_id = c1.selectbox("Bot", [p["id"] for p in allp], key="bt_bot",
                         format_func=lambda pid: (lambda p, h: f"{p['name']} · {mlabel(h[0])} {h[1]}")(P.get(pid), bot_performance.home(P.get(pid))))
    if c2.button("▶️ Rodar backtest agora", type="primary", width="stretch"):
        bar = st.progress(0.0, text="Baixando candles recentes…")
        try:
            got = bot_performance.refresh_bot(bt_id, getter=lambda s, i, n, m: cached_klines(s, i, n, m),
                                              progress=lambda f, t: bar.progress(min(f, 1.0), text=t))
        except Exception as exc:  # noqa: BLE001
            got = None
            st.error(f"Não foi possível rodar agora: {exc}")
        bar.empty()
        if got:
            st.toast("Backtest salvo no ranking.", icon="✅")
        elif got is None:
            st.warning("Sem candles para este bot agora.")
    e = bot_performance.load()["results"].get(bt_id)
    if e:
        st.markdown(f"**{e['name']}** · {mlabel(e['market'])} {e['interval']} · atualizado em {e['updated'][:16].replace('T', ' ')} UTC")
        cols = st.columns(3)
        for col, k in zip(cols, ("d1", "d7", "d30")):
            w = e[k]
            col.metric(f"Último {bot_performance.LABELS[k].lower()}", f"{w['ret_pct']:+.2f}%",
                       f"{w['trades']} operações · acerto {w['win_pct']:.0f}%", delta_color="off")
        if e.get("per_symbol"):
            st.dataframe(pd.DataFrame([{"Moeda": s.replace("USDT", ""), "Retorno no mês": v} for s, v in e["per_symbol"].items()]),
                         hide_index=True, column_config={"Retorno no mês": st.column_config.NumberColumn(format="%+.2f%%")})
    else:
        st.info("Este bot ainda não tem resultado salvo. Clique em Rodar backtest agora.")

# ------------------------------------------------------------------ calculadora
with tab_calc:
    st.caption("Escolha um bot, as moedas, o período e a sua banca: o simulador refaz as operações que o bot teria "
               "feito com os candles reais (só as regras, sem gastar tokens da IA, com taxas) e mostra quanto você teria "
               "ganhado ou perdido.")
    allp = P.list_all()
    approved_first = sorted(allp, key=lambda p: (p.get("research", {}).get("status") != "aprovado",
                                                 -(p.get("research", {}).get("monthly_pct") or -99)))

    def bot_label(pid):
        p = P.get(pid)
        rs = p.get("research") or {}
        tag = {"aprovado": "✅", "ressalva": "🟡", "fraco": "⚠️"}.get(rs.get("status"), "·")
        return f"{tag} {p['name']}" + (f" · {rs['interval']}" if rs.get("interval") else "")

    c1, c2, c3 = st.columns([2.2, 1, 1])
    pid = c1.selectbox("Bot", [p["id"] for p in approved_first], format_func=bot_label, key="sim_bot")
    persona = P.get(pid)
    rs = persona.get("research") or {}
    # mercado e timeframe começam nos que o bot foi testado (podem ser trocados)
    if st.session_state.get("sim_last_bot") != pid:
        st.session_state["sim_market"] = rs.get("market") or (persona.get("markets") or ["spot"])[0]
        st.session_state["sim_itv"] = rs.get("interval") or persona.get("tested_interval") or "1h"
        st.session_state["sim_last_bot"] = pid
    market = c2.selectbox("Mercado", list(MARKET_LABEL), key="sim_market", format_func=mlabel)
    itv = c3.selectbox("Timeframe", ["5m", "15m", "1h", "4h", "1d"], key="sim_itv")
    st.caption(f"💡 {persona.get('tip') or persona.get('summary', '')}"
               + (f" · testado em {rs['interval']} ({mlabel(rs['market']).lower()})" if rs else ""))

    c1, c2, c3, c4 = st.columns([2.2, 1, 1, 1])
    symbols = cached_symbols(market)
    default_sym = ("BTCUSDT",)
    if st.session_state.get("sim_coins_market") != market:  # trocou de mercado: os ativos antigos não existem no novo
        st.session_state["sim_coins"] = [s_ for s_ in default_sym if s_ in symbols]
        st.session_state["sim_coins_market"] = market
    coins = c1.multiselect("Ativos", symbols, key="sim_coins",
                           help="Cada ativo é simulado e as operações entram na mesma banca, na ordem em que fecharam.")
    max_days = {"5m": 60, "15m": 120, "1h": 365, "4h": 900, "1d": 1500}[itv]
    period_opts = [d for d in (7, 15, 30, 40, 60, 90, 180, 365, 730) if d <= max_days]
    days = c2.selectbox("Período (dias)", period_opts, index=period_opts.index(40) if 40 in period_opts else 0,
                        key="sim_days")
    acct = get_account(account_id("day"))
    equity = stats(acct, {})["equity"]
    bank0 = c3.number_input("Banca inicial (USDT)", 10.0, 1e8, value=float(round(equity, 2)), step=100.0, key="sim_bank",
                            help="Começa com o valor atual da sua carteira simulada.")
    risk_pct = c4.number_input("Risco por operação (%)", 0.1, 10.0, value=1.0, step=0.25, key="sim_risk",
                               help="Quanto da banca é perdido se o stop for atingido.")
    compound_on = st.toggle("Juros compostos (o risco acompanha a banca)", value=True, key="sim_comp")

    if st.button("▶️ Simular", type="primary", disabled=not coins):
        rows, per_coin = [], []
        bar = st.progress(0.0, text="Baixando candles e calculando…")
        for n_, sym in enumerate(coins, start=1):
            try:
                vt, cfg = cached_votes(sym, itv, market, int(days))
            except Exception as exc:  # noqa: BLE001 - moeda sem dados nas fontes disponíveis
                st.warning(f"{sym}: sem candles disponíveis para {itv} ({str(exc)[:120]}…). Moeda ignorada.")
                continue
            trades = fastsim.period_trades(vt, cfg, persona, days=days, market=market)
            for t in trades:
                rows.append({**t, "moeda": sym})
            rs_ = [t["r"] for t in trades]
            per_coin.append({"Moeda": sym.replace("USDT", ""), "Operações": len(rs_),
                             "Acerto": (np.mean([r > 0 for r in rs_]) * 100) if rs_ else 0.0,
                             "R médio": float(np.mean(rs_)) if rs_ else 0.0})
            bar.progress(n_ / len(coins), text=f"{sym}: {len(trades)} operações")
        bar.empty()
        rows.sort(key=lambda t: t["saida"])
        bank, peak, max_dd, curve = bank0, bank0, 0.0, []
        for t in rows:
            base = bank if compound_on else bank0
            pnl = base * risk_pct / 100 * t["r"]
            bank = max(0.0, bank + pnl)
            peak = max(peak, bank)
            max_dd = max(max_dd, (peak - bank) / peak * 100 if peak else 0)
            t["resultado"] = pnl
            t["banca"] = bank
            curve.append({"time": t["saida"], "Banca (USDT)": bank})
        coin_pnl = {}
        for t in rows:
            coin_pnl[t["moeda"]] = coin_pnl.get(t["moeda"], 0.0) + t["resultado"]
        for pc in per_coin:
            pc["Resultado (USDT)"] = coin_pnl.get(pc["Moeda"] + "USDT", 0.0)
        st.session_state["sim_result"] = {"rows": rows, "per_coin": per_coin, "bank0": bank0, "bank": bank,
                                          "max_dd": max_dd, "curve": curve, "days": days, "bot": persona["name"],
                                          "itv": itv, "market": market, "risk": risk_pct, "comp": compound_on}

    res = st.session_state.get("sim_result")
    if res:
        rows = res["rows"]
        pnl = res["bank"] - res["bank0"]
        ret = pnl / res["bank0"] * 100
        monthly = ((1 + ret / 100) ** (30 / res["days"]) - 1) * 100 if res["bank"] > 0 else -100.0
        wins = [t for t in rows if t["resultado"] > 0]
        losses = [t for t in rows if t["resultado"] <= 0]
        st.markdown(f"**{res['bot']}** · {res['itv']} {'futuros' if res['market'] == 'futures' else 'spot'} · "
                    f"últimos {res['days']} dias · risco {res['risk']:g}% por operação"
                    f"{' com juros compostos' if res['comp'] else ' (valor fixo)'}")
        m = st.columns(5)
        m[0].metric("Banca final", f"{fmt(res['bank'])} USDT", f"{fmt(pnl)} USDT ({ret:+.2f}%)")
        m[1].metric("≈ por mês", f"{monthly:+.2f}%", help="(1 + retorno do período)^(30 ÷ dias) − 1")
        m[2].metric("Operações", len(rows), f"{len(wins)} ganhos · {len(losses)} perdas", delta_color="off")
        m[3].metric("Acerto", f"{len(wins) / len(rows) * 100:.0f}%" if rows else "—")
        m[4].metric("Pior queda da banca", f"−{res['max_dd']:.1f}%")
        m = st.columns(4)
        m[0].metric("Maior ganho", f"{fmt(max((t['resultado'] for t in rows), default=0))} USDT")
        m[1].metric("Maior perda", f"{fmt(min((t['resultado'] for t in rows), default=0))} USDT")
        gross_w, gross_l = sum(t["resultado"] for t in wins), -sum(t["resultado"] for t in losses)
        m[2].metric("Fator de lucro", fmt(gross_w / gross_l) if gross_l else ("∞" if gross_w else "—"))
        m[3].metric("Resultado por operação", f"{fmt(pnl / len(rows))} USDT" if rows else "—")
        if res["curve"]:
            curve = pd.DataFrame([{"time": res["rows"][0]["entrada"], "Banca (USDT)": res["bank0"]}] + res["curve"])
            color = "#26a69a" if res["bank"] >= res["bank0"] else "#ef5350"
            fig = go.Figure(go.Scatter(x=curve["time"], y=curve["Banca (USDT)"], mode="lines", line=dict(color=color, width=2),
                                       hovertemplate="%{x|%d/%m %H:%M}<br>%{y:,.2f} USDT"))
            fig.add_hline(y=res["bank0"], line=dict(color="#8a8f98", dash="dot", width=1),
                          annotation_text="banca inicial", annotation_position="bottom right")
            fig.update_layout(height=280, template="plotly_dark", margin=dict(l=10, r=10, t=20, b=10),
                              yaxis_title="Banca (USDT)", showlegend=False)
            st.plotly_chart(fig, config={"displayModeBar": False})
            st.dataframe(pd.DataFrame(res["per_coin"]), hide_index=True, column_config={
                "Acerto": st.column_config.NumberColumn(format="%.0f%%"),
                "R médio": st.column_config.NumberColumn(format="%+.2f"),
                "Resultado (USDT)": st.column_config.NumberColumn(format="%+.2f")})
            det = pd.DataFrame(rows)[["entrada", "saida", "moeda", "lado", "preco_entrada", "preco_saida", "motivo",
                                      "r", "resultado", "banca"]].iloc[::-1]
            for col in ("entrada", "saida"):
                det[col] = pd.to_datetime(det[col]).dt.tz_convert("America/Sao_Paulo").dt.strftime("%d/%m %H:%M")
            with st.expander(f"Ver as {len(det)} operações"):
                st.dataframe(det, hide_index=True, column_config={
                    "entrada": "Entrada", "saida": "Saída", "moeda": "Moeda", "lado": "Lado",
                    "preco_entrada": "Preço entrada", "preco_saida": "Preço saída", "motivo": "Saída por",
                    "r": st.column_config.NumberColumn("R", format="%+.2f"),
                    "resultado": st.column_config.NumberColumn("Resultado (USDT)", format="%+.2f"),
                    "banca": st.column_config.NumberColumn("Banca (USDT)", format="%.2f")})
        else:
            st.info("Nenhuma operação no período: o bot não encontrou entradas nas regras dele para estas moedas.")
        st.caption("Premissas: preços reais, taxas incluídas, entrada na abertura do candle seguinte ao sinal, stop "
                   "antes do alvo quando os dois cabem no mesmo candle; a IA não é simulada (só as regras). As operações "
                   "de moedas diferentes entram na banca na ordem em que fecharam. Resultado passado não garante futuro.")

# ------------------------------------------------------------ criar/editar
def load_template(p: dict, duplicate: bool) -> None:
    ss = st.session_state
    ss["pe_id"] = None if duplicate else p.get("id")
    ss["pe_name"] = (p.get("name", "") + " (cópia)") if duplicate else p.get("name", "")
    ss["pe_author"] = "" if duplicate else p.get("author", "")
    ss["pe_summary"] = p.get("summary", "")
    ss["pe_desc"] = p.get("description", "")
    ss["pe_dir"] = p.get("direction", "misto")
    ss["pe_skills"] = [k for k, w in p.get("skills", {}).items() if w > 0 and k in SKILLS]
    for k, w in p.get("skills", {}).items():
        ss[f"pe_w_{k}"] = float(w)
    ss["pe_threshold"] = int(p.get("threshold", 30))
    ss["pe_sl"] = float(p.get("sl_atr", 1.5))
    ss["pe_tp"] = float(p.get("tp_atr", 3.0))
    ss["pe_tf"] = p.get("timeframes", "")
    ss["pe_exit"] = "surf" if p.get("trail_atr") else "tp"
    ss["pe_trail"] = float(p.get("trail_atr") or 3.0)
    ss["pe_be"] = float(p.get("be_r") or 0.0)
    ss["pe_markets"] = p.get("markets", ["futures", "spot"])
    ss["pe_home_market"], ss["pe_home_itv"] = bot_performance.home(p)
    ss["pe_visibility"] = "privado" if duplicate and p.get("builtin") else (p.get("visibility") or "comunidade")
    ss["pe_shared"] = list(p.get("shared_with") or [])
    f = p.get("filters", {})
    for k in P.FILTERS:
        ss[f"pe_f_{k}"] = bool(f.get(k))
    ss["pe_adx_min"] = int(f.get("adx_min") or 0)
    ss["pe_adx_max"] = int(f.get("adx_max") or 0)
    ss["pe_vol_mult"] = float(f.get("vol_mult") or 0.0)


if st.session_state.pop("pe_reset", False):
    for k in [k for k in st.session_state if k.startswith("pe_")]:
        del st.session_state[k]
if "persona_template" in st.session_state:
    tpl = st.session_state.pop("persona_template")
    load_template(tpl, tpl.get("duplicate", False))
for key, default in (("pe_name", ""), ("pe_author", ""), ("pe_summary", ""), ("pe_desc", ""), ("pe_dir", "misto"),
                     ("pe_skills", ["tendencia", "momentum"]), ("pe_threshold", 30), ("pe_sl", 1.5), ("pe_tp", 3.0),
                     ("pe_tf", ""), ("pe_exit", "tp"), ("pe_trail", 3.0), ("pe_be", 0.0), ("pe_markets", ["futures", "spot"]), ("pe_adx_min", 0), ("pe_adx_max", 0), ("pe_vol_mult", 0.0),
                     ("pe_id", None), ("pe_visibility", "comunidade"), ("pe_shared", []), ("pe_home_market", "futures"), ("pe_home_itv", "1h")):
    st.session_state.setdefault(key, default)

with tab_new:
    editing = st.session_state.get("pe_id")
    st.markdown(f"#### {'Editando: ' + st.session_state['pe_name'] if editing else 'Novo bot'}")
    c1, c2 = st.columns(2)
    c1.text_input("Nome do bot", key="pe_name", placeholder="Ex.: Caçador de Pullback")
    c2.text_input("Seu nome (autor)", key="pe_author", placeholder="Ex.: Freitas")
    st.text_area("Descreva a sua estratégia", key="pe_desc", height=140,
                 placeholder="Ex.: Opero só comprado, a favor da média de 200. Espero o preço corrigir até a EMA 21 com "
                             "RSI perto de 40 e entro quando o candle volta a subir com volume. Stop abaixo do último "
                             "fundo, alvo de 3 vezes o risco. Evito mercado lateral.")
    c1, c2 = st.columns([1, 2])
    if c1.button("✨ Preencher os campos a partir da descrição", disabled=not st.session_state["pe_desc"].strip()):
        with st.spinner("Interpretando a estratégia…"):
            params, source = strategy_from_text(st.session_state["pe_desc"], api_key=api_key(), model=DEFAULT_MODEL)
        st.session_state["persona_template"] = {
            **params, "name": st.session_state["pe_name"], "author": st.session_state["pe_author"],
            "description": st.session_state["pe_desc"], "id": editing, "markets": st.session_state["pe_markets"]}
        st.session_state["pe_fill_msg"] = f"Campos preenchidos por {source}. Revise antes de salvar."
        st.rerun()
    if msg := st.session_state.pop("pe_fill_msg", None):
        c2.success(msg)
    st.text_input("Resumo (uma frase)", key="pe_summary")

    st.markdown("**Tipo de entrada e indicadores**")
    c1, c2 = st.columns([1, 2])
    c1.radio("Direção", list(P.DIRECTIONS), format_func=P.DIRECTIONS.get, key="pe_dir")
    c1.multiselect("Mercados", ["futures", "spot"], key="pe_markets",
                   format_func=lambda m: "Futuros" if m == "futures" else "Spot")
    c2.multiselect("Indicadores / habilidades usadas", list(SKILLS), format_func=SKILL_NAMES.get, key="pe_skills")
    weights = {}
    if st.session_state["pe_skills"]:
        cols = c2.columns(3)
        for i, k in enumerate(st.session_state["pe_skills"]):
            st.session_state.setdefault(f"pe_w_{k}", 1.0)
            weights[k] = cols[i % 3].slider(f"Peso · {SKILL_NAMES[k]}", 0.1, 3.0, step=0.1, key=f"pe_w_{k}")

    st.markdown("**Regras de entrada e saída**")
    c1, c2, c3, c4 = st.columns(4)
    c1.slider("Limiar de entrada", 10, 60, key="pe_threshold",
              help="Força mínima do consenso (0–100) para entrar. Menor = mais agressivo (mais entradas); "
                   "maior = mais seletivo.")
    c2.number_input("Stop (× ATR)", 0.3, 10.0, step=0.1, key="pe_sl")
    c3.number_input("Alvo (× ATR)", 0.5, 30.0, step=0.5, key="pe_tp", disabled=st.session_state["pe_exit"] == "surf")
    c4.text_input("Tempos gráficos indicados", key="pe_tf", placeholder="Ex.: 15m a 4h")
    st.radio("Saída", ["tp", "surf"], horizontal=True, key="pe_exit",
             format_func=lambda k: "🎯 Alvo fixo (stop + take profit)" if k == "tp" else
             "🏄 Surfar a tendência (só stop, que acompanha o preço; sem alvo)")
    if st.session_state["pe_exit"] == "surf":
        c1, c2 = st.columns(2)
        c1.number_input("Stop móvel a (× ATR) do melhor preço", 1.0, 10.0, step=0.5, key="pe_trail",
                        help="Distância fixa (ATR da entrada) entre o melhor preço atingido e o stop. Menor = sai mais cedo.")
        c2.number_input("Levar o stop ao equilíbrio após (× risco) — 0 = não", 0.0, 5.0, step=0.5, key="pe_be",
                        help="Depois de o preço andar esse múltiplo do risco a seu favor, o stop vai para a entrada (+ taxas).")
    elif st.session_state["pe_sl"]:
        st.caption(f"Alvo/stop = {st.session_state['pe_tp'] / st.session_state['pe_sl']:.2f} : 1 (antes das taxas).")

    st.markdown("**Onde o bot é medido no ranking**")
    c1, c2 = st.columns(2)
    c1.selectbox("Mercado principal", ["futures", "spot"], key="pe_home_market", format_func=mlabel)
    c2.selectbox("Tempo gráfico principal", ["5m", "15m", "1h", "4h", "1d"], key="pe_home_itv",
                 help="O ranking diário mede o bot neste mercado e tempo gráfico (dia, semana e mês).")

    st.markdown("**Filtros**")
    cols = st.columns(3)
    for i, (k, label) in enumerate(P.FILTERS.items()):
        st.session_state.setdefault(f"pe_f_{k}", False)
        cols[i % 3].checkbox(label, key=f"pe_f_{k}")
    c1, c2 = st.columns(2)
    c1.number_input("ADX mínimo para entrar (0 = sem filtro)", 0, 60, key="pe_adx_min")
    c2.number_input("ADX máximo para entrar (0 = sem filtro)", 0, 80, key="pe_adx_max")
    st.number_input("Volume mínimo em relação à média (0 = sem filtro; ex.: 1,5 = 50% acima)", 0.0, 5.0, step=0.1,
                    key="pe_vol_mult")

    st.markdown("**Compartilhamento**")
    st.radio("Quem pode ver e usar esta estratégia", list(P.VISIBILITY), format_func=P.VISIBILITY.get, key="pe_visibility", horizontal=True,
             help="Só você pode alterar ou excluir. Quem recebe a estratégia pode usá-la nos bots e vê-la no ranking.")
    if st.session_state["pe_visibility"] == "usuarios":
        others = [u for u in accounts.list_users() if u != current_user()] if accounts.enabled() else []
        if others:
            st.multiselect("Compartilhar com", others, key="pe_shared", placeholder="Escolha um ou mais usuários")
        else:
            st.info("O compartilhamento com usuários específicos exige as contas ligadas e outros usuários cadastrados.")

    c1, c2, _ = st.columns([1, 1, 2])
    if c1.button("💾 Salvar", type="primary", width="stretch"):
        ss = st.session_state
        if not ss["pe_name"].strip() or not ss["pe_skills"]:
            st.error("Dê um nome e escolha pelo menos um indicador.")
        else:
            filters = {k: ss[f"pe_f_{k}"] for k in P.FILTERS}
            filters.update(adx_min=ss["pe_adx_min"], adx_max=ss["pe_adx_max"], vol_mult=ss["pe_vol_mult"])
            data = {"name": ss["pe_name"].strip(), "author": ss["pe_author"].strip() or "anônimo",
                    "summary": ss["pe_summary"].strip(), "description": ss["pe_desc"].strip(),
                    "direction": ss["pe_dir"], "skills": weights, "threshold": ss["pe_threshold"],
                    "sl_atr": ss["pe_sl"], "tp_atr": ss["pe_tp"], "filters": filters,
                    "markets": ss["pe_markets"] or ["futures", "spot"], "timeframes": ss["pe_tf"].strip(),
                    "visibility": ss["pe_visibility"], "shared_with": ss["pe_shared"] if ss["pe_visibility"] == "usuarios" else [],
                    "home": {"market": ss["pe_home_market"], "interval": ss["pe_home_itv"]}}
            if ss["pe_exit"] == "surf":
                data.update(trail_atr=ss["pe_trail"], be_r=ss["pe_be"])
            if editing:
                old = P.get(editing) or {}
                data.update(id=editing, created=old.get("created"))
                if old.get("owner"):
                    data["owner"] = old["owner"]
            try:
                saved = P.save_custom(data)
            except PermissionError as exc:
                st.error(str(exc))
            else:
                st.toast(f"“{saved['name']}” salva.", icon="✅")
                st.session_state["persona_saved_msg"] = (
                    f"“{saved['name']}” salva ({P.VISIBILITY[saved['visibility']].split(' ', 1)[1].lower()}). Ela aparece na "
                    "Biblioteca e entra no Ranking diário na próxima atualização (ou rode o Backtest dela agora).")
                st.session_state["pe_reset"] = True
                st.rerun()
    if c2.button("Limpar", width="stretch"):
        st.session_state["pe_reset"] = True
        st.rerun()
    if msg := st.session_state.pop("persona_saved_msg", None):
        st.success(msg)


# --------------------------------------------------------------- biblioteca
with tab_lib:
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
    cols = st.columns(3)
    for n, p in enumerate(view):
        rs = p.get("research", {})
        lv = live.get(p["id"], {})
        bot = {"long": "swing"}.get(p.get("bot"), p.get("bot")) or ("day" if "futures" in p.get("markets", []) else "swing")  # Long roda na página Spot
        with cols[n % 3].container(border=True):
            st.markdown(f"#### {p['name']}")
            mk = rs.get("market") or ("futures" if "futures" in p.get("markets", ["futures"])[:1] else "spot")
            market = {"futures": "Futuros", "spot": "Spot"}.get(mk, mk)
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
                if rs.get("prev_ret_pct") is not None:
                    st.caption(f"{'🔴' if rs['prev_ret_pct'] < 0 else '🟢'} {rs.get('prev_label', 'Nos 40 dias anteriores')}: {rs['prev_ret_pct']:+.1f}% "
                               f"({rs['prev_pos_coins']} {'moedas' if rs.get('market') in ('futures', 'spot') else 'ativos'} positivos) — teste de outro regime de mercado.")
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
            weak = rs.get("status") not in ("aprovado", "ressalva") and bool(rs)
            b1, b2 = st.columns([1.2, 1])
            b1.caption("⚠️ Fraco no teste: o sistema não o escolhe" if weak else "🤖 Escolhido sozinho quando o contexto combina")
            mine = P.can_edit(p, current_user())
            if b1.button("✏️ Editar" if mine else "📄 Duplicar e editar", key=f"edit_{p['id']}", width="stretch"):
                st.session_state["persona_template"] = {**p, "duplicate": not mine}
                st.session_state["bots_msg"] = "Os campos foram preenchidos: abra a aba ✍️ Criar bot."
                st.rerun()
            if mine and b1.checkbox("Excluir", key=f"delok_{p['id']}") and b1.button("Confirmar exclusão", key=f"del_{p['id']}"):
                P.delete_custom(p["id"])
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
                st.markdown(f"**Direção:** {P.DIRECTIONS[p.get('direction', 'misto')]} · **Saída:** {P.exit_text(p)} · "
                            f"**Filtros:** {', '.join(filt) or 'nenhum'}")
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
                        "Operações": v["n"], "Acerto": v["win_pct"], "R médio": v["avg_r"], "Retorno": v.get("ret_pct")}
                        for k, v in rs["contexts"].items()]).sort_values("R médio", ascending=False),
                        hide_index=True, column_config={
                            "% do tempo": st.column_config.NumberColumn(format="%.0f%%"),
                            "Acerto": st.column_config.NumberColumn(format="%.0f%%"),
                            "R médio": st.column_config.NumberColumn(format="%+.2f"),
                            "Retorno": st.column_config.NumberColumn(format="%+.1f%%")})

    if not view:
        st.info("Nenhum bot com esses filtros.")



# --------------------------------------------------------------- contextos
TF_SETS = [("futures", "5m", "day"), ("futures", "15m", "day"), ("futures", "1h", "day"),
           ("spot", "4h", "swing"), ("spot", "1d", "long")]

with tab_ctx:
    st.markdown("#### 🧭 Contexto agora")
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

with tab_ctx:
    st.divider()
    st.markdown("#### 📊 Desempenho por contexto")
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
        rows.append([rs["contexts"][k].get(field) if k in rs["contexts"] and rs["contexts"][k]["n"] >= 3 else None for k in ctx_keys])
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
