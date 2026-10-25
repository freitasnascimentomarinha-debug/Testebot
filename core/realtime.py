"""Gráfico em tempo real executado no navegador do usuário.

O navegador baixa o histórico e assina o fluxo WebSocket de candles
diretamente da corretora, por isso cada negociação move o candle, os
indicadores e o lucro/prejuízo das posições abertas — e, como a conexão parte
do computador do usuário (e não do servidor do Streamlit), funciona mesmo
quando o servidor está em um país bloqueado pela Binance.

Ordem de fontes (cripto): Binance (futuros ou spot) → espelho público da Binance (spot)
→ OKX. A fonte em uso é exibida no cabeçalho do gráfico.

Os indicadores são recalculados no navegador a cada negociação com as mesmas
fórmulas de ``core/indicators.py``.
"""
from __future__ import annotations

import json
from pathlib import Path

LWC_URL = "https://unpkg.com/lightweight-charts@5.0.8/dist/lightweight-charts.standalone.production.js"

# Indicadores que abrem painel próprio abaixo do preço
PANE_FLAGS = ("rsi_on", "macd_on", "stoch_on", "adx_on", "obv_on")
PANE_HEIGHT = 110


def chart_height(cfg: dict, base: int = 640) -> int:
    """Altura fixa: os indicadores ligados dentro do gráfico dividem esse espaço com o painel de preço."""
    return base + PANE_HEIGHT + PANE_HEIGHT * min(sum(bool(cfg.get(f)) for f in PANE_FLAGS), 2)


def realtime_chart_html(*, symbol: str, interval: str, market: str, cfg: dict, lines: list[dict],
                        positions: list[dict], height: int, orders: list[dict] | None = None, demo: list | None = None,
                        symbols: list[str] | None = None, prefer: str = "binance") -> str:
    """``lines``: [{"price", "color", "title", "style": "solid|dashed|dotted"}];
    ``positions``: posições abertas no ativo (para o P&L ao vivo)."""
    ind_keys = ("ema_on", "ema_fast", "ema_slow", "ema_trend_on", "ema_trend", "bb_on", "bb_period", "bb_std", "vwap_on",
                "supertrend_on", "st_period", "st_mult", "volume_on", "rsi_on", "rsi_period", "rsi_ob", "rsi_os",
                "macd_on", "macd_fast", "macd_slow", "macd_signal", "stoch_on", "stoch_k", "stoch_d",
                "adx_on", "adx_period", "obv_on")
    pos = [{**{k: p.get(k) for k in ("id", "side", "qty", "entry", "fee_pct", "fees_paid", "margin", "stop_loss", "take_profit", "leverage", "liquidation")},
            "fx": p.get("fx", 1.0)} for p in positions]
    from core.data import okx_base

    base, mult = okx_base(symbol)
    conf = json.dumps({"okx_base": base, "okx_mult": mult, "symbol": symbol.upper(), "interval": interval, "market": market, "height": height, "symbols": list(symbols or [])[:3000], "prefer": prefer,
                       "ind": {k: cfg[k] for k in ind_keys}, "lines": lines, "positions": pos,
                       "orders": [{k: o.get(k) for k in ("id", "side", "qty")} | {"price": o["limit_price"]} for o in (orders or [])],
                       **({"demo": demo} if demo else {})})
    return _TEMPLATE.replace("__TOOLS__", _TOOLS_JS).replace("__LWC__", LWC_URL).replace("__CONF__", conf)


_TOOLS_JS = (Path(__file__).with_name("chart_tools.js")).read_text(encoding="utf-8")

