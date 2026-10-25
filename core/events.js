// Painel de eventos (componente do Streamlit): cartões do Polymarket com filtro por categoria. Os números chegam prontos do Python.
export default function (component) {
  const { data, parentElement } = component;
  const nf = (v, d = 0) => Number(v).toLocaleString("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d });
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const root = parentElement.querySelector(".ev") || parentElement.appendChild(Object.assign(document.createElement("div"), { className: "ev" }));
  const cats = data.categories, now = Date.now();
  let active = root.dataset.cat || "todas";
  const left = (iso) => { const ms = new Date(iso) - now; if (ms <= 0) return "encerrando"; const h = ms / 36e5, d = Math.floor(h / 24);
    return d >= 2 ? `em ${d} dias` : d === 1 ? "amanhã" : h >= 1 ? `em ${Math.floor(h)} h` : "em minutos"; };
  const when = (iso) => new Date(iso).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
  const money = (v) => v >= 1e6 ? "US$ " + nf(v / 1e6, 1) + " mi" : v >= 1e3 ? "US$ " + nf(v / 1e3, 0) + " mil" : "US$ " + nf(v);
  const card = (e) => `<article class="card ${e.ia ? "ia" : ""}">
    <header><span class="chip c-${e.categoria}">${esc(cats[e.categoria] || e.categoria)}</span>${e.ia ? `<span class="chip ai" title="Este evento é enviado como contexto para a IA nas análises">🤖 enviado à IA</span>` : ""}</header>
    <h3><a href="https://polymarket.com/event/${esc(e.slug)}" target="_blank" rel="noopener noreferrer">${esc(e.titulo)}</a></h3>
    <div class="opts">${e.opcoes.map((o) => `<div class="o"><span class="n">${esc(o.nome)}</span><span class="b"><i style="width:${Math.max(1, o.pct)}%"></i></span><b>${nf(o.pct, o.pct < 10 ? 1 : 0)}%</b></div>`).join("")}</div>
    <footer><span title="${esc(when(e.vence))}">⏳ vence ${left(e.vence)} · ${esc(when(e.vence))}</span><span>${money(e.volume_24h)} em 24 h</span></footer></article>`;
  const draw = () => {
    const list = data.events.filter((e) => active === "todas" || e.categoria === active);
    const week = list.filter((e) => new Date(e.vence) - now <= 7 * 864e5), later = list.filter((e) => new Date(e.vence) - now > 7 * 864e5);
    root.dataset.cat = active;
    root.innerHTML = `<div class="chips"><button data-c="todas" class="${active === "todas" ? "on" : ""}">Todos (${data.events.length})</button>${Object.keys(cats).map((c) =>
      `<button data-c="${c}" class="${active === c ? "on" : ""}">${esc(cats[c])} (${data.events.filter((e) => e.categoria === c).length})</button>`).join("")}</div>
      ${week.length ? `<h2>Vencem em até 7 dias</h2><div class="grid">${week.map(card).join("")}</div>` : ""}
      ${later.length ? `<h2>Mais adiante</h2><div class="grid">${later.map(card).join("")}</div>` : ""}
      ${list.length ? "" : `<p class="empty">Nenhum evento nesta categoria agora.</p>`}
      <p class="foot">Atualizado às ${esc(data.updated)} · probabilidades de apostadores com dinheiro real no Polymarket; contexto, não recomendação.</p>`;
  };
  draw();
  root.onclick = (e) => { const b = e.target.closest("button[data-c]"); if (b) { active = b.dataset.c; draw(); } };
}
