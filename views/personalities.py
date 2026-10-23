"""Personalidades: ranking de desempenho, biblioteca, criação de estratégias e backtest."""
import pandas as pd
import streamlit as st

from core import backtest, personalities as P
from core.ai import strategy_from_text
from core.profiles import PROFILES
from core.settings import DEFAULT_MODEL, default_settings, load_settings, save_settings
from core.strategy import SKILLS
from core.ui import api_key, cached_klines, cached_symbols, fmt

st.title("🏆 Personalidades dos bots")
st.caption("Cada personalidade é uma estratégia: quais indicadores o bot usa, quando entra, em que direção e com que "
           "stop/alvo. Escolha a que performa melhor no ranking, crie a sua e compartilhe com todos.")

SKILL_NAMES = {k: v[0] for k, v in SKILLS.items()}
BOT_LABEL = {k: f"{p.icon} {p.name}" for k, p in PROFILES.items()}


def use_in_bot(pid: str, bot: str) -> None:
    persona = P.get(pid)
    cfg = load_settings(bot)
    cfg["personality"] = pid
    st.session_state[f"{bot}__personality"] = pid
    tested = persona.get("tested_interval")
    msg = f"{persona['name']} ativada no {PROFILES[bot].name}."
    if tested and tested in PROFILES[bot].intervals:
        cfg["interval"] = tested
        st.session_state[f"{bot}__interval"] = tested
        msg += f" Timeframe ajustado para {tested} (o testado)."
    if persona.get("markets") and PROFILES[bot].market not in persona["markets"]:
        msg += " Atenção: ela foi testada em outro mercado."
    save_settings(bot, cfg)
    st.toast(msg, icon="✅")


def fmt_r(v):
    return "—" if v is None else f"{v:+.2f}R"


tab_rank, tab_lib, tab_new, tab_bt = st.tabs(["🏆 Ranking", "📚 Biblioteca", "✍️ Criar estratégia", "🧪 Backtest"])

