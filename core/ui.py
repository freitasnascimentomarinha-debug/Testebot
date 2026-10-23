"""Interface Streamlit compartilhada pelas três páginas de bot."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from core import engine, risk
from core.broker import get_broker
from core.charts import PLOTLY_CONFIG, build_chart, tradingview_widget
from core.data import MarketDataError, get_klines, get_ticker
from core.paper import stats
from core.profiles import PROFILES, SYMBOLS, BotProfile
from core import indicators as ind
from core.realtime import chart_height, realtime_chart_html
from core.settings import DEFAULT_MODEL, default_settings, load_settings, save_settings
from core.storage import get_secret, load_json

# Seletor rápido de indicadores → chaves de configuração (as mesmas da aba Indicadores)
INDICATOR_FLAGS = {
    "Médias móveis (EMA)": "ema_on", "Bandas de Bollinger": "bb_on", "VWAP": "vwap_on", "SuperTrend": "supertrend_on",
    "Volume": "volume_on", "RSI": "rsi_on", "MACD": "macd_on", "Estocástico": "stoch_on", "ADX / DMI": "adx_on",
    "OBV": "obv_on", "Suportes e resistências": "sr_on", "Pivôs": "pivots_on", "Fibonacci": "fib_on",
    "Ichimoku (só na análise técnica)": "ichimoku_on",
}

AI_MODELS = (DEFAULT_MODEL, "deepseek/deepseek-v4-flash", "deepseek/deepseek-v4-pro", "deepseek/deepseek-v3.2")


# ----------------------------------------------------------------- dados (cache)
@st.cache_data(ttl=10, show_spinner=False)
def cached_klines(symbol: str, interval: str, limit: int, market: str) -> pd.DataFrame:
    return get_klines(symbol, interval, limit, market)


@st.cache_data(ttl=10, show_spinner=False)
def cached_ticker(symbol: str, market: str):
    return get_ticker(symbol, market)


def api_key() -> str | None:
    return st.session_state.get("openrouter_key") or get_secret("OPENROUTER_API_KEY")


def fmt(v: float | None, d: int = 2) -> str:
    if v is None or (isinstance(v, float) and v != v):
        return "—"
    return f"{v:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_price(v: float | None) -> str:
    if v is None:
        return "—"
    d = 2 if abs(v) >= 100 else 4 if abs(v) >= 1 else 6
    return fmt(v, d)


# ------------------------------------------------------------ estado/configuração
def _k(bot: str, name: str) -> str:
    return f"{bot}__{name}"


def init_settings(profile: BotProfile) -> dict:
    """Carrega as configurações salvas para o session_state (uma chave por
    widget) e devolve o dicionário atual, salvando se algo mudou."""
    bot = profile.key
    stored = load_settings(bot)
    for name, value in stored.items():
        st.session_state.setdefault(_k(bot, name), value)
    cfg = {name: st.session_state[_k(bot, name)] for name in stored}
    if cfg != stored:
        save_settings(bot, cfg)
    return cfg


def set_setting(bot: str, name: str, value) -> None:
    st.session_state[_k(bot, name)] = value
    cfg = load_settings(bot)
    cfg[name] = value
    save_settings(bot, cfg)


# --------------------------------------------------------------------- página
def render_bot_page(bot: str) -> None:
    profile = PROFILES[bot]
    cfg = init_settings(profile)
    broker = get_broker(bot)

    st.title(f"{profile.icon} Bot de {profile.name}")
    st.caption(f"{profile.market_label} · {profile.description} · Execução: **{broker.name}** com dados reais.")

    # Seleção de ativo e timeframe -------------------------------------------
    c1, c2, c3, c4 = st.columns([2, 1.2, 1, 1.2])
    options = list(dict.fromkeys(list(SYMBOLS) + [cfg["symbol"]]))
    c1.selectbox("Ativo", options, key=_k(bot, "symbol"), accept_new_options=True,
                 help="Escolha da lista ou digite outro par em USDT (ex.: PEPEUSDT).")
    if st.session_state[_k(bot, "interval")] not in profile.intervals:
        st.session_state[_k(bot, "interval")] = profile.default_interval
    c2.selectbox("Timeframe", profile.intervals, key=_k(bot, "interval"))
    c3.number_input("Candles", 150, 1500, step=50, key=_k(bot, "candles"))
    c4.selectbox("Atualização (s)", (5, 10, 15, 30, 60, 120, 300, 600), key=_k(bot, "refresh_sec"))
    cfg = {name: st.session_state[_k(bot, name)] for name in cfg}
    cfg["symbol"] = str(cfg["symbol"]).upper().strip()

    live_metrics(profile, cfg)
    col_chart, col_ticket = st.columns([3.2, 1.25], gap="medium")
    with col_chart:
        indicator_picker(bot, cfg)
        tab_rt, tab_chart, tab_tv = st.tabs(["⚡ Tempo real", "📈 Análise técnica (indicadores)",
                                             "🖊️ TradingView — ferramentas de desenho"])
        with tab_rt:
            positions = [p for p in broker.account()["positions"] if p["symbol"] == cfg["symbol"]]
            height = chart_height(cfg)
            components.html(realtime_chart_html(symbol=cfg["symbol"], interval=cfg["interval"], market=profile.market,
                                                cfg=cfg, lines=realtime_lines(bot, cfg), positions=positions,
                                                height=height), height=height + 5)
            st.caption("Candles transmitidos ao vivo direto da corretora para o seu navegador (WebSocket): cada "
                       "negociação move o candle, os indicadores e o lucro/prejuízo das posições abertas (já "
                       "descontadas as taxas de entrada e saída).")
        with tab_chart:
            analysis_chart(profile, cfg)
        with tab_tv:
            st.caption("Barra lateral esquerda: linhas de tendência, Fibonacci, canais, padrões, régua de medição e as "
                       "ferramentas **Posição comprada / vendida** (risco:retorno visual). Os desenhos ficam no navegador; "
                       "níveis que a IA deve considerar podem ser cadastrados em *Níveis do usuário*, abaixo.")
            components.html(tradingview_widget(cfg["symbol"], cfg["interval"], profile.market, 720), height=730)
    with col_ticket:
        trade_ticket(profile, cfg)

    ai_section(profile, cfg)
    portfolio_section(profile, cfg)
    settings_section(profile, cfg)


def indicator_picker(bot: str, cfg: dict) -> None:
    """Liga/desliga indicadores dos gráficos (mesmas chaves da aba Indicadores)."""
    key = f"{bot}__ind_pick"
    st.session_state[key] = [label for label, flag in INDICATOR_FLAGS.items() if cfg.get(flag)]

    def _apply():
        chosen = set(st.session_state[key])
        for label, flag in INDICATOR_FLAGS.items():
            st.session_state[_k(bot, flag)] = label in chosen

    st.multiselect("Indicadores no gráfico", list(INDICATOR_FLAGS), key=key, on_change=_apply,
                   placeholder="Escolha os indicadores", help="Adicione ou remova indicadores. Parâmetros (períodos, "
                   "desvios etc.) ficam em Configurações do bot → Indicadores.")


# ------------------------------------------------------- seção ao vivo (fragments)
def _cfg_now(profile: BotProfile, cfg: dict) -> dict:
    cfg_now = {**cfg, **{k: st.session_state.get(_k(profile.key, k), v) for k, v in cfg.items()}}
    cfg_now["symbol"] = str(cfg_now["symbol"]).upper().strip()
    return cfg_now


def live_metrics(profile: BotProfile, cfg: dict) -> None:
    """Atualiza dados, verifica stops/alvos da conta simulada, mostra as
    métricas e roda o piloto automático a cada ``refresh_sec`` segundos."""

    @st.fragment(run_every=int(cfg["refresh_sec"]))
    def _live():
        bot = profile.key
        cfg_now = _cfg_now(profile, cfg)
        symbol, interval = cfg_now["symbol"], cfg_now["interval"]
        try:
            raw = cached_klines(symbol, interval, int(cfg_now["candles"]), profile.market)
            ticker = cached_ticker(symbol, profile.market)
        except MarketDataError as exc:
            st.error(f"Falha ao carregar dados de {symbol}: {exc}")
            return
        df = engine.prepare(raw, cfg_now)
        price = ticker.last
        st.session_state[f"{bot}__last_price"] = price
        st.session_state[f"{bot}__atr"] = float(df["atr"].iloc[-2])
        st.session_state[f"{bot}__df"] = df
        st.session_state[f"{bot}__source"] = f"{df.attrs.get('source')} · cotação: {ticker.source}"

        broker = get_broker(bot)
        events = broker.sync(symbol, raw, price)
        for ev in events:
            t = ev.get("trade")
            msg = f"{ev['type']}: {t['side']} {t['symbol']} {t['pnl']:+.2f} USDT" if t else ev["type"]
            st.toast(msg, icon="🔔")
        if events:
            st.session_state[f"{bot}__need_rerun"] = True
        acct = broker.account()
        s = stats(acct, {symbol: price})

        m = st.columns(6)
        m[0].metric(symbol, fmt_price(price), f"{ticker.change_pct:+.2f}% 24h")
        m[1].metric("Patrimônio", f"{fmt(s['equity'])}", f"{fmt(s['total_pnl'])} ({s['total_pnl_pct']:+.2f}%)")
        m[2].metric("Resultado hoje", fmt(s["pnl_today"]), f"meta {fmt(cfg_now['daily_profit_target'], 0)}")
        m[3].metric("Operações hoje", f"{s['trades_today']}/{cfg_now['max_trades_day']}")
        m[4].metric("P&L aberto (líquido)", fmt(s["unrealized_net"]), f"{s['open_positions']} posição(ões)",
                    delta_color="off", help="Lucro/prejuízo das posições abertas já descontando taxas de entrada e saída.")
        m[5].metric("Taxa de acerto", f"{s['win_rate']:.0f}%", f"{s['trades']} trades", delta_color="off")

        if cfg_now.get("autopilot"):
            autopilot_step(profile, cfg_now, df, price)
        if st.session_state.pop(f"{bot}__need_rerun", False):
            st.rerun()  # posição encerrada/ordem executada: atualiza linhas do gráfico e carteira

    _live()


def analysis_chart(profile: BotProfile, cfg: dict) -> None:
    @st.fragment(run_every=int(cfg["refresh_sec"]))
    def _chart():
        bot = profile.key
        df = st.session_state.get(f"{bot}__df")
        if df is None:
            st.info("Carregando dados…")
            return
        cfg_now = _cfg_now(profile, cfg)
        acct = get_broker(bot).account()
        result = st.session_state.get(f"{bot}__analysis")
        plan = result.decision.to_dict() if result and result.symbol == cfg_now["symbol"] else None
        fig = build_chart(df, cfg_now, symbol=cfg_now["symbol"], interval=cfg_now["interval"], positions=acct["positions"],
                          orders=acct["orders"], history=acct["history"], plan=plan)
        st.plotly_chart(fig, config=PLOTLY_CONFIG, key=f"{bot}_chart")
        st.caption(f"Fonte: {st.session_state.get(f'{bot}__source', '')} · atualizado às "
                   f"{datetime.now().strftime('%H:%M:%S')} · role para zoom, arraste para mover, use a barra do "
                   "gráfico para desenhar linhas, retângulos e círculos.")

    _chart()


def realtime_lines(bot: str, cfg: dict) -> list[dict]:
    """Linhas de preço do gráfico em tempo real (só mudam quando há ação do
    usuário, para o gráfico não recarregar a cada atualização)."""
    acct = get_broker(bot).account()
    lines = []  # a linha de entrada (com P&L ao vivo) é desenhada pelo próprio gráfico
    for p in acct["positions"]:
        if p["symbol"] != cfg["symbol"]:
            continue
        if p.get("stop_loss"):
            lines.append({"price": p["stop_loss"], "color": "#ef5350", "title": "SL"})
        if p.get("take_profit"):
            lines.append({"price": p["take_profit"], "color": "#26a69a", "title": "TP"})
        if p.get("liquidation"):
            lines.append({"price": p["liquidation"], "color": "#ff9800", "style": "dotted", "title": "Liq."})
    df = st.session_state.get(f"{bot}__df")
    if df is not None and len(df) > 50:
        closed = df.iloc[:-1]  # níveis de candles fechados: não mudam a cada atualização
        if cfg.get("sr_on"):
            levels = ind.support_resistance(closed)
            lines += [{"price": lv["price"], "color": "rgba(38,166,154,.7)", "style": "dotted", "title": "S"}
                      for lv in levels["supports"]]
            lines += [{"price": lv["price"], "color": "rgba(239,83,80,.7)", "style": "dotted", "title": "R"}
                      for lv in levels["resistances"]]
        if cfg.get("pivots_on"):
            lines += [{"price": v, "color": "rgba(158,158,158,.8)", "title": k} for k, v in ind.pivot_points(closed).items()]
        if cfg.get("fib_on"):
            lines += [{"price": v, "color": "rgba(255,193,7,.7)", "style": "dotted", "title": f"Fib {k}"}
                      for k, v in ind.fibonacci(closed).items()]
    for o in acct["orders"]:
        if o["symbol"] == cfg["symbol"]:
            lines.append({"price": o["limit_price"], "color": "#bdbdbd", "title": f"LIMIT {o['side']}"})
    result = st.session_state.get(f"{bot}__analysis")
    if result and result.symbol == cfg["symbol"] and result.decision.decision in ("BUY", "SELL") and not result.executed:
        d = result.decision
        for price, color, title in ((d.entry, "#90caf9", "Plano: entrada"), (d.stop_loss, "#ef9a9a", "Plano: stop"),
                                    (d.take_profit, "#a5d6a7", "Plano: alvo")):
            if price:
                lines.append({"price": price, "color": color, "style": "dotted", "title": title})
    for lv in cfg.get("user_levels", []):
        if lv.get("type") == "horizontal":
            lines.append({"price": lv["price"], "color": lv.get("color", "#e91e63"), "style": "solid",
                          "title": lv.get("label") or "Nível"})
    return lines


def autopilot_step(profile: BotProfile, cfg: dict, df: pd.DataFrame, price: float) -> None:
    """Analisa automaticamente a cada candle fechado (enquanto a página estiver aberta)."""
    from core.data import last_closed_candle_time

    bot = profile.key
    marker = f"{cfg['symbol']}-{cfg['interval']}-{last_closed_candle_time(df, cfg['interval'])}"
    if st.session_state.get(f"{bot}__autopilot_last") == marker:
        st.caption(f"🤖 Piloto automático ativo — próxima análise no fechamento do candle ({marker.split('-', 2)[-1][:16]}).")
        return
    st.session_state[f"{bot}__autopilot_last"] = marker
    with st.spinner("Piloto automático analisando o candle fechado…"):
        result = engine.run_analysis(profile, cfg, df, price, api_key())
    st.session_state[f"{bot}__analysis"] = result
    if result.check and result.check.allowed:
        try:
            out = engine.execute(profile, cfg, result, price)
            st.toast(f"Piloto automático: ordem {out.get('status')} ({result.decision.decision})", icon="🤖")
        except Exception as exc:  # noqa: BLE001
            st.toast(f"Piloto automático: falha ao executar ({exc})", icon="⚠️")
    elif result.decision.decision == "CLOSE":
        engine.execute(profile, cfg, result, price)


# ------------------------------------------------------- boleta + calculadora
def trade_ticket(profile: BotProfile, cfg: dict) -> None:
    bot = profile.key
    price = st.session_state.get(f"{bot}__last_price")
    atr_v = st.session_state.get(f"{bot}__atr")
    if not price:
        st.info("Carregando cotação…")
        return
    broker = get_broker(bot)
    acct = broker.account()
    s = stats(acct, {cfg["symbol"]: price})
    lev = risk.effective_leverage(cfg)

    st.subheader("🧮 Boleta e calculadora")
    can_short = cfg["allow_short"] and (profile.market == "futures" or cfg["leverage_on"])
    sides = ["Compra (long)", "Venda (short)"] if can_short else ["Compra (long)"]
    side_label = st.segmented_control("Lado", sides, default=sides[0], key=f"{bot}__t_side") or sides[0]
    side = "BUY" if side_label.startswith("Compra") else "SELL"
    otype = st.segmented_control("Tipo", ["Mercado", "Limitada"], default="Mercado", key=f"{bot}__t_type") or "Mercado"
    sign = 1 if side == "BUY" else -1

    entry = price
    if otype == "Limitada":
        entry = st.number_input("Preço limite", value=float(price), format="%.6f", key=f"{bot}__t_limit")
    sl_default = entry - sign * (atr_v or price * 0.01) * float(cfg["atr_sl_mult"])
    tp_default = entry + sign * (atr_v or price * 0.01) * float(cfg["atr_tp_mult"])
    use_atr = st.toggle("Stop/alvo automáticos pelo ATR", value=True, key=f"{bot}__t_auto")
    c1, c2 = st.columns(2)
    if use_atr:
        sl, tp = risk.round_price(sl_default, price), risk.round_price(tp_default, price)
        c1.metric("Stop loss", fmt_price(sl))
        c2.metric("Take profit", fmt_price(tp))
    else:
        sl = c1.number_input("Stop loss", value=float(risk.round_price(sl_default, price)), format="%.6f", key=f"{bot}__t_sl")
        tp = c2.number_input("Take profit", value=float(risk.round_price(tp_default, price)), format="%.6f", key=f"{bot}__t_tp")

    sizing = st.radio("Tamanho por", ["Perda máxima", "Valor (margem)"], horizontal=True, key=f"{bot}__t_sizing")
    budget = risk.risk_budget(cfg, s["equity"])
    if sizing == "Perda máxima":
        risk_usdt = st.number_input("Perda máxima no trade (USDT)", min_value=0.0, value=float(round(budget, 2)),
                                    step=5.0, key=f"{bot}__t_risk")
        calc = risk.calculate(side, entry, sl, tp, leverage=lev, fee_pct=float(cfg["fee_pct"]),
                              risk_usdt=risk_usdt, available=s["available"])
    else:
        margin = st.number_input("Margem a alocar (USDT)", min_value=0.0, value=float(min(500.0, s["available"])),
                                 step=50.0, key=f"{bot}__t_margin")
        calc = risk.calculate(side, entry, sl, tp, leverage=lev, fee_pct=float(cfg["fee_pct"]),
                              margin_usdt=margin, available=s["available"])

    rr_ok = calc.rr is not None and calc.rr >= float(cfg["min_rr"])
    st.markdown(
        f"""
