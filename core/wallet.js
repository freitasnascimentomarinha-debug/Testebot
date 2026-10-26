// Carteira (componente do Streamlit): resumo, gráficos em SVG com dica ao passar o mouse e abas de resultado, comparação, histórico e extrato.
export default function (component) {
  const { data, parentElement } = component;
  const nf = (v, d = 2) => (v == null || Number.isNaN(v)) ? "—" : Number(v).toLocaleString("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d });
  const sg = (v, d = 2) => v == null ? "—" : (v > 0 ? "+" : v < 0 ? "−" : "") + nf(Math.abs(v), d);
  const cls = (v) => v > 0 ? "up" : v < 0 ? "dn" : "";
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const dt = (iso, sec) => iso ? new Date(iso).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", year: "2-digit", hour: "2-digit", minute: "2-digit", ...(sec ? { second: "2-digit" } : {}) }) : "—";
  const root = parentElement.querySelector(".wx") || parentElement.appendChild(Object.assign(document.createElement("div"), { className: "wx" }));
  const S = root.state || (root.state = { tab: "evo", q: "", bot: "", org: "" });
  const s = data.stats, neg = (s.total_pnl || 0) < 0;
  const tile = (l, v, sub = "", c = "") => `<div class="tile"><span class="lbl">${l}</span><b class="${c}">${v}</b>${sub ? `<small>${sub}</small>` : ""}</div>`;

  // gráfico de área com dica (pontos [x_ms, y])
  function area(id, pts, { h = 240, color, base = null, fmt = (v) => nf(v), label = "" } = {}) {
    if (pts.length < 2) return `<p class="empty">A curva aparece conforme a carteira é atualizada (a cada 5 min ou a cada operação).</p>`;
    const W = 1000, P = 6, xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
    const x0 = Math.min(...xs), x1 = Math.max(...xs), lo = Math.min(...ys, base ?? Infinity), hi = Math.max(...ys, base ?? -Infinity), sp = (hi - lo) || 1;
    const X = (t) => P + (t - x0) / ((x1 - x0) || 1) * (W - 2 * P), Y = (v) => h - P - (v - lo) / sp * (h - 2 * P);
    const line = pts.map((p) => `${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join(" ");
    const c = color || (ys[ys.length - 1] >= (base ?? ys[0]) ? "#26a69a" : "#ef5350");
    root._charts = root._charts || {}; root._charts[id] = { pts, X, Y, fmt, label, W, h };
    return `<div class="chartbox" data-chart="${id}"><svg viewBox="0 0 ${W} ${h}" height="${h}" preserveAspectRatio="none">
      <defs><linearGradient id="g${id}" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="${c}" stop-opacity=".32"/><stop offset="1" stop-color="${c}" stop-opacity="0"/></linearGradient></defs>
      ${base != null ? `<line x1="${P}" x2="${W - P}" y1="${Y(base)}" y2="${Y(base)}" stroke="#5d606b" stroke-dasharray="5 5"/>` : ""}
      <polygon fill="url(#g${id})" points="${X(x0)},${h - P} ${line} ${X(x1)},${h - P}"/><polyline fill="none" stroke="${c}" stroke-width="2.2" vector-effect="non-scaling-stroke" points="${line}"/>
      <line class="cur" x1="0" x2="0" y1="0" y2="${h}" stroke="#8a8f98" stroke-dasharray="3 3" style="display:none"/></svg><div class="tip"></div></div>`;
  }
  function bars(days) {
    if (!days.length) return `<p class="empty">Sem operações encerradas ainda.</p>`;
    const W = 1000, h = 200, mx = Math.max(...days.map((d) => Math.abs(d.pnl)), 1), bw = Math.max(3, Math.min(40, (W - 20) / days.length - 4)), zero = h / 2;
    return `<svg viewBox="0 0 ${W} ${h}" height="${h}" preserveAspectRatio="none" style="display:block;width:100%"><line x1="0" x2="${W}" y1="${zero}" y2="${zero}" stroke="#2a3042"/>
      ${days.map((d, i) => { const x = 10 + i * ((W - 20) / days.length), bh = Math.abs(d.pnl) / mx * (h / 2 - 8);
        return `<rect x="${x}" y="${d.pnl >= 0 ? zero - bh : zero}" width="${bw}" height="${Math.max(1, bh)}" rx="3" fill="${d.pnl >= 0 ? "#26a69a" : "#ef5350"}"><title>${d.date.split("-").reverse().join("/")}: ${sg(d.pnl)} USDT · ${d.n} operações</title></rect>`; }).join("")}</svg>`;
  }
  const cmp = (title, obj) => `<div class="panel"><h3>${title}</h3><div class="cmp">${Object.entries(obj).map(([k, v]) => `<div class="cmpc"><h4>${esc(k)}</h4><div class="kv">
      <span>Operações</span><b>${v.n}</b><span>Acerto</span><b>${nf(v.win_pct, 0)}%</b><span>Resultado</span><b class="${cls(v.pnl)}">${sg(v.pnl)} USDT</b>
      <span>Ganho médio</span><b class="up">${sg(v.avg_win)}</b><span>Perda média</span><b class="dn">${sg(v.avg_loss)}</b><span>Fator de lucro</span><b>${v.pf == null ? "—" : nf(v.pf)}</b></div></div>`).join("") || `<p class="empty">Sem operações encerradas.</p>`}</div></div>`;

  function tabBody() {
    if (S.tab === "evo") {
      const pts = data.curve.map((c) => [new Date(c[0]).getTime(), c[1]]);
      let peak = -Infinity; const dd = pts.map(([t, v]) => { peak = Math.max(peak, v); return [t, (v / peak - 1) * 100]; });
      return `<div class="panel"><h3>Evolução da banca <span class="mut" style="text-transform:none;letter-spacing:0">tracejado = capital investido</span></h3>${area("eq", pts, { base: s.invested, fmt: (v) => nf(v) + " USDT" })}</div>
        <div class="panel"><h3>Queda a partir do pico (drawdown)</h3>${area("dd", dd, { h: 120, color: "#ef5350", fmt: (v) => nf(v) + "%" })}</div>`;
    }
    if (S.tab === "day") {
      return `<div class="panel"><h3>Resultado por dia</h3>${bars(data.daily)}</div>${data.daily.length ? `<div class="panel scroll"><table class="t"><tr><th>Data</th><th>Operações</th><th>Ganhos</th><th>Perdas</th><th>Acerto</th><th>Taxas</th><th>Resultado</th><th>Acumulado</th></tr>
        ${data.daily.slice().reverse().map((d) => `<tr><td>${d.date.split("-").reverse().join("/")}</td><td>${d.n}</td><td class="up">${d.wins}</td><td class="dn">${d.n - d.wins}</td><td>${nf(d.wins / d.n * 100, 0)}%</td><td>${nf(d.fees)}</td><td class="${cls(d.pnl)}"><b>${sg(d.pnl)}</b></td><td class="${cls(d.acc)}">${sg(d.acc)}</td></tr>`).join("")}</table></div>` : ""}`;
    }
    if (S.tab === "cmp") return cmp("Por quem decidiu", data.by_origin) + cmp("Por bot", data.by_bot);
    if (S.tab === "hist") {
      const bots = [...new Set(data.trades.map((t) => t.bot))], orgs = [...new Set(data.trades.map((t) => t.origin))], q = S.q.trim().toUpperCase();
      const list = data.trades.filter((t) => (!S.bot || t.bot === S.bot) && (!S.org || t.origin === S.org) && (!q || (t.symbol || "").includes(q)));
      const total = list.reduce((a, t) => a + (t.pnl || 0), 0);
      return `<div class="bar"><div class="seg"><button data-bot="" class="${!S.bot ? "on" : ""}">Todos os bots</button>${bots.map((b) => `<button data-bot="${esc(b)}" class="${S.bot === b ? "on" : ""}">${esc(b)}</button>`).join("")}</div>
          <div class="seg"><button data-org="" class="${!S.org ? "on" : ""}">Todas as origens</button>${orgs.map((o) => `<button data-org="${esc(o)}" class="${S.org === o ? "on" : ""}">${esc(o)}</button>`).join("")}</div>
          <input class="search" placeholder="Filtrar ativo (ex.: BTC)" value="${esc(S.q)}"></div>
        <p class="mut" style="margin:0">${list.length} operações · resultado do filtro: <b class="${cls(total)}">${sg(total)} USDT</b></p>
        ${list.length ? `<div class="panel scroll"><table class="t"><tr><th>Encerrada</th><th>Ativo</th><th>Lado</th><th>Bot / origem</th><th>Entrada → saída</th><th>Motivo</th><th>Taxas</th><th>Resultado</th><th>% margem</th></tr>
          ${list.map((t) => `<tr><td>${dt(t.closed)}</td><td><b>${esc(t.symbol)}</b></td><td><span class="chip ${t.side === "BUY" ? "buy" : "sell"}">${t.side === "BUY" ? "Compra" : "Venda"}</span>${t.lev > 1 ? ` <span class="mut">${nf(t.lev, 0)}×</span>` : ""}</td>
            <td>${esc(t.bot)}<br><span class="mut">${esc(t.origin)}${t.personality ? " · " + esc(t.personality) : ""}</span></td><td>${nf(t.entry, 4)} → ${nf(t.exit, 4)}</td><td>${esc(t.reason)}</td><td>${nf(t.fees)}</td>
            <td class="${cls(t.pnl)}"><b>${sg(t.pnl)}</b></td><td class="${cls(t.pct)}">${t.pct == null ? "—" : sg(t.pct, 1) + "%"}</td></tr>`).join("")}</table></div>` : `<p class="empty">Nenhuma operação encerrada com esses filtros.</p>`}`;
    }
    return data.ledger.length ? `<div class="panel scroll"><table class="t"><tr><th>Data/hora</th><th>Lançamento</th><th>Bot</th><th>Ativo</th><th>Valor</th><th>Banca realizada</th><th>Detalhe</th></tr>
      ${data.ledger.map((e) => `<tr><td>${dt(e.time, true)}</td><td>${esc(e.type)}</td><td>${esc(e.bot)}</td><td>${esc(e.symbol)}</td><td class="${cls(e.amount)}"><b>${sg(e.amount)}</b></td><td>${nf(e.bank)}</td><td class="mut">${esc(e.detail)}</td></tr>`).join("")}</table></div>
      <p class="mut" style="margin:0">Banca realizada = saldo livre + margens em uso (sem o resultado das posições ainda abertas).</p>` : `<p class="empty">Sem lançamentos.</p>`;
  }
  const TABS = { evo: "📈 Evolução", day: "📅 Resultado diário", cmp: "🧑‍💻 Você × Bots", hist: "📜 Histórico", led: "🧾 Extrato" };
  function draw() {
    root.innerHTML = `<div class="hero">
      <div class="big ${neg ? "neg" : ""}"><span class="lbl">${esc(data.label)} · banca</span><div class="v">${nf(s.equity)} <small>USDT</small></div>
        <div class="d ${cls(s.total_pnl)}">${sg(s.total_pnl)} USDT (${sg(s.total_pnl_pct)}%) desde o início</div>
        ${data.brl ? `<div class="brl">≈ R$ ${nf(s.equity * data.brl)} · USDT/BRL ${nf(data.brl, 4)}</div>` : ""}
        <div class="brl">${data.mode === "única" ? "Carteira única (bots + você)" : "Separada por bot"} · criada em ${esc(data.created.split("-").reverse().join("/"))}</div></div>
      <div class="tiles">${tile("Capital investido", nf(s.invested), "inicial " + nf(data.initial))}${tile("Saldo livre", nf(s.available))}
        ${tile("Alocado em posições", nf(s.in_margin), s.open_positions + " posição(ões)")}${tile("P&L aberto (líquido)", sg(s.unrealized_net), "", cls(s.unrealized_net))}
        ${tile("Hoje", sg(s.pnl_today), s.trades_today + " operações", cls(s.pnl_today))}${tile("Operações", s.trades)}
        ${tile("Taxa de acerto", nf(s.win_rate, 1) + "%")}${tile("Fator de lucro", s.profit_factor_inf ? "∞" : nf(s.profit_factor))}
        ${tile("Ganho / perda médios", `<span class="up">${nf(s.avg_win)}</span> / <span class="dn">${nf(s.avg_loss)}</span>`)}${tile("Drawdown máximo", "−" + nf(Math.abs(s.max_drawdown || 0)) + "%", "", "dn")}</div></div>
      <div class="seg">${Object.entries(TABS).map(([k, l]) => `<button data-tab="${k}" class="${S.tab === k ? "on" : ""}">${l}</button>`).join("")}</div>
      ${tabBody()}`;
    const sch = root.querySelector(".search"); if (sch && root._fs) { sch.focus(); sch.setSelectionRange(sch.value.length, sch.value.length); }
  }
  draw();
  root.onclick = (e) => {
    const b = e.target.closest("button"); if (!b) return;
    if (b.dataset.tab) S.tab = b.dataset.tab; else if (b.dataset.bot !== undefined) S.bot = b.dataset.bot; else if (b.dataset.org !== undefined) S.org = b.dataset.org; else return;
    root._fs = false; draw();
  };
  root.oninput = (e) => { if (e.target.classList.contains("search")) { S.q = e.target.value; root._fs = true; draw(); } };
  root.onmousemove = (e) => {
    const box = e.target.closest(".chartbox"); if (!box) return; const c = root._charts[box.dataset.chart]; if (!c) return;
    const r = box.getBoundingClientRect(), fx = (e.clientX - r.left) / r.width * c.W;
    let best = c.pts[0]; for (const p of c.pts) if (Math.abs(c.X(p[0]) - fx) < Math.abs(c.X(best[0]) - fx)) best = p;
    const ln = box.querySelector(".cur"), tp = box.querySelector(".tip"), px = c.X(best[0]) / c.W * r.width;
    ln.setAttribute("x1", c.X(best[0])); ln.setAttribute("x2", c.X(best[0])); ln.style.display = "";
    tp.style.display = "block"; tp.innerHTML = `${dt(new Date(best[0]).toISOString())}<br><b>${c.fmt(best[1])}</b>`;
    tp.style.left = Math.min(r.width - 140, Math.max(0, px + 10)) + "px"; tp.style.top = "8px";
  };
  root.onmouseleave = () => root.querySelectorAll(".tip, .cur").forEach((x) => (x.style.display = "none"));
}
