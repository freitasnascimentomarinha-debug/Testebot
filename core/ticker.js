// Faixa de cotações em movimento (componente do Streamlit). Os preços são buscados direto pelo navegador (a Binance responde a ele
// mesmo quando bloqueia o servidor); sem resposta, valem os últimos números enviados pelo Python.
export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  const nf = (v, d = 2) => Number(v).toLocaleString("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d });
  const px = (v) => nf(v, v >= 100 ? 2 : v >= 1 ? 4 : 6);
  const root = parentElement.querySelector(".tk") || parentElement.appendChild(Object.assign(document.createElement("div"), { className: "tk" }));
  const quotes = { ...(data.quotes || {}) };
  const SN = data.sentiment || {};
  const tag = (s) => { const x = SN[s]; return x ? `<em class="sn ${x.vies === "altista" ? "up" : x.vies === "baixista" ? "dn" : ""}" title="${esc(x.leitura)}">🔮 ${x.vies === "altista" ? "▲" : x.vies === "baixista" ? "▼" : "•"} ${x.vies}</em>` : ""; };
  const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const item = (s) => { const q = quotes[s]; if (!q) return ""; const up = q[1] >= 0;
    return `<button class="it ${s === data.current ? "cur" : ""}" data-sym="${s}"><b>${s.replace(/USDT$/, "")}</b><span>${px(q[0])}</span><i class="${up ? "up" : "dn"}">${up ? "▲" : "▼"} ${nf(Math.abs(q[1]))}%</i>${tag(s)}</button>`; };
  const draw = () => {
    const html = data.symbols.map(item).join("");
    if (!html) { root.innerHTML = ""; return; }
    const cur = SN[data.current], lead = cur ? `<div class="lead ${cur.vies === "altista" ? "up" : cur.vies === "baixista" ? "dn" : ""}" title="${esc(cur.leitura)}">🔮 ${esc(data.current.replace(/USDT$/, ""))} · ${esc(cur.vies)}<small>Polymarket</small></div>` : "";
    const track = root.querySelector(".track");
    if (track && root.dataset.n === String(Object.keys(quotes).length)) {   // só troca os números: a faixa não reinicia
      track.innerHTML = html + html; const l = root.querySelector(".lead"); if (l) l.outerHTML = lead; else if (lead) root.insertAdjacentHTML("afterbegin", lead); return;
    }
    root.dataset.n = String(Object.keys(quotes).length);
    root.innerHTML = `${lead}<div class="view"><div class="track" style="animation-duration:${Math.max(30, data.symbols.length * 4)}s">${html}${html}</div></div>`;
  };
  draw();
  const load = async () => {
    try {
      const url = data.market === "futures" ? "https://fapi.binance.com/fapi/v1/ticker/24hr"
        : "https://api.binance.com/api/v3/ticker/24hr?type=MINI&symbols=" + encodeURIComponent(JSON.stringify(data.symbols));
      const r = await fetch(url); if (!r.ok) throw new Error(r.status);
      for (const t of await r.json()) if (data.symbols.includes(t.symbol)) {
        const last = parseFloat(t.lastPrice), pct = t.priceChangePercent !== undefined ? parseFloat(t.priceChangePercent) : (parseFloat(t.openPrice) ? (last / parseFloat(t.openPrice) - 1) * 100 : 0);
        quotes[t.symbol] = [last, pct];
      }
      draw();
    } catch (e) { /* mantém os números do servidor */ }
  };
  load();
  if (root._timer) clearInterval(root._timer);
  root._timer = setInterval(load, 20000);
  root.onclick = (e) => { const b = e.target.closest("button[data-sym]"); if (b && b.dataset.sym !== data.current) setTriggerValue("pick", { symbol: b.dataset.sym, uid: Date.now() + "-" + Math.random() }); };
}
