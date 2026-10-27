"""Bots: ranking diário (dia, semana e mês), calculadora, backtest sob demanda, criação, biblioteca e contextos — tudo numa página."""
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import accounts, bot_performance, bots_view, grid_dca, fastsim, indicators as ind, personalities as P, regime
from core.ai import strategy_from_text
from core.paper import account_id, get_account, stats
from core.profiles import PROFILES
from core.settings import DEFAULT_MODEL, default_settings
from core.storage import current_user
from core.strategy import SKILLS
from core.ui import api_key, cached_klines, cached_symbols, cached_votes

st.title("🤖 Bots")
st.caption("Cada bot é uma estratégia (indicadores, entrada, direção e stop/alvo) treinada num mercado e tempo gráfico. O ranking é refeito "
           "sozinho uma vez por dia com os candles mais recentes; a calculadora e o backtest mostram quanto cada um teria rendido. "
           "Resultado passado não garante resultado futuro. No fechamento de cada candle o sistema escolhe sozinho o melhor bot para o contexto.")

SKILL_NAMES = {k: v[0] for k, v in SKILLS.items()}
MARKET_LABEL = {"futures": "Futuros", "spot": "Spot (só compra)"}


def mlabel(m: str) -> str:
    return MARKET_LABEL.get(m, m)


live = {r["id"]: r for r in P.ranking()}
bots = [p for p in P.list_all() if p.get("research", {}).get("monthly_pct") is not None or not p.get("builtin")] + grid_dca.all_bots()
if msg := st.session_state.pop("bots_msg", None):
    st.info(msg)

tab_rank, tab_calc, tab_bt, tab_ml, tab_new, tab_lib, tab_ctx = st.tabs(["🏆 Ranking", "🧮 Calculadora", "🔁 Backtest", "🧪 Modelo ML",
                                                                         "✍️ Criar bot", "📚 Biblioteca", "🧭 Contextos"])

# ------------------------------------------------------------------ ranking diário
bot_performance.refresh_if_due()   # 1x por dia, em segundo plano (o worker 24/7 também dispara)


_UI_CSS = Path(bots_view.__file__).with_name("bots_ui.css").read_text(encoding="utf-8")


@st.cache_resource(show_spinner=False)
def _comp(name: str):
    return st.components.v2.component(f"tb_{name}", css=_UI_CSS, js=Path(bots_view.__file__).with_name(f"{name}.js").read_text(encoding="utf-8"))


def _run_backtest(pid: str) -> None:
    """Backtest forçado de um bot (botão no ranking ou na aba Backtest)."""
    bar = st.progress(0.0, text="Baixando candles recentes…")
    try:
        got = bot_performance.refresh_bot(pid, getter=lambda s_, i_, n_, m_: cached_klines(s_, i_, n_, m_),
                                          progress=lambda f, t: bar.progress(min(f, 1.0), text=t))
    except Exception as exc:  # noqa: BLE001
        got = None
        st.error(f"Não foi possível rodar agora: {exc}")
    bar.empty()
    st.toast("Backtest salvo no ranking." if got else "Sem candles para este bot agora.", icon="✅" if got else "⚠️")


def _action(res, key: str):
    ev = getattr(res, "action", None)
    if ev and ev.get("uid") != st.session_state.get(key):
        st.session_state[key] = ev.get("uid")
        return ev
    return None


NOTE = (f"Simulado em {', '.join(s_.replace('USDT', '') for s_ in P.PERIOD_SYMBOLS)} (cada moeda com a própria banca; o valor é a média), só com as "
        "regras do bot, entrada no candle seguinte ao sinal, taxas e 1% de risco por operação. Clique num bot para ver os detalhes.")


