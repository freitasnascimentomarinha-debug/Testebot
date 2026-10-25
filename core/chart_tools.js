// ============================================================== ferramentas do gráfico em tempo real
// Barra de ferramentas (desenho, ordens pelo gráfico), tipos de vela, escala logarítmica, indicadores ligáveis no próprio gráfico
// e linhas de stop/alvo arrastáveis. Roda dentro do iframe do gráfico; as ações que mexem na conta (ordem limite, stop/alvo,
// zerar, cancelar) vão por postMessage para a página, que as valida e executa (core/ui.py → chart_bridge).
const LS = (() => { try { return window.localStorage; } catch (e) { return null; } })();
const lsGet = (k, d) => { try { const v = JSON.parse(LS.getItem(k)); return v == null ? d : v; } catch (e) { return d; } };
const lsSet = (k, v) => { try { LS.setItem(k, JSON.stringify(v)); } catch (e) {} };
const send = msg => { try { window.parent.postMessage({tb: 1, symbol: C.symbol, market: C.market, uid: Date.now() + "-" + Math.random().toString(36).slice(2, 7), ...msg}, "*"); } catch (e) {} };
const chartEl = $("chart");

// ---------------------------------------------------------------- coordenadas (tempo e preço ↔ pixels)
const idxOfTime = t => {
  const n = data.length; if (!n) return 0;
  if (t >= data[n - 1].time) return n - 1 + (t - data[n - 1].time) / SEC;
  if (t <= data[0].time) return (t - data[0].time) / SEC;
  let lo = 0, hi = n - 1;
  while (hi - lo > 1) { const m = (lo + hi) >> 1; if (data[m].time <= t) lo = m; else hi = m; }
  return lo + (t - data[lo].time) / Math.max(1, data[hi].time - data[lo].time);
};
const timeOfIdx = i => {
  const n = data.length; if (!n) return 0;
  if (i >= n - 1) return data[n - 1].time + (i - (n - 1)) * SEC;
  if (i <= 0) return data[0].time + i * SEC;
  const lo = Math.floor(i);
  return data[lo].time + (i - lo) * (data[lo + 1].time - data[lo].time);
};
const xOf = t => chart.timeScale().logicalToCoordinate(idxOfTime(t));
const yOf = p => candles.priceToCoordinate(p);
function paneBox() {  // área do preço, em pixels do contêiner
  const ps = chart.panes();
  return {w: chart.timeScale().width(), h: ps.length ? ps[0].getHeight() : chartEl.clientHeight};
}
function pointFromEvent(e) {
  const r = chartEl.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top, b = paneBox();
  if (x < 0 || y < 0 || x > b.w || y > b.h) return null;
  const lg = chart.timeScale().coordinateToLogical(x), pr = candles.coordinateToPrice(y);
  if (lg == null || pr == null) return null;
  return {x, y, t: timeOfIdx(lg), p: pr};
}

// ---------------------------------------------------------------- desenhos
const DKEY = "tb_draw_" + C.market + "_" + C.symbol;
let DRAW = lsGet(DKEY, []).filter(d => d && d.type && d.p1);   // {id, type, p1:{t,p}, p2:{t,p}, color}  (t = tempo do gráfico)
let draft = null, selected = null, tool = "cursor", ruler = null;
const COLORS = {line: "#ffd54f", hline: "#42a5f5", rect: "#ab47bc", fib: "#ff9800"};
const FIB = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1];
const saveDraw = () => lsSet(DKEY, DRAW);
const uid = () => Math.random().toString(36).slice(2, 9);

class DrawView {
  renderer() { return {draw: target => target.useMediaCoordinateSpace(({context: ctx, mediaSize}) => paintAll(ctx, mediaSize))}; }
}
class DrawPrimitive {
  constructor() { this._v = [new DrawView()]; }
  attached(p) { this._req = p.requestUpdate; }
  detached() {}
  paneViews() { return this._v; }
  update() { if (this._req) this._req(); }
}
const prim = new DrawPrimitive();
candles.attachPrimitive(prim);
const redraw = () => prim.update();

