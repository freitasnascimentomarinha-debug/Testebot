// Ranking diário dos bots (componente do Streamlit): pódio, lista ordenável com filtros e detalhes por bot. Filtros e linha aberta ficam
// guardados no próprio elemento, então sobrevivem às atualizações automáticas. "Rodar backtest" volta ao Python como gatilho.
export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  const nf = (v, d = 2) => (v == null || Number.isNaN(v)) ? "—" : Number(v).toLocaleString("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d });
  const sg = (v, d = 2) => v == null ? "—" : (v > 0 ? "+" : v < 0 ? "−" : "") + nf(Math.abs(v), d) + "%";
  const cls = (v) => v == null ? "zero" : v > 0 ? "up" : v < 0 ? "dn" : "zero";
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const root = parentElement.querySelector(".bx") || parentElement.appendChild(Object.assign(document.createElement("div"), { className: "bx" }));
  const S = root.state || (root.state = { m: "", i: "", sort: "d30", q: "", open: data.focus || null });
  if (data.focus) S.open = data.focus;
  const W = { d1: "Dia", d7: "Semana", d30: "Mês" };
  const val = (r, k, f = "ret_pct") => (r[k] || {})[f];
  const statusChip = (s) => s === "aprovado" ? `<span class="chip ok">✅ aprovado</span>` : s === "ressalva" ? `<span class="chip mid">🟡 ressalva</span>` : s === "fraco" ? `<span class="chip bad">⚠️ fraco</span>` : "";
  const mk = (m) => `<span class="chip ${m === "futures" ? "fut" : "spot"}">${m === "futures" ? "Futuros" : "Spot"}</span>`;
  function spark(h, w = 110, hgt = 28) {
    const pts = (h || []).map((x) => x.d30).filter((x) => x != null);
    if (pts.length < 2) return `<span class="mut" style="font-size:.7rem">—</span>`;
    const lo = Math.min(...pts, 0), hi = Math.max(...pts, 0), sp = hi - lo || 1;
    const xy = pts.map((v, i) => `${(i / (pts.length - 1) * w).toFixed(1)},${(hgt - 2 - (v - lo) / sp * (hgt - 4)).toFixed(1)}`).join(" ");
    const z = (hgt - 2 - (0 - lo) / sp * (hgt - 4)).toFixed(1), c = pts[pts.length - 1] >= 0 ? "#26a69a" : "#ef5350";
    return `<svg class="spark" width="${w}" height="${hgt}"><line x1="0" x2="${w}" y1="${z}" y2="${z}" stroke="#2a3042" stroke-dasharray="3 3"/><polyline fill="none" stroke="${c}" stroke-width="1.8" points="${xy}"/></svg>`;
  }
  function details(r) {
    const ps = Object.entries(r.per_symbol || {}), mx = Math.max(1, ...ps.map(([, v]) => Math.abs(v)));
    const win = (k) => `<div class="kv"><span>Retorno</span><b class="${cls(val(r, k))}">${sg(val(r, k))}</b><span>Operações</span><b>${val(r, k, "trades") ?? "—"}</b>
      <span>Acerto</span><b>${val(r, k, "win_pct") == null ? "—" : nf(val(r, k, "win_pct"), 0) + "%"}</b><span>Pior queda</span><b>${val(r, k, "dd_pct") == null ? "—" : "−" + nf(val(r, k, "dd_pct"), 1) + "%"}</b></div>`;
    return `<div class="det">
      ${["d1", "d7", "d30"].map((k) => `<div><h5>${W[k]}</h5>${win(k)}</div>`).join("")}
      <div><h5>Mês por moeda</h5>${ps.length ? ps.map(([s, v]) => `<div class="sym"><span>${esc(s.replace(/USDT$/, ""))}</span><span class="tr"><i style="${v >= 0 ? "left:50%" : "right:50%"};width:${Math.abs(v) / mx * 50}%;background:${v >= 0 ? "#26a69a" : "#ef5350"}"></i></span><b class="${cls(v)}">${sg(v)}</b></div>`).join("") : `<p class="empty">Sem dados.</p>`}</div>
      <div><h5>Evolução do mês (dia a dia)</h5>${spark(r.history, 220, 54)}<p class="foot" style="margin-top:6px">${r.updated ? "Atualizado em " + esc(r.updated) + " UTC" : "Ainda não calculado"}${r.live_trades ? ` · real: ${r.live_trades} operações, ${nf(r.live_pnl)} USDT` : ""}</p>
        <button class="btn pri" data-bt="${esc(r.id)}" ${data.busy === r.id ? "disabled" : ""}>${data.busy === r.id ? "Rodando…" : "▶️ Rodar backtest agora"}</button></div></div>`;
  }
  function draw() {
    const all = data.rows;
    const itvs = [...new Set(all.filter((r) => !S.m || r.market === S.m).map((r) => r.interval))].sort((a, b) => (data.order[a] ?? 99) - (data.order[b] ?? 99));
    if (S.i && !itvs.includes(S.i)) S.i = "";
    const q = S.q.trim().toLowerCase();
    const rows = all.filter((r) => (!S.m || r.market === S.m) && (!S.i || r.interval === S.i) && (!q || r.name.toLowerCase().includes(q)))
      .sort((a, b) => (val(b, S.sort) ?? -1e9) - (val(a, S.sort) ?? -1e9));
    const top = rows.filter((r) => val(r, S.sort) != null).slice(0, 3);
    const medals = ["🥇", "🥈", "🥉"];
    const single = !!data.focus;
    root.innerHTML = `
      ${single ? "" : `<div class="bar">
        <div class="seg">${[["", "Todos"], ["futures", "Futuros"], ["spot", "Spot"]].map(([k, l]) => `<button data-m="${k}" class="${S.m === k ? "on" : ""}">${l}</button>`).join("")}</div>
        <div class="seg">${[""].concat(itvs).map((k) => `<button data-i="${k}" class="${S.i === k ? "on" : ""}">${k || "Todos"}</button>`).join("")}</div>
        <div class="seg">${Object.entries(W).map(([k, l]) => `<button data-s="${k}" class="${S.sort === k ? "on" : ""}">${l}</button>`).join("")}</div>
        <input class="search" placeholder="Buscar bot…" value="${esc(S.q)}"></div>
      ${top.length ? `<div class="podium">${top.map((r, n) => `<div class="pod g${n + 1}" data-open="${esc(r.id)}"><span class="medal">${medals[n]}</span>
        <h4>${esc(r.name)}</h4><div class="row3">${mk(r.market)}<span class="chip">${esc(r.interval)}</span>${statusChip(r.status)}</div>
        <span class="lbl">Retorno no ${W[S.sort].toLowerCase()}</span><div class="big ${cls(val(r, S.sort))}">${sg(val(r, S.sort))}</div>
        <div class="row3">${["d1", "d7", "d30"].filter((k) => k !== S.sort).map((k) => `<span class="pill ${cls(val(r, k))}">${W[k]} ${sg(val(r, k), 1)}</span>`).join("")}</div>
        ${spark(r.history, 200, 30)}</div>`).join("")}</div>` : ""}`}
      <div class="list">
        ${single ? "" : `<div class="lh"><span>#</span><span>Bot</span>${Object.entries(W).map(([k, l]) => `<span class="s ${S.sort === k ? "on" : ""}" data-s="${k}">${l} ${S.sort === k ? "▼" : ""}</span>`).join("")}<span>Operações/mês</span><span>Acerto</span><span>Evolução</span><span></span></div>`}
        ${rows.length ? rows.map((r, n) => `<div class="lr ${S.open === r.id ? "open" : ""}" data-open="${esc(r.id)}">
          <span class="pos">${single ? "" : n + 1}</span>
          <span class="nm"><b title="${esc(r.name)}">${esc(r.name)}</b><span class="tags">${mk(r.market)}<span class="chip">${esc(r.interval)}</span>${statusChip(r.status)}${r.kind ? `<span class="chip ok">${r.kind === "grid" ? "🕸️ grade" : "🪜 DCA"}</span>` : ""}${r.builtin ? "" : `<span class="chip">criado por usuário</span>`}</span></span>
          ${["d1", "d7", "d30"].map((k) => `<span class="${k === "d30" ? "" : "hide-s"}"><span class="pill ${cls(val(r, k))}">${sg(val(r, k))}</span></span>`).join("")}
          <span class="hide-s">${val(r, "d30", "trades") ?? "—"}</span><span class="hide-s">${val(r, "d30", "win_pct") == null ? "—" : nf(val(r, "d30", "win_pct"), 0) + "%"}</span>
          <span class="hide-s">${spark(r.history)}</span><span class="chev">›</span></div>${S.open === r.id ? details(r) : ""}`).join("") : `<p class="empty" style="padding:12px">Nenhum bot com esses filtros.</p>`}
      </div>
      ${single ? "" : `<p class="foot">${esc(data.note)}</p>`}`;
    const s = root.querySelector(".search");
    if (s && root._focusSearch) { s.focus(); s.setSelectionRange(s.value.length, s.value.length); }
  }
  draw();
  root.onclick = (e) => {
    const b = e.target.closest("button, [data-open], [data-s]"); if (!b) return;
    if (b.dataset.bt) { setTriggerValue("action", { kind: "backtest", id: b.dataset.bt, uid: Date.now() + "-" + Math.random() }); return; }
    if (b.dataset.m !== undefined) S.m = b.dataset.m;
    else if (b.dataset.i !== undefined) S.i = b.dataset.i;
    else if (b.dataset.s) S.sort = b.dataset.s;
    else if (b.dataset.open) S.open = S.open === b.dataset.open && !data.focus ? null : b.dataset.open;
    root._focusSearch = false; draw();
  };
  root.oninput = (e) => { if (e.target.classList.contains("search")) { S.q = e.target.value; root._focusSearch = true; draw(); } };
}