_TEMPLATE = r"""<!doctype html><html><head><meta charset="utf-8">
<script src="__LWC__"></script>
<style>
  html,body{margin:0;background:#0e1117;color:#d1d4dc;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;overflow:hidden}
  #bar{display:flex;gap:14px;align-items:baseline;flex-wrap:wrap;padding:6px 8px;font-size:13px;min-height:28px}
  #sym{font-weight:700;font-size:15px;cursor:pointer;padding:2px 8px;border-radius:7px;background:#1e2433;border:1px solid #2a3042} #sym:hover{border-color:#5a6385}
  #symbox{position:fixed;top:36px;left:8px;z-index:30;width:230px;background:#141824;border:1px solid #2a3042;border-radius:10px;padding:8px;box-shadow:0 8px 24px rgba(0,0,0,.5);display:none}
  #symbox input{width:100%;box-sizing:border-box;background:#0e1117;color:#e6e8ee;border:1px solid #2a3042;border-radius:7px;padding:7px 9px;font-size:13px;margin-bottom:6px}
  #symlist{max-height:260px;overflow:auto} #symlist div{padding:5px 8px;border-radius:6px;cursor:pointer;font-size:13px} #symlist div:hover,#symlist div.on{background:#2a3042} #px{font-size:20px;font-weight:700;font-variant-numeric:tabular-nums}
  .up{color:#26a69a} .dn{color:#ef5350} .mut{color:#8a8f98}
  #dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#8a8f98;margin-right:5px}
  #dot.live{background:#26a69a;box-shadow:0 0 6px #26a69a} #dot.err{background:#ef5350}
  #pnl{font-weight:700;font-size:15px;font-variant-numeric:tabular-nums;padding:1px 8px;border-radius:6px}
  #pnl.up{background:rgba(38,166,154,.15)} #pnl.dn{background:rgba(239,83,80,.15)}
  #chart{width:100%}
  #ohlc{position:absolute;left:46px;top:66px;z-index:3;font-size:12px;pointer-events:none;font-variant-numeric:tabular-nums}
  #tools{position:absolute;left:6px;top:96px;z-index:5;display:flex;flex-direction:column;gap:3px;background:rgba(14,17,23,.85);padding:3px;border:1px solid #2a2e39;border-radius:6px}
  #tools button,#menu button,#closebtn{background:#1c2030;color:#d1d4dc;border:1px solid #2a2e39;border-radius:4px;cursor:pointer;font-size:14px;min-width:28px;height:26px}
  #tools button.on{background:#26a69a;color:#06130f;border-color:#26a69a} #tools button:hover,#menu button:hover{border-color:#8a8f98}
  #menu{display:inline-flex;gap:8px;align-items:center;font-size:12px} #menu select{background:#1c2030;color:#d1d4dc;border:1px solid #2a2e39;border-radius:4px;height:26px}
  #menu button{font-size:12px;padding:0 8px} .chk{display:inline-flex;gap:3px;align-items:center;cursor:pointer}
  #closebtn{font-size:12px;padding:0 10px;background:#7b2d2d;border-color:#ef5350}
  #indbox{position:absolute;right:70px;top:34px;z-index:6;background:#161a25;border:1px solid #2a2e39;border-radius:6px;padding:8px 10px;font-size:12px;display:flex;flex-direction:column;gap:3px;max-width:220px}
  #indbox label{display:flex;gap:6px;align-items:center;cursor:pointer}
  #zoom{position:absolute;right:78px;bottom:34px;z-index:5;display:flex;gap:3px}
  #zoom button{background:rgba(28,32,48,.92);color:#d1d4dc;border:1px solid #2a2e39;border-radius:4px;cursor:pointer;font-size:15px;width:30px;height:28px;padding:0}
  #zoom button:hover{border-color:#8a8f98}
  #pop{position:absolute;z-index:7;background:#161a25;border:1px solid #2a2e39;border-radius:6px;padding:8px;font-size:12px;width:210px}
  #pop button{display:block;width:100%;margin:5px 0 0;padding:6px;border-radius:4px;border:1px solid #2a2e39;background:#1c2030;color:#d1d4dc;cursor:pointer}
  #pop button.b{background:#1f6f66;border-color:#26a69a} #pop button.s{background:#7b2d2d;border-color:#ef5350}
</style></head><body>
<div id="bar"><span id="sym"></span><span id="px">—</span><span id="chg" class="mut"></span>
<span id="pnl" style="display:none"></span>
<span class="mut">fecha em <b id="cd">--:--</b></span>
<span class="mut"><span id="dot"></span><span id="st">conectando…</span></span>
<span class="mut" id="ticks"></span></div>
<div id="ohlc" class="mut"></div><div id="chart"></div>
<script>
const C = __CONF__, I = C.ind, L = LightweightCharts;
const SEC = {"1m":60,"3m":180,"5m":300,"15m":900,"30m":1800,"1h":3600,"2h":7200,"4h":14400,"6h":21600,"12h":43200,"1d":86400,"3d":259200,"1w":604800,"1M":2592000}[C.interval];
const OKX_BAR = {"1m":"1m","3m":"3m","5m":"5m","15m":"15m","30m":"30m","1h":"1H","2h":"2H","4h":"4H","6h":"6Hutc","12h":"12Hutc","1d":"1Dutc","3d":"3Dutc","1w":"1Wutc","1M":"1Mutc"}[C.interval];
const TZ = -new Date().getTimezoneOffset() * 60;  // exibe no fuso do navegador
const fut = C.market === "futures";
const okxInst = C.okx_base + "-USDT" + (fut ? "-SWAP" : "");
const M = C.okx_mult, VI = fut ? 6 : 5;  // OKX: preço por moeda (×M p/ pares 1000X da Binance); volume em moeda-base
const okxRow = k => row(+k[0], k[1] * M, k[2] * M, k[3] * M, k[4] * M, k[VI] / M);
const $ = id => document.getElementById(id);
const UP = "#26a69a", DN = "#ef5350";
$("sym").textContent = C.symbol + (fut ? " · Perpétuo" : " · Spot") + " · " + C.interval + " ▾";
{ // trocar de moeda clicando no nome: busca e lista dos pares do mercado
  const box = document.createElement("div"); box.id = "symbox";
  box.innerHTML = '<input placeholder="Buscar moeda… (ex.: SOL)" autocomplete="off"><div id="symlist"></div>'; document.body.appendChild(box);
  const inp = box.querySelector("input"), list = box.querySelector("#symlist");
  const draw = () => { const q = inp.value.trim().toUpperCase(); const rows = (C.symbols || []).filter(s => s.includes(q)).sort((a, b) => (a.startsWith(q) ? 0 : 1) - (b.startsWith(q) ? 0 : 1)).slice(0, 80);
    list.innerHTML = rows.map(s => `<div data-s="${s}" class="${s === C.symbol ? "on" : ""}">${s.replace(/USDT$/, "")}<span class="mut">/USDT</span></div>`).join("") || '<div class="mut">Nenhuma moeda encontrada</div>'; };
  $("sym").onclick = () => { box.style.display = box.style.display === "block" ? "none" : "block"; if (box.style.display === "block") { inp.value = ""; draw(); inp.focus(); } };
  inp.oninput = draw;
  inp.onkeydown = e => { if (e.key === "Enter") { const f = list.querySelector("div[data-s]"); if (f) f.click(); } if (e.key === "Escape") box.style.display = "none"; };
  list.onclick = e => { const d = e.target.closest("div[data-s]"); if (!d) return; box.style.display = "none"; if (d.dataset.s !== C.symbol) send({kind: "symbol", value: d.dataset.s}); };
}
const fmt = v => v == null || isNaN(v) ? "—" : Math.abs(v) >= 100
  ? v.toLocaleString("pt-BR", {minimumFractionDigits: 2, maximumFractionDigits: 2})
  : v.toLocaleString("pt-BR", {maximumSignificantDigits: 6});
const UNIT = "USDT";
const money = v => (v >= 0 ? "+" : "−") + Math.abs(v).toLocaleString("pt-BR", {minimumFractionDigits: 2, maximumFractionDigits: 2});

// ------------------------------------------------------------- indicadores
const nan = v => v == null || Number.isNaN(v);
function ema(src, p) { const k = 2 / (p + 1); let prev = null; return src.map(v => nan(v) ? null : (prev = prev === null ? v : v * k + prev * (1 - k))); }
function rma(src, p) { const a = 1 / p; let prev = null; return src.map(v => nan(v) ? null : (prev = prev === null ? v : v * a + prev * (1 - a))); }
function sma(src, p) { let s = 0; return src.map((v, i) => { s += v; if (i >= p) s -= src[i - p]; return i >= p - 1 ? s / p : null; }); }
function rollStd(src, p, mean) { return src.map((v, i) => { if (i < p - 1) return null; let q = 0; for (let j = i - p + 1; j <= i; j++) q += (src[j] - mean[i]) ** 2; return Math.sqrt(q / p); }); }
function rollMin(src, p) { return src.map((v, i) => i < p - 1 ? null : Math.min(...src.slice(i - p + 1, i + 1))); }
function rollMax(src, p) { return src.map((v, i) => i < p - 1 ? null : Math.max(...src.slice(i - p + 1, i + 1))); }
function smaN(src, p) { return src.map((v, i) => { if (i < p - 1) return null; let s = 0; for (let j = i - p + 1; j <= i; j++) { if (nan(src[j])) return null; s += src[j]; } return s / p; }); }
function trueRange(d) { return d.map((c, i) => i === 0 ? c.high - c.low : Math.max(c.high - c.low, Math.abs(c.high - d[i - 1].close), Math.abs(c.low - d[i - 1].close))); }

function compute(d) {
  const o = {}, close = d.map(c => c.close);
  if (I.ema_on) { o.ema_fast = ema(close, I.ema_fast); o.ema_slow = ema(close, I.ema_slow); }
  if (I.ema_trend_on) o.ema_trend = ema(close, I.ema_trend);
  if (I.bb_on) { const m = sma(close, I.bb_period), s = rollStd(close, I.bb_period, m);
    o.bb_mid = m; o.bb_up = m.map((v, i) => v === null ? null : v + I.bb_std * s[i]); o.bb_low = m.map((v, i) => v === null ? null : v - I.bb_std * s[i]); }
  if (I.vwap_on) { let day = null, pv = 0, vv = 0;
    o.vwap = d.map(c => { const dd = Math.floor(c.utc / 86400); if (dd !== day) { day = dd; pv = 0; vv = 0; }
      pv += (c.high + c.low + c.close) / 3 * c.volume; vv += c.volume; return vv ? pv / vv : null; }); }
  if (I.supertrend_on) {
    const p = I.st_period, a = rma(trueRange(d), p), n = d.length;
    const up = d.map((c, i) => (c.high + c.low) / 2 + I.st_mult * a[i]), lo = d.map((c, i) => (c.high + c.low) / 2 - I.st_mult * a[i]);
    const fu = up.slice(), fl = lo.slice(), dir = new Array(n).fill(1), line = new Array(n).fill(null);
    for (let i = 1; i < n; i++) {
      fu[i] = (up[i] < fu[i - 1] || close[i - 1] > fu[i - 1]) ? up[i] : fu[i - 1];
      fl[i] = (lo[i] > fl[i - 1] || close[i - 1] < fl[i - 1]) ? lo[i] : fl[i - 1];
      dir[i] = dir[i - 1] === -1 && close[i] > fu[i - 1] ? 1 : dir[i - 1] === 1 && close[i] < fl[i - 1] ? -1 : dir[i - 1];
      line[i] = i < p ? null : (dir[i] === 1 ? fl[i] : fu[i]);
    }
    o.st_up = line.map((v, i) => dir[i] === 1 ? v : null); o.st_dn = line.map((v, i) => dir[i] === -1 ? v : null);
  }
  if (I.rsi_on) { const g = [null], l = [null];
    for (let i = 1; i < d.length; i++) { const x = close[i] - close[i - 1]; g.push(Math.max(x, 0)); l.push(Math.max(-x, 0)); }
    const ag = rma(g, I.rsi_period), al = rma(l, I.rsi_period);
    o.rsi = ag.map((v, i) => v === null ? null : al[i] === 0 ? 100 : 100 - 100 / (1 + v / al[i])); }
  if (I.macd_on) { const f = ema(close, I.macd_fast), s = ema(close, I.macd_slow), m = f.map((v, i) => v - s[i]), sg = ema(m, I.macd_signal);
    o.macd = m; o.macd_signal = sg; o.macd_hist = m.map((v, i) => v - sg[i]); }
  if (I.stoch_on) { const lo = rollMin(d.map(c => c.low), I.stoch_k), hi = rollMax(d.map(c => c.high), I.stoch_k);
    const k = smaN(close.map((v, i) => lo[i] === null || hi[i] === lo[i] ? null : 100 * (v - lo[i]) / (hi[i] - lo[i])), 3);
    o.stoch_k = k; o.stoch_d = smaN(k, I.stoch_d); }
  if (I.adx_on) { const p = I.adx_period, pdm = [0], mdm = [0];
    for (let i = 1; i < d.length; i++) { const u = d[i].high - d[i - 1].high, w = d[i - 1].low - d[i].low;
      pdm.push(u > w && u > 0 ? u : 0); mdm.push(w > u && w > 0 ? w : 0); }
    const tr = rma(trueRange(d), p), pr = rma(pdm, p), mr = rma(mdm, p);
    o.di_plus = pr.map((v, i) => 100 * v / tr[i]); o.di_minus = mr.map((v, i) => 100 * v / tr[i]);
    o.adx = rma(o.di_plus.map((v, i) => { const s = v + o.di_minus[i]; return s ? 100 * Math.abs(v - o.di_minus[i]) / s : null; }), p); }
  if (I.obv_on) { let acc = 0; o.obv = d.map((c, i) => acc += i === 0 ? 0 : Math.sign(c.close - d[i - 1].close) * c.volume); }
  return o;
}

// ------------------------------------------------------------------ gráfico
let H = C.height;   // altura atual (muda no modo tela cheia)
const chart = L.createChart($("chart"), {
  height: H - 40, layout: {background: {color: "#0e1117"}, textColor: "#d1d4dc", panes: {separatorColor: "#2a2e39"}},
  grid: {vertLines: {color: "#1c2030"}, horzLines: {color: "#1c2030"}},
  crosshair: {mode: 0}, rightPriceScale: {borderColor: "#2a2e39"},
  timeScale: {borderColor: "#2a2e39", timeVisible: SEC < 86400, secondsVisible: false, rightOffset: 6},
});
const candles = chart.addSeries(L.CandlestickSeries, {upColor: UP, downColor: DN, borderVisible: false, wickUpColor: UP, wickDownColor: DN});
const SERIES = [];  // {key, s, kind}
let pane = 0;
function buildInd() {
  SERIES.length = 0; pane = 0;
const line = (key, color, pane, opts = {}) => SERIES.push({key, s: chart.addSeries(L.LineSeries, {color, lineWidth: 1,
  priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, ...opts}, pane)});
if (I.volume_on) { const s = chart.addSeries(L.HistogramSeries, {priceFormat: {type: "volume"}, priceScaleId: "vol", lastValueVisible: false, priceLineVisible: false}, 0);
  s.priceScale().applyOptions({scaleMargins: {top: 0.82, bottom: 0}}); SERIES.push({key: "volume", s, kind: "vol"}); }
if (I.ema_on) { line("ema_fast", "#f5c518", 0, {lineWidth: 2, title: "EMA " + I.ema_fast}); line("ema_slow", "#ff7f0e", 0, {lineWidth: 2, title: "EMA " + I.ema_slow}); }
if (I.ema_trend_on) line("ema_trend", "#ab47bc", 0, {lineWidth: 2, title: "EMA " + I.ema_trend});
if (I.bb_on) { ["bb_up", "bb_mid", "bb_low"].forEach(k => line(k, "rgba(100,149,237,.75)", 0, {lineStyle: k === "bb_mid" ? 0 : 1})); }
if (I.vwap_on) line("vwap", "#00bcd4", 0, {lineWidth: 2, lineStyle: 2, title: "VWAP"});
if (I.supertrend_on) { line("st_up", UP, 0, {lineWidth: 2}); line("st_dn", DN, 0, {lineWidth: 2}); }
const guide = (s, v, c) => s.createPriceLine({price: v, color: c || "#5d606b", lineWidth: 1, lineStyle: 1, axisLabelVisible: false, title: ""});
if (I.rsi_on) { pane++; line("rsi", "#ab47bc", pane, {title: "RSI", lastValueVisible: true});
  const s = SERIES[SERIES.length - 1].s; guide(s, I.rsi_ob, DN); guide(s, I.rsi_os, UP); }
if (I.macd_on) { pane++; SERIES.push({key: "macd_hist", kind: "hist", s: chart.addSeries(L.HistogramSeries, {priceLineVisible: false, lastValueVisible: false}, pane)});
  line("macd", "#42a5f5", pane, {title: "MACD"}); line("macd_signal", "#ff7f0e", pane); }
if (I.stoch_on) { pane++; line("stoch_k", "#42a5f5", pane, {title: "Estoc."}); line("stoch_d", "#ff7f0e", pane);
  guide(SERIES[SERIES.length - 1].s, 80, DN); guide(SERIES[SERIES.length - 1].s, 20, UP); }
if (I.adx_on) { pane++; line("adx", "#fdd835", pane, {lineWidth: 2, title: "ADX"}); line("di_plus", UP, pane); line("di_minus", DN, pane);
  guide(SERIES[SERIES.length - 3].s, 25); }
if (I.obv_on) { pane++; line("obv", "#26c6da", pane, {title: "OBV"}); }
}
function destroyInd() { SERIES.forEach(x => chart.removeSeries(x.s)); SERIES.length = 0; }
buildInd();
function layoutPanes() {  // painel de preço com o espaço restante (mínimo 260 px); indicadores com altura fixa, menor se faltar espaço
  const ps = chart.panes(); if (ps.length < 2) return;
  const total = H - 40 - 30;  // desconta a escala de tempo
  const h = Math.max(70, Math.min(__PANE_H__, Math.floor((total - 260) / (ps.length - 1))));
  ps.forEach((p, i) => p.setHeight(i === 0 ? total - (ps.length - 1) * h : h));
}

const STYLE = {solid: 0, dotted: 1, dashed: 2};
C.lines.forEach(l => candles.createPriceLine({price: l.price, color: l.color, lineWidth: l.width || 1,
  lineStyle: STYLE[l.style || "dashed"], axisLabelVisible: true, title: l.title || ""}));
// Linhas de entrada das posições, com o P&L ao vivo no rótulo
const POS = C.positions.map(p => ({...p, sign: p.side === "BUY" ? 1 : -1,
  pl: candles.createPriceLine({price: p.entry, color: "#42a5f5", lineWidth: 2, lineStyle: 0, axisLabelVisible: true, title: ""})}));
new ResizeObserver(() => chart.applyOptions({width: document.body.clientWidth})).observe(document.body);

let data = [], ticks = 0, source = "", open24 = null;
const point = (c, v) => nan(v) ? {time: c.time} : {time: c.time, value: v};
function render(all) {
  const o = compute(data), n = data.length - 1;
  SERIES.forEach(({key, s, kind}) => {
    if (kind === "vol") { const pt = c => ({time: c.time, value: c.volume, color: c.close >= c.open ? "rgba(38,166,154,.45)" : "rgba(239,83,80,.45)"});
      all ? s.setData(data.map(pt)) : s.update(pt(data[n])); return; }
    const arr = o[key], pt = i => kind === "hist" ? (nan(arr[i]) ? {time: data[i].time} : {time: data[i].time, value: arr[i], color: arr[i] >= 0 ? "rgba(38,166,154,.6)" : "rgba(239,83,80,.6)"}) : point(data[i], arr[i]);
    all ? s.setData(data.map((c, i) => pt(i))) : s.update(pt(n));
  });
}
function setAll(rows) {
  data = rows; candles.setData(data); render(true); layoutPanes(); if (window.applyType) applyType();
  chart.timeScale().setVisibleLogicalRange({from: data.length - 150, to: data.length + 5});
  if (data.length) showPrice(data[data.length - 1]);
}
let pending = false;
function upsert(c) {
  const last = data[data.length - 1];
  if (last && c.time < last.time) return;
  if (last && c.time === last.time) data[data.length - 1] = c; else data.push(c);
  candles.update(c); ticks++; showPrice(c); if (window.refreshType && ctype !== "candle") refreshType(c);
  if (!pending) { pending = true; setTimeout(() => { pending = false; render(false); }, 200); }  // até 5 recálculos/s
}
function showPrice(c) {
  const prev = data.length > 1 ? data[data.length - 2].close : c.open;
  $("px").textContent = fmt(c.close); $("px").className = c.close >= prev ? "up" : "dn";
  if (open24) { const ch = (c.close / open24 - 1) * 100; $("chg").textContent = (ch >= 0 ? "+" : "") + ch.toFixed(2) + "% 24h"; $("chg").className = ch >= 0 ? "up" : "dn"; }
  $("ticks").textContent = ticks ? ticks + " atualizações" : "";
  if (POS.length) {
    let total = 0, margin = 0;
    POS.forEach(p => {
      // líquido: variação − taxa já paga na abertura − taxa estimada de saída
      const fx = p.fx || 1;
      const v = p.sign * (c.close - p.entry) * p.qty * fx - p.fees_paid - c.close * p.qty * fx * p.fee_pct / 100;
      total += v; margin += p.margin;
      p.pl.applyOptions({title: (p.side === "BUY" ? "COMPRA " : "VENDA ") + p.qty + "  " + money(v), color: v >= 0 ? UP : DN});
    });
    const el = $("pnl"); el.style.display = "";
    el.textContent = "P&L " + money(total) + " " + UNIT + " (" + (total / margin * 100).toFixed(1) + "% margem)";
    el.className = total >= 0 ? "up" : "dn";
  }
}
chart.subscribeCrosshairMove(p => {
  const c = p && p.seriesData && p.seriesData.get(candles);
  $("ohlc").innerHTML = c ? `A <b>${fmt(c.open)}</b> M <b>${fmt(c.high)}</b> m <b>${fmt(c.low)}</b> F <b>${fmt(c.close)}</b>` : "";
});
setInterval(() => {
  if (!data.length) return;
  const left = Math.max(0, Math.round(data[data.length - 1].utc + SEC - Date.now() / 1000));
  const h = Math.floor(left / 3600), m = Math.floor(left % 3600 / 60), s = left % 60;
  $("cd").textContent = (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(s).padStart(2, "0");
}, 1000);
function status(txt, cls) { $("st").textContent = txt; $("dot").className = cls || ""; }

__TOOLS__
// ------------------------------------------------------------------ fontes
const row = (t, o, h, l, c, v) => ({time: t / 1000 + TZ, utc: t / 1000, open: +o, high: +h, low: +l, close: +c, volume: +v});
const SOURCES = [];
const sl = C.symbol.toLowerCase();
if (C.demo) SOURCES.push({name: "Demonstração", kind: "demo"});
if (fut) SOURCES.push({name: "Binance Futuros", kind: "bn", rest: `https://fapi.binance.com/fapi/v1/klines?symbol=${C.symbol}&interval=${C.interval}&limit=1000`,
  t24: `https://fapi.binance.com/fapi/v1/ticker/24hr?symbol=${C.symbol}`, ws: `wss://fstream.binance.com/ws/${sl}@kline_${C.interval}`});
else {
  SOURCES.push({name: "Binance Spot", kind: "bn", rest: `https://api.binance.com/api/v3/klines?symbol=${C.symbol}&interval=${C.interval}&limit=1000`,
    t24: `https://api.binance.com/api/v3/ticker/24hr?symbol=${C.symbol}`, ws: `wss://stream.binance.com:443/ws/${sl}@kline_${C.interval}`});
  // Mesma Binance, porta oficial 9443 do WebSocket: alternativa quando a 443 é bloqueada na rede do usuário
  SOURCES.push({name: "Binance Spot (porta 9443)", kind: "bn", rest: `https://api.binance.com/api/v3/klines?symbol=${C.symbol}&interval=${C.interval}&limit=1000`,
    t24: `https://api.binance.com/api/v3/ticker/24hr?symbol=${C.symbol}`, ws: `wss://stream.binance.com:9443/ws/${sl}@kline_${C.interval}`});
  SOURCES.push({name: "Binance Spot (espelho)", kind: "bn", rest: `https://data-api.binance.vision/api/v3/klines?symbol=${C.symbol}&interval=${C.interval}&limit=1000`,
    t24: `https://data-api.binance.vision/api/v3/ticker/24hr?symbol=${C.symbol}`, ws: `wss://data-stream.binance.vision/ws/${sl}@kline_${C.interval}`});
}
SOURCES.push({name: fut ? "OKX Perpétuo" : "OKX Spot", kind: "okx"});
// Corretora escolhida pelo usuário: vem primeiro (a Bybit entra como fonte; a OKX já existe e só sobe na fila)
const BY_IV = {"1m":"1","3m":"3","5m":"5","15m":"15","30m":"30","1h":"60","2h":"120","4h":"240","6h":"360","12h":"720","1d":"D","1w":"W","1M":"M"}[C.interval];
if (C.prefer === "bybit" && BY_IV) SOURCES.unshift({name: fut ? "Bybit Perpétuo" : "Bybit Spot", kind: "bybit"});
if (C.prefer === "okx") SOURCES.unshift(SOURCES.splice(SOURCES.findIndex(x => x.kind === "okx"), 1)[0]);
if (C.demo) SOURCES.unshift(SOURCES.splice(SOURCES.findIndex(x => x.kind === "demo"), 1)[0]);

// Corretoras sem WebSocket de candles aqui: histórico pela API pública (REST) e atualização da vela a cada 2,5 s. Cada adaptador devolve
// linhas [ms, abertura, máxima, mínima, fechamento, volume]; se a corretora não tem o par ou o tempo gráfico, o gráfico passa à fonte seguinte.
const BASE = C.symbol.replace(/USDT$/, "");
const getJ = async url => { const r = await fetch(url); if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); };
const asc = rows => rows.sort((a, b) => a[0] - b[0]);
const IV = C.interval, NOW = () => Math.floor(Date.now() / 1000), STEP = SEC;
const pick = m => m[IV];
const ADAPT = {
  coinbase: () => { const g = pick({"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "6h": 21600, "1d": 86400}); if (!g || fut) return null;
    return {name: "Coinbase Spot", fetch: async n => asc((await getJ(`https://api.exchange.coinbase.com/products/${BASE}-USD/candles?granularity=${g}`)).slice(0, Math.min(n, 300))
      .map(k => [k[0] * 1000, k[3], k[2], k[1], k[4], k[5]]))}; },
  kraken: () => { const i = pick({"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440, "1w": 10080}); if (!i || fut) return null;
    const pair = (BASE === "BTC" ? "XBT" : BASE) + "USDT";
    return {name: "Kraken Spot", fetch: async n => { const j = await getJ(`https://api.kraken.com/0/public/OHLC?pair=${pair}&interval=${i}`);
      if (j.error && j.error.length) throw new Error(j.error[0]); const key = Object.keys(j.result).find(x => x !== "last");
      return j.result[key].slice(-n).map(k => [k[0] * 1000, k[1], k[2], k[3], k[4], k[6]]); }}; },
  kucoin: () => {
    if (fut) { const g = pick({"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "2h": 120, "4h": 240, "12h": 720, "1d": 1440, "1w": 10080}); if (!g) return null;
      return {name: "KuCoin Perpétuo", fetch: async n => { const to = Date.now(); const j = await getJ(`https://api-futures.kucoin.com/api/v1/kline/query?symbol=${BASE === "BTC" ? "XBT" : BASE}USDTM&granularity=${g}&from=${to - n * STEP * 1000}&to=${to}`);
        return j.data.map(k => [k[0], k[1], k[2], k[3], k[4], k[5]]); }}; }
    const t = pick({"1m": "1min", "3m": "3min", "5m": "5min", "15m": "15min", "30m": "30min", "1h": "1hour", "2h": "2hour", "4h": "4hour", "6h": "6hour", "12h": "12hour", "1d": "1day", "1w": "1week"}); if (!t) return null;
    return {name: "KuCoin Spot", fetch: async n => { const e = NOW(); const j = await getJ(`https://api.kucoin.com/api/v1/market/candles?type=${t}&symbol=${BASE}-USDT&startAt=${e - Math.min(n, 1500) * STEP}&endAt=${e}`);
      return asc(j.data.map(k => [k[0] * 1000, k[1], k[3], k[4], k[2], k[5]])); }}; },
  bitget: () => {
    const g = fut ? pick({"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1H", "4h": "4H", "6h": "6H", "12h": "12H", "1d": "1D", "1w": "1W"})
      : pick({"1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min", "1h": "1h", "4h": "4h", "6h": "6h", "12h": "12h", "1d": "1day", "1w": "1week"}); if (!g) return null;
    const url = fut ? `https://api.bitget.com/api/v2/mix/market/candles?symbol=${C.symbol}&productType=USDT-FUTURES&granularity=${g}&limit=` : `https://api.bitget.com/api/v2/spot/market/candles?symbol=${C.symbol}&granularity=${g}&limit=`;
    return {name: fut ? "Bitget Perpétuo" : "Bitget Spot", fetch: async n => asc((await getJ(url + Math.min(n, 1000))).data.map(k => [+k[0], k[1], k[2], k[3], k[4], k[5]]))}; },
  gate: () => { const i = pick(fut ? {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1h", "2h": "2h", "4h": "4h", "6h": "6h", "12h": "12h", "1d": "1d", "1w": "7d"}
      : {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1h", "4h": "4h", "1d": "1d", "1w": "7d"}); if (!i) return null;
    return {name: fut ? "Gate Perpétuo" : "Gate Spot", fetch: async n => { const lim = Math.min(n, 1000);
      if (fut) return asc((await getJ(`https://api.gateio.ws/api/v4/futures/usdt/candlesticks?contract=${BASE}_USDT&interval=${i}&limit=${lim}`)).map(k => [k.t * 1000, k.o, k.h, k.l, k.c, k.v]));
      return asc((await getJ(`https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair=${BASE}_USDT&interval=${i}&limit=${lim}`)).map(k => [k[0] * 1000, k[5], k[3], k[4], k[2], k[6]])); }}; },
  mexc: () => {
    if (fut) { const i = pick({"1m": "Min1", "5m": "Min5", "15m": "Min15", "30m": "Min30", "1h": "Min60", "4h": "Hour4", "8h": "Hour8", "1d": "Day1", "1w": "Week1"}); if (!i) return null;
      return {name: "MEXC Perpétuo", fetch: async n => { const e = NOW(); const d = (await getJ(`https://contract.mexc.com/api/v1/contract/kline/${BASE}_USDT?interval=${i}&start=${e - n * STEP}&end=${e}`)).data;
        return d.time.map((t, x) => [t * 1000, d.open[x], d.high[x], d.low[x], d.close[x], d.vol[x]]); }}; }
    const i = pick({"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "60m", "4h": "4h", "1d": "1d", "1w": "1W"}); if (!i) return null;
    return {name: "MEXC Spot", fetch: async n => asc((await getJ(`https://api.mexc.com/api/v3/klines?symbol=${C.symbol}&interval=${i}&limit=${Math.min(n, 1000)}`)).map(k => [k[0], k[1], k[2], k[3], k[4], k[5]]))}; },
  htx: () => { const p = pick({"1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min", "1h": "60min", "4h": "4hour", "1d": "1day", "1w": "1week"}); if (!p) return null;
    const url = fut ? `https://api.hbdm.com/linear-swap-ex/market/history/kline?contract_code=${BASE}-USDT&period=${p}&size=` : `https://api.huobi.pro/market/history/kline?symbol=${BASE.toLowerCase()}usdt&period=${p}&size=`;
    return {name: fut ? "HTX Perpétuo" : "HTX Spot", fetch: async n => { const j = await getJ(url + Math.min(n, 1000)); if (j.status && j.status !== "ok") throw new Error("HTX sem dados");
      return asc(j.data.map(k => [k.id * 1000, k.open, k.high, k.low, k.close, k.amount != null ? k.amount : k.vol])); }}; },
  bingx: () => { const i = pick({"1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1h", "2h": "2h", "4h": "4h", "6h": "6h", "8h": "8h", "12h": "12h", "1d": "1d", "3d": "3d", "1w": "1w", "1M": "1M"}); if (!i) return null;
    const url = fut ? `https://open-api.bingx.com/openApi/swap/v3/quote/klines?symbol=${BASE}-USDT&interval=${i}&limit=` : `https://open-api.bingx.com/openApi/spot/v2/market/kline?symbol=${BASE}-USDT&interval=${i}&limit=`;
    return {name: fut ? "BingX Perpétuo" : "BingX Spot", fetch: async n => asc((await getJ(url + Math.min(n, 1000))).data.map(k => Array.isArray(k) ? [+k[0], k[1], k[2], k[3], k[4], k[5]] : [+k.time, k.open, k.high, k.low, k.close, k.volume]))}; },
};
if (ADAPT[C.prefer]) { const a = ADAPT[C.prefer](); if (a) SOURCES.unshift({kind: "poll", ...a}); }
if (C.demo) SOURCES.unshift(SOURCES.splice(SOURCES.findIndex(x => x.kind === "demo"), 1)[0]);
const byCat = fut ? "linear" : "spot";
const byRow = k => row(+k[0], k[1], k[2], k[3], k[4], k[5]);
async function bybitHistory() {
  const r = await fetch(`https://api.bybit.com/v5/market/kline?category=${byCat}&symbol=${C.symbol}&interval=${BY_IV}&limit=1000`);
  const j = await r.json(); if (j.retCode !== 0 || !j.result.list.length) throw new Error("Bybit sem dados");
  return j.result.list.reverse().map(byRow);
}

async function okxHistory() {
  let rows = [], after = "", url = "candles";
  for (let i = 0; i < 4 && rows.length < 1000; i++) {
    const r = await fetch(`https://www.okx.com/api/v5/market/${url}?instId=${okxInst}&bar=${OKX_BAR}&limit=${url === "candles" ? 300 : 100}${after ? "&after=" + after : ""}`);
    const j = await r.json(); if (j.code !== "0" || !j.data.length) break;
    rows = rows.concat(j.data); after = j.data[j.data.length - 1][0]; url = "history-candles";
  }
  if (!rows.length) throw new Error("OKX sem dados");
  try { const t = await (await fetch(`https://www.okx.com/api/v5/market/ticker?instId=${okxInst}`)).json(); open24 = +t.data[0].open24h * M; } catch (e) {}
  return rows.reverse().map(okxRow);
}
async function history(src) {
  if (src.kind === "demo") return C.demo.map(k => row(k[0], k[1], k[2], k[3], k[4], k[5]));
  if (src.kind === "okx") return okxHistory();
  if (src.kind === "bybit") return bybitHistory();
  if (src.kind === "poll") {
    const rows = await src.fetch(1000); if (!rows.length) throw new Error(src.name + " sem dados");
    const ref = rows.filter(k => k[0] <= rows[rows.length - 1][0] - 86400000).pop(); if (ref) open24 = +ref[4];   // variação de 24 h pelo fechamento de um dia antes
    return rows.map(k => row(k[0], k[1], k[2], k[3], k[4], k[5]));
  }
  const r = await fetch(src.rest); if (!r.ok) throw new Error("HTTP " + r.status);
  try { open24 = +(await (await fetch(src.t24)).json()).openPrice; } catch (e) {}
  return (await r.json()).map(k => row(k[0], k[1], k[2], k[3], k[4], k[5]));
}

let ws = null, retry = 0, pingTimer = null;
function stream(i) {
  const src = SOURCES[i]; if (!src) { status("sem fluxo ao vivo — recarregue a página", "err"); return; }
  if (src.kind === "demo") { status("demonstração (sem fluxo ao vivo)", "live"); return; }
  if (src.kind === "poll") {   // sem WebSocket: confere as últimas velas a cada 2,5 s
    status("ao vivo · " + src.name + " (atualiza a cada 2,5 s)", "live"); clearInterval(pingTimer);
    pingTimer = setInterval(async () => { try { (await src.fetch(4)).forEach(k => upsert(row(k[0], k[1], k[2], k[3], k[4], k[5]))); } catch (e) {} }, 2500);
    return;
  }
  let opened = false;
  status("conectando a " + src.name + "…");
  ws = new WebSocket(src.kind === "okx" ? "wss://ws.okx.com/ws/v5/business" : src.kind === "bybit" ? "wss://stream.bybit.com/v5/public/" + byCat : src.ws);
  const failover = setTimeout(() => { if (!opened) { ws.onclose = null; ws.close(); stream(i + 1); } }, 6000);
  ws.onopen = () => {
    if (src.kind === "bybit") {
      ws.send(JSON.stringify({op: "subscribe", args: [`kline.${BY_IV}.${C.symbol}`]}));
      clearInterval(pingTimer); pingTimer = setInterval(() => ws.readyState === 1 && ws.send(JSON.stringify({op: "ping"})), 20000);
    }
    if (src.kind === "okx") {
      ws.send(JSON.stringify({op: "subscribe", args: [{channel: "candle" + OKX_BAR, instId: okxInst}]}));
      clearInterval(pingTimer); pingTimer = setInterval(() => ws.readyState === 1 && ws.send("ping"), 20000);
    }
  };
  ws.onmessage = ev => {
    if (ev.data === "pong") return;
    const m = JSON.parse(ev.data);
    let c = null;
    if (src.kind === "bn" && m.k) c = row(m.k.t, m.k.o, m.k.h, m.k.l, m.k.c, m.k.v);
    if (src.kind === "okx" && m.data) c = okxRow(m.data[0]);
    if (src.kind === "bybit" && m.topic && m.data && m.data[0]) c = byRow([m.data[0].start, m.data[0].open, m.data[0].high, m.data[0].low, m.data[0].close, m.data[0].volume]);
    if (!c) return;
    if (!opened) { opened = true; clearTimeout(failover); retry = 0; status("ao vivo · " + src.name + (source && source !== src.name ? " (histórico: " + source + ")" : ""), "live"); }
    upsert(c);
  };
  ws.onclose = () => {
    clearTimeout(failover);
    if (!opened) { stream(i + 1); return; }
    status("reconectando…", "err");
    setTimeout(() => stream(i), Math.min(30000, 1000 * 2 ** retry++));
  };
}
(async () => {
  for (let i = 0; i < SOURCES.length; i++) {
    try { setAll(await history(SOURCES[i])); source = SOURCES[i].name; stream(i); return; }
    catch (e) { console.warn(SOURCES[i].name, e); }
  }
  status("não foi possível carregar dados no navegador", "err");
})();
// Ao voltar para a aba, sincroniza o histórico (o navegador pode pausar o WebSocket em segundo plano)
document.addEventListener("visibilitychange", async () => {
  if (document.visibilityState !== "visible" || !source) return;
  try { const lr = chart.timeScale().getVisibleLogicalRange(); setAll(await history(SOURCES.find(s => s.name === source)));
    if (lr) chart.timeScale().setVisibleLogicalRange(lr); } catch (e) {}
});
</script></body></html>""".replace("__PANE_H__", str(PANE_HEIGHT))
