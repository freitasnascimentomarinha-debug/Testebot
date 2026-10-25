"""Interface Streamlit compartilhada pelas três páginas de bot."""
from __future__ import annotations

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from core import ai as ai_mod, engine, execution, paper, personalities, ranking, regime, risk, scanner
from core.broker import get_broker
from core.charts import tradingview_widget
from core import leverage as lev_rules
from core.data import MarketDataError, get_funding_rate, get_klines, get_ticker, list_symbols
from core.profiles import PROFILES, SYMBOLS, BotProfile, style_of
from core import indicators as ind
from core.realtime import chart_height, realtime_chart_html
from core.settings import DEFAULT_MODEL, default_settings, load_settings, save_settings
from core.storage import get_secret, load_json

# Seletor rápido de indicadores → chaves de configuração (as mesmas da aba Indicadores)
INDICATOR_FLAGS = {
    "Médias móveis (EMA rápida e lenta)": "ema_on", "EMA de tendência (200)": "ema_trend_on",
    "Bandas de Bollinger": "bb_on", "VWAP": "vwap_on", "SuperTrend": "supertrend_on",
    "Volume": "volume_on", "RSI": "rsi_on", "MACD": "macd_on", "Estocástico": "stoch_on", "ADX / DMI": "adx_on",
    "OBV": "obv_on", "Suportes e resistências": "sr_on", "Pivôs": "pivots_on", "Fibonacci": "fib_on",
    "Ichimoku (só na análise técnica)": "ichimoku_on",
}

AI_MODELS = (DEFAULT_MODEL, "deepseek/deepseek-v4-flash", "deepseek/deepseek-v4-pro", "deepseek/deepseek-v3.2")


# ----------------------------------------------------------------- dados (cache)
@st.cache_data(ttl=10, show_spinner=False)
def cached_klines(symbol: str, interval: str, limit: int, market: str) -> pd.DataFrame:
    return get_klines(symbol, interval, limit, market)


# Objetos (Ticker, faixas de alavancagem) ficam em cache_resource: o cache_data os serializa com pickle, que falha quando o app recarrega
# os módulos após uma atualização do código (a classe guardada deixa de ser a mesma do módulo).
@st.cache_resource(ttl=10, show_spinner=False)
def cached_ticker(symbol: str, market: str):
    return get_ticker(symbol, market)


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def cached_symbols(market: str) -> list[str]:
    try:
        return list_symbols(market)
    except Exception:  # noqa: BLE001
        return list(SYMBOLS)


@st.cache_data(ttl=300, show_spinner=False)
def cached_funding(symbol: str) -> float | None:
    return get_funding_rate(symbol)


@st.cache_resource(ttl=6 * 3600, show_spinner=False)
def cached_brackets(symbol: str):
    return lev_rules.brackets(symbol)


@st.cache_data(ttl=1800, show_spinner=False, max_entries=60)
def cached_votes(symbol: str, interval: str, market: str, days: int):
    """Votos de todas as habilidades (simulação rápida) para os últimos ``days`` dias + aquecimento.
    Calculado uma vez por moeda/timeframe e reaproveitado por todos os bots."""
    return ranking.votes_for(symbol, interval, market, days, get_klines)


def api_key() -> str | None:
    return get_secret("OPENROUTER_API_KEY") or st.session_state.get("_or_key")


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
    for name, value in st.session_state.pop(_k(bot, "__pending"), {}).items():  # mudanças pedidas por botões na execução anterior
        st.session_state[_k(bot, name)] = value
    for name, value in stored.items():
        st.session_state.setdefault(_k(bot, name), value)
    cfg = {name: st.session_state[_k(bot, name)] for name in stored}
    if cfg != stored:
        save_settings(bot, cfg)
    return cfg


