"""Gráfico em tempo real executado no navegador do usuário.

O navegador baixa o histórico e assina o fluxo WebSocket de candles
diretamente da corretora, por isso cada negociação move o candle na hora — e,
como a conexão parte do computador do usuário (e não do servidor do
Streamlit), funciona mesmo quando o servidor está em um país bloqueado pela
Binance.

Ordem de fontes: Binance (futuros ou spot) → espelho público da Binance (spot)
→ OKX. A fonte em uso é exibida no cabeçalho do gráfico.
"""
from __future__ import annotations

import json

LWC_URL = "https://unpkg.com/lightweight-charts@4.2.3/dist/lightweight-charts.standalone.production.js"


def realtime_chart_html(*, symbol: str, interval: str, market: str, ema_periods: list[int],
                        lines: list[dict], height: int = 620) -> str:
    """``lines``: [{"price", "color", "title", "style": "solid|dashed|dotted"}]."""
    cfg = json.dumps({"symbol": symbol.upper(), "interval": interval, "market": market,
                      "emas": ema_periods, "lines": lines, "height": height})
    return f"""<!doctype html><html><head><meta charset="utf-8">
<script src="{LWC_URL}"></script>
<style>
  html,body{{margin:0;background:#0e1117;color:#d1d4dc;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;overflow:hidden}}
  #bar{{display:flex;gap:14px;align-items:baseline;flex-wrap:wrap;padding:6px 8px;font-size:13px}}
  #sym{{font-weight:700;font-size:15px}} #px{{font-size:20px;font-weight:700;font-variant-numeric:tabular-nums}}
  .up{{color:#26a69a}} .dn{{color:#ef5350}} .mut{{color:#8a8f98}}
  #dot{{display:inline-block;width:8px;height:8px;border-radius:50%;background:#8a8f98;margin-right:5px}}
  #dot.live{{background:#26a69a;box-shadow:0 0 6px #26a69a}} #dot.err{{background:#ef5350}}
  #chart{{width:100%}}
  #ohlc{{position:absolute;left:10px;top:44px;z-index:3;font-size:12px;pointer-events:none;font-variant-numeric:tabular-nums}}
</style></head><body>
<div id="bar"><span id="sym"></span><span id="px">—</span><span id="chg" class="mut"></span>
<span class="mut">fecha em <b id="cd">--:--</b></span>
<span class="mut"><span id="dot"></span><span id="st">conectando…</span></span>
<span class="mut" id="ticks"></span></div>
<div id="ohlc" class="mut"></div><div id="chart"></div>
<script>
const C = {cfg};
const SEC = {{"1m":60,"3m":180,"5m":300,"15m":900,"30m":1800,"1h":3600,"2h":7200,"4h":14400,"6h":21600,"12h":43200,"1d":86400,"3d":259200,"1w":604800,"1M":2592000}}[C.interval];
const OKX_BAR = {{"1m":"1m","3m":"3m","5m":"5m","15m":"15m","30m":"30m","1h":"1H","2h":"2H","4h":"4H","6h":"6Hutc","12h":"12Hutc","1d":"1Dutc","3d":"3Dutc","1w":"1Wutc","1M":"1Mutc"}}[C.interval];
const TZ = -new Date().getTimezoneOffset() * 60;  // exibe no fuso do navegador
const fut = C.market === "futures";
const base = C.symbol.replace(/USDT$/, ""), okxInst = base + "-USDT" + (fut ? "-SWAP" : "");
const $ = id => document.getElementById(id);
$("sym").textContent = C.symbol + (fut ? " · Perpétuo" : " · Spot") + " · " + C.interval;

const chart = LightweightCharts.createChart($("chart"), {{
  height: C.height - 40, layout: {{background: {{color: "#0e1117"}}, textColor: "#d1d4dc"}},
  grid: {{vertLines: {{color: "#1c2030"}}, horzLines: {{color: "#1c2030"}}}},
  crosshair: {{mode: 0}}, rightPriceScale: {{borderColor: "#2a2e39"}},
  timeScale: {{borderColor: "#2a2e39", timeVisible: SEC < 86400, secondsVisible: false, rightOffset: 6}},
}});
const candles = chart.addCandlestickSeries({{upColor: "#26a69a", downColor: "#ef5350", borderVisible: false,
  wickUpColor: "#26a69a", wickDownColor: "#ef5350"}});
const vol = chart.addHistogramSeries({{priceFormat: {{type: "volume"}}, priceScaleId: "vol", lastValueVisible: false, priceLineVisible: false}});
chart.priceScale("vol").applyOptions({{scaleMargins: {{top: 0.82, bottom: 0}}}});
const EMA_COLORS = ["#f5c518", "#ff7f0e", "#ab47bc"];
const emas = C.emas.map((p, i) => ({{p, k: 2 / (p + 1), vals: [], s: chart.addLineSeries({{color: EMA_COLORS[i % 3],
  lineWidth: i === 2 ? 2 : 1, priceLineVisible: false, lastValueVisible: false, title: "EMA " + p}})}}));
const STYLE = {{solid: 0, dotted: 1, dashed: 2}};
C.lines.forEach(l => candles.createPriceLine({{price: l.price, color: l.color, lineWidth: l.width || 1,
  lineStyle: STYLE[l.style || "dashed"], axisLabelVisible: true, title: l.title || ""}}));
new ResizeObserver(() => chart.applyOptions({{width: document.body.clientWidth}})).observe(document.body);

let data = [], ticks = 0, source = "", open24 = null;
const fmt = v => v >= 100 ? v.toLocaleString("pt-BR", {{minimumFractionDigits: 2, maximumFractionDigits: 2}})
  : v.toLocaleString("pt-BR", {{maximumSignificantDigits: 6}});

function emaRecalc() {{
  emas.forEach(e => {{
    e.vals = []; let prev = null;
    data.forEach((c, i) => {{ prev = prev === null ? c.close : c.close * e.k + prev * (1 - e.k); e.vals.push(prev); }});
    e.s.setData(data.map((c, i) => ({{time: c.time, value: e.vals[i]}})).slice(Math.min(e.p, data.length - 1)));
  }});
}}
function setAll(rows) {{
  data = rows;
  candles.setData(data);
  vol.setData(data.map(c => ({{time: c.time, value: c.volume, color: c.close >= c.open ? "rgba(38,166,154,.45)" : "rgba(239,83,80,.45)"}})));
  emaRecalc();
  chart.timeScale().setVisibleLogicalRange({{from: data.length - 150, to: data.length + 5}});
  if (data.length) showPrice(data[data.length - 1]);
}}
function upsert(c) {{
  const last = data[data.length - 1];
  if (last && c.time < last.time) return;
  if (last && c.time === last.time) data[data.length - 1] = c; else data.push(c);
  candles.update(c);
  vol.update({{time: c.time, value: c.volume, color: c.close >= c.open ? "rgba(38,166,154,.45)" : "rgba(239,83,80,.45)"}});
  const n = data.length - 1;
  emas.forEach(e => {{
    const prev = n > 0 ? e.vals[n - 1] : c.close;
    e.vals[n] = c.close * e.k + prev * (1 - e.k);
    if (n >= e.p) e.s.update({{time: c.time, value: e.vals[n]}});
  }});
  ticks++; showPrice(c);
}}
function showPrice(c) {{
  const prev = data.length > 1 ? data[data.length - 2].close : c.open;
  $("px").textContent = fmt(c.close);
  $("px").className = c.close >= prev ? "up" : "dn";
  if (open24) {{ const ch = (c.close / open24 - 1) * 100; $("chg").textContent = (ch >= 0 ? "+" : "") + ch.toFixed(2) + "% 24h"; $("chg").className = ch >= 0 ? "up" : "dn"; }}
  $("ticks").textContent = ticks ? ticks + " atualizações" : "";
}}
chart.subscribeCrosshairMove(p => {{
  const c = p && p.seriesData && p.seriesData.get(candles);
  $("ohlc").innerHTML = c ? `A <b>${{fmt(c.open)}}</b> M <b>${{fmt(c.high)}}</b> m <b>${{fmt(c.low)}}</b> F <b>${{fmt(c.close)}}</b>` : "";
}});
setInterval(() => {{
  if (!data.length) return;
  const end = data[data.length - 1].time - TZ + SEC, left = Math.max(0, Math.round(end - Date.now() / 1000));
  const h = Math.floor(left / 3600), m = Math.floor(left % 3600 / 60), s = left % 60;
  $("cd").textContent = (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(s).padStart(2, "0");
}}, 1000);
function status(txt, cls) {{ $("st").textContent = txt; $("dot").className = cls || ""; }}

// ---------------- fontes ----------------
const bnRow = k => ({{time: k[0] / 1000 + TZ, open: +k[1], high: +k[2], low: +k[3], close: +k[4], volume: +k[5]}});
const SOURCES = [];
if (fut) SOURCES.push({{name: "Binance Futuros", rest: `https://fapi.binance.com/fapi/v1/klines?symbol=${{C.symbol}}&interval=${{C.interval}}&limit=1000`,
  t24: `https://fapi.binance.com/fapi/v1/ticker/24hr?symbol=${{C.symbol}}`, ws: `wss://fstream.binance.com/ws/${{C.symbol.toLowerCase()}}@kline_${{C.interval}}`, kind: "bn"}});
else {{
  SOURCES.push({{name: "Binance Spot", rest: `https://api.binance.com/api/v3/klines?symbol=${{C.symbol}}&interval=${{C.interval}}&limit=1000`,
    t24: `https://api.binance.com/api/v3/ticker/24hr?symbol=${{C.symbol}}`, ws: `wss://stream.binance.com:443/ws/${{C.symbol.toLowerCase()}}@kline_${{C.interval}}`, kind: "bn"}});
  SOURCES.push({{name: "Binance Spot (espelho)", rest: `https://data-api.binance.vision/api/v3/klines?symbol=${{C.symbol}}&interval=${{C.interval}}&limit=1000`,
    t24: `https://data-api.binance.vision/api/v3/ticker/24hr?symbol=${{C.symbol}}`, ws: `wss://data-stream.binance.vision/ws/${{C.symbol.toLowerCase()}}@kline_${{C.interval}}`, kind: "bn"}});
}}
SOURCES.push({{name: fut ? "OKX Perpétuo" : "OKX Spot", kind: "okx"}});

async function okxHistory() {{
  let rows = [], after = "", url = "candles";
  for (let i = 0; i < 4 && rows.length < 1000; i++) {{
    const r = await fetch(`https://www.okx.com/api/v5/market/${{url}}?instId=${{okxInst}}&bar=${{OKX_BAR}}&limit=${{url === "candles" ? 300 : 100}}${{after ? "&after=" + after : ""}}`);
    const j = await r.json(); if (j.code !== "0" || !j.data.length) break;
    rows = rows.concat(j.data); after = j.data[j.data.length - 1][0]; url = "history-candles";
  }}
  if (!rows.length) throw new Error("OKX sem dados");
  try {{ const t = await (await fetch(`https://www.okx.com/api/v5/market/ticker?instId=${{okxInst}}`)).json(); open24 = +t.data[0].open24h; }} catch (e) {{}}
  return rows.reverse().map(k => ({{time: +k[0] / 1000 + TZ, open: +k[1], high: +k[2], low: +k[3], close: +k[4], volume: +k[5]}}));
}}
async function history(src) {{
  if (src.kind === "okx") return okxHistory();
  const r = await fetch(src.rest); if (!r.ok) throw new Error("HTTP " + r.status);
  try {{ open24 = +(await (await fetch(src.t24)).json()).openPrice; }} catch (e) {{}}
  return (await r.json()).map(bnRow);
}}

let ws = null, wsIdx = 0, retry = 0, pingTimer = null;
function stream(i) {{
  const src = SOURCES[i]; if (!src) {{ status("sem fluxo ao vivo — recarregue a página", "err"); return; }}
  let opened = false;
  status("conectando a " + src.name + "…");
  ws = new WebSocket(src.kind === "okx" ? "wss://ws.okx.com/ws/v5/business" : src.ws);
  const failover = setTimeout(() => {{ if (!opened) {{ ws.onclose = null; ws.close(); stream(i + 1); }} }}, 6000);
  ws.onopen = () => {{
    if (src.kind === "okx") {{
      ws.send(JSON.stringify({{op: "subscribe", args: [{{channel: "candle" + OKX_BAR, instId: okxInst}}]}}));
      clearInterval(pingTimer); pingTimer = setInterval(() => ws.readyState === 1 && ws.send("ping"), 20000);
    }}
  }};
  ws.onmessage = ev => {{
    if (ev.data === "pong") return;
    const m = JSON.parse(ev.data);
    let c = null;
    if (src.kind === "bn" && m.k) c = {{time: m.k.t / 1000 + TZ, open: +m.k.o, high: +m.k.h, low: +m.k.l, close: +m.k.c, volume: +m.k.v}};
    if (src.kind === "okx" && m.data) {{ const k = m.data[0]; c = {{time: +k[0] / 1000 + TZ, open: +k[1], high: +k[2], low: +k[3], close: +k[4], volume: +k[5]}}; }}
    if (!c) return;
    if (!opened) {{ opened = true; clearTimeout(failover); retry = 0; status("ao vivo · " + src.name + (source && source !== src.name ? " (histórico: " + source + ")" : ""), "live"); }}
    upsert(c);
  }};
  ws.onerror = () => {{}};
  ws.onclose = () => {{
    clearTimeout(failover);
    if (!opened) {{ stream(i + 1); return; }}
    status("reconectando…", "err");
    setTimeout(() => stream(i), Math.min(30000, 1000 * 2 ** retry++));
  }};
}}

(async () => {{
  for (let i = 0; i < SOURCES.length; i++) {{
    try {{ setAll(await history(SOURCES[i])); source = SOURCES[i].name; stream(i); return; }}
    catch (e) {{ console.warn(SOURCES[i].name, e); }}
  }}
  status("não foi possível carregar dados no navegador", "err");
}})();
// Ao voltar para a aba, sincroniza o histórico (o navegador pode pausar o WebSocket em segundo plano)
document.addEventListener("visibilitychange", async () => {{
  if (document.visibilityState !== "visible" || !source) return;
  const src = SOURCES.find(s => s.name === source);
  try {{ const rows = await history(src); const lr = chart.timeScale().getVisibleLogicalRange(); setAll(rows); if (lr) chart.timeScale().setVisibleLogicalRange(lr); }} catch (e) {{}}
}});
</script></body></html>"""