function seg(ctx, x1, y1, x2, y2) { ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke(); }
function label(ctx, txt, x, y, color) {
  ctx.font = "11px system-ui,sans-serif"; const w = ctx.measureText(txt).width + 8;
  ctx.fillStyle = "rgba(14,17,23,.85)"; ctx.fillRect(x, y - 8, w, 16); ctx.fillStyle = color || "#d1d4dc"; ctx.fillText(txt, x + 4, y + 4);
}
function paintOne(ctx, d, size, sel) {
  const x1 = xOf(d.p1.t), y1 = yOf(d.p1.p), color = d.color || COLORS[d.type] || "#ffd54f";
  if (y1 == null) return;
  ctx.lineWidth = sel ? 2.5 : 1.5; ctx.strokeStyle = color; ctx.fillStyle = color; ctx.setLineDash([]);
  if (d.type === "hline") {
    seg(ctx, 0, y1, size.width, y1); label(ctx, fmt(d.p1.p), 6, y1 - 10, color); return;
  }
  const x2 = xOf(d.p2.t), y2 = yOf(d.p2.p);
  if (x1 == null || x2 == null || y2 == null) return;
  if (d.type === "line") {
    seg(ctx, x1, y1, x2, y2);
  } else if (d.type === "rect") {
    ctx.globalAlpha = .15; ctx.fillRect(Math.min(x1, x2), Math.min(y1, y2), Math.abs(x2 - x1), Math.abs(y2 - y1)); ctx.globalAlpha = 1;
    ctx.strokeRect(Math.min(x1, x2), Math.min(y1, y2), Math.abs(x2 - x1), Math.abs(y2 - y1));
  } else if (d.type === "fib") {
    const xa = Math.min(x1, x2), xb = Math.max(x1, x2, size.width - 60);
    ctx.setLineDash([4, 3]); seg(ctx, x1, y1, x2, y2); ctx.setLineDash([]);
    FIB.forEach(r => {
      const price = d.p2.p + (d.p1.p - d.p2.p) * r, y = yOf(price); if (y == null) return;
      ctx.globalAlpha = .75; seg(ctx, xa, y, xb, y); ctx.globalAlpha = 1;
      label(ctx, (r * 100).toFixed(1).replace(".0", "") + "%  " + fmt(price), xa + 4, y - 9, color);
    });
  }
  if (sel) [[x1, y1], [x2, y2]].forEach(([x, y]) => { ctx.fillStyle = "#fff"; ctx.beginPath(); ctx.arc(x, y, 4, 0, 7); ctx.fill(); });
}
function paintRuler(ctx, r) {
  const x1 = xOf(r.p1.t), y1 = yOf(r.p1.p), x2 = xOf(r.p2.t), y2 = yOf(r.p2.p);
  if (x1 == null || x2 == null || y1 == null || y2 == null) return;
  const up = r.p2.p >= r.p1.p, c = up ? UP : DN;
  ctx.globalAlpha = .15; ctx.fillStyle = c; ctx.fillRect(Math.min(x1, x2), Math.min(y1, y2), Math.abs(x2 - x1), Math.abs(y2 - y1)); ctx.globalAlpha = 1;
  ctx.strokeStyle = c; ctx.lineWidth = 1; ctx.setLineDash([4, 3]); seg(ctx, x1, y1, x2, y2); ctx.setLineDash([]);
  const dp = r.p2.p - r.p1.p, bars = Math.round(idxOfTime(r.p2.t) - idxOfTime(r.p1.t)), secs = Math.abs(r.p2.t - r.p1.t);
  const dur = secs >= 86400 ? (secs / 86400).toFixed(1) + " d" : secs >= 3600 ? (secs / 3600).toFixed(1) + " h" : Math.round(secs / 60) + " min";
  label(ctx, `${dp >= 0 ? "+" : ""}${fmt(dp)} (${(dp / r.p1.p * 100).toFixed(2)}%) · ${Math.abs(bars)} velas · ${dur}`, Math.min(x1, x2) + 6, Math.min(y1, y2) - 12, c);
}
function paintAll(ctx, size) {
  DRAW.forEach(d => paintOne(ctx, d, size, d.id === selected));
  if (draft) paintOne(ctx, draft, size, false);
  if (ruler) paintRuler(ctx, ruler);
}

