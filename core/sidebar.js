// Menu lateral (componente do Streamlit): navegação em grupos e lista de moedas com preço e variação de 24 h. Cliques voltam ao Python.
export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  const nf = (v, d = 2) => Number(v).toLocaleString("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d });
  const px = (v) => nf(v, v >= 100 ? 2 : v >= 1 ? 4 : 6);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const root = parentElement.querySelector(".sb") || parentElement.appendChild(Object.assign(document.createElement("div"), { className: "sb" }));
  const wm = Object.fromEntries((data.watch || []).map((w) => [w.symbol, w]));
  root.innerHTML = `
    <div class="brand"><span>📈</span><b>TradeBot</b></div>
    ${data.groups.map((g) => `<div class="grp"><small>${esc(g.title)}</small>${g.items.map((i) =>
      `<button class="nav ${i.active ? "on" : ""}" data-go="${esc(i.path)}"><span class="ic">${esc(i.icon)}</span>${esc(i.title)}</button>`).join("")}</div>`).join("")}
    ${(data.symbols || []).length ? `<div class="grp"><small>${esc(data.watch_title)}</small><div class="wl">${data.symbols.map((sym) => { const w = wm[sym];
      return `<button class="coin" data-sym="${esc(sym)}"><b>${esc(sym.replace(/USDT$/, ""))}</b><span class="p">${w ? px(w.price) : "—"}</span><span class="c ${w && w.pct < 0 ? "dn" : "up"}">${w ? (w.pct >= 0 ? "+" : "−") + nf(Math.abs(w.pct)) + "%" : ""}</span></button>`; }).join("")}</div></div>` : ""}`;
  // preços direto do navegador (a Binance responde a ele mesmo quando bloqueia o servidor); sem resposta, ficam os do servidor
  const paint = (q) => { root.querySelectorAll(".coin").forEach((b) => { const v = q[b.dataset.sym]; if (!v) return;
    b.querySelector(".p").textContent = px(v[0]); const c = b.querySelector(".c"); c.className = "c " + (v[1] >= 0 ? "up" : "dn"); c.textContent = (v[1] >= 0 ? "+" : "−") + nf(Math.abs(v[1])) + "%"; }); };
  const load = async () => {
    try {
      const list = data.symbols || []; if (!list.length) return;
      const url = data.market === "futures" ? "https://fapi.binance.com/fapi/v1/ticker/24hr"
        : "https://api.binance.com/api/v3/ticker/24hr?type=MINI&symbols=" + encodeURIComponent(JSON.stringify(list));
      const r = await fetch(url); if (!r.ok) return; const q = {};
      for (const t of await r.json()) if (list.includes(t.symbol)) { const l = parseFloat(t.lastPrice); q[t.symbol] = [l, t.priceChangePercent !== undefined ? parseFloat(t.priceChangePercent) : (parseFloat(t.openPrice) ? (l / parseFloat(t.openPrice) - 1) * 100 : 0)]; }
      paint(q);
    } catch (e) { /* mantém os do servidor */ }
  };
  load();
  root.onclick = (e) => {
    const b = e.target.closest("button"); if (!b) return;
    const uid = Date.now() + "-" + Math.random();
    if (b.dataset.go !== undefined) setTriggerValue("go", { path: b.dataset.go, uid });
    else if (b.dataset.sym) setTriggerValue("go", { symbol: b.dataset.sym, uid });
  };
}
