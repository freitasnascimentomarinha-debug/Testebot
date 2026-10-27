// Laboratório de treino (componente do Streamlit): cada variante de dados de treino comparada com a base no mesmo teste.
export default function (component) {
  const { data, parentElement } = component;
  const nf = (v, d = 2) => (v == null || Number.isNaN(v)) ? "—" : Number(v).toLocaleString("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d });
  const sg = (v, d = 2, suf = "%") => v == null ? "—" : (v > 0 ? "+" : v < 0 ? "−" : "") + nf(Math.abs(v), d) + suf;
  const cls = (v) => v == null ? "zero" : v > 0 ? "up" : v < 0 ? "dn" : "zero";
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const root = parentElement.querySelector(".bx") || parentElement.appendChild(Object.assign(document.createElement("div"), { className: "bx" }));
  const S = root.state || (root.state = { key: null });
  if (data.sel && data.sel !== S.lastSel) { S.key = data.sel; S.lastSel = data.sel; }
  const ICON = { base: "📏", moedas: "🪙", historico: "📜", features: "🧩", tudo: "🧪" };
  function draw() {
    const res = data.results;
    if (!res.length) { root.innerHTML = `<p class="empty">Nenhum experimento rodado ainda. Escolha o mercado e o tempo gráfico e clique em Rodar experimento.</p>`; return; }
    if (!res.some((r) => r.key === S.key)) S.key = res[0].key;
    const r = res.find((x) => x.key === S.key);
    const base = r.rows.find((x) => x.key === "base");
    const wins = r.rows.filter((x) => x.better);
    const best = wins.sort((a, b) => b.d_mon - a.d_mon)[0];
    root.innerHTML = `
      <div class="bar"><div class="seg">${res.map((x) => `<button data-k="${esc(x.key)}" class="${x.key === S.key ? "on" : ""}">${x.market === "futures" ? "Futuros" : "Spot"} ${esc(x.interval)}</button>`).join("")}</div>
        <span class="foot">Rodado em ${esc(r.ran_at)} UTC · teste nas mesmas moedas e nos mesmos ${nf(r.test_days, 0)} dias para todas as variantes</span></div>
      <div class="lab-verdict ${best ? "ok" : "no"}">${best ? `✅ <b>${esc(best.label)}</b> melhorou: mediana dos modelos ${sg(best.d_mon)} ao mês contra a base e ${best.confirmed} modelo(s) confirmados nas duas metades do teste.`
        : `➖ Nenhuma variante melhorou a mediana dos modelos com confirmação nas duas metades do teste. Mais dados não ajudaram neste mercado e tempo gráfico.`}</div>
      <div class="lab-grid">${r.rows.map((x) => `<div class="lab-card ${x.key === "base" ? "base" : x.better ? "good" : "bad"}">
        <div class="lab-h"><span>${ICON[x.key] || "•"}</span><b>${esc(x.label)}</b>${x.key === "base" ? `<span class="chip">referência</span>` : x.better ? `<span class="chip ok">melhorou</span>` : `<span class="chip bad">não melhorou</span>`}</div>
        <small class="mut">${nf(x.train_days, 0)} dias de treino · ${x.coins} moedas</small>
        <div class="tiles">
          <div class="tile"><span class="lbl">Mediana ao mês</span><b class="${cls(x.mon_med)}">${sg(x.mon_med)}</b><small class="${cls(x.d_mon)}">${x.d_mon == null ? "base" : sg(x.d_mon) + " vs base"}</small></div>
          <div class="tile"><span class="lbl">AUC mediana</span><b>${nf(x.auc_med, 3)}</b><small class="${cls(x.d_auc)}">${x.d_auc == null ? "base" : sg(x.d_auc, 3, "") + " vs base"}</small></div>
          <div class="tile"><span class="lbl">Confirmados</span><b>${x.confirmed}</b><small>${x.positive}/${x.total} positivos</small></div>
        </div>
        <small>Melhor: ${esc(x.best)} <b class="${cls(x.best_monthly)}">${sg(x.best_monthly)}</b></small></div>`).join("")}</div>
      <p class="foot">Cada variante treina os mesmos algoritmos com re-treino (walk-forward) e é testada nas mesmas velas, operando sozinha, com taxas. "Confirmados" = modelos com ${data.min_trades}+ operações positivos nas duas metades do teste. Uma variante só conta como melhora se subir a mediana e não reduzir os confirmados.</p>`;
  }
  root.onclick = (e) => { const t = e.target.closest("[data-k]"); if (t) { S.key = t.dataset.k; draw(); } };
  draw();
}
