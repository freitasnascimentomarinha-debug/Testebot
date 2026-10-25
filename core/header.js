// Cabeçalho da página do bot (componente do Streamlit): título, chips, tempo gráfico em botões e os números do dia.
export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  const nf = (v, d = 2) => (v == null || Number.isNaN(v)) ? "—" : Number(v).toLocaleString("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d });
  const px = (v) => v == null ? "—" : nf(v, Math.abs(v) >= 100 ? 2 : Math.abs(v) >= 1 ? 4 : 6);
  const sg = (v, d = 2) => (v >= 0 ? "+" : "−") + nf(Math.abs(v), d);
  const cls = (v) => (v > 0 ? "up" : v < 0 ? "dn" : "");
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const root = parentElement.querySelector(".hd") || parentElement.appendChild(Object.assign(document.createElement("div"), { className: "hd" }));
  const m = data.metrics, tile = (k, v, sub, tone = "", tip = "") =>
    `<div class="tile" ${tip ? `title="${esc(tip)}"` : ""}><span>${k}</span><b class="${tone}">${v}</b>${sub ? `<small class="${tone}">${sub}</small>` : ""}</div>`;
  root.innerHTML = `
    <div class="top">
      <div class="ttl"><span class="ico">${esc(data.icon)}</span><h1>${esc(data.name)}</h1>
        <span class="chip mk">${esc(data.market_label)}</span><span class="chip st">${esc(data.style)}</span><span class="chip ac ${data.account_real ? "real" : ""}">${esc(data.account)}</span></div>
      <div class="tfs">${data.intervals.map((i) => `<button data-i="${i}" class="${i === data.interval ? "on" : ""}">${i}</button>`).join("")}</div>
    </div>
    <div class="tiles">
      <div class="tile px"><span>${esc(data.symbol)}</span><b>${px(m.price)}</b><small class="${cls(m.change_pct)}">${sg(m.change_pct)}% 24h</small></div>
      ${tile("Banca", nf(m.equity) + " USDT", sg(m.total_pnl) + " (" + sg(m.total_pnl_pct) + "%)", cls(m.total_pnl), "Patrimônio da carteira simulada: saldo livre + margens + P&L em aberto.")}
      ${tile("Resultado hoje", sg(m.pnl_today), "", cls(m.pnl_today))}
      ${tile("Operações hoje", m.trades_today, "")}
      ${tile("P&L aberto (líquido)", sg(m.unrealized_net), m.open_positions + " posição(ões)", cls(m.unrealized_net), "Já descontadas as taxas de entrada e saída.")}
      ${tile("Taxa de acerto", nf(m.win_rate, 0) + "%", m.trades + " trades")}
    </div>
    ${data.context ? `<div class="ctx">🧭 <b>Contexto agora (${esc(data.interval)}):</b> ${esc(data.context.label)} — <span>${esc(data.context.desc)}</span></div>` : ""}`;
  root.onclick = (e) => {
    const b = e.target.closest("button[data-i]");
    if (b && b.dataset.i !== data.interval) setTriggerValue("interval", { value: b.dataset.i, uid: Date.now() + "-" + Math.random() });
  };
}
