// Menu lateral (componente do Streamlit): navegação em grupos e lista de moedas com preço e variação de 24 h. Cliques voltam ao Python.
export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  const nf = (v, d = 2) => Number(v).toLocaleString("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d });
  const px = (v) => nf(v, v >= 100 ? 2 : v >= 1 ? 4 : 6);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const root = parentElement.querySelector(".sb") || parentElement.appendChild(Object.assign(document.createElement("div"), { className: "sb" }));
  root.innerHTML = `
    <div class="brand"><span>📈</span><b>TradeBot</b></div>
    ${data.groups.map((g) => `<div class="grp"><small>${esc(g.title)}</small>${g.items.map((i) =>
      `<button class="nav ${i.active ? "on" : ""}" data-go="${esc(i.path)}"><span class="ic">${esc(i.icon)}</span>${esc(i.title)}</button>`).join("")}</div>`).join("")}
    ${data.watch.length ? `<div class="grp"><small>${esc(data.watch_title)}</small><div class="wl">${data.watch.map((w) =>
      `<button class="coin" data-sym="${esc(w.symbol)}"><b>${esc(w.symbol.replace(/USDT$/, ""))}</b><span class="p">${px(w.price)}</span><span class="c ${w.pct >= 0 ? "up" : "dn"}">${w.pct >= 0 ? "+" : "−"}${nf(Math.abs(w.pct))}%</span></button>`).join("")}</div></div>` : ""}`;
  root.onclick = (e) => {
    const b = e.target.closest("button"); if (!b) return;
    const uid = Date.now() + "-" + Math.random();
    if (b.dataset.go !== undefined) setTriggerValue("go", { path: b.dataset.go, uid });
    else if (b.dataset.sym) setTriggerValue("go", { symbol: b.dataset.sym, uid });
  };
}