// distância (px) de um ponto ao desenho, para selecionar/arrastar
function hit(d, x, y) {
  const y1 = yOf(d.p1.p); if (y1 == null) return 1e9;
  if (d.type === "hline") return Math.abs(y - y1);
  const x1 = xOf(d.p1.t), x2 = xOf(d.p2.t), y2 = yOf(d.p2.p); if (x1 == null || x2 == null || y2 == null) return 1e9;
  if (d.type === "line") {
    const dx = x2 - x1, dy = y2 - y1, l2 = dx * dx + dy * dy || 1, t = Math.max(0, Math.min(1, ((x - x1) * dx + (y - y1) * dy) / l2));
    return Math.hypot(x - (x1 + t * dx), y - (y1 + t * dy));
  }
  if (d.type === "rect") {
    const inX = x >= Math.min(x1, x2) - 4 && x <= Math.max(x1, x2) + 4, inY = y >= Math.min(y1, y2) - 4 && y <= Math.max(y1, y2) + 4;
    if (!inX || !inY) return 1e9;
    return Math.min(Math.abs(x - x1), Math.abs(x - x2), Math.abs(y - y1), Math.abs(y - y2));
  }
  if (d.type === "fib") {
    let best = 1e9; const xa = Math.min(x1, x2), xb = Math.max(x1, x2, paneBox().w - 60);
    if (x < xa - 4 || x > xb + 4) return best;
    FIB.forEach(r => { const yy = yOf(d.p2.p + (d.p1.p - d.p2.p) * r); if (yy != null) best = Math.min(best, Math.abs(y - yy)); });
    return best;
  }
  return 1e9;
}

// ---------------------------------------------------------------- barra de ferramentas
const TOOLS = [["cursor", "✥", "Selecionar / mover (Delete apaga)"], ["line", "╱", "Linha de tendência"], ["hline", "─", "Linha horizontal"],
  ["rect", "▭", "Retângulo"], ["fib", "𝔽", "Retração de Fibonacci"], ["ruler", "📏", "Régua de medição"], ["order", "🛒", "Ordem limite pelo gráfico"]];
const tb = document.createElement("div"); tb.id = "tools";
tb.innerHTML = TOOLS.map(([k, ico, tip]) => `<button data-tool="${k}" title="${tip}">${ico}</button>`).join("") +
  `<button id="t-del" title="Apagar o desenho selecionado">⌫</button><button id="t-clear" title="Apagar todos os desenhos deste ativo">🗑</button>`;
document.body.appendChild(tb);
function setTool(t) {
  tool = t; draft = null; if (t !== "ruler") ruler = null; hidePop();
  tb.querySelectorAll("button[data-tool]").forEach(b => b.classList.toggle("on", b.dataset.tool === t));
  chartEl.style.cursor = t === "cursor" ? "" : "crosshair"; redraw();
}
tb.addEventListener("click", e => { const b = e.target.closest("button"); if (!b) return;
  if (b.dataset.tool) setTool(b.dataset.tool === tool ? "cursor" : b.dataset.tool);
  else if (b.id === "t-del") deleteSelected();
  else if (b.id === "t-clear" && DRAW.length && confirm("Apagar todos os desenhos de " + C.symbol + "?")) { DRAW = []; selected = null; saveDraw(); redraw(); } });
function deleteSelected() { if (selected) { DRAW = DRAW.filter(d => d.id !== selected); selected = null; saveDraw(); redraw(); } }
document.addEventListener("keydown", e => {
  if (e.key === "Delete" || e.key === "Backspace") deleteSelected();
  if (e.key === "Escape") { setTool("cursor"); selected = null; redraw(); }
});

// ---------------------------------------------------------------- menu: tipo de vela, escala, indicadores
const bar = $("bar");
const menu = document.createElement("span"); menu.id = "menu";
menu.innerHTML = `<select id="ctype" title="Tipo de vela"><option value="candle">Velas</option><option value="ha">Heikin-Ashi</option><option value="line">Linha</option><option value="area">Área</option></select>
<label class="chk" title="Escala logarítmica"><input type="checkbox" id="logs"> Log</label>
<button id="indbtn" title="Indicadores no gráfico">Indicadores ▾</button>`;
bar.appendChild(menu);
const indBox = document.createElement("div"); indBox.id = "indbox"; indBox.style.display = "none";
const INDS = [["ema_on", "Médias (EMA rápida/lenta)"], ["ema_trend_on", "EMA de tendência"], ["bb_on", "Bollinger"], ["vwap_on", "VWAP"], ["supertrend_on", "SuperTrend"],
  ["volume_on", "Volume"], ["rsi_on", "RSI"], ["macd_on", "MACD"], ["stoch_on", "Estocástico"], ["adx_on", "ADX / DMI"], ["obv_on", "OBV"]];
indBox.innerHTML = INDS.map(([k, n]) => `<label><input type="checkbox" data-ind="${k}"> ${n}</label>`).join("") +
  `<div class="mut" style="margin-top:4px">Só altera a exibição neste gráfico; os períodos ficam em Configurações.</div>`;