# ------------------------------------------------------------------ ranking
with tab_rank:
    rows = P.ranking()
    st.markdown(
        "A pontuação é o **R médio por operação** (resultado ÷ risco planejado: +1R = ganhou o que arriscou) "
        "ponderado pela quantidade de operações. Operações reais dos bots valem o dobro dos backtests. Com menos de "
        "10 operações, o resultado ainda é pouco confiável.")

    # --- Retorno simulado nos últimos 40 dias -------------------------------------
    with st.container(border=True):
        st.markdown("**📅 Quanto cada personalidade teria rendido nos últimos 40 dias**")
        c1, c2, c3, c4 = st.columns([1, 1, 1, 1.4])
        p_market = c1.selectbox("Mercado", ["futures", "spot"], key="per_m",
                                format_func=lambda m: "Futuros" if m == "futures" else "Spot")
        p_itv = c2.selectbox("Timeframe", ("15m", "1h", "4h"), index=1, key="per_i")
        p_risk = c3.selectbox("Risco por operação", (0.5, 1.0, 2.0), index=1, key="per_r",
                              format_func=lambda r: f"{r:g}% da banca")
        pkey = P.period_key(p_market, p_itv, 40, p_risk)
        period = P.period_results(pkey)
        missing = [p for p in P.list_all() if p["id"] not in period["results"]]
        label = "Calcular" if not period["results"] else ("Calcular as que faltam" if missing else "Recalcular")
        if c4.button(f"▶️ {label} ({len(missing) or len(P.list_all())} personalidades)", type="primary",
                     width="stretch"):
            todo = missing or P.list_all()
            prof = PROFILES["day" if p_market == "futures" else "swing"]
            base = {**default_settings(prof), "interval": p_itv}
            n_candles = 40 * backtest.PER_DAY[p_itv] + 250
            frames = {sym: cached_klines(sym, p_itv, n_candles, p_market) for sym in P.PERIOD_SYMBOLS}
            bar = st.progress(0.0, text="Simulando…")
            for k, persona_ in enumerate(todo, start=1):
                per_symbol = [backtest.period_return(frames[sym], {**base, "symbol": sym}, prof, persona_,
                                                     days=40, risk_pct=p_risk) for sym in P.PERIOD_SYMBOLS]
                summary = P.summarize_period(per_symbol)
                P.save_period_result(pkey, persona_["id"], summary)
                bar.progress(k / len(todo), text=f"{persona_['name']}: {summary['return_pct']:+.2f}%")
            st.rerun()
        st.caption(
            f"Conta: cada operação do backtest move a banca em **{p_risk:g}% × R** (stop = −{p_risk:g}%, alvo de 3R = "
            f"+{3 * p_risk:g}%), com juros compostos: banca final = banca × (1 + {p_risk / 100:g}·R₁) × "
            f"(1 + {p_risk / 100:g}·R₂) × … Simulado em {', '.join(s.replace('USDT', '') for s in P.PERIOD_SYMBOLS)} "
            "separadamente (uma banca para cada); a coluna mostra a média, já com taxas. "
            + (f"Calculado em {period['date']}." if period["date"] else "Ainda não calculado.")
            + " Resultado passado não garante resultado futuro.")

    table = pd.DataFrame([{
        "#": i + 1, "Personalidade": r["name"], "Autor": r["author"],
        "Retorno 40 dias": (period["results"].get(r["id"]) or {}).get("return_pct"),
        "Pior queda 40d": (period["results"].get(r["id"]) or {}).get("max_dd_pct"),
        "Moedas positivas": (f"{period['results'][r['id']]['positive']}/{period['results'][r['id']]['symbols']}"
                             if r["id"] in period["results"] else None),
        "Operações 40d": (period["results"].get(r["id"]) or {}).get("trades"),
        "Pontuação": r["score"], "Operações reais": r["live_trades"],
        "Acerto real": r["live_win_rate"], "R médio real": r["live_avg_r"], "Resultado real (USDT)": r["live_pnl"],
        "Operações backtest": r["bt_trades"], "R médio backtest": r["bt_avg_r"], "Acerto backtest": r["bt_win_rate"],
        "Confiável": "✅" if r["enough_data"] else "⏳ poucos dados",
    } for i, r in enumerate(rows)])
    for col in ("Retorno 40 dias", "Pior queda 40d", "Operações 40d"):
        table[col] = pd.to_numeric(table[col], errors="coerce")
    if period["results"]:  # com o cálculo dos 40 dias, ele define a ordem (sem dados ficam por último)
        table = table.sort_values("Retorno 40 dias", ascending=False, na_position="last").reset_index(drop=True)
        table["#"] = range(1, len(table) + 1)
    for col in ("Pontuação", "Acerto real", "R médio real", "Acerto backtest", "R médio backtest"):
        table[col] = pd.to_numeric(table[col], errors="coerce")  # sem dados → célula vazia
    st.dataframe(table, hide_index=True, placeholder="—", column_config={
        "Retorno 40 dias": st.column_config.NumberColumn(format="%+.2f%%", help="Retorno composto médio nas 5 moedas"),
        "Pior queda 40d": st.column_config.NumberColumn(format="−%.1f%%", help="Maior queda da banca (pior moeda)"),
        "Pontuação": st.column_config.NumberColumn(format="%+.3f"),
        "Acerto real": st.column_config.NumberColumn(format="%.0f%%"),
        "Acerto backtest": st.column_config.NumberColumn(format="%.0f%%"),
        "R médio real": st.column_config.NumberColumn(format="%+.2f"),
        "R médio backtest": st.column_config.NumberColumn(format="%+.2f"),
        "Resultado real (USDT)": st.column_config.NumberColumn(format="%.2f")})
    with st.expander("⚡ Atualizar o ranking com backtests de todas as personalidades"):
        st.caption("Roda o backtest (só regras, sem gastar tokens) de todas as personalidades no mesmo ativo e "
                   "timeframe e soma ao ranking. Leva cerca de 2 s por personalidade.")
        c1, c2, c3, c4 = st.columns(4)
        m_all = c1.selectbox("Mercado", ["futures", "spot"], key="all_m",
                             format_func=lambda m: "Futuros" if m == "futures" else "Spot")
        sy = cached_symbols(m_all)
        s_all = c2.selectbox("Ativo", sy, index=sy.index("BTCUSDT") if "BTCUSDT" in sy else 0, key="all_s")
        i_all = c3.selectbox("Timeframe", ("15m", "1h", "4h", "1d"), index=1, key="all_i")
        if c4.button("Rodar todos", type="primary", width="stretch"):
            prof = PROFILES["day" if m_all == "futures" else "swing"]
            cfg_all = {**default_settings(prof), "symbol": s_all, "interval": i_all}
            df_all = cached_klines(s_all, i_all, 1000, m_all)
            bar = st.progress(0.0)
            items = P.list_all()
            for n, persona_ in enumerate(items, start=1):
                res_ = backtest.run(df_all, cfg_all, prof, persona_)
                if res_["trades"]:
                    P.save_backtest(persona_["id"], {k: v for k, v in res_.items() if k not in ("detail", "curve")})
                bar.progress(n / len(items), text=f"{persona_['name']}: {res_['trades']} operações, "
                                                  f"{res_['avg_r']:+.2f}R por operação")
            st.rerun()
    if period["results"]:
        chart = table.dropna(subset=["Retorno 40 dias"])[["Personalidade", "Retorno 40 dias"]]
        st.bar_chart(chart, x="Personalidade", y="Retorno 40 dias", horizontal=True, sort="-Retorno 40 dias",
                     height=40 + 28 * len(chart), color="#26a69a")
    elif any(r["score"] is not None for r in rows):
        scored = [r for r in rows if r["score"] is not None]
        chart = pd.DataFrame({"Personalidade": [r["name"] for r in scored], "Pontuação": [r["score"] for r in scored]})
        st.bar_chart(chart, x="Personalidade", y="Pontuação", horizontal=True, sort="-Pontuação",
                     height=40 + 28 * len(scored), color="#26a69a")
    else:
        st.info("Ainda não há dados. Clique em Calcular acima para ver quanto cada personalidade teria rendido "
                "nos últimos 40 dias.")
    c1, c2, c3 = st.columns([2, 1.2, 1])
    pick = c1.selectbox("Usar uma personalidade", [r["id"] for r in rows], format_func=lambda i: P.get(i)["name"])
    bot = c2.selectbox("no bot", list(PROFILES), format_func=BOT_LABEL.get, key="rank_bot")
    if c3.button("Usar agora", type="primary", width="stretch"):
        use_in_bot(pick, bot)

