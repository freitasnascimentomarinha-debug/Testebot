// Book de ordens (componente do Streamlit): profundidade ao vivo da Binance pelo navegador (WebSocket, com consulta periódica de reserva).
export default function (component) {
  const { data, parentElement } = component;
  const nf = (v, d = 2) => Number(v).toLocaleString("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d });
  const dec = (p) => (p >= 1000 ? 2 : p >= 10 ? 3 : p >= 1 ? 4 : p >= 0.1 ? 5 : 6);
  const qd = (q) => (q >= 1000 ? 0 : q >= 10 ? 1 : q >= 1 ? 2 : 3);
  const root = parentElement.querySelector(".bk") || parentElement.appendChild(Object.assign(document.createElement("div"), { className: "bk" }));
  const sym = data.symbol.toLowerCase(), key = data.market + ":" + sym;
  if (root.dataset.key === key) return;   // mesma moeda: o fluxo ao vivo continua; nada a refazer
  root.dataset.key = key;
  if (root._ws) { try { root._ws.close(); } catch (e) {} }
  if (root._poll) clearInterval(root._poll);
  root.innerHTML = `<div class="top"><b>${data.symbol}</b><span class="mut">${data.market === "futures" ? "Perpétuo" : "Spot"} · 12 níveis</span><span class="st mut">conectando…</span></div>
    <div class="press"><span class="b"></span><span class="a"></span></div><div class="pl"><span class="up pb"></span><span class="dn pa"></span></div>
    <div class="hd"><span>Preço (USDT)</span><span>Quantidade</span><span>Total</span></div><div class="asks"></div><div class="mid"></div><div class="bids"></div>`;
  const q = (s) => root.querySelector(s);
  let last = 0;
  const draw = (bids, asks) => {
    const B = bids.slice(0, 12).map((x) => [+x[0], +x[1]]), A = asks.slice(0, 12).map((x) => [+x[0], +x[1]]);
    if (!B.length || !A.length) return;
    last = Date.now();
    const cum = (rows) => { let t = 0; return rows.map((r) => (t += r[1], t)); };
    const cb = cum(B), ca = cum(A), mx = Math.max(cb[cb.length - 1], ca[ca.length - 1]);
    const d = dec(B[0][0]), row = (r, c, cls) => `<div class="r ${cls}"><i style="width:${(c / mx * 100).toFixed(1)}%"></i><span class="p">${nf(r[0], d)}</span><span>${nf(r[1], qd(r[1]))}</span><span class="t">${nf(c, qd(c))}</span></div>`;
    q(".asks").innerHTML = A.map((r, i) => row(r, ca[i], "ask")).reverse().join("");
    q(".bids").innerHTML = B.map((r, i) => row(r, cb[i], "bid")).join("");
    const spread = A[0][0] - B[0][0], mid = (A[0][0] + B[0][0]) / 2;
    q(".mid").innerHTML = `<b>${nf(mid, d)}</b><span class="mut">spread ${nf(spread, d)} (${nf(spread / mid * 100, 3)}%)</span>`;
    const tb = cb[cb.length - 1], ta = ca[ca.length - 1], pb = tb / (tb + ta) * 100;
    q(".press .b").style.width = pb + "%"; q(".press .a").style.width = (100 - pb) + "%";
    q(".pb").textContent = "Compradores " + nf(pb, 0) + "%"; q(".pa").textContent = nf(100 - pb, 0) + "% Vendedores";
    q(".st").textContent = "ao vivo";
  };
  const rest = async () => {
    try {
      const url = data.market === "futures" ? `https://fapi.binance.com/fapi/v1/depth?symbol=${data.symbol}&limit=20` : `https://api.binance.com/api/v3/depth?symbol=${data.symbol}&limit=20`;
      const r = await fetch(url); if (!r.ok) throw new Error(r.status); const j = await r.json(); draw(j.bids, j.asks);
    } catch (e) { q(".st").textContent = "sem conexão com a corretora"; }
  };
  try {
    const ws = new WebSocket(data.market === "futures" ? `wss://fstream.binance.com/ws/${sym}@depth20@500ms` : `wss://stream.binance.com:9443/ws/${sym}@depth20@1000ms`);
    root._ws = ws;
    ws.onmessage = (m) => { if (!root.isConnected) { ws.close(); return; } const j = JSON.parse(m.data); draw(j.b || j.bids, j.a || j.asks); };
  } catch (e) { /* cai na consulta periódica */ }
  rest();
  root._poll = setInterval(() => { if (!root.isConnected) { clearInterval(root._poll); return; } if (Date.now() - last > 4000) rest(); }, 2500);
}