@st.fragment(run_every=30)
def _ranking():
    upd, busy = bot_performance.last_update(), bot_performance.running()
    st.caption(("🔄 Atualizando o ranking de hoje em segundo plano… muda sozinho quando terminar. " if busy else "")
               + (f"Atualizado em {upd:%d/%m %H:%M} UTC · próxima atualização automática amanhã." if upd else "Ainda não calculado."))
    rows = bot_performance.rows()
    if not rows or all(not r["d30"] for r in rows):
        st.info("O ranking diário ainda não foi calculado. Ele roda sozinho em segundo plano; para um bot específico agora, use a aba 🔁 Backtest.")
        return
    res = _comp("bot_rank")(key="bots-rank", data=bots_view.rank_data(rows, bot_performance.history, note=NOTE), on_action_change=lambda: None)
    if (ev := _action(res, "rk_uid")) and ev.get("kind") == "backtest":
        _run_backtest(ev["id"])
        st.rerun(scope="fragment")


with tab_rank:
    _ranking()

# ------------------------------------------------------------------ backtest sob demanda
with tab_bt:
    st.caption("Força agora a atualização de um bot: refaz a simulação de 1, 7 e 30 dias com os candles mais recentes no mercado e tempo gráfico "
               "dele, salva no ranking e mostra o resultado por moeda. A atualização automática de todos continua 1x por dia.")
    allp = bot_performance.tracked()
    c1, c2 = st.columns([2.4, 1])
    bt_id = c1.selectbox("Bot", [p["id"] for p in allp], key="bt_bot",
                         format_func=lambda pid: (lambda p, h: f"{p['name']} · {mlabel(h[0])} {h[1]}")(bot_performance.get_bot(pid), bot_performance.home(bot_performance.get_bot(pid))))
    if c2.button("▶️ Rodar backtest agora", type="primary", width="stretch"):
        _run_backtest(bt_id)
    one = [r for r in bot_performance.rows() if r["id"] == bt_id and r["d30"]]
    if one:
        res_bt = _comp("bot_rank")(key="bots-bt", data=bots_view.rank_data(one, bot_performance.history, focus=bt_id), on_action_change=lambda: None)
        if (ev := _action(res_bt, "bt_uid")) and ev.get("kind") == "backtest":
            _run_backtest(ev["id"])
            st.rerun()
    else:
        st.info("Este bot ainda não tem resultado salvo. Clique em Rodar backtest agora.")

