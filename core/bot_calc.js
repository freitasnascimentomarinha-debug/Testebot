// Resultado da calculadora (componente do Streamlit): números principais e a curva da banca em SVG.
export default function (component) {
  const { data, parentElement } = component;
  const nf = (v, d = 2) => (v == null || Number.isNaN(v)) ? "—" : Number(v).toLocaleString("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d });
  const sg = (v, d = 2) => v == null ? "—" : (v > 0 ? "+" : v < 0 ? "−" : "") + nf(Math.abs(v), d);
  const cls = (v) => v > 0 ? "up" : v < 0 ? "dn" : "";
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const root = parentElement.querySelector(".bx") || parentElement.appendChild(Object.assign(document.createElement("div"), { className: "bx" }));
  const r = data.r;
  const tile = (l, v, s = "", c = "") => `<div class="ctile"><span class="lbl">${l}</span><b class="${c}">${v}</b>${s ? `<small>${s}</small>` : ""}</div>`;
  function curve() {
    const pts = r.curve; if (pts.length < 2) return "";
    const W = 900, H = 220, P = 8, xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
    const x0 = Math.min(...xs), x1 = Math.max(...xs), lo = Math.min(...ys, r.bank0), hi = Math.max(...ys, r.bank0), sp = hi - lo || 1;
    const X = (t) => P + (t - x0) / ((x1 - x0) || 1) * (W - 2 * P), Y = (v) => H - P - (v - lo) / sp * (H - 2 * P);
    const line = pts.map((p) => `${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join(" ");
    const c = r.bank >= r.bank0 ? "#26a69a" : "#ef5350";
    const d0 = new Date(x0).toLocaleDateString("pt-BR"), d1 = new Date(x1).toLocaleDateString("pt-BR");
    return `<div class="chart"><span class="lbl">Banca ao longo do período</span>
      <svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" preserveAspectRatio="none" style="display:block;margin-top:6px">
        <defs><linearGradient id="g" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="${c}" stop-opacity=".35"/><stop offset="1" stop-color="${c}" stop-opacity="0"/></linearGradient></defs>
        <line x1="${P}" x2="${W - P}" y1="${Y(r.bank0)}" y2="${Y(r.bank0)}" stroke="#5d606b" stroke-dasharray="4 4"/>
        <polygon fill="url(#g)" points="${X(x0)},${H - P} ${line} ${X(x1)},${H - P}"/><polyline fill="none" stroke="${c}" stroke-width="2.2" points="${line}"/></svg>
      <div class="bar" style="justify-content:space-between"><span class="foot">${d0}</span><span class="foot">linha tracejada = banca inicial (${nf(r.bank0)} USDT)</span><span class="foot">${d1}</span></div></div>`;
  }
  const neg = r.bank < r.bank0;
  root.innerHTML = `<p class="foot"><b style="color:#e6e8ee">${esc(r.bot)}</b> · ${esc(r.itv)} ${r.market === "futures" ? "futuros" : "spot"} · últimos ${r.days} dias · risco ${nf(r.risk, 2).replace(/,?0+$/, "")}% por operação${r.comp ? " com juros compostos" : " (valor fixo)"}</p>
    <div class="ctiles">
      <div class="ctile hero ${neg ? "neg" : ""}"><span class="lbl">Banca final</span><b>${nf(r.bank)} USDT</b><small class="${cls(r.pnl)}">${sg(r.pnl)} USDT (${sg(r.ret)}%)</small></div>
      ${tile("≈ por mês", sg(r.monthly) + "%", "(1 + retorno)^(30 ÷ dias) − 1", cls(r.monthly))}
      ${tile("Operações", r.n, `${r.wins} ganhos · ${r.losses} perdas`)}
      ${tile("Acerto", r.n ? nf(r.wins / r.n * 100, 0) + "%" : "—")}
      ${tile("Pior queda da banca", "−" + nf(r.max_dd, 1) + "%", "", "dn")}
      ${tile("Fator de lucro", r.pf == null ? "—" : r.pf === "inf" ? "∞" : nf(r.pf), "ganhos ÷ perdas")}
      ${tile("Maior ganho", sg(r.best) + " USDT", "", "up")}${tile("Maior perda", sg(r.worst) + " USDT", "", "dn")}
    </div>${curve()}`;
}