def queue_setting(bot: str, **changes) -> None:
    """Muda configurações cujo widget já foi desenhado nesta execução (o Streamlit proíbe alterar o valor de um widget depois
    de criado): salva agora e aplica no início da próxima execução, antes dos widgets."""
    cfg = load_settings(bot)
    cfg.update(changes)
    save_settings(bot, cfg)
    pending = st.session_state.get(_k(bot, "__pending"), {})
    st.session_state[_k(bot, "__pending")] = {**pending, **changes}


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

    st.title(f"{profile.icon} {profile.name}")
    st.caption(f"{profile.market_label} · estilo pelo tempo gráfico: **{style_of(st.session_state.get(_k(bot, 'interval'), cfg['interval']))}** "
               "(até 1h day trade · 2h a 12h swing · 1d ou mais long) · dados reais.")

    execution_banner()

    # Seleção de ativo e timeframe -------------------------------------------
    c1, c2, c3, c4 = st.columns([2, 1.2, 1, 1.2])
    all_symbols = cached_symbols(profile.market)
    options = list(dict.fromkeys([s_ for s_ in SYMBOLS if s_ in all_symbols] + [cfg["symbol"]] + all_symbols))
    c1.selectbox(f"Ativo ({len(all_symbols)} pares em USDT)", options, key=_k(bot, "symbol"), accept_new_options=True,
                 help="Clique e digite para buscar qualquer moeda negociada na Binance "
                      f"{'Futuros' if profile.market == 'futures' else 'Spot'} (ex.: PEPE, SOL, DOGE).")
    if st.session_state[_k(bot, "interval")] not in profile.intervals:
        st.session_state[_k(bot, "interval")] = profile.default_interval
    c2.selectbox("Timeframe", profile.intervals, key=_k(bot, "interval"))
    c3.number_input("Candles", 150, 1500, step=50, key=_k(bot, "candles"))
    c4.selectbox("Atualização (s)", (5, 10, 15, 30, 60, 120, 300, 600), key=_k(bot, "refresh_sec"))
    cfg = {name: st.session_state[_k(bot, name)] for name in cfg}
    cfg["symbol"] = str(cfg["symbol"]).upper().strip()

    live_metrics(profile, cfg)

    # Layout em L, como no terminal da Binance: gráfico no centro, painel de ordem na lateral direita e,
    # embaixo, posições/histórico, controle do bot e configurações.
    col_chart, col_side = st.columns([3.3, 1.2], gap="medium")
    with col_chart:
        indicator_picker(bot, cfg)
        tab_rt, tab_tv, tab_ctl, tab_cfg = st.tabs(["⚡ Tempo real", "🖊️ TradingView — ferramentas de desenho", "🧠 Análise do bot",
                                                     "⚙️ Configurações"])
        with tab_rt:
            positions = [p for p in broker.account()["positions"] if p["symbol"] == cfg["symbol"] and p.get("market") == profile.market]
            height = chart_height(cfg)
            components.html(realtime_chart_html(symbol=cfg["symbol"], interval=cfg["interval"], market=profile.market,
                                                cfg=cfg, lines=realtime_lines(bot, cfg), positions=positions,
                                                height=height), height=height + 5)
        with tab_tv:
            st.caption("Barra lateral esquerda: linhas de tendência, Fibonacci, canais, padrões, régua e as ferramentas "
                       "**Posição comprada / vendida**. Os desenhos ficam no navegador; níveis para a IA ficam em "
                       "*Configurações → Níveis do usuário*.")
            components.html(tradingview_widget(cfg["symbol"], cfg["interval"], profile.market, 720), height=730)
        with tab_ctl:
            analysis_panel(profile, cfg)
        with tab_cfg:
            settings_section(profile, cfg)
    with col_side:
        bot_power(profile, cfg)
        t_order, t_bot = st.tabs(["✍️ Ordem", "🤖 Entrada do bot"])
        with t_order:
            trade_ticket(profile, cfg)
        with t_bot:
            entry_panel(profile, cfg)

    portfolio_section(profile, cfg)


def execution_banner() -> None:
    """Conta em que as ordens são executadas (escolhida na barra lateral)."""
    mode = execution.get_mode()
    st.caption(f"Conta de operação: **{execution.MODES[mode]}**" + (" · ordens simuladas com dados reais." if mode == "simulada" else "")
               + " · troque em **Minha conta**.")
    if (why := execution.orders_problem(mode)):
        st.warning(why)


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
        htf_raw = mtf_raw = None
        if engine.needs_htf(cfg_now):  # personalidade com filtro de tendência dos tempos maiores
            try:
                htf_raw, mtf_raw = engine.htf_frames(
                    lambda s, i, n, m: cached_klines(s, i, n, m), cfg_now, len(raw), profile.market)
            except MarketDataError:
                st.warning("Sem dados do tempo maior: o filtro de tendência bloqueará entradas até voltar.")
        df = engine.prepare(raw, cfg_now, htf_raw, mtf_raw)
        price = ticker.last
        st.session_state[f"{bot}__last_price"] = price
        st.session_state[f"{bot}__atr"] = float(df["atr"].iloc[-2])
        st.session_state[f"{bot}__df"] = df
        st.session_state[f"{bot}__source"] = f"{df.attrs.get('source')} · cotação: {ticker.source}"
        broker = get_broker(bot)
        funding = cached_funding(symbol) if profile.market == "futures" else None
        events = broker.sync(symbol, raw, price, funding)
        for ev in events:
            t = ev.get("trade")
            msg = f"{ev['type']}: {t['side']} {t['symbol']} {t['pnl']:+.2f} USDT" if t else ev["type"]
            st.toast(msg, icon="🔔")
        if events:
            st.session_state[f"{bot}__need_rerun"] = True
        s = broker.stats({symbol: price})

        m = st.columns(6)
        m[0].metric(symbol, fmt_price(price), f"{ticker.change_pct:+.2f}% 24h")
        m[1].metric("Banca", f"{fmt(s['equity'])}", f"{fmt(s['total_pnl'])} ({s['total_pnl_pct']:+.2f}%)",
                    help="Patrimônio da carteira simulada (saldo livre + margens + P&L em aberto), em USDT.")
        m[2].metric("Resultado hoje", fmt(s["pnl_today"]))
        m[3].metric("Operações hoje", f"{s['trades_today']}")
        m[4].metric("P&L aberto (líquido)", fmt(s["unrealized_net"]), f"{s['open_positions']} posição(ões)",
                    delta_color="off", help="Lucro/prejuízo das posições abertas já descontando taxas de entrada e saída.")
        m[5].metric("Taxa de acerto", f"{s['win_rate']:.0f}%", f"{s['trades']} trades", delta_color="off")

        ctx = str(df["regime"].iloc[-2])
        st.session_state[f"{bot}__context"] = ctx
        st.caption(f"🧭 **Contexto do gráfico agora ({interval}):** {regime.label(ctx)} — {regime.REGIMES[ctx][1]}")

        # Posições abertas em outros ativos (abertas pela varredura) também precisam de stop e alvo conferidos
        for ev in scanner.sync_open(profile, cached_klines, cached_ticker, cached_funding, skip={symbol}):
            t = ev.get("trade")
            st.toast(f"{ev['type']}: {t['side']} {t['symbol']} {t['pnl']:+.2f} USDT" if t else ev["type"], icon="🔔")
            st.session_state[f"{bot}__need_rerun"] = True
        auto_scan(profile, cfg_now, df, price)
        if st.session_state.pop(f"{bot}__need_rerun", False):
            st.rerun()  # posição encerrada/ordem executada: atualiza linhas do gráfico e carteira

    _live()