# ------------------------------------------------------------------ modelo de machine learning (protótipo)
with tab_ml:
    st.caption("Protótipo inspirado no FreqAI: um modelo (LightGBM) treinado com o histórico recente de várias moedas e do BTC prevê a chance de "
               "o preço subir nas próximas velas. Ele pode entrar como **mais um voto** no placar dos bots e como **filtro**: quando o mercado "
               "está diferente de tudo o que o modelo viu no treino (índice de dissimilaridade alto), o bot fica de fora. Antes de ligar, "
               "compare no backtest com re-treino abaixo.")
    from core import ml
    from core.settings import load_settings, save_settings

    st.markdown("##### Ao vivo")
    cols = st.columns(2)
    for col, bk in zip(cols, ("day", "swing")):
        prof, cfg_b = PROFILES[bk], load_settings(bk)
        with col.container(border=True):
            stt = ml.status(prof.market, cfg_b["interval"])
            st.markdown(f"**{prof.icon} {prof.name}** · {cfg_b['interval']}")
            if stt:
                a_ = stt.get("auc_holdout")
                st.caption(f"Modelo treinado em {stt['trained_at'][:16].replace('T', ' ')} UTC · {stt['rows']:,} velas de {len(stt['symbols'])} moedas "
                           f"({stt['days']} dias) · {stt['kind']} · AUC fora do treino: {'—' if a_ is None else f'{a_:.3f}'} · re-treina sozinho 1x por dia")
            else:
                st.caption("Ainda sem modelo neste tempo gráfico.")
            c1, c2, c3 = st.columns([1, 1, 1])
            v_on = c1.toggle("Voto do modelo", value=bool(cfg_b.get("ml_vote")), key=f"ml_v_{bk}")
            f_on = c2.toggle("Filtro (não opere)", value=bool(cfg_b.get("ml_filter")), key=f"ml_f_{bk}")
            w_ml = c3.number_input("Peso do voto", 0.1, 3.0, value=float(cfg_b.get("ml_weight") or 1.0), step=0.1, key=f"ml_w_{bk}")
            if (v_on, f_on, w_ml) != (bool(cfg_b.get("ml_vote")), bool(cfg_b.get("ml_filter")), float(cfg_b.get("ml_weight") or 1.0)):
                save_settings(bk, {**cfg_b, "ml_vote": v_on, "ml_filter": f_on, "ml_weight": w_ml})
                for name_ in ("ml_vote", "ml_filter", "ml_weight"):   # a página do bot relê a configuração salva
                    st.session_state.pop(f"{bk}__{name_}", None)
                st.toast("Configuração do modelo salva.", icon="🧪")
            if st.button("🧠 Treinar agora", key=f"ml_t_{bk}"):
                bar = st.progress(0.0, text="Baixando candles…")
                try:
                    m_ = ml.train_live(prof.market, cfg_b["interval"], getter=lambda s_, i_, n_, k_: cached_klines(s_, i_, n_, k_),
                                       progress=lambda f, t: bar.progress(min(f, 1.0), text=t))
                    st.toast(f"Modelo treinado ({m_.kind}).", icon="✅")
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    bar.empty()
                    st.error(f"Não foi possível treinar agora: {exc}")
            if stt and stt.get("importance"):
                st.caption("O que mais pesa: " + " · ".join(f"{k} {v * 100:.0f}%" for k, v in stt["importance"][:6]))

    st.markdown("##### Backtest com re-treino (walk-forward)")
    st.caption("O modelo é re-treinado a cada passo só com o passado e prevê o período seguinte, como aconteceria ao vivo. Depois cada bot daquele "
               "mercado/tempo gráfico é simulado nas mesmas velas: sem o modelo, com o filtro, com o voto e com os dois.")
    c1, c2, c3, c4, c5 = st.columns(5)
    wf_m = c1.selectbox("Mercado", ["futures", "spot"], format_func=mlabel, key="wf_m")
    wf_i = c2.selectbox("Tempo gráfico", ["15m", "1h", "4h"], index=1, key="wf_i")
    wf_test = c3.selectbox("Período de teste (dias)", [30, 60, 90], index=1, key="wf_t")
    wf_train = c4.number_input("Janela de treino (dias)", 10, 365, value=ml.TRAIN_DAYS.get(wf_i, 60), key=f"wf_tr_{wf_i}")
    wf_step = c5.selectbox("Re-treinar a cada (dias)", [3, 7, 14], index=1, key="wf_s")
    if st.button("▶️ Rodar backtest com re-treino", type="primary"):
        bar = st.progress(0.0, text="Baixando candles…")
        frames_ = {}
        for k_, sym in enumerate(P.PERIOD_SYMBOLS, start=1):
            try:
                vt_, cfg_ = cached_votes(sym, wf_i, wf_m, int(wf_train + wf_test + 2))
                vt_ = vt_.copy()
                vt_.attrs["cfg"] = cfg_
                frames_[sym] = vt_
            except Exception as exc:  # noqa: BLE001
                st.warning(f"{sym}: sem candles ({str(exc)[:80]})")
            bar.progress(k_ / len(P.PERIOD_SYMBOLS) * 0.4, text=f"Candles de {sym}")
        if frames_:
            cfg0 = next(iter(frames_.values())).attrs["cfg"]
            out_ = ml.walk_forward(frames_, wf_i, float(cfg0["fee_pct"]), train_days=wf_train, step_days=wf_step, test_days=wf_test,
                                   btc=frames_.get("BTCUSDT"), progress=lambda f, t: bar.progress(0.4 + 0.5 * f, text=t))
            for v_ in out_.values():
                v_.attrs["cfg"] = cfg0
            bots_ = [p for p in bot_performance.tracked() if bot_performance.home(p) == (wf_m, wf_i) and not p.get("kind")]
            st.session_state["ml_wf"] = {"eval": ml.evaluate(out_, wf_test), "cmp": ml.compare_bots(out_, bots_, wf_m, wf_test),
                                         "label": f"{mlabel(wf_m)} {wf_i} · teste de {wf_test} dias · treino de {wf_train} dias · re-treino a cada {wf_step} dias"}
        bar.empty()
    wf = st.session_state.get("ml_wf")
    if wf:
        ev_ = wf["eval"]
        st.markdown(f"**{wf['label']}**")
        if ev_.get("n"):
            m_ = st.columns(5)
            m_[0].metric("AUC fora do treino", f"{ev_['auc']:.3f}" if ev_["auc"] is not None else "—",
                         help="0,5 = moeda ao ar; acima de 0,55 já é uma vantagem útil; acima de 0,6 é raro em cripto.")
            m_[1].metric("Acerto da direção", f"{ev_['acc'] * 100:.1f}%", f"{ev_['base_up'] * 100:.0f}% das velas subiram", delta_color="off")
            m_[2].metric("Acerto quando confiante", "—" if ev_["acc_conf"] is None else f"{ev_['acc_conf'] * 100:.1f}%",
                         f"{ev_['conf_share'] * 100:.0f}% das velas (p < 45% ou > 55%)", delta_color="off")
            m_[3].metric("Velas bloqueadas pelo filtro", f"{ev_['blocked_share'] * 100:.1f}%")
            m_[4].metric("Velas avaliadas", f"{ev_['n']:,}")
        if wf["cmp"]:
            tbl = []
            for r in wf["cmp"]:
                row = {"Bot": r["name"]}
                for k_, lab in (("base", "Sem modelo"), ("filtro", "Com filtro"), ("voto", "Com voto"), ("ambos", "Voto + filtro")):
                    row[f"{lab} · retorno"] = r[k_]["ret"]
                    row[f"{lab} · op."] = r[k_]["n"]
                tbl.append(row)
            df_ = pd.DataFrame(tbl)
            st.dataframe(df_, hide_index=True, column_config={c: st.column_config.NumberColumn(format="%+.2f%%") for c in df_.columns if c.endswith("retorno")})
            best = {k_: sum(r[k_]["ret"] for r in wf["cmp"]) / len(wf["cmp"]) for k_ in ("base", "filtro", "voto", "ambos")}
            names = {"base": "sem modelo", "filtro": "com filtro", "voto": "com voto", "ambos": "voto + filtro"}
            win = max(best, key=best.get)
            st.caption("Média dos bots: " + " · ".join(f"{names[k_]} {v:+.2f}%" for k_, v in best.items())
                       + (f". Melhor: **{names[win]}**." if win != "base" else ". O modelo não melhorou a média neste teste: deixe desligado."))
        else:
            st.info("Nenhum bot treinado neste mercado e tempo gráfico para comparar.")
        st.caption("Retorno = média das 5 moedas (cada uma com a própria banca, 1% de risco por operação, com taxas). Resultado passado não garante futuro.")