# --------------------------------------------------------------- biblioteca
with tab_lib:
    in_use = {k: load_settings(k).get("personality") for k in PROFILES}
    for p in P.list_all():
        with st.container(border=True):
            c1, c2 = st.columns([3, 1.2])
            using = [PROFILES[b].name for b, pid in in_use.items() if pid == p["id"]]
            c1.markdown(f"#### {p['name']}  \n"
                        f"{'Pronta' if p.get('builtin') else 'Da comunidade'} · por **{p.get('author') or '—'}**"
                        + (f" · em uso: {', '.join(using)}" if using else ""))
            c1.write(p.get("summary") or "")
            with c1.expander("Ver estratégia completa"):
                st.write(p.get("description", ""))
                skills = sorted(p.get("skills", {}).items(), key=lambda kv: -kv[1])
                st.markdown("**Indicadores/habilidades (peso):** " + ", ".join(
                    f"{SKILL_NAMES.get(k, k)} ({w:g})" for k, w in skills if w > 0))
                f = p.get("filters", {})
                filt = [P.FILTERS[k] for k, v in f.items() if v and k in P.FILTERS]
                if f.get("adx_min"):
                    filt.append(f"ADX ≥ {f['adx_min']}")
                if f.get("adx_max"):
                    filt.append(f"ADX ≤ {f['adx_max']}")
                st.markdown(f"**Direção:** {P.DIRECTIONS[p.get('direction', 'misto')]} · **Limiar de entrada:** "
                            f"{p.get('threshold')} · **Stop/alvo:** {p.get('sl_atr')}× / {p.get('tp_atr')}× ATR · "
                            f"**Tempos gráficos:** {p.get('timeframes') or '—'}")
                st.markdown("**Filtros:** " + (", ".join(filt) or "nenhum"))
                if rs := p.get("research"):
                    st.markdown(
                        f"**Resultado da pesquisa (futuros 1h, 1% de risco por operação, 40 dias):** "
                        f"{rs['busca_pct']:+.1f}% nas moedas da busca (BTC, ETH, SOL, BNB, XRP) · "
                        f"{rs['inéditas_pct']:+.1f}% em moedas que a busca não viu (DOGE, ADA, LINK, AVAX, LTC) · "
                        f"{rs['anteriores_r']:+.2f}R por operação nos 40 dias anteriores · pior queda "
                        f"{rs['pior_queda_pct']:.0f}% · acerto ~{rs['acerto_pct']}%. Passado não garante futuro.")
            with c2:
                target = st.selectbox("Bot", list(PROFILES), format_func=BOT_LABEL.get, key=f"lib_bot_{p['id']}",
                                      label_visibility="collapsed")
                if st.button("Usar neste bot", key=f"use_{p['id']}", width="stretch", type="primary"):
                    use_in_bot(p["id"], target)
                if st.button("Duplicar e editar" if p.get("builtin") else "Editar", key=f"edit_{p['id']}",
                             width="stretch"):
                    st.session_state["persona_template"] = {**p, "duplicate": bool(p.get("builtin"))}
                    st.info("Abra a aba ✍️ Criar estratégia: os campos foram preenchidos.")
                if not p.get("builtin"):
                    if st.checkbox("Confirmar exclusão", key=f"delok_{p['id']}"):
                        if st.button("Excluir", key=f"del_{p['id']}", width="stretch"):
                            P.delete_custom(p["id"])
                            st.rerun()

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
    ss["pe_markets"] = p.get("markets", ["futures", "spot"])
    f = p.get("filters", {})
    for k in P.FILTERS:
        ss[f"pe_f_{k}"] = bool(f.get(k))
    ss["pe_adx_min"] = int(f.get("adx_min") or 0)
    ss["pe_adx_max"] = int(f.get("adx_max") or 0)