def realtime_lines(bot: str, cfg: dict) -> list[dict]:
    """Linhas de preço do gráfico em tempo real (só mudam quando há ação do
    usuário, para o gráfico não recarregar a cada atualização)."""
    market = PROFILES[bot].market  # o mesmo par existe em futuros e no spot: cada página mostra só as ordens do seu mercado
    acct = get_broker(bot).account()
    lines = []  # a linha de entrada (com P&L ao vivo) é desenhada pelo próprio gráfico
    for p in acct["positions"]:
        if p["symbol"] != cfg["symbol"] or p.get("market") != market:
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
        if o["symbol"] == cfg["symbol"] and o.get("market") == market:
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


def auto_scan(profile: BotProfile, cfg: dict, df: pd.DataFrame, price: float) -> None:
    """No fechamento de cada candle: com o bot ligado faz a varredura (procura oportunidades e opera); desligado, só atualiza a
    leitura do ativo da tela, sem gastar IA."""
    from core.data import last_closed_candle_time

    bot = profile.key
    on = bool(cfg.get("autopilot"))
    marker = f"{cfg['symbol']}-{cfg['interval']}-{last_closed_candle_time(df, cfg['interval'])}-{int(on)}"
    if st.session_state.get(f"{bot}__scan_marker") == marker:
        return
    st.session_state[f"{bot}__scan_marker"] = marker
    if on and (why := execution.orders_problem()):
        st.caption("🤖 Bot em espera: " + why)
    if on and not personalities.allowed(profile.market, cfg["interval"]):
        st.warning("Bot em espera: nenhum bot foi treinado e testado neste tempo gráfico. Troque o tempo gráfico.")
        on = False
    if on and not execution.orders_problem():
        if ranking.is_stale(profile.market, cfg["interval"]):  # a cada 7 dias o ranking é refeito com o mercado recente
            with st.spinner("Atualizando o ranking semanal dos bots…"):
                if engine.ensure_ranking(profile, cfg):
                    st.toast("Ranking semanal dos bots atualizado.", icon="🏆")
        with st.spinner("Procurando oportunidades…"):
            report = scanner.run(profile, cfg, api_key(), klines=cached_klines, ticker=cached_ticker,
                                 funding=cached_funding)
        for ex in report.executed:
            word = {"BUY": "Comprou", "SELL": "Vendeu", "CLOSE": "Encerrou"}[ex["action"]]
            st.toast(f"{word} {ex['symbol']} ({ex['status']})", icon="🤖")
    else:  # bot desligado: só a leitura do ativo da tela (regras, sem IA)
        res = engine.run_analysis(profile, cfg, df, price, None, log=False)
        report = scanner.ScanReport(time=res.time, interval=cfg["interval"], scanned=1, viewed=res)
    st.session_state[f"{bot}__scan"] = report
    st.session_state[f"{bot}__need_rerun"] = True


# ------------------------------------------------------- boleta de entrada
ENTRY_KEYS = ("leverage_on", "leverage", "margin_mode", "risk_mode", "max_loss_usdt", "max_loss_pct", "atr_sl_mult", "atr_tp_mult",
              "allow_short")