document.body.appendChild(indBox);
$("indbtn").onclick = () => { indBox.style.display = indBox.style.display === "none" ? "block" : "none"; };
const IKEY = "tb_ind_" + C.market, DEF = JSON.stringify(INDS.map(([k]) => !!I[k]));
const saved = lsGet(IKEY, null);
if (saved && saved.def === DEF) INDS.forEach(([k]) => { if (k in saved.on) I[k] = saved.on[k]; });   // padrão mudou na página: vale o novo
function syncInd() { indBox.querySelectorAll("input[data-ind]").forEach(c => { c.checked = !!I[c.dataset.ind]; }); }
indBox.addEventListener("change", e => {
  const k = e.target.dataset.ind; if (!k) return;
  I[k] = e.target.checked; lsSet(IKEY, {def: DEF, on: Object.fromEntries(INDS.map(([n]) => [n, !!I[n]]))});
  destroyInd(); buildInd(); render(true); layoutPanes();
});
syncInd();

let ctype = lsGet("tb_ctype", "candle");
$("ctype").value = ctype;
const lineSeries = chart.addSeries(L.LineSeries, {color: "#42a5f5", lineWidth: 2, priceLineVisible: false, lastValueVisible: false, visible: false});
const areaSeries = chart.addSeries(L.AreaSeries, {lineColor: "#42a5f5", topColor: "rgba(66,165,245,.35)", bottomColor: "rgba(66,165,245,0)", priceLineVisible: false,
  lastValueVisible: false, visible: false});
function haRows() {
  const out = []; let pO = null, pC = null;
  data.forEach(c => { const hc = (c.open + c.high + c.low + c.close) / 4, ho = pO === null ? (c.open + c.close) / 2 : (pO + pC) / 2;
    out.push({time: c.time, open: ho, high: Math.max(c.high, ho, hc), low: Math.min(c.low, ho, hc), close: hc}); pO = ho; pC = hc; });
  return out;
}
function applyType() {   // os dados do tipo escolhido substituem os da série de velas
  candles.applyOptions({visible: ctype === "candle" || ctype === "ha"});
  lineSeries.applyOptions({visible: ctype === "line"}); areaSeries.applyOptions({visible: ctype === "area"});
  if (!data.length) return;
  candles.setData(ctype === "ha" ? haRows() : data);
  if (ctype === "line") lineSeries.setData(data.map(c => ({time: c.time, value: c.close})));
  if (ctype === "area") areaSeries.setData(data.map(c => ({time: c.time, value: c.close})));
}
$("ctype").onchange = e => { ctype = e.target.value; lsSet("tb_ctype", ctype); applyType(); };
$("logs").checked = lsGet("tb_log", false);
const applyLog = () => chart.priceScale("right").applyOptions({mode: $("logs").checked ? 1 : 0});
$("logs").onchange = () => { lsSet("tb_log", $("logs").checked); applyLog(); };
applyLog();
// quando chegam dados novos, o tipo de vela escolhido acompanha
function refreshType(c) {
  if (ctype === "ha") { const h = haRows(); candles.update(h[h.length - 1]); }
  else if (ctype === "line") lineSeries.update({time: c.time, value: c.close});
  else if (ctype === "area") areaSeries.update({time: c.time, value: c.close});
}

// ---------------------------------------------------------------- ordens, posições e stops arrastáveis
const popup = document.createElement("div"); popup.id = "pop"; popup.style.display = "none"; document.body.appendChild(popup);
const hidePop = () => { popup.style.display = "none"; };
const lastPx = () => data.length ? data[data.length - 1].close : null;
function openOrderPopup(pt) {
  const buy = `<button data-side="BUY" class="b">Comprar limite @ ${fmt(pt.p)}</button>`;
  const sell = fut ? `<button data-side="SELL" class="s">Vender limite @ ${fmt(pt.p)}</button>` : "";
  popup.innerHTML = `<b>Ordem limite</b>${buy}${sell}<button data-side="">Cancelar</button>
    <div class="mut">Tamanho pela perda máxima por trade; stop e alvo pelo ATR (Entrada do bot).</div>`;
  popup.style.left = Math.min(pt.x + 12, chartEl.clientWidth - 230) + "px"; popup.style.top = Math.max(40, pt.y - 20) + "px"; popup.style.display = "block";
  popup.onclick = e => { const b = e.target.closest("button"); if (!b) return; hidePop();
    if (b.dataset.side) send({kind: "limit", side: b.dataset.side, price: pt.p}); setTool("cursor"); };
}
// linhas de stop/alvo/liquidação das posições e ordens pendentes (arrastar stop/alvo muda a proteção)
const PL = [];   // {pos, kind: "sl"|"tp"|"liq", line}
// resultado líquido da posição se o preço chegar a ``price`` (já com a taxa de entrada e a estimada de saída): é o P&L mostrado no stop e no alvo
const netAt = (p, price) => { const fx = p.fx || 1;
  return p.sign * (price - p.entry) * p.qty * fx - p.fees_paid - price * p.qty * fx * p.fee_pct / 100; };