if st.session_state.pop("pe_reset", False):
    for k in [k for k in st.session_state if k.startswith("pe_")]:
        del st.session_state[k]
if "persona_template" in st.session_state:
    tpl = st.session_state.pop("persona_template")
    load_template(tpl, tpl.get("duplicate", False))
for key, default in (("pe_name", ""), ("pe_author", ""), ("pe_summary", ""), ("pe_desc", ""), ("pe_dir", "misto"),
                     ("pe_skills", ["tendencia", "momentum"]), ("pe_threshold", 30), ("pe_sl", 1.5), ("pe_tp", 3.0),
                     ("pe_tf", ""), ("pe_markets", ["futures", "spot"]), ("pe_adx_min", 0), ("pe_adx_max", 0),
                     ("pe_id", None)):
    st.session_state.setdefault(key, default)

with tab_new:
    editing = st.session_state.get("pe_id")
    st.markdown(f"#### {'Editando: ' + st.session_state['pe_name'] if editing else 'Nova estratégia'}")
    c1, c2 = st.columns(2)
    c1.text_input("Nome da personalidade", key="pe_name", placeholder="Ex.: Caçador de Pullback")
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
    c3.number_input("Alvo (× ATR)", 0.5, 30.0, step=0.5, key="pe_tp")
    c4.text_input("Tempos gráficos indicados", key="pe_tf", placeholder="Ex.: 15m a 4h")
    if st.session_state["pe_sl"]:
        st.caption(f"Alvo/stop = {st.session_state['pe_tp'] / st.session_state['pe_sl']:.2f} : 1 (antes das taxas).")

    st.markdown("**Filtros**")
    cols = st.columns(3)
    for i, (k, label) in enumerate(P.FILTERS.items()):
        st.session_state.setdefault(f"pe_f_{k}", False)
        cols[i % 3].checkbox(label, key=f"pe_f_{k}")
    c1, c2 = st.columns(2)
    c1.number_input("ADX mínimo para entrar (0 = sem filtro)", 0, 60, key="pe_adx_min")
    c2.number_input("ADX máximo para entrar (0 = sem filtro)", 0, 80, key="pe_adx_max")

    c1, c2, _ = st.columns([1, 1, 2])
    if c1.button("💾 Salvar e compartilhar", type="primary", width="stretch"):
        ss = st.session_state
        if not ss["pe_name"].strip() or not ss["pe_skills"]:
            st.error("Dê um nome e escolha pelo menos um indicador.")
        else:
            filters = {k: ss[f"pe_f_{k}"] for k in P.FILTERS}
            filters.update(adx_min=ss["pe_adx_min"], adx_max=ss["pe_adx_max"])
            data = {"name": ss["pe_name"].strip(), "author": ss["pe_author"].strip() or "anônimo",
                    "summary": ss["pe_summary"].strip(), "description": ss["pe_desc"].strip(),
                    "direction": ss["pe_dir"], "skills": weights, "threshold": ss["pe_threshold"],
                    "sl_atr": ss["pe_sl"], "tp_atr": ss["pe_tp"], "filters": filters,
                    "markets": ss["pe_markets"] or ["futures", "spot"], "timeframes": ss["pe_tf"].strip()}
            if editing:
                old = P.get(editing) or {}
                data.update(id=editing, created=old.get("created"))
            saved = P.save_custom(data)
            st.toast(f"“{saved['name']}” salva e compartilhada.", icon="✅")
            st.session_state["persona_saved_msg"] = (f"“{saved['name']}” salva. Ela já aparece na Biblioteca, no Ranking "
                                                "e na escolha de personalidade de cada bot.")
            st.session_state["pe_reset"] = True
            st.rerun()
    if c2.button("Limpar", width="stretch"):
        st.session_state["pe_reset"] = True
        st.rerun()
    if msg := st.session_state.pop("persona_saved_msg", None):
        st.success(msg)