def entry_panel(profile: BotProfile, cfg: dict) -> None:
    """Configurações com que o bot entra no mercado: tamanho pelo risco, stop/alvo, alavancagem e margem."""
    bot = profile.key
    k = lambda n: _k(bot, n)  # noqa: E731
    c = st.columns([1.2, 1])
    c[0].radio("Perda máxima por trade", ["% do saldo", "USDT"], key=k("risk_mode"), horizontal=True,
               help="Quanto a banca perde se o stop for atingido. O tamanho da posição é calculado a partir dele (já com as taxas).")
    if st.session_state[k("risk_mode")] == "USDT":
        c[1].number_input("USDT por trade", 1.0, 1e6, step=5.0, key=k("max_loss_usdt"))
    else:
        c[1].number_input("% do patrimônio", 0.1, 20.0, step=0.1, key=k("max_loss_pct"))
    c = st.columns(2)
    c[0].number_input("Stop = ATR ×", 0.5, 10.0, step=0.1, key=k("atr_sl_mult"),
                      help="Usado nas entradas sem stop próprio. Cada bot do ranking tem o seu stop/alvo testado; este vale para a boleta manual.")
    c[1].number_input("Alvo = ATR ×", 0.5, 30.0, step=0.5, key=k("atr_tp_mult"))
    if profile.market == "futures":
        leverage_controls(profile, cfg)
        st.toggle("Permitir operações vendidas (short)", key=k("allow_short"))
    else:
        st.caption("Spot: compra e venda à vista com o seu saldo, sem alavancagem, margem ou venda a descoberto.")

    cfg = {**cfg, **{n: st.session_state[k(n)] for n in ENTRY_KEYS}}
    price, atr_v = st.session_state.get(f"{bot}__last_price"), st.session_state.get(f"{bot}__atr")
    if not price or not atr_v:
        return
    s = get_broker(bot).stats({cfg["symbol"]: price})
    sl, tp = price - atr_v * float(cfg["atr_sl_mult"]), price + atr_v * float(cfg["atr_tp_mult"])
    calc = risk.calculate("BUY", price, sl, tp, leverage=risk.effective_leverage(cfg), fee_pct=float(cfg["fee_pct"]),
                          risk_usdt=risk.risk_budget(cfg, s["equity"]), available=s["available"], symbol=cfg["symbol"],
                          market=profile.market, margin_mode=cfg["margin_mode"])
    st.caption(f"Uma compra agora a {fmt_price(price)} teria {calc.qty:g} {cfg['symbol'].removesuffix('USDT')} · margem "
               f"{fmt(calc.margin)} USDT ({calc.leverage:g}×) · risco {fmt(calc.risk_usdt)} USDT · retorno {fmt(calc.reward_usdt)} USDT · "
               f"R:R {fmt(calc.rr) if calc.rr else '—'}. Sem bloqueio por metas ou limites diários.")