const NAMES = {sl: "SL ↕", tp: "TP ↕", liq: "Liq."};
const lineTitle = (p, kind, price) => NAMES[kind] + "  " + money(netAt(p, price)) + " " + UNIT;
POS.forEach(p => {
  const mk = (kind, price, color) => { if (price) PL.push({pos: p, kind, line: candles.createPriceLine({price, color, lineWidth: 1, lineStyle: kind === "liq" ? 1 : 2,
    axisLabelVisible: true, title: lineTitle(p, kind, price)})}); };
  mk("sl", p.stop_loss, DN); mk("tp", p.take_profit, UP); mk("liq", p.liquidation, "#ff9800");
});
const OL = (C.orders || []).map(o => ({o, line: candles.createPriceLine({price: o.price, color: "#bdbdbd", lineWidth: 1, lineStyle: 2, axisLabelVisible: true,
  title: "LIMIT " + (o.side === "BUY" ? "COMPRA " : "VENDA ") + o.qty + " ✕"})}));
let dragLine = null;
const near = (y, price) => { const yy = yOf(price); return yy != null && Math.abs(y - yy) <= 6; };
function validProtect(p, kind, price) {
  const long = p.side === "BUY";
  if (kind === "sl") return long ? price < p.entry : price > p.entry;
  return long ? price > p.entry : price < p.entry;
}