# ------------------------------------------------------------------ backtest
with tab_bt:
    st.caption("Testa a personalidade nos candles reais mais recentes usando só as regras (sem gastar tokens da IA). "
               "Resultados em R: +1R = ganhou o que arriscou em uma operação.")
    allp = P.list_all()
    c1, c2, c3, c4, c5 = st.columns([2, 1, 1.4, 1, 1])
    pid = c1.selectbox("Personalidade", [p["id"] for p in allp], format_func=lambda i: P.get(i)["name"], key="bt_p")
    persona = P.get(pid)
    market = c2.selectbox("Mercado", ["futures", "spot"], key="bt_m",
                          format_func=lambda m: "Futuros" if m == "futures" else "Spot")
    symbols = cached_symbols(market)
    symbol = c3.selectbox("Ativo", symbols, index=symbols.index("BTCUSDT") if "BTCUSDT" in symbols else 0, key="bt_s")
    interval = c4.selectbox("Timeframe", ("5m", "15m", "30m", "1h", "4h", "1d"), index=3, key="bt_i")
    candles = c5.selectbox("Candles", (500, 1000, 1500), index=1, key="bt_n")
    count = st.checkbox("Contar este resultado no ranking", value=True)
    if st.button("▶️ Rodar backtest", type="primary"):
        profile = PROFILES["day" if market == "futures" else "swing"]
        cfg = {**default_settings(profile), "symbol": symbol, "interval": interval}
        with st.spinner("Baixando candles e simulando…"):
            df = cached_klines(symbol, interval, int(candles), market)
            res = backtest.run(df, cfg, profile, persona)
        st.session_state["bt_result"] = res
        if count and res["trades"]:
            P.save_backtest(pid, {k: v for k, v in res.items() if k not in ("detail", "curve")})
    res = st.session_state.get("bt_result")
    if res:
        st.markdown(f"**{res['personality_name']}** · {res['symbol']} {res['interval']} · {res['period']}")
        m = st.columns(6)
        m[0].metric("Operações", res["trades"])
        m[1].metric("Acerto", f"{res['win_rate']:.0f}%")
        m[2].metric("R médio", fmt_r(res["avg_r"]))
        m[3].metric("Total", fmt_r(res["total_r"]))
        m[4].metric("Fator de lucro", "—" if res["profit_factor"] is None else fmt(res["profit_factor"]))
        m[5].metric("Pior sequência", f"−{res['max_dd_r']:.1f}R")
        st.caption(f"Arriscando 1% da banca por operação, o resultado seria ≈ {res['total_r']:+.1f}% no período.")
        if res["curve"]:
            curve = pd.DataFrame(res["curve"]).set_index("time")
            st.line_chart(curve["r_acumulado"].rename("R acumulado"), height=240)
            det = pd.DataFrame(res["detail"])
            st.dataframe(det.iloc[::-1], hide_index=True, column_config={
                "r": st.column_config.NumberColumn("R", format="%+.2f")})
        else:
            st.info("Nenhuma entrada no período: a personalidade foi seletiva demais para este ativo/timeframe.")
