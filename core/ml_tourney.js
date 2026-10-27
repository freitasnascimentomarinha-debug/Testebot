// Torneio de modelos (componente do Streamlit): campeão geral, campeões por contexto, placar e mapa de calor modelo × contexto.
// O mercado/tempo gráfico e a linha aberta ficam guardados no próprio elemento.
export default function (component) {
  const { data, parentElement } = component;
  const nf = (v, d = 2) => (v == null || Number.isNaN(v)) ? "—" : Number(v).toLocaleString("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d });
  const sg = (v, d = 2) => v == null ? "—" : (v > 0 ? "+" : v < 0 ? "−" : "") + nf(Math.abs(v), d) + "%";
  const cls = (v) => v == null ? "zero" : v > 0 ? "up" : v < 0 ? "dn" : "zero";
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const root = parentElement.querySelector(".bx") || parentElement.appendChild(Object.assign(document.createElement("div"), { className: "bx" }));
  const S = root.state || (root.state = { key: null, open: null, sort: "monthly" });
  if (data.sel && data.sel !== S.lastSel) { S.key = data.sel; S.lastSel = data.sel; }
  const res = data.results;
  const G = Object.fromEntries(data.groups);
  const mk = (m) => `<span class="chip ${m === "futures" ? "fut" : "spot"}">${m === "futures" ? "Futuros" : "Spot"}</span>`;
  const heat = (v) => {
    if (v == null) return "transparent";
    const a = Math.min(Math.abs(v) / 1.0, 1) * 0.55 + 0.08;
    return v >= 0 ? `rgba(38,166,154,${a.toFixed(2)})` : `rgba(239,83,80,${a.toFixed(2)})`;
  };
  function draw() {
    if (!res.length) { root.innerHTML = `<p class="empty">Nenhum torneio rodado ainda. Escolha o mercado e o tempo gráfico acima e clique em Rodar torneio.</p>`; return; }
    if (!res.some((r) => r.key === S.key)) S.key = res[0].key;
    const r = res.find((x) => x.key === S.key);
    const champ = r.rows.find((x) => x.combo === r.champion);
    const best = champ || r.rows[0];
    const rows = [...r.rows].sort((a, b) => S.sort === "auc" ? (b.auc ?? 0) - (a.auc ?? 0) : S.sort === "win" ? b.win - a.win : 0);
    const ctxCh = Object.entries(r.by_ctx);
    const byCombo = Object.fromEntries(r.rows.map((x) => [x.combo, x]));
    const top = r.rows.slice(0, 10);
    root.innerHTML = `
      <div class="bar"><div class="seg">${res.map((x) => `<button data-k="${esc(x.key)}" class="${x.key === S.key ? "on" : ""}">${x.market === "futures" ? "Futuros" : "Spot"} ${esc(x.interval)}${data.busy.includes(x.key) ? " ⏳" : ""}</button>`).join("")}</div>
        <span class="foot">Rodado em ${esc(r.ran_at)} UTC · teste de ${nf(r.test_days, 0)} dias · treino de ${nf(r.train_days, 0)} dias · re-treino a cada ${nf(r.step_days, 0)} dias · ${esc(r.symbols.join(", "))}</span></div>
      <div class="podium">
        <div class="pod ${champ ? "g1" : ""}"><span class="medal">${champ ? "🏆" : "🤷"}</span>
          <span class="lbl">Campeão geral · ${mk(r.market)} <span class="chip">${esc(r.interval)}</span></span>
          <h4>${champ ? esc(champ.algo) : "Nenhum modelo teve vantagem"}</h4>
          <span class="mut" style="font-size:.78rem">${champ ? esc(champ.target) : `Melhor colocado: ${esc(best.algo)} · ${esc(best.target)}. O modelo ao vivo continua no padrão (LightGBM · direção).`}</span>
          <div class="big ${cls(best.monthly)}">${sg(best.monthly)}<span class="mut" style="font-size:.8rem;font-weight:600"> ao mês</span></div>
          <div class="row3"><span class="pill zero">AUC ${nf(best.auc, 3)}</span><span class="pill zero">${best.n} op.</span><span class="pill zero">acerto ${nf(best.win, 0)}%</span><span class="pill zero">PF ${nf(best.pf, 2)}</span></div></div>
        <div class="pod"><span class="lbl">Campeões por contexto</span>
          ${ctxCh.length ? `<div class="mt-ctx">${ctxCh.map(([g, c]) => { const x = byCombo[c] || {}; const cx = (x.ctx || {})[g] || {};
            return `<div><span>${esc(G[g] || g)}</span><b>${esc(x.algo)}</b><small>${esc(x.target)}</small><span class="pill ${cls(cx.avg)}">${sg(cx.avg, 2)}/op · ${cx.n ?? 0}</span></div>`; }).join("")}</div>`
            : `<p class="empty">Nenhum modelo teve resultado positivo em um contexto com operações suficientes.</p>`}
          <p class="foot">Ao vivo, quando o gráfico está num desses contextos, o voto vem do campeão dele.</p></div>
      </div>
      <div class="list">
        <div class="lh mt"><span>#</span><span>Modelo</span><span class="s ${S.sort === "auc" ? "on" : ""}" data-s="auc">AUC</span><span>Operações</span><span class="s ${S.sort === "win" ? "on" : ""}" data-s="win">Acerto</span><span>Média/op.</span><span class="s ${S.sort === "monthly" ? "on" : ""}" data-s="monthly">Ao mês</span><span>PF</span><span></span></div>
        ${rows.map((x, n) => `<div class="lr mt ${S.open === x.combo ? "open" : ""}" data-open="${esc(x.combo)}">
          <span class="pos">${x.combo === r.champion ? "🏆" : n + 1}</span>
          <span class="nm"><b>${esc(x.algo)}</b><span class="tags"><span class="chip">${esc(x.target)}</span>${x.n < data.min_trades ? `<span class="chip mid">poucas operações</span>` : ""}${Object.entries(r.by_ctx).filter(([, c]) => c === x.combo).map(([g]) => `<span class="chip ok">${esc(G[g])}</span>`).join("")}</span></span>
          <span class="${x.auc != null && x.auc >= 0.53 ? "up" : x.auc != null && x.auc < 0.5 ? "dn" : ""}" style="font-weight:700">${nf(x.auc, 3)}</span>
          <span>${x.n}</span><span>${nf(x.win, 0)}%</span><span class="${cls(x.avg)}">${sg(x.avg, 2)}</span>
          <span><span class="pill ${cls(x.monthly)}">${sg(x.monthly)}</span></span><span>${nf(x.pf, 2)}</span><span class="chev">›</span></div>
          ${S.open === x.combo ? `<div class="det"><div><h5>Por contexto do gráfico</h5><table class="ctx"><tr><th>Contexto</th><th>Op.</th><th>Acerto</th><th>Média/op.</th><th>1ª metade</th><th>2ª metade</th><th>AUC</th></tr>
            ${data.groups.map(([g, lab]) => { const c = x.ctx[g] || {}; return c.n || c.auc != null ? `<tr><td>${esc(lab)}</td><td>${c.n || 0}</td><td>${c.n ? nf(c.win, 0) + "%" : "—"}</td><td class="${cls(c.avg)}">${c.n ? sg(c.avg) : "—"}</td>${(c.halves || [null, null]).map((h) => `<td class="${cls(h)}">${h == null ? "—" : sg(h)}</td>`).join("")}<td>${nf(c.auc, 3)}</td></tr>` : ""; }).join("")}</table></div>
            <div><h5>Metades do teste (soma por moeda)</h5><div class="kv"><span>1ª metade</span><b class="${cls(x.halves[0])}">${sg(x.halves[0])}</b><span>2ª metade</span><b class="${cls(x.halves[1])}">${sg(x.halves[1])}</b></div>
            <p class="foot" style="margin-top:6px">Para ser campeão, o modelo precisa ganhar nas duas metades: o melhor de muitas tentativas costuma ter tido sorte, e a outra metade confirma ou derruba.</p></div></div>` : ""}`).join("")}
      </div>
      <div class="chart"><span class="lbl">Mapa de calor · resultado médio por operação (top 10 modelos × contexto)</span>
        <div class="mt-heat" style="grid-template-columns: minmax(170px, 1.6fr) repeat(${data.groups.length}, minmax(64px, 1fr))">
          <span></span>${data.groups.map(([, lab]) => `<span class="hh">${esc(lab)}</span>`).join("")}
          ${top.map((x) => `<span class="hn" title="${esc(x.algo)} · ${esc(x.target)}">${esc(x.algo)}<small>${esc(x.target)}</small></span>${data.groups.map(([g]) => { const c = x.ctx[g] || {};
            return `<span class="hc ${r.by_ctx[g] === x.combo ? "best" : ""}" style="background:${c.n ? heat(c.avg) : "transparent"}">${c.n ? sg(c.avg, 2) + `<small>${c.n} op.</small>` : `<small>—</small>`}</span>`; }).join("")}`).join("")}
        </div></div>
      <p class="foot">Cada modelo opera sozinho nas velas de teste (fora do treino): compra quando a chance de alta passa de ${nf(data.thr * 100, 0)}%${r.market === "futures" ? `, vende quando fica abaixo de ${nf(100 - data.thr * 100, 0)}%` : ""}, sai pelo prazo ou pela barreira do alvo e paga as taxas. "Ao mês" = soma dos resultados por moeda (banca inteira em cada operação, sem alavancagem) levada a 30 dias. AUC 0,5 = moeda ao ar. Campeão geral exige ${data.min_trades}+ operações e resultado positivo nas duas metades do teste; o de contexto, o mesmo naquele contexto. Resultado passado não garante futuro.</p>`;
  }
  root.onclick = (e) => {
    const t = e.target.closest("[data-k],[data-s],[data-open]");
    if (!t) return;
    if (t.dataset.k) { S.key = t.dataset.k; S.open = null; }
    else if (t.dataset.s) S.sort = t.dataset.s;
    else if (t.dataset.open) S.open = S.open === t.dataset.open ? null : t.dataset.open;
    draw();
  };
  draw();
}
