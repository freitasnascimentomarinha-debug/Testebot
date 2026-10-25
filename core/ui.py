"""Interface Streamlit compartilhada pelas três páginas de bot."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from core import nav as nav_mod, ai as ai_mod, analysis_view, chart_actions, ticket_view, engine, execution, paper, personalities, positions_view, ranking, regime, risk, scanner
from core.broker import get_broker
from core import leverage as lev_rules
from core.data import MarketDataError, get_funding_rate, get_klines, get_ticker, list_symbols
from core.profiles import PROFILES, SYMBOLS, BotProfile, style_of
from core import indicators as ind
from core.realtime import chart_height, realtime_chart_html
from core.settings import DEFAULT_MODEL, FORCED as FORCED_SETTINGS, default_settings, load_settings, save_settings
from core.storage import get_secret, load_json

# Seletor rápido de indicadores → chaves de configuração (as mesmas da aba Indicadores)
INDICATOR_FLAGS = {
    "Médias móveis (EMA rápida e lenta)": "ema_on", "EMA de tendência (200)": "ema_trend_on",
    "Bandas de Bollinger": "bb_on", "VWAP": "vwap_on", "SuperTrend": "supertrend_on",
    "Volume": "volume_on", "RSI": "rsi_on", "MACD": "macd_on", "Estocástico": "stoch_on", "ADX / DMI": "adx_on",
    "OBV": "obv_on", "Suportes e resistências": "sr_on", "Pivôs": "pivots_on", "Fibonacci": "fib_on",
    "Ichimoku (só na análise técnica)": "ichimoku_on",
}



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
    for name, value in FORCED_SETTINGS.items():   # não são mais escolhas do usuário (vale também para sessões abertas antes)
        st.session_state[_k(bot, name)] = value
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

    nav_mod.ticker_strip(bot, profile.market, str(cfg["symbol"]).upper())
    header_slot = st.container()   # o cabeçalho é desenhado pelo fragmento ao vivo, mas ocupa o topo da página
    execution_banner()

    # Ativo: clique no nome da moeda dentro do gráfico; tempo gráfico: botões do cabeçalho; candles e atualização: Configurações → Gráfico
    all_symbols = cached_symbols(profile.market)
    if st.session_state[_k(bot, "interval")] not in profile.intervals:
        st.session_state[_k(bot, "interval")] = profile.default_interval
    cfg = {name: st.session_state[_k(bot, name)] for name in cfg}
    cfg["symbol"] = str(cfg["symbol"]).upper().strip()

    with header_slot:
        live_metrics(profile, cfg)

    # Layout em L, como no terminal da Binance: gráfico no centro, painel de ordem na lateral direita e,
    # embaixo, posições/histórico, controle do bot e configurações.
    col_chart, col_side = st.columns([3.3, 1.2], gap="medium")
    with col_chart:
        tab_rt, tab_book, tab_ctl, tab_cfg = st.tabs(["⚡ Tempo real", "📖 Book de ordens", "🧠 Análise do bot", "⚙️ Configurações"])
        with tab_rt:
            positions = [p for p in broker.account()["positions"] if p["symbol"] == cfg["symbol"] and p.get("market") == profile.market]
            height = chart_height(cfg)
            orders = [o for o in broker.account()["orders"] if o["symbol"] == cfg["symbol"] and o.get("market") == profile.market]
            components.html(realtime_chart_html(symbol=cfg["symbol"], interval=cfg["interval"], market=profile.market,
                                                cfg=cfg, lines=realtime_lines(bot, cfg), positions=positions, orders=orders,
                                                height=height, symbols=all_symbols), height=height + 5)
        with tab_book:
            _book_component()(key=f"{bot}-book", data={"symbol": cfg["symbol"], "market": profile.market})
        with tab_ctl:
            analysis_panel(profile, cfg)
        with tab_cfg:
            settings_section(profile, cfg)
    with col_side:
        bot_power(profile, cfg)
        t_order, t_bot = st.tabs(["✍️ Ordem", "🤖 Entrada do bot"])
        with t_order:
            ticket_panel(profile, cfg)
        with t_bot:
            entry_panel(profile, cfg)

    portfolio_section(profile, cfg)
    chart_bridge(profile, cfg)


CHART_BRIDGE_JS = """
export default function (component) {
  const { setTriggerValue } = component;
  // O gráfico (iframe) avisa a página por postMessage; aqui o aviso vira um valor para o Python, que valida tudo antes de agir.
  const onMessage = (e) => { const d = e.data; if (d && d.tb === 1 && typeof d.kind === 'string') setTriggerValue('chart', d); };
  window.addEventListener('message', onMessage);
  return () => window.removeEventListener('message', onMessage);
}
"""


@st.cache_resource(show_spinner=False)
def _chart_bridge():
    return st.components.v2.component("tb_chart_bridge", js=CHART_BRIDGE_JS)


def chart_bridge(profile: BotProfile, cfg: dict) -> None:
    """Recebe e executa os pedidos feitos no gráfico (ordem limite, mover stop/alvo, zerar, cancelar)."""
    bot = profile.key
    res = _chart_bridge()(key=f"{bot}-chart-bridge", on_chart_change=lambda: None)
    ev = getattr(res, "chart", None)
    if not ev or ev.get("uid") == st.session_state.get(f"{bot}__chart_uid"):
        return
    st.session_state[f"{bot}__chart_uid"] = ev.get("uid")
    if ev.get("kind") == "symbol":   # moeda escolhida no próprio gráfico
        sym = str(ev.get("value", "")).upper().strip()
        if sym in cached_symbols(profile.market) and sym != cfg["symbol"]:
            set_setting(bot, "symbol", sym)
            st.rerun()
        return
    ok, msg = chart_actions.handle(profile, cfg, ev, st.session_state.get(f"{bot}__last_price"), st.session_state.get(f"{bot}__atr"))
    if msg:
        st.toast(msg, icon="✅" if ok else "🚫")
    if ok:
        st.rerun()


def execution_banner() -> None:
    """Aviso quando a conta de operação escolhida não pode enviar ordens (a conta em uso aparece no cabeçalho)."""
    if (why := execution.orders_problem(execution.get_mode())):
        st.warning(why)


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

        ctx = str(df["regime"].iloc[-2])
        st.session_state[f"{bot}__context"] = ctx
        mode = execution.get_mode()
        hdr = {"icon": profile.icon, "name": profile.name, "market_label": profile.market_label, "style": style_of(interval),
               "account": execution.MODES[mode], "account_real": mode == "exchange_real", "intervals": list(profile.intervals),
               "interval": interval, "symbol": symbol,
               "context": {"label": regime.label(ctx), "desc": regime.REGIMES[ctx][1]},
               "metrics": {"price": price, "change_pct": ticker.change_pct, "equity": s["equity"], "total_pnl": s["total_pnl"],
                           "total_pnl_pct": s["total_pnl_pct"], "pnl_today": s["pnl_today"], "trades_today": s["trades_today"],
                           "unrealized_net": s["unrealized_net"], "open_positions": s["open_positions"], "win_rate": s["win_rate"],
                           "trades": s["trades"]}}
        res = _header_component()(key=f"{bot}-header", data=hdr, on_interval_change=lambda: None)
        ev = getattr(res, "interval", None)
        if ev and ev.get("uid") != st.session_state.get(f"{bot}__hdr_uid"):
            st.session_state[f"{bot}__hdr_uid"] = ev.get("uid")
            if ev.get("value") in profile.intervals:
                set_setting(bot, "interval", ev["value"])
                st.rerun(scope="app")

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
    lines = []  # entrada, stop, alvo e liquidação das posições e as ordens limitadas são desenhados pelo próprio gráfico (arrastáveis)
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
    """Varredura por tempo: com o bot ligado, a cada ``scan_minutes`` (padrão 15) procura oportunidades em várias moedas e opera.
    Abrir a página ou trocar de moeda/tempo gráfico não varre nada: só atualiza a leitura do ativo da tela (regras, sem IA)."""
    from core.data import last_closed_candle_time

    bot = profile.key
    on = bool(cfg.get("autopilot"))
    if on and (why := execution.orders_problem()):
        st.caption("🤖 Bot em espera: " + why)
        on = False
    if on and not personalities.allowed(profile.market, cfg["interval"]):
        st.warning("Bot em espera: nenhum bot foi treinado e testado neste tempo gráfico. Troque o tempo gráfico.")
        on = False
    minutes = float(cfg.get("scan_minutes") or scanner.DEFAULT_MINUTES)
    if on and scanner.claim(bot, minutes):
        if ranking.is_stale(profile.market, cfg["interval"]):  # a cada 7 dias o ranking é refeito com o mercado recente
            with st.spinner("Atualizando o ranking semanal dos bots…"):
                if engine.ensure_ranking(profile, cfg):
                    st.toast("Ranking semanal dos bots atualizado.", icon="🏆")
        with st.spinner("Procurando oportunidades…"):
            report = scanner.run(profile, cfg, api_key(), klines=cached_klines, ticker=cached_ticker, funding=cached_funding)
        for ex in report.executed:
            word = {"BUY": "Comprou", "SELL": "Vendeu", "CLOSE": "Encerrou"}[ex["action"]]
            st.toast(f"{word} {ex['symbol']} ({ex['status']})", icon="🤖")
        st.session_state[f"{bot}__scan"] = report
        st.session_state[f"{bot}__view_marker"] = f"{cfg['symbol']}-{cfg['interval']}-{last_closed_candle_time(df, cfg['interval'])}"
        st.session_state[f"{bot}__need_rerun"] = True
        return
    # sem varredura agora: a leitura do ativo da tela se renova a cada candle fechado ou ao trocar de moeda/tempo (só regras)
    marker = f"{cfg['symbol']}-{cfg['interval']}-{last_closed_candle_time(df, cfg['interval'])}"
    if st.session_state.get(f"{bot}__view_marker") == marker and st.session_state.get(f"{bot}__scan") is not None:
        return
    st.session_state[f"{bot}__view_marker"] = marker
    res = engine.run_analysis(profile, cfg, df, price, None, log=False)
    old = st.session_state.get(f"{bot}__scan")
    report = scanner.ScanReport(time=res.time, interval=cfg["interval"], scanned=1, viewed=res)
    if old is not None and old.interval == cfg["interval"]:   # mantém o resultado da última varredura de verdade
        report.scanned, report.opportunities, report.executed, report.notes = old.scanned, old.opportunities, old.executed, old.notes
        report.scan_time, report.exit_views = getattr(old, "scan_time", ""), getattr(old, "exit_views", [])
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
    held = (f"investiria {fmt(calc.notional)} USDT" if profile.market == "spot" else f"usaria margem de {fmt(calc.margin)} USDT ({calc.leverage:g}×)")
    st.caption(f"Uma compra agora a {fmt_price(price)} teria {calc.qty:g} {cfg['symbol'].removesuffix('USDT')} · {held} · "
               f"risco {fmt(calc.risk_usdt)} USDT · retorno {fmt(calc.reward_usdt)} USDT · "
               f"R:R {fmt(calc.rr) if calc.rr else '—'}. Sem bloqueio por metas ou limites diários.")


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
                       "a alavancagem.")
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
        if not on:
            scanner.reset(bot)   # ao ligar, a primeira varredura é na hora; depois, a cada scan_minutes
        st.rerun()
    if blocked:
        trained = personalities.trained_intervals(profile.market)
        st.caption(f"Nenhum bot treinado no {cfg['interval']}. Tempos com bots: {', '.join(trained) or '—'}.")


_AN_JS = Path(__file__).with_name("analysis.js").read_text(encoding="utf-8")
_AN_CSS = Path(__file__).with_name("analysis.css").read_text(encoding="utf-8")


@st.cache_resource(show_spinner=False)
def _analysis_component():
    return st.components.v2.component("tb_analysis", css=_AN_CSS, js=_AN_JS)


def analysis_panel(profile: BotProfile, cfg: dict) -> None:
    """O que o bot enxerga agora: placar e fatos medidos, o que falta para agir, decisões da IA sobre saídas e a varredura."""
    bot = profile.key
    minutes = float(cfg.get("scan_minutes") or scanner.DEFAULT_MINUTES)
    data = analysis_view.view(profile, cfg, st.session_state.get(f"{bot}__scan"), on=bool(cfg.get("autopilot")),
                              next_at=scanner.next_scan(bot, minutes))
    _analysis_component()(key=f"{bot}-analysis", data={"analysis": data})


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
            spot = profile.market == "spot"
            hist = pd.DataFrame(history).reindex(columns=[
                "closed", "personality_name", "symbol", "side", "qty", "entry", "exit"] + ([] if spot else ["leverage"]) + ["reason", "pnl",
                "pnl_pct_margin", "fees_total", "source"]).iloc[::-1]
            hist["personality_name"] = hist["personality_name"].fillna("")
            hist["closed"] = pd.to_datetime(hist["closed"]).dt.tz_convert("America/Sao_Paulo").dt.strftime("%d/%m %H:%M")
            st.dataframe(hist, hide_index=True, column_config={
                "closed": "Encerrado", "personality_name": "Quem deu a entrada", "symbol": "Ativo", "side": "Lado", "qty": "Qtd.",
                "entry": "Entrada", "exit": "Saída", "leverage": "Alav.", "reason": "Motivo",
                "pnl": st.column_config.NumberColumn("P&L (USDT)", format="%.2f"),
                "pnl_pct_margin": st.column_config.NumberColumn("% do investido" if spot else "% margem", format="%.1f%%"),
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


_CARDS_JS = (Path(__file__).with_name("position_cards.js")).read_text(encoding="utf-8")
_CARDS_CSS = (Path(__file__).with_name("position_cards.css")).read_text(encoding="utf-8")


@st.cache_resource(show_spinner=False)
def _cards_component():
    return st.components.v2.component("tb_position_cards", css=_CARDS_CSS, js=_CARDS_JS)


_BOOK_JS = Path(__file__).with_name("book.js").read_text(encoding="utf-8")
_BOOK_CSS = Path(__file__).with_name("book.css").read_text(encoding="utf-8")


@st.cache_resource(show_spinner=False)
def _book_component():
    return st.components.v2.component("tb_book", css=_BOOK_CSS, js=_BOOK_JS)


_TICKET_JS = Path(__file__).with_name("ticket.js").read_text(encoding="utf-8")
_TICKET_CSS = Path(__file__).with_name("ticket.css").read_text(encoding="utf-8")
_HEADER_JS = Path(__file__).with_name("header.js").read_text(encoding="utf-8")
_HEADER_CSS = Path(__file__).with_name("header.css").read_text(encoding="utf-8")


@st.cache_resource(show_spinner=False)
def _header_component():
    return st.components.v2.component("tb_header", css=_HEADER_CSS, js=_HEADER_JS)


@st.cache_resource(show_spinner=False)
def _ticket_component():
    return st.components.v2.component("tb_ticket", css=_TICKET_CSS, js=_TICKET_JS)


def ticket_panel(profile: BotProfile, cfg: dict) -> None:
    """Boleta manual (componente em HTML/CSS/JS): o formulário volta ao Python, que calcula o risco e valida o envio."""

    @st.fragment
    def _ticket():
        bot = profile.key
        price, atr_v = st.session_state.get(f"{bot}__last_price"), st.session_state.get(f"{bot}__atr")
        if not price:
            st.info("Carregando cotação…")
            return
        c = {**cfg, **{n: st.session_state[_k(bot, n)] for n in ENTRY_KEYS}}
        stats = get_broker(bot).stats({c["symbol"]: price})
        key = f"{bot}-ticket"
        max_lev = cached_brackets(c["symbol"])[0][0].max_leverage if profile.market == "futures" else 1
        res = _ticket_component()(key=key, data=ticket_view.view(profile, c, st.session_state.get(f"{bot}__t_form"), price, atr_v, stats, max_lev),
                                  on_form_change=lambda: None, on_send_change=lambda: None)
        form = getattr(res, "form", None)
        if form is not None and form != st.session_state.get(f"{bot}__t_form"):
            st.session_state[f"{bot}__t_form"] = form
            st.rerun(scope="fragment")  # recalcula o resumo com o formulário novo
        ev = getattr(res, "send", None)
        if ev and ev.get("uid") != st.session_state.get(f"{bot}__t_uid"):
            st.session_state[f"{bot}__t_uid"] = ev.get("uid")
            ok, msg = ticket_view.submit(profile, c, ev, price, atr_v, max_lev)
            st.toast(msg, icon="✅" if ok else "🚫")
            if ok:
                st.rerun(scope="app")

    _ticket()


def open_positions(profile: BotProfile, cfg: dict) -> None:
    """Cards das posições abertas (componente em HTML/CSS/JS), com o resultado atualizado automaticamente."""

    @st.fragment(run_every=int(cfg["refresh_sec"]))
    def _cards():
        bot = profile.key
        acct = get_broker(bot).account()
        price = st.session_state.get(f"{bot}__last_price", 0)
        positions = [p for p in acct["positions"] if p.get("market") == profile.market]
        if not positions:
            st.caption("Nenhuma posição aberta.")
            return
        prices = {p["symbol"]: (price if p["symbol"] == cfg["symbol"] else _safe_price(p["symbol"], profile.market) or p["entry"]) for p in positions}
        cards = [positions_view.card_data(p, prices[p["symbol"]]) for p in positions]
        res = _cards_component()(key=f"{bot}-position-cards", data={"cards": cards}, on_action_change=lambda: None)
        ev = getattr(res, "action", None)
        if ev and ev.get("uid") != st.session_state.get(f"{bot}__card_uid"):
            st.session_state[f"{bot}__card_uid"] = ev.get("uid")
            ok, msg = chart_actions.handle_card(profile, ev, lambda sym: prices.get(sym) or _safe_price(sym, profile.market))
            if msg:
                st.toast(msg, icon="✅" if ok else "🚫")
            if ok:
                st.rerun(scope="app")

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
    labels = ["Gráfico", "Varredura", "Indicadores", "IA", "Conta"]
    tabs = dict(zip(labels, st.tabs(labels)))
    t_scan, t_ind, t_ai, t_acct = (tabs[n] for n in labels[1:])

    with tabs["Gráfico"]:
        c = st.columns(2)
        c[0].number_input("Candles carregados", 150, 1500, step=50, key=k("candles"))
        c[1].selectbox("Atualização (s)", (5, 10, 15, 30, 60, 120, 300, 600), key=k("refresh_sec"),
                       help="De quantos em quantos segundos a página confere preços, stops e alvos e roda o bot.")
        st.caption("A moeda se troca clicando no nome dela no topo do gráfico; o tempo gráfico, nos botões do cabeçalho.")

    with t_scan:
        st.toggle("🔎 Procurar oportunidades em várias moedas", key=k("scan_on"),
                  help="Com o bot ligado, a cada candle fechado ele sorteia moedas de maior volume do mercado (futuros ou spot, conforme esta "
                       "página), analisa os últimos 120 candles fechados de cada uma no tempo gráfico atual (só com regras, sem gastar IA), "
                       "escolhe sozinho o melhor bot do ranking para o contexto de cada uma e entra nas melhores oportunidades. "
                       "Desligado, opera só a moeda da tela.")
        off = not st.session_state[k("scan_on")]
        st.number_input("Varrer a cada (minutos)", 1, 240, key=k("scan_minutes"),
                        help="Padrão 15. Com o bot ligado, a varredura roda de tempos em tempos — não ao abrir a página nem ao trocar de "
                             "moeda ou tempo gráfico. Também vale para o worker 24/7.")
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
        if not get_secret("OPENROUTER_API_KEY"):  # sem chave nos Secrets: informe aqui (vale para todas as páginas, só nesta sessão)
            def _save_key():
                st.session_state["_or_key"] = st.session_state[f"{bot}__or_key_w"]

            st.text_input("Chave da OpenRouter (somente nesta sessão)", type="password", key=f"{bot}__or_key_w",
                          value=st.session_state.get("_or_key", ""), on_change=_save_key,
                          help="Para não digitar sempre, defina OPENROUTER_API_KEY nos Secrets do Streamlit.")
        st.caption("A IA escolhe o modelo sozinha, confirma ou veta as entradas do bot e decide se encerra posições abertas. "
                   "Stop e alvo continuam valendo, e sem sinal das regras ela nunca abre operação sozinha.")
        c = st.columns(2)
        c[0].selectbox("Personalidade da IA (tom das explicações)", list(ai_mod.AI_PERSONAS), key=k("ai_persona"),
                       format_func=lambda i: ai_mod.AI_PERSONAS[i][0])
        c[1].slider("Temperatura", 0.0, 1.0, step=0.05, key=k("ai_temperature"),
                    help="Quanto a IA varia as respostas. Perto de 0, ela responde de forma estável e repetível (melhor para decisões de "
                         "trade). Perto de 1, fica mais criativa e imprevisível. Recomendado: 0,1 a 0,3.")
        st.caption(ai_mod.AI_PERSONAS[st.session_state.get(k("ai_persona"), ai_mod.DEFAULT_PERSONA)][1])
        st.slider("Candles enviados como contexto", 20, 200, step=10, key=k("ai_candles_context"))
        st.text_area("Instruções da sua estratégia para a IA", key=k("ai_instructions"), height=110,
                     placeholder="Ex.: Só operar a favor da EMA 200. Evitar entradas 30 min antes de notícias dos EUA. "
                                 "Priorizar pullbacks na VWAP.")

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
