// Aba "Análise do bot" (componente do Streamlit): fatos medidos, o que falta para o bot agir, decisões da IA sobre saídas e varredura.
export default function (component) {
  const { data, parentElement } = component;
  const nf = (v, d = 2) => (v == null || Number.isNaN(v)) ? "—" : Number(v).toLocaleString("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d });
  const px = (v) => v == null ? "—" : nf(v, Math.abs(v) >= 100 ? 2 : Math.abs(v) >= 1 ? 4 : 6);
  const sg = (v, d = 2) => (v >= 0 ? "+" : "−") + nf(Math.abs(v), d);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const md = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
  const root = parentElement.querySelector(".an") || parentElement.appendChild(Object.assign(document.createElement("div"), { className: "an" }));
  const a = data.analysis;
  if (!a) { root.innerHTML = `<p class="empty">A leitura aparece em instantes.</p>`; return; }
  const s = a.score, pct = Math.max(0, Math.min(100, Math.abs(s.value) / Math.max(1, s.needed) * 100));
  const side = s.value >= 0 ? "up" : "dn";
  const sc = a.scan;
  const scanTxt = !sc.on ? "Bot desligado: só a leitura do ativo na tela (sem IA e sem ordens)."
    : `Última varredura ${sc.last || "—"} UTC (${sc.scanned} ativo(s)) · próxima ${sc.next_in_min == null ? "em instantes" : "em ~" + sc.next_in_min + " min"} · a cada ${sc.minutes} min`;
  const act = {BUY: "Comprou", SELL: "Vendeu", CLOSE: "Encerrou"};
  root.innerHTML = `
  <section class="card head ${a.tone}">
    <div class="h1"><span class="dot"></span><h2>${esc(a.title)}</h2><span class="chip">${esc(a.symbol)} · ${esc(a.interval)}</span>${a.bot ? `<span class="chip bot">${esc(a.bot)}</span>` : ""}</div>
    <div class="chips">${a.context.name ? `<span class="chip ctx" title="${esc(a.context.rule)}">${esc(a.context.name)}</span>` : ""}${a.bias ? `<span class="chip">viés ${esc(a.bias)}</span>` : ""}<span class="chip mut">${esc(a.when)} UTC${a.ai ? " · lido pela IA" : ""}</span></div>
    ${a.summary ? `<p class="lead">${md(a.summary)}</p>` : ""}
    ${a.why ? `<p class="ia">🤖 ${md(a.why)}</p>` : ""}
    ${a.entry ? `<div class="ent"><span>Entrada <b>${px(a.entry.price)}</b></span><span class="dn">Stop <b>${px(a.entry.stop)}</b></span><span class="up">Alvo <b>${px(a.entry.target)}</b></span><span>${nf(a.entry.qty, 6).replace(/,?0+$/, "")} un.</span><span>Risco <b>${nf(a.entry.risk)} USDT</b></span></div>` : ""}
    ${a.executed.map((e) => `<p class="ok">✅ ${act[e.action] || e.action} ${esc(e.symbol)} (${esc(e.status)})</p>`).join("")}
  </section>
  <div class="grid">
    <section class="card"><h3>Placar do bot</h3>
      <div class="meter"><span class="bar ${side}" style="width:${pct}%"></span><i></i></div>
      <p class="small">${sg(s.value, 1)} de ±${nf(s.needed, 0)} necessários para ${s.value >= 0 ? "comprar" : "vender"}${pct >= 100 ? (a.blocks.length ? " — atingido, mas barrado pelo filtro abaixo" : " — atingido") : ""}.</p>
      ${a.blocks.length ? a.blocks.map((b) => `<p class="blk">⛔ ${esc(b)}</p>`).join("") : ""}
      <h4>O que mais pesa</h4>
      ${a.drivers.map((d) => `<div class="drv"><span class="vt ${d.vote >= 0 ? "up" : "dn"}">${sg(d.vote)}</span><div><b>${esc(d.name)}</b><small>${esc(d.detail)}</small></div></div>`).join("")}
    </section>
    <section class="card"><h3>Leitura do gráfico</h3>
      <ul class="facts">${a.facts.map((f) => `<li>${esc(f)}</li>`).join("")}</ul>
      ${a.trigger ? `<h4>O que faria o bot entrar</h4><p class="small">${md(a.trigger)}</p>` : ""}
      ${a.bot_note ? `<h4>Bot para este contexto</h4><p class="small">${esc(a.bot_note)}</p>` : ""}
    </section>
  </div>
  ${a.exits.length ? `<section class="card"><h3>Decisão da IA sobre posições abertas</h3>${a.exits.map((e) => `<div class="exit ${e.acao === "CLOSE" ? "warn" : ""}"><b>${esc(e.symbol)}</b><span class="chip ${e.acao === "CLOSE" ? "warnc" : ""}">${e.acao === "CLOSE" ? "Encerrar" : "Manter"}${e.confianca ? " · " + e.confianca + "%" : ""}</span><p>${esc(e.motivo)}</p></div>`).join("")}</section>` : ""}
  ${a.opportunities.length ? `<section class="card"><h3>Oportunidades da última varredura</h3><table><tr><th>Ativo</th><th>Lado</th><th>Bot</th><th>Entrada</th><th>Stop</th><th>Alvo</th></tr>${a.opportunities.map((o) => `<tr><td><b>${esc(o.symbol)}</b></td><td class="${o.side === "BUY" ? "up" : "dn"}">${o.side === "BUY" ? "Compra" : "Venda"}</td><td>${esc(o.bot)}</td><td>${px(o.entry)}</td><td>${px(o.stop)}</td><td>${px(o.target)}</td></tr>`).join("")}</table></section>` : ""}
  <p class="foot">🔎 ${scanTxt}</p>${a.notes.map((n) => `<p class="foot">⚠️ ${esc(n)}</p>`).join("")}`;
}
