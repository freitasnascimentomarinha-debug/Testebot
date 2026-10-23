"""Gráfico de trade interativo (Plotly) com indicadores e ferramentas de desenho."""
from __future__ import annotations

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from core import indicators as ind

UP, DOWN = "#26a69a", "#ef5350"

PLOTLY_CONFIG = {
    "scrollZoom": True,
    "displaylogo": False,
    "modeBarButtonsToAdd": ["drawline", "drawopenpath", "drawclosedpath", "drawcircle", "drawrect", "eraseshape"],
    "modeBarButtonsToRemove": ["lasso2d", "select2d", "autoScale2d"],
    "toImageButtonOptions": {"format": "png", "filename": "grafico_trade", "scale": 2},
}


def build_chart(df, cfg: dict, *, symbol: str, interval: str, positions=(), orders=(), history=(),
                plan: dict | None = None, height: int = 760) -> go.Figure:
    lower = [name for name, on in (("Volume", cfg["volume_on"]), ("RSI", cfg["rsi_on"]),
                                   ("MACD", cfg["macd_on"]), ("Estocástico", cfg["stoch_on"]),
                                   ("ADX", cfg["adx_on"]), ("OBV", cfg["obv_on"])) if on]
    rows = 1 + len(lower)
    heights = [0.55] + [0.45 / len(lower)] * len(lower) if lower else [1.0]
    fig = make_subplots(rows=rows, cols=1, shared_xaxes=True, vertical_spacing=0.02, row_heights=heights)
    x = df["time"]

    fig.add_trace(go.Candlestick(x=x, open=df["open"], high=df["high"], low=df["low"], close=df["close"],
                                 name=symbol, increasing_line_color=UP, decreasing_line_color=DOWN,
                                 increasing_fillcolor=UP, decreasing_fillcolor=DOWN), row=1, col=1)

    def line(col, name, color, width=1.2, dash=None, row=1):
        fig.add_trace(go.Scatter(x=x, y=df[col], name=name, mode="lines", showlegend=row == 1,
                                 line=dict(color=color, width=width, dash=dash)), row=row, col=1)

    if cfg["ema_on"]:
        line("ema_fast", f"EMA {cfg['ema_fast']}", "#f5c518")
        line("ema_slow", f"EMA {cfg['ema_slow']}", "#ff7f0e")
    if cfg.get("ema_trend_on"):
        line("ema_trend", f"EMA {cfg['ema_trend']}", "#ab47bc", 1.6)
    if cfg["bb_on"]:
        line("bb_up", "BB sup.", "rgba(100,149,237,.7)", 1, "dot")
        line("bb_mid", "BB média", "rgba(100,149,237,.5)", 1)
        line("bb_low", "BB inf.", "rgba(100,149,237,.7)", 1, "dot")
    if cfg["vwap_on"]:
        line("vwap", "VWAP", "#00bcd4", 1.4, "dash")
    if cfg["supertrend_on"]:
        for d, color, label in ((1, UP, "SuperTrend ↑"), (-1, DOWN, "SuperTrend ↓")):
            fig.add_trace(go.Scatter(x=x, y=df["st_line"].where(df["st_dir"] == d), name=label, mode="lines",
                                     line=dict(color=color, width=1.6)), row=1, col=1)
    if cfg.get("ichimoku_on") and "ichi_span_a" in df:
        line("ichi_tenkan", "Tenkan", "#29b6f6", 1)
        line("ichi_kijun", "Kijun", "#8d6e63", 1)
        fig.add_trace(go.Scatter(x=x, y=df["ichi_span_a"], name="Senkou A", line=dict(color="rgba(38,166,154,.5)", width=1)), row=1, col=1)
        fig.add_trace(go.Scatter(x=x, y=df["ichi_span_b"], name="Senkou B", fill="tonexty",
                                 fillcolor="rgba(150,150,150,.12)", line=dict(color="rgba(239,83,80,.5)", width=1)), row=1, col=1)

    def hline(y, text, color, dash="dot", width=1):
        fig.add_hline(y=y, line=dict(color=color, dash=dash, width=width), row=1, col=1,
                      annotation_text=text, annotation_position="right", annotation_font_size=10,
                      annotation_font_color=color)

    if cfg["sr_on"]:
        levels = ind.support_resistance(df)
        for lv in levels["supports"]:
            hline(lv["price"], f"S {lv['price']:.6g} ({lv['touches']}×)", "rgba(38,166,154,.8)")
        for lv in levels["resistances"]:
            hline(lv["price"], f"R {lv['price']:.6g} ({lv['touches']}×)", "rgba(239,83,80,.8)")
    if cfg["pivots_on"]:
        for k, v in ind.pivot_points(df).items():
            hline(v, f"{k} {v:.6g}", "rgba(158,158,158,.8)", "dash")
    if cfg["fib_on"]:
        for k, v in ind.fibonacci(df).items():
            hline(v, f"Fib {k}", "rgba(255,193,7,.7)", "dashdot")

    for lv in cfg.get("user_levels", []):
        color = lv.get("color", "#e91e63")
        if lv.get("type") == "trend":
            fig.add_shape(type="line", x0=lv["t1"], y0=lv["p1"], x1=lv["t2"], y1=lv["p2"],
                          line=dict(color=color, width=2), row=1, col=1)
        else:
            hline(lv["price"], lv.get("label") or f"{lv['price']:.6g}", color, "solid", 1.5)

    for p in positions:
        if p["symbol"] != symbol:
            continue
        side = "COMPRA" if p["side"] == "BUY" else "VENDA"
        hline(p["entry"], f"{side} {p['qty']:g} @ {p['entry']:.6g}", "#42a5f5", "solid", 2)
        if p.get("stop_loss"):
            hline(p["stop_loss"], f"SL {p['stop_loss']:.6g}", DOWN, "dash", 1.5)
        if p.get("take_profit"):
            hline(p["take_profit"], f"TP {p['take_profit']:.6g}", UP, "dash", 1.5)
        if p.get("liquidation"):
            hline(p["liquidation"], f"Liq. {p['liquidation']:.6g}", "#ff9800", "dot", 1)
    for o in orders:
        if o["symbol"] == symbol:
            hline(o["limit_price"], f"LIMIT {o['side']} {o['limit_price']:.6g}", "#bdbdbd", "dashdot", 1.5)
    if plan and plan.get("decision") in ("BUY", "SELL"):
        if plan.get("entry"):
            hline(plan["entry"], "Plano: entrada", "#90caf9", "dot", 1.2)
        if plan.get("stop_loss"):
            hline(plan["stop_loss"], "Plano: stop", "#ef9a9a", "dot", 1.2)
        if plan.get("take_profit"):
            hline(plan["take_profit"], "Plano: alvo", "#a5d6a7", "dot", 1.2)

    t0 = df["time"].iloc[0]
    trades = [t for t in history if t["symbol"] == symbol and t["closed"] >= t0.isoformat()]
    if trades:
        fig.add_trace(go.Scatter(
            x=[t["opened"] for t in trades], y=[t["entry"] for t in trades], mode="markers", name="Entradas",
            marker=dict(symbol=["triangle-up" if t["side"] == "BUY" else "triangle-down" for t in trades],
                        size=12, color=["#42a5f5"] * len(trades), line=dict(width=1, color="white")),
            hovertext=[f"{t['side']} {t['qty']:g} @ {t['entry']:.6g}" for t in trades]), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=[t["closed"] for t in trades], y=[t["exit"] for t in trades], mode="markers", name="Saídas",
            marker=dict(symbol="x", size=10, color=[UP if t["pnl"] > 0 else DOWN for t in trades]),
            hovertext=[f"{t['reason']}: {t['pnl']:+.2f} USDT" for t in trades]), row=1, col=1)

    for i, name in enumerate(lower, start=2):
        if name == "Volume":
            colors = [UP if c >= o else DOWN for c, o in zip(df["close"], df["open"])]
            fig.add_trace(go.Bar(x=x, y=df["volume"], name="Volume", marker_color=colors, opacity=0.6, showlegend=False), row=i, col=1)
            line("vol_sma", "Vol. média 20", "#bdbdbd", 1, row=i)
        elif name == "RSI":
            line("rsi", "RSI", "#ab47bc", row=i)
            fig.add_hrect(y0=cfg["rsi_os"], y1=cfg["rsi_ob"], fillcolor="rgba(171,71,188,.08)", line_width=0, row=i, col=1)
            fig.add_hline(y=cfg["rsi_ob"], line=dict(color=DOWN, dash="dot", width=1), row=i, col=1)
            fig.add_hline(y=cfg["rsi_os"], line=dict(color=UP, dash="dot", width=1), row=i, col=1)
        elif name == "MACD":
            fig.add_trace(go.Bar(x=x, y=df["macd_hist"], name="Histograma", showlegend=False,
                                 marker_color=[UP if v >= 0 else DOWN for v in df["macd_hist"].fillna(0)]), row=i, col=1)
            line("macd", "MACD", "#42a5f5", row=i)
            line("macd_signal", "Sinal", "#ff7f0e", row=i)
        elif name == "Estocástico":
            line("stoch_k", "%K", "#42a5f5", row=i)
            line("stoch_d", "%D", "#ff7f0e", row=i)
            fig.add_hline(y=80, line=dict(color=DOWN, dash="dot", width=1), row=i, col=1)
            fig.add_hline(y=20, line=dict(color=UP, dash="dot", width=1), row=i, col=1)
        elif name == "ADX":
            line("adx", "ADX", "#fdd835", row=i)
            line("di_plus", "+DI", UP, 1, row=i)
            line("di_minus", "-DI", DOWN, 1, row=i)
            fig.add_hline(y=25, line=dict(color="#9e9e9e", dash="dot", width=1), row=i, col=1)
        elif name == "OBV":
            line("obv", "OBV", "#26c6da", row=i)
        fig.update_yaxes(title_text=name, title_font_size=10, row=i, col=1)

    fig.update_layout(
        height=height, template="plotly_dark", margin=dict(l=10, r=90, t=30, b=10),
        xaxis_rangeslider_visible=False, dragmode="pan", hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0, font_size=10),
        uirevision=f"{symbol}-{interval}",  # mantém zoom/desenhos entre atualizações
        newshape=dict(line_color="#ffeb3b", line_width=2),
        title=dict(text=f"{symbol} · {interval} · fonte: {df.attrs.get('source', '')}", font_size=12, x=0.01, y=0.995),
    )
    fig.update_yaxes(side="right", row=1, col=1)
    visible = df.tail(150)
    pad = (visible["high"].max() - visible["low"].min()) * 0.05
    fig.update_xaxes(range=[visible["time"].iloc[0], df["time"].iloc[-1] + (df["time"].iloc[-1] - df["time"].iloc[-10])])
    fig.update_yaxes(range=[visible["low"].min() - pad, visible["high"].max() + pad], row=1, col=1)
    return fig