| | |
|---|---|
| Quantidade | **{calc.qty:g}** |
| Nocional | {fmt(calc.notional)} USDT |
| Margem ({calc.leverage:g}×) | {fmt(calc.margin)} USDT |
| Risco (stop) | <span style="color:#ef5350">−{fmt(calc.risk_usdt)} USDT</span> ({fmt(calc.stop_pct)}%) |
| Retorno (alvo) | <span style="color:#26a69a">+{fmt(calc.reward_usdt)} USDT</span> ({fmt(calc.tp_pct)}%) |
| Risco:retorno | **{fmt(calc.rr) if calc.rr else '—'}** {'✅' if rr_ok else '⚠️'} |
| Taxas (ida+volta) | {fmt(calc.fees_usdt)} USDT |
| Break-even | {fmt_price(calc.breakeven)} |
| Liquidação est. | {fmt_price(calc.liquidation)} |
""", unsafe_allow_html=True)
    for w in calc.warnings:
        st.warning(w)

    if st.button(f"Enviar ordem simulada — {'COMPRAR' if side == 'BUY' else 'VENDER'}", type="primary",
                 width="stretch", key=f"{bot}__t_send", disabled=calc.qty <= 0):
        check = risk.check_trade(cfg, s, side, entry, sl, tp, profile.market)
        hard = [r for r in check.reasons if "risco:retorno" not in r and "Meta" not in r and "atingid" not in r]
        if hard:
            for r in hard:
                st.error(r)
        else:
            for r in check.reasons:
                st.warning(f"Aviso (ordem manual permitida): {r}")
            try:
                out = broker.place_order(symbol=cfg["symbol"], market=profile.market, side=side, qty=calc.qty,
                                         order_type="LIMIT" if otype == "Limitada" else "MARKET", price=price,
                                         limit_price=entry if otype == "Limitada" else None, stop_loss=sl,
                                         take_profit=tp, leverage=lev, fee_pct=float(cfg["fee_pct"]),
                                         slippage_pct=float(cfg["slippage_pct"]), source="manual",
                                         max_loss_planned=calc.risk_usdt)
                st.success(f"Ordem {out['status'].lower()}.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))


# ------------------------------------------------------------------- IA
def ai_section(profile: BotProfile, cfg: dict) -> None:
    bot = profile.key
    st.divider()
    st.subheader("🤖 Análise e programação de ordens com IA")
    key = api_key()
    c1, c2, c3 = st.columns([1.4, 1, 1.6])
    run = c1.button("⚡ Analisar mercado e programar ordem", type="primary", width="stretch", key=f"{bot}__run_ai")
    c2.toggle("Executar automaticamente se aprovado", key=_k(bot, "ai_auto_execute"))
    c3.toggle("Piloto automático (a cada candle fechado)", key=_k(bot, "autopilot"),
              help="Enquanto esta página estiver aberta, o bot analisa cada candle fechado e executa as ordens "
                   "aprovadas pelo gestor de risco. Para operar 24/7 use o worker.py.")
    if not key:
        st.info("Sem chave da OpenRouter: o bot usa somente as habilidades de programação. Informe a chave na barra "
                "lateral ou em `.streamlit/secrets.toml` para ativar o DeepSeek.")

    if run:
        df = st.session_state.get(f"{bot}__df")
        price = st.session_state.get(f"{bot}__last_price")
        if df is None or not price:
            st.warning("Aguarde o carregamento do gráfico.")
        else:
            with st.spinner(f"Executando habilidades e consultando {cfg['ai_model'] if key else 'regras'}…"):
                result = engine.run_analysis(profile, cfg, df, price, key)
            st.session_state[f"{bot}__analysis"] = result
            if cfg["ai_auto_execute"] and ((result.check and result.check.allowed) or result.decision.decision == "CLOSE"):
                try:
                    out = engine.execute(profile, cfg, result, price)
                    st.success(f"Ordem programada automaticamente: {out.get('status')}.")
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Falha ao executar: {exc}")

    result = st.session_state.get(f"{bot}__analysis")
    if not result:
        st.caption("Clique no botão para o bot executar as habilidades técnicas, enviar o contexto ao DeepSeek e "
                   "propor a ordem já dimensionada pela sua perda máxima por trade.")
        return
    render_analysis(profile, cfg, result)


def render_analysis(profile: BotProfile, cfg: dict, result: engine.AnalysisResult) -> None:
    bot = profile.key
    d = result.decision
    label = {"BUY": "🟢 COMPRA", "SELL": "🔴 VENDA", "HOLD": "⚪ AGUARDAR", "CLOSE": "🟠 ENCERRAR POSIÇÕES"}[d.decision]
    if result.error:
        st.warning(f"A IA falhou e foi usada a decisão por regras: {result.error}")
    with st.container(border=True):
        h = st.columns([1.3, 1, 1, 1, 1, 1])
        h[0].markdown(f"### {label}")
        h[1].metric("Confiança", f"{d.confidence}%")
        h[2].metric("Entrada", fmt_price(d.entry or result.price), d.order_type)
        h[3].metric("Stop", fmt_price(d.stop_loss))
        h[4].metric("Alvo", fmt_price(d.take_profit))
        h[5].metric("Placar regras", f"{result.plan['score']:+.0f}", result.plan["regime"], delta_color="off")
        st.markdown(f"**Análise ({'IA · ' + d.model if d.source == 'ia' else 'somente regras'}):** {d.reasoning}")
        if d.risks:
            st.markdown(f"**Riscos:** {d.risks}")
        if d.invalidation:
            st.markdown(f"**Invalidação:** {d.invalidation}")
        if d.management:
            st.markdown(f"**Condução:** {d.management}")
        if result.plan.get("note"):
            st.info(result.plan["note"])

        if result.check:
            calc = result.check.calc
            if calc:
                st.markdown(f"**Dimensionamento:** {calc.qty:g} {result.symbol} · nocional {fmt(calc.notional)} USDT · "
                            f"margem {fmt(calc.margin)} USDT ({calc.leverage:g}×) · risco {fmt(calc.risk_usdt)} USDT · "
                            f"retorno {fmt(calc.reward_usdt)} USDT · R:R {fmt(calc.rr) if calc.rr else '—'}")
            if result.check.allowed:
                st.success("Gestor de risco: ordem APROVADA.")
            else:
                st.error("Gestor de risco: ordem BLOQUEADA — " + " | ".join(result.check.reasons))

        executable = (result.check and result.check.allowed) or d.decision == "CLOSE"
        if result.executed:
            st.success(f"Ordem enviada: {result.executed.get('status')}")
        elif executable and st.button("✅ Executar plano na conta simulada", key=f"{bot}__exec_plan", type="primary"):
            price = st.session_state.get(f"{bot}__last_price", result.price)
            try:
                out = engine.execute(profile, cfg, result, price)
                st.success(f"Ordem enviada: {out.get('status')}")
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(str(exc))

        with st.expander("Habilidades de programação (votos que alimentaram a IA)"):
            st.dataframe(pd.DataFrame([{"Habilidade": sk["name"], "Voto": round(sk["vote"], 2),
                                        "Peso": profile.skill_weights.get(sk["key"], 1.0), "Leitura": sk["detail"]}
                                       for sk in result.plan["skills"]]),
                         hide_index=True, column_config={"Voto": st.column_config.ProgressColumn(
                             min_value=-1, max_value=1, format="%.2f")})
            lv = result.plan["levels"]
            st.caption("Suportes: " + ", ".join(fmt_price(x["price"]) for x in lv["supports"]) +
                       " · Resistências: " + ", ".join(fmt_price(x["price"]) for x in lv["resistances"]))
        if d.raw:
            with st.expander("Resposta bruta da IA"):
                st.code(d.raw, language="json")
                if d.usage:
                    st.caption(f"Tokens: {d.usage}")


# ------------------------------------------------------------- carteira
def portfolio_section(profile: BotProfile, cfg: dict) -> None:
    bot = profile.key
    broker = get_broker(bot)
    acct = broker.account()
    price = st.session_state.get(f"{bot}__last_price", 0)
    st.divider()
    st.subheader("💼 Conta simulada")
    t1, t2, t3, t4, t5 = st.tabs(["Posições abertas", "Ordens pendentes", "Histórico", "Curva de patrimônio", "Log de decisões"])
    with t1:
        open_positions(profile, cfg)
    with t2:
        if not acct["orders"]:
            st.caption("Nenhuma ordem pendente.")
        for o in acct["orders"]:
            c = st.columns([4, 1])
            c[0].write(f"LIMIT {o['side']} {o['qty']:g} {o['symbol']} @ {fmt_price(o['limit_price'])} · "
                       f"SL {fmt_price(o['stop_loss'])} · TP {fmt_price(o['take_profit'])} · {o['source']}")
            if c[1].button("Cancelar", key=f"{bot}_cancel_{o['id']}"):
                broker.cancel_order(o["id"])
                st.rerun()
    with t3:
        if acct["history"]:
            hist = pd.DataFrame(acct["history"])[["closed", "symbol", "side", "qty", "entry", "exit", "leverage",
                                                  "reason", "pnl", "pnl_pct_margin", "fees_total", "source"]].iloc[::-1]
            hist["closed"] = pd.to_datetime(hist["closed"]).dt.tz_convert("America/Sao_Paulo").dt.strftime("%d/%m %H:%M")
            st.dataframe(hist, hide_index=True, column_config={
                "closed": "Encerrado", "symbol": "Ativo", "side": "Lado", "qty": "Qtd.", "entry": "Entrada",
                "exit": "Saída", "leverage": "Alav.", "reason": "Motivo",
                "pnl": st.column_config.NumberColumn("P&L (USDT)", format="%.2f"),
                "pnl_pct_margin": st.column_config.NumberColumn("% margem", format="%.1f%%"),
                "fees_total": st.column_config.NumberColumn("Taxas", format="%.2f"), "source": "Origem"})
            s = stats(acct, {cfg["symbol"]: price})
            c = st.columns(5)
            c[0].metric("Fator de lucro", "∞" if s["profit_factor"] == float("inf") else fmt(s["profit_factor"]))
            c[1].metric("Ganho médio", fmt(s["avg_win"]))
            c[2].metric("Perda média", fmt(s["avg_loss"]))
            c[3].metric("Drawdown máx.", f"{s['max_drawdown']:.2f}%")
            c[4].download_button("⬇️ Exportar CSV", hist.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
                                 file_name=f"historico_{bot}.csv", mime="text/csv")
        else:
            st.caption("Nenhuma operação encerrada ainda.")
    with t4:
        curve = pd.DataFrame(acct["equity_curve"])
        if len(curve) > 1:
            curve["time"] = pd.to_datetime(curve["time"])
            st.line_chart(curve.set_index("time")["equity"], height=260)
        else:
            st.caption("A curva aparece após as primeiras atualizações.")
    with t5:
        logs = (load_json(engine.LOG_FILE, {}) or {}).get(bot, [])
        if logs:
            st.dataframe(pd.DataFrame(logs[::-1])[["time", "symbol", "interval", "decision", "source", "confidence",
                                                   "score", "approved", "executed", "reasons", "reasoning"]],
                         hide_index=True)
        else:
            st.caption("Nenhuma análise registrada.")


def open_positions(profile: BotProfile, cfg: dict) -> None:
    """Cards das posições abertas, com P&L atualizado automaticamente."""

    @st.fragment(run_every=int(cfg["refresh_sec"]))
    def _cards():
        bot = profile.key
        broker = get_broker(bot)
        acct = broker.account()
        price = st.session_state.get(f"{bot}__last_price", 0)
        if not acct["positions"]:
            st.caption("Nenhuma posição aberta.")
        for p in acct["positions"]:
            p_price = price if p["symbol"] == cfg["symbol"] else _safe_price(p["symbol"], profile.market) or p["entry"]
            gross = (p_price - p["entry"]) * p["qty"] * (1 if p["side"] == "BUY" else -1)
            net = gross - p["fees_paid"] - p_price * p["qty"] * p["fee_pct"] / 100
            with st.container(border=True):
                c = st.columns([1.6, 1, 1.1, 1, 1, 1.2, 1])
                c[0].markdown(f"**{'🟢 COMPRA' if p['side'] == 'BUY' else '🔴 VENDA'} {p['symbol']}**  \n"
                              f"{p['qty']:g} @ {fmt_price(p['entry'])} · {p['leverage']:g}× · {p['source']}")
                c[1].metric("Atual", fmt_price(p_price))
                c[2].metric("P&L líquido", fmt(net), f"{net / p['margin'] * 100:+.1f}% margem" if p["margin"] else None)
                new_sl = c[3].number_input("Stop", value=float(p["stop_loss"] or 0), format="%.6f", key=f"{bot}_sl_{p['id']}")
                new_tp = c[4].number_input("Alvo", value=float(p["take_profit"] or 0), format="%.6f", key=f"{bot}_tp_{p['id']}")
                if c[5].button("Atualizar SL/TP", key=f"{bot}_upd_{p['id']}"):
                    broker.update_protection(p["id"], new_sl or None, new_tp or None)
                    st.rerun(scope="app")
                if c[6].button("Zerar", key=f"{bot}_close_{p['id']}", type="primary"):
                    tr = broker.close_position(p["id"], p_price, "Manual")
                    st.toast(f"Posição encerrada: {tr['pnl']:+.2f} USDT")
                    st.rerun(scope="app")
        st.caption("P&L líquido = variação de preço − taxa de entrada − taxa estimada de saída. No gráfico em "
                   f"tempo real ele muda a cada negociação; aqui, a cada {cfg['refresh_sec']} s.")

    _cards()


def _safe_price(symbol: str, market: str) -> float | None:
    try:
        return cached_ticker(symbol, market).last
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------- configurações
def settings_section(profile: BotProfile, cfg: dict) -> None:
    bot = profile.key
    k = lambda n: _k(bot, n)  # noqa: E731
    st.divider()
    st.subheader("⚙️ Configurações do bot")
    t_risk, t_goal, t_lev, t_ind, t_ai, t_lv, t_acct = st.tabs(
        ["Risco por trade", "Metas de operação", "Alavancagem", "Indicadores", "IA", "Níveis do usuário", "Conta"])

    with t_risk:
        c = st.columns(3)
        c[0].radio("Perda máxima definida em", ["USDT", "% do saldo"], key=k("risk_mode"), horizontal=True)
        if cfg["risk_mode"] == "USDT":
            c[1].number_input("Perda mínima aceitável por trade (USDT)", 1.0, 1e6, step=5.0, key=k("max_loss_usdt"),
                              help="Valor máximo que você aceita perder se o stop for atingido. O tamanho da posição "
                                   "é calculado a partir dele (já incluindo as taxas).")
        else:
            c[1].number_input("Perda máxima por trade (% do patrimônio)", 0.1, 20.0, step=0.1, key=k("max_loss_pct"))
        c[2].number_input("Risco:retorno mínimo", 0.5, 10.0, step=0.1, key=k("min_rr"))
        c = st.columns(4)
        c[0].number_input("Stop = ATR ×", 0.5, 10.0, step=0.1, key=k("atr_sl_mult"))
        c[1].number_input("Alvo = ATR ×", 0.5, 30.0, step=0.5, key=k("atr_tp_mult"))
        c[2].number_input("Taxa por lado (%)", 0.0, 1.0, step=0.01, format="%.3f", key=k("fee_pct"))
        c[3].number_input("Slippage simulado (%)", 0.0, 1.0, step=0.01, format="%.3f", key=k("slippage_pct"))

    with t_goal:
        c = st.columns(4)
        c[0].number_input("Meta de operações por dia", 1, 100, key=k("max_trades_day"))
        c[1].number_input("Meta de lucro diária (USDT)", 0.0, 1e6, step=10.0, key=k("daily_profit_target"),
                          help="Ao atingir, o bot deixa de abrir operações até o dia seguinte (UTC). 0 = sem meta.")
        c[2].number_input("Limite de perda diária (USDT)", 0.0, 1e6, step=10.0, key=k("daily_max_loss"))
        c[3].number_input("Máx. posições simultâneas", 1, 20, key=k("max_open_positions"))

    with t_lev:
        label = "Operar alavancado (futuros)" if profile.market == "futures" else "Operar alavancado (margem, como nos futuros)"
        st.toggle(label, key=k("leverage_on"))
        c = st.columns(3)
        c[0].slider("Alavancagem", 1, profile.max_leverage, key=k("leverage"), disabled=not cfg["leverage_on"])
        c[1].radio("Modo de margem", ["Isolada", "Cruzada"], key=k("margin_mode"), horizontal=True)
        c[2].toggle("Permitir operações vendidas (short)", key=k("allow_short"),
                    help="No spot, vender a descoberto exige margem (alavancagem ligada).")
        if cfg["leverage_on"]:
            liq_long = risk.liquidation_price("BUY", 100, cfg["leverage"])
            st.caption(f"Com {cfg['leverage']}× uma posição comprada é liquidada com queda aproximada de "
                       f"{100 - liq_long:.1f}% (margem isolada). O gestor de risco bloqueia stops além da liquidação.")

    with t_ind:
        st.caption("Ligue/desligue a exibição no gráfico. As habilidades da IA usam todos os indicadores calculados.")
        c = st.columns(4)
        with c[0]:
            st.markdown("**Tendência**")
            st.checkbox("Médias móveis (EMA)", key=k("ema_on"))
            st.number_input("EMA rápida", 2, 100, key=k("ema_fast"))
            st.number_input("EMA lenta", 3, 200, key=k("ema_slow"))
            st.number_input("EMA de tendência", 20, 400, key=k("ema_trend"))
            st.checkbox("SuperTrend", key=k("supertrend_on"))
            st.number_input("SuperTrend período", 5, 50, key=k("st_period"))
            st.number_input("SuperTrend multiplicador", 1.0, 6.0, step=0.5, key=k("st_mult"))
            st.checkbox("Ichimoku", key=k("ichimoku_on"))
        with c[1]:
            st.markdown("**Volatilidade e preço médio**")
            st.checkbox("Bandas de Bollinger", key=k("bb_on"))
            st.number_input("Bollinger período", 5, 100, key=k("bb_period"))
            st.number_input("Bollinger desvios", 1.0, 4.0, step=0.5, key=k("bb_std"))
            st.number_input("ATR período", 5, 50, key=k("atr_period"))
            st.checkbox("VWAP diário", key=k("vwap_on"))
            st.checkbox("Pivôs clássicos", key=k("pivots_on"))
        with c[2]:
            st.markdown("**Osciladores**")
            st.checkbox("RSI", key=k("rsi_on"))
            st.number_input("RSI período", 2, 50, key=k("rsi_period"))
            st.number_input("RSI sobrecompra", 50, 95, key=k("rsi_ob"))
            st.number_input("RSI sobrevenda", 5, 50, key=k("rsi_os"))
            st.checkbox("MACD", key=k("macd_on"))
            st.number_input("MACD rápida", 2, 50, key=k("macd_fast"))
            st.number_input("MACD lenta", 5, 100, key=k("macd_slow"))
            st.number_input("MACD sinal", 2, 50, key=k("macd_signal"))
        with c[3]:
            st.markdown("**Volume e níveis**")
            st.checkbox("Volume", key=k("volume_on"))
            st.checkbox("OBV", key=k("obv_on"))
            st.checkbox("Estocástico", key=k("stoch_on"))
            st.number_input("Estocástico %K", 3, 50, key=k("stoch_k"))
            st.number_input("Estocástico %D", 1, 20, key=k("stoch_d"))
            st.checkbox("ADX / DMI", key=k("adx_on"))
            st.number_input("ADX período", 5, 50, key=k("adx_period"))
            st.checkbox("Suportes e resistências automáticos", key=k("sr_on"))
            st.checkbox("Fibonacci automático", key=k("fib_on"))

    with t_ai:
        c = st.columns(3)
        if cfg["ai_model"] not in AI_MODELS:
            st.session_state[k("ai_model")] = DEFAULT_MODEL
        c[0].selectbox("Modelo (OpenRouter)", AI_MODELS, key=k("ai_model"), accept_new_options=True)
        c[1].slider("Temperatura", 0.0, 1.0, step=0.05, key=k("ai_temperature"))
        c[2].slider("Confiança mínima para executar (%)", 0, 100, key=k("ai_min_confidence"))
        st.slider("Candles enviados como contexto", 20, 200, step=10, key=k("ai_candles_context"))
        st.text_area("Instruções da sua estratégia para a IA", key=k("ai_instructions"), height=110,
                     placeholder="Ex.: Só operar a favor da EMA 200. Evitar entradas 30 min antes de notícias dos EUA. "
                                 "Priorizar pullbacks na VWAP.")

    with t_lv:
        st.caption("Níveis desenhados aqui aparecem no gráfico, persistem entre sessões e são enviados à IA.")
        price = st.session_state.get(f"{bot}__last_price", 0.0) or 0.0
        with st.form(f"{bot}_lv_form", clear_on_submit=True, border=False):
            c = st.columns([1, 1.2, 1.5, 0.8, 1])
            typ = c[0].selectbox("Tipo", ["Horizontal", "Tendência"])
            p1 = c[1].number_input("Preço (ou preço 1)", value=float(price), format="%.6f")
            label_ = c[2].text_input("Rótulo", placeholder="Ex.: zona de demanda")
            color = c[3].color_picker("Cor", "#e91e63")
            p2 = c[4].number_input("Preço 2 (tendência)", value=float(price), format="%.6f")
            c2 = st.columns(2)
            t1 = c2[0].text_input("Data/hora 1 (tendência, AAAA-MM-DD HH:MM UTC)")
            t2 = c2[1].text_input("Data/hora 2 (tendência)")
            if st.form_submit_button("Adicionar nível"):
                levels = list(cfg["user_levels"])
                if typ == "Horizontal":
                    levels.append({"type": "horizontal", "price": p1, "label": label_, "color": color})
                else:
                    try:
                        levels.append({"type": "trend", "p1": p1, "p2": p2, "label": label_, "color": color,
                                       "t1": pd.Timestamp(t1, tz="UTC").isoformat(), "t2": pd.Timestamp(t2, tz="UTC").isoformat()})
                    except ValueError:
                        st.error("Datas inválidas para a linha de tendência.")
                set_setting(bot, "user_levels", levels)
                st.rerun()
        for i, lv in enumerate(cfg["user_levels"]):
            c = st.columns([5, 1])
            desc = (f"Horizontal {fmt_price(lv['price'])}" if lv["type"] == "horizontal"
                    else f"Tendência {fmt_price(lv['p1'])} → {fmt_price(lv['p2'])}")
            c[0].markdown(f"<span style='color:{lv.get('color')}'>■</span> {desc} — {lv.get('label', '')}", unsafe_allow_html=True)
            if c[1].button("Remover", key=f"{bot}_lv_rm_{i}"):
                set_setting(bot, "user_levels", [x for j, x in enumerate(cfg["user_levels"]) if j != i])
                st.rerun()

    with t_acct:
        acct = get_broker(bot).account()
        st.write(f"Saldo inicial: **{fmt(acct['initial'])} USDT** · criada em {acct['created'][:10]}")
        c = st.columns([1, 1, 2])
        initial = c[0].number_input("Novo saldo inicial (USDT)", 100.0, 1e7, value=float(acct["initial"]), step=1000.0,
                                    key=f"{bot}__reset_val")
        confirm = c[1].checkbox("Confirmo apagar posições e histórico", key=f"{bot}__reset_ok")
        if c[2].button("Reiniciar conta simulada", disabled=not confirm, key=f"{bot}__reset_btn"):
            get_broker(bot).reset(initial)
            st.success("Conta reiniciada.")
            st.rerun()
        if st.button("Restaurar configurações padrão deste bot", key=f"{bot}__defaults"):
            defaults = default_settings(profile)
            save_settings(bot, defaults)
            for name in defaults:
                st.session_state.pop(_k(bot, name), None)
            st.rerun()
