// Minha conta (componente do Streamlit): perfil, escolha da conta de operação em cartões, suas escolhas salvas e o uso da IA.
export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  const nf = (v, d = 2) => (v == null || Number.isNaN(v)) ? "—" : Number(v).toLocaleString("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d });
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const root = parentElement.querySelector(".wx") || parentElement.appendChild(Object.assign(document.createElement("div"), { className: "wx" }));
  const u = data.user;
  root.innerHTML = `<div class="big"><div class="uh"><span class="av" style="background:#42a5f5;width:52px;height:52px;font-size:1.2rem">${esc(u.name.slice(0, 2).toUpperCase())}</span><div>
      <b style="font-size:1.4rem">${esc(u.name)}</b> ${u.admin ? `<span class="chip on">⭐ admin</span>` : ""}
      <div class="sub">${u.created ? "conta criada em " + esc(u.created.split("-").reverse().join("/")) + " · " : ""}dados guardados em: ${esc(u.storage)}</div></div></div></div>
    <div class="panel"><h3>🏦 Conta de operação <span class="mut" style="text-transform:none;letter-spacing:0">clique para escolher · fica salva na sua conta</span></h3>
      <div class="modes">${data.modes.map((m) => `<div class="mode ${m.key === data.mode ? "sel" : ""}" data-mode="${esc(m.key)}"><b>${esc(m.label)}</b><p>${esc(m.desc)}</p>
        ${m.key === data.mode ? `<span class="chip on" style="align-self:flex-start">em uso</span>` : ""}${m.warn ? `<span class="w">⚠️ ${esc(m.warn)}</span>` : ""}</div>`).join("")}</div></div>
    <div class="panel"><h3>💾 Suas escolhas salvas <span class="mut" style="text-transform:none;letter-spacing:0">voltam iguais em qualquer aparelho · altere em cada bot</span></h3>
      <div class="tiles" style="margin-bottom:10px"><div class="tile"><span class="lbl">Banca inicial da carteira</span><b>${nf(data.bank)} USDT</b></div>
        ${data.ai ? `<div class="tile"><span class="lbl">Análises da IA hoje</span><b>${data.ai.used}${data.ai.limit > 0 ? " de " + data.ai.limit : ""}</b>
          ${data.ai.limit > 0 ? `<div class="meter"><i style="width:${Math.min(100, data.ai.used / data.ai.limit * 100)}%"></i></div>` : `<small>sem limite</small>`}</div>` : ""}</div>
      <div class="cmp">${data.bots.map((b) => `<div class="cmpc"><h4>${esc(b.name)} ${b.autopilot ? `<span class="chip on">🟢 ligado</span>` : `<span class="chip">⚪ desligado</span>`}</h4><div class="kv">
        <span>Ativo</span><b>${esc(b.symbol)}</b><span>Tempo gráfico</span><b>${esc(b.interval)}</b><span>Perda máxima por trade</span><b>${esc(b.risk)}</b>
        <span>Alavancagem</span><b>${esc(b.leverage)}</b><span>Bot do momento</span><b>${esc(b.personality)}</b><span>Varredura</span><b>${esc(b.scan)}</b></div></div>`).join("")}</div></div>`;
  root.onclick = (e) => {
    const m = e.target.closest(".mode"); if (!m || m.dataset.mode === data.mode) return;
    setTriggerValue("mode", { mode: m.dataset.mode, uid: Date.now() + "-" + Math.random() });
  };
}