def trade_ticket(profile: BotProfile, cfg: dict) -> None:
    """Boleta manual: ordem a mercado ou limitada com a calculadora de risco."""
    bot = profile.key
    price = st.session_state.get(f"{bot}__last_price")
    atr_v = st.session_state.get(f"{bot}__atr")
    if not price:
        st.info("Carregando cotação…")
        return
    broker = get_broker(bot)
    s = broker.stats({cfg["symbol"]: price})

    cfg = {**cfg, **{n: st.session_state[_k(bot, n)] for n in ENTRY_KEYS}}
    lev = risk.effective_leverage(cfg)
    can_short = profile.market == "futures" and cfg["allow_short"]
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
        c1.markdown(f"Stop  \n**:red[{fmt_price(sl)}]**")
        c2.markdown(f"Alvo  \n**:green[{fmt_price(tp)}]**")
    else:
        sl = c1.number_input("Stop loss", value=float(risk.round_price(sl_default, price)), format="%.6f", key=f"{bot}__t_sl")
        tp = c2.number_input("Take profit", value=float(risk.round_price(tp_default, price)), format="%.6f", key=f"{bot}__t_tp")

    sizing = st.radio("Tamanho por", ["Perda máxima", "Valor (margem)"], horizontal=True, key=f"{bot}__t_sizing")
    budget = risk.risk_budget(cfg, s["equity"])
    if sizing == "Perda máxima":
        risk_usdt = st.number_input("Perda máxima no trade (USDT)", min_value=0.0, value=float(round(budget, 2)),
                                    step=5.0, key=f"{bot}__t_risk")
        calc = risk.calculate(side, entry, sl, tp, leverage=lev, fee_pct=float(cfg["fee_pct"]),
                              risk_usdt=risk_usdt, available=s["available"], symbol=cfg["symbol"],
                              market=profile.market, margin_mode=cfg["margin_mode"])
    else:
        margin = st.number_input("Margem a alocar (USDT)", min_value=0.0, value=float(min(500.0, s["available"])),
                                 step=50.0, key=f"{bot}__t_margin")
        calc = risk.calculate(side, entry, sl, tp, leverage=lev, fee_pct=float(cfg["fee_pct"]),
                              margin_usdt=margin, available=s["available"], symbol=cfg["symbol"],
                              market=profile.market, margin_mode=cfg["margin_mode"])

    m1, m2 = st.columns(2)
    m1.markdown(f"Quantidade  \n**{calc.qty:g}**")
    m2.markdown(f"Nocional  \n**{fmt(calc.notional)}** USDT")
    m1.markdown(f"Risco (stop)  \n**:red[−{fmt(calc.risk_usdt)}]** USDT ({fmt(calc.stop_pct)}%)")
    m2.markdown(f"Retorno (alvo)  \n**:green[+{fmt(calc.reward_usdt)}]** USDT ({fmt(calc.tp_pct)}%)")
    st.caption(f"R:R {fmt(calc.rr) if calc.rr else '—'} · margem {fmt(calc.margin)} USDT ({calc.leverage:g}×) · taxas {fmt(calc.fees_usdt)} · "
               f"break-even {fmt_price(calc.breakeven)}" + (f" · liquidação {fmt_price(calc.liquidation)}" if calc.liquidation else ""))
    for w in calc.warnings:
        st.warning(w)

    blocked = execution.orders_problem()
    if st.button(f"Enviar ordem — {'COMPRAR' if side == 'BUY' else 'VENDER'}", type="primary",
                 width="stretch", key=f"{bot}__t_send", disabled=calc.qty <= 0 or bool(blocked)):
        check = risk.check_trade(cfg, s, side, entry, sl, tp, profile.market)
        if check.reasons:
            for r in check.reasons:
                st.error(r)
        else:
            for n in check.notes:
                st.info(n)
            try:
                out = broker.place_order(symbol=cfg["symbol"], market=profile.market, side=side, qty=calc.qty,
                                         order_type="LIMIT" if otype == "Limitada" else "MARKET", price=price,
                                         limit_price=entry if otype == "Limitada" else None, stop_loss=sl,
                                         take_profit=tp, leverage=lev, fee_pct=float(cfg["fee_pct"]),
                                         slippage_pct=float(cfg["slippage_pct"]), source="manual",
                                         max_loss_planned=calc.risk_usdt, margin_mode=cfg["margin_mode"], fx=calc.fx)
                st.success(f"Ordem {out['status'].lower()}.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    if blocked:
        st.caption(blocked)


def leverage_controls(profile: BotProfile, cfg: dict) -> None:
    """Alavancagem e modo de margem na boleta, com os limites da Binance."""
    bot = profile.key
    futures = profile.market == "futures"
    c1, c2 = st.columns([1, 1.2])
    c1.toggle("Alavancado", key=_k(bot, "leverage_on"), help="Alavancagem do contrato perpétuo.")
    c2.radio("Margem", ["Isolada", "Cruzada"], key=_k(bot, "margin_mode"), horizontal=True,
             help="Isolada: o risco fica limitado à margem da posição. Cruzada: todo o saldo livre "
                  "sustenta a posição (liquidação mais distante, mas pode perder mais).")
    mode = st.session_state[_k(bot, "margin_mode")]
    if futures:
        tiers, source = cached_brackets(cfg["symbol"])
        max_lev = tiers[0].max_leverage
    else:
        max_lev, source = lev_rules.SPOT_MARGIN_MAX[mode], "Binance Margin"
    key = _k(bot, "leverage")
    st.session_state[key] = int(min(max(1, st.session_state.get(key, 1)), max_lev))
    if st.session_state.get(_k(bot, "leverage_on")):
        st.slider(f"Alavancagem (máx. {max_lev}× em {cfg['symbol'] if futures else mode})", 1, max_lev, key=key,
                  help=f"Limite conforme a tabela da {source}. Em futuros, a posição máxima diminui conforme "
                       "a alavancagem — veja Configurações → Alavancagem.")
    else:
        st.caption("Sem alavancagem (1×)" + ("" if futures else " — compra à vista com saldo próprio."))


# ------------------------------------------------------------------- bot automático
def bot_power(profile: BotProfile, cfg: dict) -> None:
    """Liga/desliga o bot (no topo do painel lateral)."""
    bot = profile.key
    on = bool(cfg.get("autopilot"))
    blocked = not personalities.allowed(profile.market, cfg["interval"])
    st.markdown("🟢 **Bot ligado**" if on else "⚪ **Bot desligado**")
    if st.button("⏹️ Desligar" if on else "▶️ Ligar o bot", type="secondary" if on else "primary", width="stretch",
                 key=f"{bot}__power", disabled=blocked and not on,
                 help="Ligado, o bot analisa os ativos da varredura a cada candle fechado e opera sozinho."):
        set_setting(bot, "autopilot", not on)
        st.session_state.pop(f"{bot}__scan_marker", None)
        st.rerun()
    if blocked:
        trained = personalities.trained_intervals(profile.market)
        st.caption(f"Nenhum bot treinado no {cfg['interval']}. Tempos com bots: {', '.join(trained) or '—'}.")


def analysis_panel(profile: BotProfile, cfg: dict) -> None:
    """Resumo automático do que o bot enxerga: um único bloco simples, com os detalhes técnicos recolhidos."""
    bot = profile.key
    rep = st.session_state.get(f"{bot}__scan")
    if rep is None or rep.viewed is None:
        st.info("A leitura aparece em instantes, no fechamento do candle.")
        return
    res, d = rep.viewed, rep.viewed.decision
    adv = d.advice or {}
    on = bool(cfg.get("autopilot"))
    with st.container(border=True):
        head = {"BUY": "🟢 Oportunidade de compra", "SELL": "🔴 Oportunidade de venda", "HOLD": "⚪ Sem oportunidade agora",
                "CLOSE": "🟠 Sinal contrário: encerrando a posição"}[d.decision]
        bot_name = (res.personality or {}).get("name")
        st.markdown(f"### {head} em {res.symbol} · {res.interval}")
        if bot_name:
            st.caption(f"Bot do momento: {bot_name}")
        st.markdown(adv.get("resumo") or adv.get("cenario") or d.reasoning)
        if adv.get("dica"):
            st.info("💡 " + adv["dica"])
        if d.decision in ("BUY", "SELL") and res.check and res.check.calc:
            c = res.check.calc
            st.caption(f"Entrada {fmt_price(d.entry or res.price)} · stop {fmt_price(d.stop_loss)} · alvo {fmt_price(d.take_profit)} · "
                       f"{c.qty:g} unidades · risco {fmt(c.risk_usdt)} USDT")
        for ex in rep.executed:
            word = {"BUY": "Comprou", "SELL": "Vendeu", "CLOSE": "Encerrou posição em"}[ex["action"]]
            st.success(f"✅ {word} {ex['symbol']} ({ex['status']})")
    when = res.time[11:16] + " UTC" if res.time else ""
    if on:
        names = ", ".join(sorted({o.symbol for o in rep.opportunities})) or "nenhuma"
        st.caption(f"Última varredura {when}: {rep.scanned} ativo(s) analisados no {rep.interval} · oportunidades: {names}.")
    else:
        st.caption(f"Bot desligado: leitura só do ativo na tela ({when}), sem usar a IA. Ligue o bot para ele procurar oportunidades sozinho.")
    for note in rep.notes[:3]:
        st.caption("⚠️ " + note)
    with st.expander("Detalhes técnicos"):
        st.write(d.reasoning)
        if adv.get("leitura_tecnica"):
            st.markdown("\n".join(f"- {x}" for x in adv["leitura_tecnica"]))
        persona = personalities.get((res.personality or {}).get("id"))
        weights = (persona or {}).get("skills") or profile.skill_weights
        skills = res.plan.get("skills")
        if skills:
            st.dataframe(pd.DataFrame([{"Habilidade": sk["name"], "Voto": round(sk["vote"], 2), "Peso": weights.get(sk["key"], 1.0),
                                        "Leitura": sk["detail"]} for sk in skills]), hide_index=True,
                         column_config={"Voto": st.column_config.ProgressColumn(min_value=-1, max_value=1, format="%.2f")})
    if rep.opportunities:
        st.markdown("**Oportunidades da última varredura**")
        st.dataframe(pd.DataFrame([{"Ativo": o.symbol, "Lado": "Compra" if o.decision.decision == "BUY" else "Venda",
                                    "Bot": (o.personality or {}).get("name", ""), "Entrada": o.decision.entry or o.price,
                                    "Stop": o.decision.stop_loss, "Alvo": o.decision.take_profit} for o in rep.opportunities]),
                     hide_index=True)


# ------------------------------------------------------------- carteira
def portfolio_section(profile: BotProfile, cfg: dict) -> None:
    bot = profile.key
    broker = get_broker(bot)
    acct = broker.account()
    price = st.session_state.get(f"{bot}__last_price", 0)
    t1, t2, t3, t4, t5 = st.tabs(["Posições abertas", "Ordens pendentes", "Histórico", "Curva de patrimônio", "Log de decisões"])
    with t1:
        open_positions(profile, cfg)
    with t2:
        orders = [o for o in acct["orders"] if o.get("market") == profile.market]
        if not orders:
            st.caption("Nenhuma ordem pendente.")
        for o in orders:
            c = st.columns([4, 1])
            c[0].write(f"LIMIT {o['side']} {o['qty']:g} {o['symbol']} @ {fmt_price(o['limit_price'])} · "
                       f"SL {fmt_price(o['stop_loss'])} · TP {fmt_price(o['take_profit'])} · {o['source']}")
            if c[1].button("Cancelar", key=f"{bot}_cancel_{o['id']}"):
                broker.cancel_order(o["id"])
                st.rerun()
    with t3:
        history = [t for t in acct["history"] if t.get("market", profile.market) == profile.market]
        if history:
            hist = pd.DataFrame(history).reindex(columns=[
                "closed", "bot", "symbol", "side", "qty", "entry", "exit", "leverage", "reason", "pnl",
                "pnl_pct_margin", "fees_total", "source"]).iloc[::-1]
            hist["bot"] = hist["bot"].map(lambda b: PROFILES[b].name if b in PROFILES else "")
            hist["closed"] = pd.to_datetime(hist["closed"]).dt.tz_convert("America/Sao_Paulo").dt.strftime("%d/%m %H:%M")
            st.dataframe(hist, hide_index=True, column_config={
                "closed": "Encerrado", "bot": "Bot", "symbol": "Ativo", "side": "Lado", "qty": "Qtd.", "entry": "Entrada",
                "exit": "Saída", "leverage": "Alav.", "reason": "Motivo",
                "pnl": st.column_config.NumberColumn("P&L (USDT)", format="%.2f"),
                "pnl_pct_margin": st.column_config.NumberColumn("% margem", format="%.1f%%"),
                "fees_total": st.column_config.NumberColumn("Taxas", format="%.2f"), "source": "Origem"})
            s = broker.stats({cfg["symbol"]: price})
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


def position_details(p: dict, price_now: float) -> dict:
    """Números da posição aberta (USDT): margem, liquidação, taxas e resultado líquido no stop e no alvo."""
    fx, fee = p.get("fx", 1.0), p["fee_pct"] / 100
    fees_open = float(p.get("fees_paid", 0.0))

    def net_at(price):
        return paper.pnl_of(p, price) - fees_open - price * p["qty"] * fx * fee

    return {"margin": p["margin"], "liquidation": p.get("liquidation"), "fees_open": fees_open,
            "fees_close": price_now * p["qty"] * fx * fee, "notional": price_now * p["qty"] * fx,
            "loss_sl": net_at(p["stop_loss"]) if p.get("stop_loss") else None,
            "gain_tp": net_at(p["take_profit"]) if p.get("take_profit") else None}


def open_positions(profile: BotProfile, cfg: dict) -> None:
    """Cards das posições abertas, com P&L atualizado automaticamente."""

    @st.fragment(run_every=int(cfg["refresh_sec"]))
    def _cards():
        bot = profile.key
        broker = get_broker(bot)
        acct = broker.account()
        price = st.session_state.get(f"{bot}__last_price", 0)
        positions = [p for p in acct["positions"] if p.get("market") == profile.market]
        if not positions:
            st.caption("Nenhuma posição aberta.")
        for p in positions:
            p_price = price if p["symbol"] == cfg["symbol"] else _safe_price(p["symbol"], profile.market) or p["entry"]
            gross = paper.pnl_of(p, p_price)
            net = gross - p["fees_paid"] - p_price * p["qty"] * p.get("fx", 1.0) * p["fee_pct"] / 100
            with st.container(border=True):
                c = st.columns([1.6, 1, 1.1, 1, 1, 1.2, 1])
                bot_name = PROFILES[p["bot"]].name if p.get("bot") in PROFILES else ""
                c[0].markdown(f"**{'🟢 COMPRA' if p['side'] == 'BUY' else '🔴 VENDA'} {p['symbol']}**  \n"
                              f"{p['qty']:g} @ {fmt_price(p['entry'])} · {p['leverage']:g}× {p.get('margin_mode', '')}"
                              f"  \n{bot_name} · {'você' if p['source'] == 'manual' else 'bot (' + p['source'] + ')'}")
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
                d = position_details(p, p_price)
                m = st.columns(6)
                m[0].metric("Margem", fmt(d["margin"]), help="Valor do seu saldo travado nesta posição (USDT).")
                m[1].metric("Preço de liquidação", fmt_price(d["liquidation"]) if d["liquidation"] else "—",
                            help="Se o preço chegar aqui, a margem é perdida. Sem alavancagem não há liquidação.")
                m[2].metric("Taxas", fmt(d["fees_open"] + d["fees_close"]),
                            help=f"Já paga na entrada: {fmt(d['fees_open'])} USDT · estimada na saída: {fmt(d['fees_close'])} USDT.")
                m[3].metric("Perda no stop", fmt(d["loss_sl"]) if d["loss_sl"] is not None else "sem stop",
                            help="Resultado líquido (já com as taxas) se o stop for atingido.")
                m[4].metric("Ganho no alvo", fmt(d["gain_tp"]) if d["gain_tp"] is not None else "sem alvo",
                            help="Resultado líquido (já com as taxas) se o alvo for atingido.")
                m[5].metric("Valor da posição", fmt(d["notional"]), help="Quantidade × preço atual (USDT).")

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
    futures = profile.market == "futures"
    labels = (["Alavancagem"] if futures else []) + ["Varredura", "Indicadores", "IA", "Níveis do usuário", "Conta"]
    tabs = dict(zip(labels, st.tabs(labels)))
    t_scan, t_ind, t_ai, t_lv, t_acct = (tabs[n] for n in labels[-5:])

    with t_scan:
        st.toggle("🔎 Procurar oportunidades em várias moedas", key=k("scan_on"),
                  help="Com o bot ligado, a cada candle fechado ele sorteia moedas de maior volume do mercado (futuros ou spot, conforme esta "
                       "página), analisa os últimos 120 candles fechados de cada uma no tempo gráfico atual (só com regras, sem gastar IA), "
                       "escolhe sozinho o melhor bot do ranking para o contexto de cada uma e entra nas melhores oportunidades. "
                       "Desligado, opera só a moeda da tela.")
        off = not st.session_state[k("scan_on")]
        c = st.columns(4)
        c[0].number_input("Moedas por varredura", 1, 100, key=k("scan_count"), disabled=off,
                          help="Padrão 15. A moeda da tela entra sempre; as demais são sorteadas. Mais moedas = mais oportunidades, "
                               "mas a varredura demora mais.")
        c[1].number_input("Sorteio entre as N de maior volume", 10, 200, step=10, key=k("scan_pool"), disabled=off,
                          help="Volume negociado nas últimas 24 h neste mercado (moedas estáveis ficam de fora).")
        c[2].number_input("Bots testados por moeda", 1, 10, key=k("scan_bots"), disabled=off,
                          help="Em cada moeda o sistema lê o contexto e testa, em ordem, os melhores bots do ranking para ele até um "
                               "dar sinal. Mais bots = mais chances de achar entrada, mas a varredura demora mais.")
        c[3].number_input("Entradas novas por varredura", 1, 10, key=k("scan_max_entries"), disabled=off,
                          help="Quantas das melhores oportunidades o bot abre a cada candle fechado. No máximo uma posição por moeda.")
        st.caption("A IA é consultada só para a melhor oportunidade de cada varredura (e só quando o bot encontra uma), "
                   "para economizar tokens. Sem oportunidade, nada é enviado à IA.")

    with t_ind:
        st.caption("Ligue/desligue só a **exibição no gráfico**. O bot e a IA leem **todos** os indicadores (médias, RSI, MACD, Bollinger, "
                   "ADX, Estocástico, OBV, VWAP, SuperTrend, Ichimoku, suportes/resistências, pivôs e Fibonacci) mesmo desligados aqui.")
        c = st.columns(4)
        with c[0]:
            st.markdown("**Tendência**")
            st.checkbox("Médias móveis (EMA rápida e lenta)", key=k("ema_on"))
            st.number_input("EMA rápida", 2, 200, key=k("ema_fast"))
            st.number_input("EMA lenta", 3, 400, key=k("ema_slow"))
            st.checkbox("EMA de tendência", key=k("ema_trend_on"))
            st.number_input("EMA de tendência (período)", 20, 400, key=k("ema_trend"))
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
        if not get_secret("OPENROUTER_API_KEY"):  # sem chave nos Secrets: informe aqui (vale para todas as páginas, só nesta sessão)
            def _save_key():
                st.session_state["_or_key"] = st.session_state[f"{bot}__or_key_w"]

            st.text_input("Chave da OpenRouter (somente nesta sessão)", type="password", key=f"{bot}__or_key_w",
                          value=st.session_state.get("_or_key", ""), on_change=_save_key,
                          help="Para não digitar sempre, defina OPENROUTER_API_KEY nos Secrets do Streamlit.")
        st.selectbox("Personalidade da IA (tom das explicações)", list(ai_mod.AI_PERSONAS), key=k("ai_persona"),
                     format_func=lambda i: ai_mod.AI_PERSONAS[i][0], help=None)
        st.caption(ai_mod.AI_PERSONAS[st.session_state.get(k("ai_persona"), ai_mod.DEFAULT_PERSONA)][1])
        st.toggle("Deixar a IA interferir na decisão de ativar o bot", key=k("ai_intervene"),
                  help="Desligado (padrão): a IA só explica resumidamente o que acontece no mercado e dá uma dica útil sobre o "
                       "contexto; o bot entra quando as regras do bot do momento dão sinal. Ligado: no fechamento do candle a IA "
                       "também confirma ou veta o sinal — se discordar, o bot não entra naquele momento. Sem sinal das regras, "
                       "a IA nunca abre operação sozinha.")
        c[1].slider("Temperatura", 0.0, 1.0, step=0.05, key=k("ai_temperature"))
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
        c = st.columns(2)
        c[0].number_input("Taxa por lado (%)", 0.0, 1.0, step=0.01, format="%.3f", key=k("fee_pct"))
        c[1].number_input("Slippage simulado (%)", 0.0, 1.0, step=0.01, format="%.3f", key=k("slippage_pct"))
        st.write("A banca, os aportes/retiradas, o extrato e o histórico completo ficam na página **Carteira**.")
        st.page_link("views/wallet.py", label="Abrir Carteira simulada", icon="💰")
        if st.button("Restaurar configurações padrão deste bot", key=f"{bot}__defaults"):
            defaults = default_settings(profile)
            save_settings(bot, defaults)
            for name in defaults:
                st.session_state.pop(_k(bot, name), None)
            st.rerun()
