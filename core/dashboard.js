// Painel geral (componente do Streamlit): banca e curva, cartões dos bots, posições abertas, próximos eventos e as últimas decisões.
export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  const nf = (v, d = 2) => (v == null || Number.isNaN(v)) ? "—" : Number(v).toLocaleString("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d });
  const sg = (v, d = 2) => v == null ? "—" : (v > 0 ? "+" : v < 0 ? "−" : "") + nf(Math.abs(v), d);
  const cls = (v) => v > 0 ? "up" : v < 0 ? "dn" : "";
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const hm = (iso) => iso ? new Date(iso).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "";
  const root = parentElement.querySelector(".wx") || parentElement.appendChild(Object.assign(document.createElement("div"), { className: "wx" }));
  const S = root.state || (root.state = { open: {}, filter: "" });
  const e = data.equity, neg = (e.total_pnl || 0) < 0;
  function spark() {
    const pts = data.curve.map((c) => [new Date(c[0]).getTime(), c[1]]);
    if (pts.length < 2) return `<p class="empty">A curva aparece conforme a carteira é atualizada.</p>`;
    const W = 1000, h = 130, P = 4, xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
    const x0 = Math.min(...xs), x1 = Math.max(...xs), lo = Math.min(...ys, e.invested), hi = Math.max(...ys, e.invested), sp = (hi - lo) || 1;
    const X = (t) => P + (t - x0) / ((x1 - x0) || 1) * (W - 2 * P), Y = (v) => h - P - (v - lo) / sp * (h - 2 * P);
    const line = pts.map((p) => `${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join(" "), c = neg ? "#ef5350" : "#26a69a";
    return `<svg viewBox="0 0 ${W} ${h}" height="${h}" preserveAspectRatio="none" style="display:block;width:100%"><defs><linearGradient id="dg" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="${c}" stop-opacity=".35"/><stop offset="1" stop-color="${c}" stop-opacity="0"/></linearGradient></defs>
      <line x1="${P}" x2="${W - P}" y1="${Y(e.invested)}" y2="${Y(e.invested)}" stroke="#5d606b" stroke-dasharray="5 5"/><polygon fill="url(#dg)" points="${X(x0)},${h - P} ${line} ${X(x1)},${h - P}"/>
      <polyline fill="none" stroke="${c}" stroke-width="2.2" vector-effect="non-scaling-stroke" points="${line}"/></svg>`;
  }
  const dchip = (d) => ({ BUY: `<span class="chip buy">🟢 Compra</span>`, SELL: `<span class="chip sell">🔴 Venda</span>`, CLOSE: `<span class="chip">🟠 Encerrar</span>` }[d] || `<span class="chip hold">⚪ Esperar</span>`);
  function draw() {
    const decs = data.decisions.filter((d) => !S.filter || (S.filter === "acao" ? d.decision !== "HOLD" : d.bot === S.filter));
    const bots = [...new Set(data.decisions.map((d) => d.bot))];
    root.innerHTML = `<div class="hero">
      <div class="big ${neg ? "neg" : ""}"><span class="lbl">${data.mode === "única" ? "Carteira única" : "Bancas somadas"} · patrimônio</span><div class="v">${nf(e.equity)} <small>USDT</small></div>
        <div class="d ${cls(e.total_pnl)}">${sg(e.total_pnl)} USDT (${sg(e.total_pnl_pct)}%)</div>
        <div class="tiles" style="margin-top:8px"><div class="tile"><span class="lbl">Hoje</span><b class="${cls(e.pnl_today)}">${sg(e.pnl_today)}</b><small>${e.trades_today} operações</small></div>
          <div class="tile"><span class="lbl">Posições</span><b>${e.open_positions}</b><small>P&L ${sg(e.unrealized_net)}</small></div>
          <div class="tile"><span class="lbl">Acerto</span><b>${nf(e.win_rate, 0)}%</b><small>${e.trades} trades</small></div></div></div>
      <div class="panel"><h3>Evolução da banca <span class="mut" style="text-transform:none;letter-spacing:0">tracejado = capital investido</span></h3>${spark()}
        <div style="display:flex;justify-content:flex-end;margin-top:8px"><button class="btn" data-go="carteira">💰 Abrir carteira</button></div></div></div>
      <div class="bots">${data.cards.map((c) => { const s = c.stats; return `<div class="bot"><header><div><h4>${esc(c.icon)} ${esc(c.name)}</h4>
          <div class="sub">${esc(c.market)} · ${esc(c.symbol)} ${esc(c.interval)} · ${esc(c.leverage)}</div></div><span class="chip ${c.autopilot ? "on" : ""}">${c.autopilot ? "🟢 bot ligado" : "⚪ bot desligado"}</span></header>
        <div class="g"><div><span class="lbl">Hoje</span><b class="${cls(s.pnl_today)}">${sg(s.pnl_today)}</b></div><div><span class="lbl">Operações hoje</span><b>${s.trades_today}</b></div>
          <div><span class="lbl">Posições</span><b>${s.open_positions}</b></div><div><span class="lbl">Acerto</span><b>${nf(s.win_rate, 0)}%</b></div></div>
        <button class="btn pri" data-go="${esc(c.key)}">Abrir ${esc(c.name)} →</button></div>`; }).join("")}</div>
      <div class="two"><div class="panel"><h3>Últimas decisões dos bots</h3>
          <div class="seg" style="margin-bottom:8px"><button data-f="" class="${!S.filter ? "on" : ""}">Todas</button><button data-f="acao" class="${S.filter === "acao" ? "on" : ""}">Só entradas/saídas</button>${bots.map((b) => `<button data-f="${esc(b)}" class="${S.filter === b ? "on" : ""}">${esc(b)}</button>`).join("")}</div>
          <div class="feed">${decs.length ? decs.map((d, i) => `<div class="fi ${S.open[i] ? "open" : ""}" data-i="${i}"><span class="tm">${hm(d.time)}</span><div>
            <div class="hd">${dchip(d.decision)}<b>${esc(d.symbol)}</b><span class="mut">${esc(d.interval)} · ${esc(d.bot)}${d.personality ? " · " + esc(d.personality) : ""}</span>
              ${d.source === "ia" ? `<span class="chip">🤖 IA ${d.confidence ?? ""}%</span>` : `<span class="chip">regras</span>`}${d.executed ? `<span class="chip on">executada</span>` : ""}</div>
            <div class="why">${esc(d.reasoning)}</div></div></div>`).join("") : `<p class="empty">Nenhuma análise ainda. Ligue um bot: ele analisa sozinho a cada varredura.</p>`}</div></div>
        <div style="display:flex;flex-direction:column;gap:12px">
          <div class="panel"><h3>Posições abertas</h3>${data.positions.length ? data.positions.map((p) => `<div class="pos"><span><span class="chip ${p.side === "BUY" ? "buy" : "sell"}">${p.side === "BUY" ? "Compra" : "Venda"}</span> <b style="text-align:left">${esc(p.symbol)}</b> <span class="mut">${esc(p.who)}</span></span>
            <b class="${cls(p.net)}">${sg(p.net)} USDT</b><span class="mut">entrada ${nf(p.entry, 4)} · agora ${nf(p.price_now, 4)}</span><span class="${cls(p.net_pct)}" style="text-align:right">${sg(p.net_pct)}%</span></div>`).join("") : `<p class="empty">Nenhuma posição aberta.</p>`}</div>
          <div class="panel"><h3>Próximos eventos <button class="btn" data-go="eventos" style="padding:4px 9px">Ver todos</button></h3>${data.events.length ? data.events.map((v) => `<div class="ev"><b>${esc(v.evento)}</b>
            <div class="p">${esc(v.categoria)} · vence em ${v.vence_em_dias} dia(s) · ${v.probabilidades.map((o) => esc(o.opcao) + " " + nf(o.pct, 0) + "%").join(" · ")}</div></div>`).join("") : `<p class="empty">Os eventos aparecem depois que a página Eventos ou a IA os carrega.</p>`}</div></div></div>`;
  }
  draw();
  root.onclick = (ev) => {
    const b = ev.target.closest("button, .fi"); if (!b) return;
    if (b.dataset.go) { setTriggerValue("go", { page: b.dataset.go, uid: Date.now() + "-" + Math.random() }); return; }
    if (b.dataset.f !== undefined) S.filter = b.dataset.f; else if (b.dataset.i !== undefined) S.open[b.dataset.i] = !S.open[b.dataset.i];
    draw();
  };
}