// ---------------------------------------------------------------- mouse
let down = null;
chartEl.addEventListener("pointerdown", e => {
  const pt = pointFromEvent(e); if (!pt) return; hidePop();
  down = {x: e.clientX, y: e.clientY, pt, moved: false, drag: null};
  if (tool === "cursor") {
    const dl = PL.find(l => l.kind !== "liq" && near(pt.y, l.line.options().price));
    if (dl) { dragLine = dl; down.drag = "line"; chart.applyOptions({handleScroll: false, handleScale: false}); return; }
    const best = DRAW.map(d => [hit(d, pt.x, pt.y), d]).filter(a => a[0] < 7).sort((a, b) => a[0] - b[0])[0];
    selected = best ? best[1].id : null; redraw();
    if (best) { down.drag = {d: best[1], p1: {...best[1].p1}, p2: best[1].p2 ? {...best[1].p2} : null, lg: chart.timeScale().coordinateToLogical(pt.x), pr: pt.p};
      chart.applyOptions({handleScroll: false, handleScale: false}); }
  }
});
window.addEventListener("pointermove", e => {
  const pt = pointFromEvent(e);
  if (down && Math.hypot(e.clientX - down.x, e.clientY - down.y) > 4) down.moved = true;
  if (down && down.drag === "line" && pt) {   // o rótulo mostra o P&L líquido que a posição teria se o preço chegar aqui
    dragLine.line.applyOptions({price: pt.p, title: lineTitle(dragLine.pos, dragLine.kind, pt.p)}); return; }
  if (down && down.drag && down.drag.d && pt) {            // mover desenho inteiro
    const dl = chart.timeScale().coordinateToLogical(pt.x) - down.drag.lg, dp = pt.p - down.drag.pr, d = down.drag.d;
    const sh = (o, base) => ({t: timeOfIdx(idxOfTime(base.t) + dl), p: base.p + dp});
    d.p1 = sh(d.p1, down.drag.p1); if (d.p2) d.p2 = sh(d.p2, down.drag.p2); redraw(); return;
  }
  if (!pt) return;
  if (draft) { draft.p2 = {t: pt.t, p: pt.p}; redraw(); }
  if (ruler && !ruler.done) { ruler.p2 = {t: pt.t, p: pt.p}; redraw(); }
});
window.addEventListener("pointerup", e => {
  if (!down) return; const was = down; down = null;
  chart.applyOptions({handleScroll: true, handleScale: true});
  if (was.drag === "line") {                                 // soltou uma linha de stop/alvo
    const pt = pointFromEvent(e), l = dragLine; dragLine = null;
    const price = pt ? pt.p : l.line.options().price, prev = l.kind === "sl" ? l.pos.stop_loss : l.pos.take_profit;
    const back = () => l.line.applyOptions({price: prev, title: lineTitle(l.pos, l.kind, prev)});
    if (!pt || !validProtect(l.pos, l.kind, price)) { back(); return; }
    if (confirm((l.kind === "sl" ? "Mover o STOP" : "Mover o ALVO") + " para " + fmt(price) + "?\nResultado se for atingido: " + money(netAt(l.pos, price)) + " " + UNIT)) {
      if (l.kind === "sl") l.pos.stop_loss = price; else l.pos.take_profit = price;
      l.line.applyOptions({title: lineTitle(l.pos, l.kind, price)});
      send({kind: "protect", id: l.pos.id, stop_loss: l.pos.stop_loss || null, take_profit: l.pos.take_profit || null});
    } else back();
    return;
  }
  if (was.drag && was.drag.d) { saveDraw(); return; }
  if (was.moved) return;                                     // foi arrasto do gráfico, não clique
  const pt = was.pt;
  if (tool === "cursor") {                                   // clique sobre a linha de uma ordem pendente cancela
    const ol = OL.find(x => near(pt.y, x.o.price));
    if (ol && confirm("Cancelar a ordem limite em " + fmt(ol.o.price) + "?")) send({kind: "cancel_order", id: ol.o.id});
    return;
  }
  if (tool === "hline") { DRAW.push({id: uid(), type: "hline", p1: {t: pt.t, p: pt.p}, color: COLORS.hline}); saveDraw(); setTool("cursor"); return; }
  if (tool === "order") { openOrderPopup(pt); return; }
  if (tool === "ruler") {
    if (ruler && !ruler.done) { ruler.done = true; ruler.p2 = {t: pt.t, p: pt.p}; } else ruler = {p1: {t: pt.t, p: pt.p}, p2: {t: pt.t, p: pt.p}, done: false};
    redraw(); return;
  }
  if (tool === "line" || tool === "rect" || tool === "fib") {
    if (!draft) draft = {id: uid(), type: tool, p1: {t: pt.t, p: pt.p}, p2: {t: pt.t, p: pt.p}, color: COLORS[tool]};
    else { draft.p2 = {t: pt.t, p: pt.p}; DRAW.push(draft); selected = draft.id; draft = null; saveDraw(); setTool("cursor"); }
    redraw();
  }
});
// zerar posições (botão ao lado do P&L)
const closeBtn = document.createElement("button"); closeBtn.id = "closebtn"; closeBtn.textContent = "Zerar"; closeBtn.style.display = "none";
bar.appendChild(closeBtn);
if (C.positions.length) { closeBtn.style.display = "";
  closeBtn.onclick = () => { if (confirm("Zerar a(s) posição(ões) aberta(s) em " + C.symbol + " a mercado?")) C.positions.forEach(p => send({kind: "close", id: p.id})); }; }
setTool("cursor");

// ---------------------------------------------------------------- zoom (canto do gráfico)
const zoomBox = document.createElement("div"); zoomBox.id = "zoom";
zoomBox.innerHTML = `<button data-z="in" title="Aproximar">＋</button><button data-z="out" title="Afastar">－</button><button data-z="fit" title="Ajustar ao padrão">⤢</button>`;
chartEl.style.position = "relative"; chartEl.appendChild(zoomBox);   // ancorado no canto do próprio gráfico
function zoomBy(f) {   // mantém a vela mais recente na tela e muda a quantidade de velas visíveis
  const ts = chart.timeScale(), r = ts.getVisibleLogicalRange(); if (!r) return;
  const span = Math.min(Math.max((r.to - r.from) * f, 8), 5000);
  ts.setVisibleLogicalRange({from: r.to - span, to: r.to});
}
zoomBox.addEventListener("click", e => { const b = e.target.closest("button"); if (!b) return;
  if (b.dataset.z === "in") zoomBy(0.7);
  else if (b.dataset.z === "out") zoomBy(1 / 0.7);
  else { chart.priceScale("right").applyOptions({autoScale: true}); chart.timeScale().setVisibleLogicalRange({from: data.length - 150, to: data.length + 5}); } });
