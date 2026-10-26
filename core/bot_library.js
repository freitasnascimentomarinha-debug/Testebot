// Biblioteca de bots (componente do Streamlit): cards com filtros, ordenação e detalhes. Editar/duplicar/excluir voltam ao Python.
export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  const nf = (v, d = 1) => (v == null || Number.isNaN(v)) ? "—" : Number(v).toLocaleString("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d });
  const sg = (v, d = 1) => v == null ? "—" : (v > 0 ? "+" : v < 0 ? "−" : "") + nf(Math.abs(v), d) + "%";
  const cls = (v) => v == null ? "" : v > 0 ? "up" : v < 0 ? "dn" : "";
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const root = parentElement.querySelector(".bx") || parentElement.appendChild(Object.assign(document.createElement("div"), { className: "bx" }));
  const S = root.state || (root.state = { style: "", q: "", ok: false, sort: "month", open: {} });
  const ST = { "": "Todos", day: "⚡ Day trade", swing: "🌊 Swing", long: "🏔️ Longo prazo" };
  const SORT = { month: "% ao mês", win: "Acerto", dd: "Menor queda", live: "Operações reais" };
  const statusChip = (s) => s === "aprovado" ? `<span class="chip ok">✅ aprovado na prova final</span>` : s === "ressalva" ? `<span class="chip mid">🟡 aprovado com ressalva</span>` : s === "fraco" ? `<span class="chip bad">⚠️ fraco no período</span>` : "";
  function card(b) {
    const r = b.research, open = !!S.open[b.id];
    return `<article class="card st-${esc(r ? r.status : "")}">
      <h4>${esc(b.name)}</h4>
      <div class="tags"><span class="chip">${esc(ST[b.style] || b.style || "")}</span>${b.interval ? `<span class="chip">${esc(b.interval)}</span>` : ""}<span class="chip ${b.market === "futures" ? "fut" : "spot"}">${b.market === "futures" ? "Futuros" : "Spot"}</span><span class="chip">R:R ${esc(b.rr)}</span>${b.builtin ? "" : `<span class="chip">por ${esc(b.author || "—")}</span>`}</div>
      ${b.specialty ? `<div class="spec">${esc(b.specialty)}</div>` : ""}
      ${b.tip ? `<div class="tip">💡 ${esc(b.tip)}</div>` : ""}
      ${b.contexts_only ? `<div class="tip">🔒 Opera só em: ${esc(b.contexts_only)}</div>` : ""}
      ${r ? `<div class="tiles"><div class="tile"><span class="lbl">Ao mês (simulado)</span><b class="${cls(r.monthly_pct)}">${sg(r.monthly_pct)}</b><small>${sg(r.ret_pct)} em ${esc(r.period_label || "")}</small></div>
        <div class="tile"><span class="lbl">Acerto</span><b>${nf(r.win_pct, 0)}%</b><small>~${nf(r.trades_month, 0)} op./mês</small></div>
        <div class="tile"><span class="lbl">Pior queda</span><b class="dn">−${nf(r.dd_pct, 0)}%</b><small>${r.pos_coins ?? "—"} moedas +</small></div></div>
        <div class="tags">${statusChip(r.status)}</div>` : `<div class="tip mut">Ainda sem simulação: rode o backtest na aba 🔁 Backtest.</div>`}
      <div class="tip">${b.live_trades ? `📊 Real: ${b.live_trades} operações · acerto ${nf(b.live_win, 0)}% · ${nf(b.live_pnl, 2)} USDT` : "📊 Real: ainda sem operações."}</div>
      <div class="acts"><button class="btn" data-more="${esc(b.id)}">${open ? "Fechar detalhes" : "Detalhes"}</button>
        <button class="btn" data-edit="${esc(b.id)}">${b.can_edit ? "✏️ Editar" : "📄 Duplicar e editar"}</button>
        ${b.can_edit ? `<button class="btn del" data-del="${esc(b.id)}">Excluir</button>` : ""}</div>
      ${open ? `<div class="more">${b.description ? `<div>${esc(b.description)}</div>` : ""}
        <div><b>Indicadores (peso):</b> ${esc(b.skills)}</div><div><b>Direção:</b> ${esc(b.direction)} · <b>Saída:</b> ${esc(b.exit)} · <b>Filtros:</b> ${esc(b.filters || "nenhum")}</div>
        ${b.per_symbol && b.per_symbol.length ? `<div><b>Por moeda (${esc(r.period_label || "")}):</b> ${b.per_symbol.map(([s, v]) => `<span class="${cls(v)}">${esc(s)} ${sg(v)}</span>`).join(" · ")}</div>` : ""}
        ${b.contexts && b.contexts.length ? `<table class="ctx"><tr><th>Contexto</th><th>Op.</th><th>Acerto</th><th>R médio</th></tr>${b.contexts.map((c) => `<tr><td>${esc(c.label)}</td><td>${c.n}</td><td>${nf(c.win_pct, 0)}%</td><td class="${cls(c.avg_r)}">${c.avg_r >= 0 ? "+" : ""}${nf(c.avg_r, 2)}</td></tr>`).join("")}</table>` : ""}</div>` : ""}
    </article>`;
  }
  function draw() {
    const q = S.q.trim().toLowerCase();
    const key = { month: (b) => -(b.research ? b.research.monthly_pct ?? -999 : -999), win: (b) => -(b.research ? b.research.win_pct || 0 : 0),
      dd: (b) => (b.research ? b.research.dd_pct ?? 999 : 999), live: (b) => -(b.live_trades || 0) }[S.sort];
    const list = data.bots.filter((b) => (!S.style || b.style === S.style) && (!S.ok || (b.research && b.research.status === "aprovado"))
      && (!q || (b.name + " " + (b.specialty || "") + " " + (b.skills || "")).toLowerCase().includes(q))).sort((a, b) => key(a) - key(b));
    const ok = data.bots.filter((b) => b.research && b.research.status === "aprovado").length;
    root.innerHTML = `<div class="bar"><div class="seg">${Object.entries(ST).map(([k, l]) => `<button data-st="${k}" class="${S.style === k ? "on" : ""}">${l}</button>`).join("")}</div>
        <div class="seg">${Object.entries(SORT).map(([k, l]) => `<button data-so="${k}" class="${S.sort === k ? "on" : ""}">${l}</button>`).join("")}</div>
        <div class="seg"><button data-ok="1" class="${S.ok ? "on" : ""}">✅ Só aprovados</button></div>
        <input class="search" placeholder="Buscar por nome, especialidade ou indicador…" value="${esc(S.q)}"></div>
      <p class="foot">${list.length} de ${data.bots.length} bots · ${ok} aprovados na prova final (moedas que o teste não viu)</p>
      ${list.length ? `<div class="grid">${list.map(card).join("")}</div>` : `<p class="empty">Nenhum bot com esses filtros.</p>`}`;
    const s = root.querySelector(".search");
    if (root._focusSearch) { s.focus(); s.setSelectionRange(s.value.length, s.value.length); }
  }
  draw();
  root.onclick = (e) => {
    const b = e.target.closest("button"); if (!b) return;
    const uid = Date.now() + "-" + Math.random();
    if (b.dataset.edit) { setTriggerValue("action", { kind: "edit", id: b.dataset.edit, uid }); return; }
    if (b.dataset.del) { if (confirm("Excluir este bot? Não dá para desfazer.")) setTriggerValue("action", { kind: "delete", id: b.dataset.del, uid }); return; }
    if (b.dataset.more) S.open[b.dataset.more] = !S.open[b.dataset.more];
    else if (b.dataset.st !== undefined) S.style = b.dataset.st;
    else if (b.dataset.so) S.sort = b.dataset.so;
    else if (b.dataset.ok) S.ok = !S.ok;
    root._focusSearch = false; draw();
  };
  root.oninput = (e) => { if (e.target.classList.contains("search")) { S.q = e.target.value; root._focusSearch = true; draw(); } };
}