def tradingview_widget(symbol: str, interval: str, market: str, height: int = 760) -> str:
    """Widget gratuito do TradingView: conjunto completo de ferramentas de
    desenho (Fibonacci, tendências, canais, padrões, régua e as ferramentas
    "Posição comprada/vendida" para cálculo de risco:retorno)."""
    tv_interval = {"1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30", "1h": "60", "2h": "120",
                   "4h": "240", "6h": "360", "12h": "720", "1d": "D", "3d": "3D", "1w": "W", "1M": "M"}[interval]
    from core import markets

    if markets.is_crypto(market):
        tv_symbol = f"BINANCE:{symbol}{'.P' if market == 'futures' else ''}"
    else:
        tv_symbol = markets.tv_symbol(market, symbol)
    return f"""
<div class="tradingview-widget-container" style="height:{height}px;width:100%">
  <div id="tv_chart" style="height:{height}px;width:100%"></div>
  <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
  <script type="text/javascript">
  new TradingView.widget({{
    "autosize": true, "symbol": "{tv_symbol}", "interval": "{tv_interval}", "timezone": "America/Sao_Paulo",
    "theme": "dark", "style": "1", "locale": "br", "allow_symbol_change": true, "enable_publishing": false,
    "hide_side_toolbar": false, "withdateranges": true, "details": true, "hotlist": false, "calendar": false,
    "studies": ["STD;EMA", "STD;RSI", "STD;MACD"], "container_id": "tv_chart"
  }});
  </script>
</div>"""