# ------------------------------------------------------------------ calculadora
with tab_calc:
    st.caption("Escolha um bot, as moedas, o período e a sua banca: o simulador refaz as operações que o bot teria "
               "feito com os candles reais (só as regras, sem gastar tokens da IA, com taxas) e mostra quanto você teria "
               "ganhado ou perdido.")
    allp = P.list_all() + grid_dca.all_bots()
    approved_first = sorted(allp, key=lambda p: (p.get("research", {}).get("status") != "aprovado",
                                                 -(p.get("research", {}).get("monthly_pct") or -99)))

    def bot_label(pid):
        p = bot_performance.get_bot(pid)
        if p.get("kind"):
            return f"{p['name']} · {p['home']['interval']}"
        rs = p.get("research") or {}
        tag = {"aprovado": "✅", "ressalva": "🟡", "fraco": "⚠️"}.get(rs.get("status"), "·")
        return f"{tag} {p['name']}" + (f" · {rs['interval']}" if rs.get("interval") else "")

    c1, c2, c3 = st.columns([2.2, 1, 1])
    pid = c1.selectbox("Bot", [p["id"] for p in approved_first], format_func=bot_label, key="sim_bot")
    persona = bot_performance.get_bot(pid)
    rs = persona.get("research") or ({"market": persona["home"]["market"], "interval": persona["home"]["interval"]} if persona.get("kind") else {})
    # mercado e timeframe começam nos que o bot foi testado (podem ser trocados)
    if st.session_state.get("sim_last_bot") != pid:
        st.session_state["sim_market"] = rs.get("market") or (persona.get("markets") or ["spot"])[0]
        st.session_state["sim_itv"] = rs.get("interval") or persona.get("tested_interval") or "1h"
        st.session_state["sim_last_bot"] = pid
    market = c2.selectbox("Mercado", list(MARKET_LABEL), key="sim_market", format_func=mlabel)
    itv = c3.selectbox("Timeframe", ["5m", "15m", "1h", "4h", "1d"], key="sim_itv")
    if persona.get("kind"):
        st.caption("🕸️ " + grid_dca.describe(persona) + " Na grade e no DCA a banca é dividida igualmente entre os ativos; o risco por operação não se aplica.")
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
    risk_pct = c4.number_input("Risco por operação (%)", 0.1, 10.0, value=1.0, step=0.25, key="sim_risk", disabled=bool(persona.get("kind")),
                               help="Quanto da banca é perdido se o stop for atingido.")
    compound_on = st.toggle("Juros compostos (o risco acompanha a banca)", value=True, key="sim_comp", disabled=bool(persona.get("kind")))

    if st.button("▶️ Simular", type="primary", disabled=not coins):
        rows, per_coin = [], []
        bar = st.progress(0.0, text="Baixando candles e calculando…")
        for n_, sym in enumerate(coins, start=1):
            try:
                vt, cfg = cached_votes(sym, itv, market, int(days))
            except Exception as exc:  # noqa: BLE001 - moeda sem dados nas fontes disponíveis
                st.warning(f"{sym}: sem candles disponíveis para {itv} ({str(exc)[:120]}…). Moeda ignorada.")
                continue
            if persona.get("kind"):   # grade/DCA: simulador próprio, com uma fatia da banca por ativo
                start_ = vt["time"].iloc[-1] - pd.Timedelta(days=days)
                trades = grid_dca.simulate(persona, vt, itv, float(cfg["fee_pct"]), start_time=start_, capital=bank0 / len(coins))["trades"]
            else:
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
            pnl = t["resultado"] if persona.get("kind") else base * risk_pct / 100 * t["r"]
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
                                          "itv": itv, "market": market, "risk": risk_pct, "comp": compound_on, "kind": persona.get("kind")}

    res = st.session_state.get("sim_result")
    if res:
        rows = res["rows"]
        _comp("bot_calc")(key="bots-calc", data={"r": bots_view.calc_view(res)})
        if res["curve"]:
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
    res_lib = _comp("bot_library")(key="bots-lib", data=bots_view.library_data(bots, live, lambda p: P.can_edit(p, current_user()),
                                                                            perf=bot_performance.load()["results"]),
                                   on_action_change=lambda: None)
    if ev := _action(res_lib, "lib_uid"):
        p = P.get(ev.get("id"))
        if p and ev.get("kind") == "edit":
            mine = P.can_edit(p, current_user())
            st.session_state["persona_template"] = {**p, "duplicate": not mine}
            st.session_state["bots_msg"] = "Os campos foram preenchidos: abra a aba ✍️ Criar bot."
            st.rerun()
        elif p and ev.get("kind") == "delete" and P.can_edit(p, current_user()):
            P.delete_custom(p["id"])
            st.toast(f"“{p['name']}” excluído.", icon="🗑️")
            st.rerun()

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
