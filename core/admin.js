// Administração de contas (componente do Streamlit): resumo, busca, abas por estado e ações por conta. As ações voltam ao Python, que confere a permissão.
export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const when = (iso) => iso ? new Date(iso).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", year: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—";
  const ago = (iso) => { if (!iso) return "nunca"; const m = (Date.now() - new Date(iso)) / 6e4; return m < 60 ? `há ${Math.max(1, Math.round(m))} min` : m < 1440 ? `há ${Math.round(m / 60)} h` : `há ${Math.round(m / 1440)} dia(s)`; };
  const COLORS = ["#26a69a", "#42a5f5", "#ab47bc", "#ffb74d", "#ef5350", "#8d6e63", "#66bb6a", "#29b6f6"];
  const color = (u) => COLORS[[...u].reduce((a, c) => a + c.charCodeAt(0), 0) % COLORS.length];
  const root = parentElement.querySelector(".wx") || parentElement.appendChild(Object.assign(document.createElement("div"), { className: "wx" }));
  const S = root.state || (root.state = { tab: data.rows.some((r) => r.estado === data.PENDING) ? "pend" : "act", q: "", panel: {} });
  const by = { pend: data.rows.filter((r) => r.estado === data.PENDING), act: data.rows.filter((r) => r.estado === data.ACTIVE), blk: data.rows.filter((r) => r.estado === data.BLOCKED) };
  const send = (kind, user, extra = {}) => setTriggerValue("action", { kind, user, ...extra, uid: Date.now() + "-" + Math.random() });
  function card(r, cls) {
    const me = r.usuario === data.me, locked = r.principal || me, p = S.panel[r.usuario];
    let acts = "";
    if (cls === "pend") acts = `<button class="btn ok" data-k="approve" data-u="${esc(r.usuario)}">✅ Autorizar</button><button class="btn no" data-k="reject" data-u="${esc(r.usuario)}">🚫 Recusar</button>`;
    else if (cls === "blk") acts = `<button class="btn ok" data-k="unblock" data-u="${esc(r.usuario)}">↩️ Reativar</button><button class="btn no" data-p="del" data-u="${esc(r.usuario)}">🗑️ Excluir</button>`;
    else if (!locked) acts = `<button class="btn" data-k="block" data-u="${esc(r.usuario)}">⛔ Bloquear</button><button class="btn" data-p="pw" data-u="${esc(r.usuario)}">🔑 Senha</button>
        <button class="btn" data-k="admin" data-u="${esc(r.usuario)}">${r.papel === "admin" ? "Remover admin" : "⭐ Tornar admin"}</button><button class="btn no" data-p="del" data-u="${esc(r.usuario)}">🗑️ Excluir</button>`;
    const panel = p === "pw" ? `<div class="inline"><input type="password" placeholder="Nova senha provisória (mín. 8)" data-pw="${esc(r.usuario)}"><button class="btn ok" data-k="password" data-u="${esc(r.usuario)}">Definir</button></div>`
      : p === "del" ? `<div class="inline"><label><input type="checkbox" checked data-wipe="${esc(r.usuario)}"> apagar também os dados (carteira, extrato, configurações)</label><button class="btn no" data-k="delete" data-u="${esc(r.usuario)}">Confirmar exclusão</button></div>` : "";
    return `<div class="user ${cls}"><div class="uh"><span class="av" style="background:${color(r.usuario)}">${esc(r.usuario.slice(0, 2).toUpperCase())}</span><div>
        <b>${esc(r.usuario)}</b> ${r.papel === "admin" ? `<span class="chip on">⭐ admin</span>` : ""}${r.principal ? ` <span class="chip">principal (Secrets)</span>` : ""}${me ? ` <span class="chip">você</span>` : ""}
        <div class="sub">${cls === "pend" ? "pediu acesso em " + when(r.criado) : "criada em " + when(r.criado) + " · último acesso " + ago(r.ultimo_acesso)}</div></div></div>
      ${r.nota ? `<div class="mut" style="font-size:.8rem">💬 ${esc(r.nota)}</div>` : cls === "pend" ? `<div class="mut" style="font-size:.8rem">💬 não informou quem é</div>` : ""}
      ${acts ? `<div class="acts">${acts}</div>` : `<div class="mut" style="font-size:.76rem">${me ? "Esta é a sua conta." : "Conta principal: só muda pelos Secrets."}</div>`}${panel}</div>`;
  }
  function draw() {
    const q = S.q.trim().toLowerCase(), list = (S.tab === "all" ? data.rows : by[S.tab]).filter((r) => !q || (r.usuario + " " + (r.nota || "")).toLowerCase().includes(q));
    const cls = (r) => r.estado === data.PENDING ? "pend" : r.estado === data.BLOCKED ? "blk" : "act";
    root.innerHTML = `<div class="tiles">
        <div class="tile" style="border-left:4px solid #ffb74d"><span class="lbl">Pedidos pendentes</span><b>${by.pend.length}</b><small>${by.pend.length ? "aguardando você" : "nada a autorizar"}</small></div>
        <div class="tile" style="border-left:4px solid #26a69a"><span class="lbl">Contas ativas</span><b>${by.act.length}</b><small>${by.act.filter((r) => r.papel === "admin").length} admin(s)</small></div>
        <div class="tile" style="border-left:4px solid #ef5350"><span class="lbl">Bloqueadas</span><b>${by.blk.length}</b></div>
        <div class="tile"><span class="lbl">Acessaram nas últimas 24 h</span><b>${data.rows.filter((r) => r.ultimo_acesso && Date.now() - new Date(r.ultimo_acesso) < 864e5).length}</b></div></div>
      <div class="bar"><div class="seg">${[["pend", "⏳ Pendentes", by.pend.length], ["act", "✅ Ativas", by.act.length], ["blk", "⛔ Bloqueadas", by.blk.length], ["all", "📋 Todas", data.rows.length]]
        .map(([k, l, n]) => `<button data-tab="${k}" class="${S.tab === k ? "on" : ""}">${l} (${n})</button>`).join("")}</div><input class="search" placeholder="Buscar usuário ou nome informado…" value="${esc(S.q)}"></div>
      ${list.length ? `<div class="users">${list.map((r) => card(r, cls(r))).join("")}</div>` : `<p class="empty">${S.tab === "pend" ? "Nenhum pedido pendente." : "Nenhuma conta aqui."}</p>`}`;
    const s = root.querySelector(".search"); if (root._fs) { s.focus(); s.setSelectionRange(s.value.length, s.value.length); }
  }
  draw();
  root.onclick = (e) => {
    const b = e.target.closest("button"); if (!b) return;
    const u = b.dataset.u;
    if (b.dataset.tab) S.tab = b.dataset.tab;
    else if (b.dataset.p) S.panel[u] = S.panel[u] === b.dataset.p ? null : b.dataset.p;
    else if (b.dataset.k === "password") { const pw = root.querySelector(`input[data-pw="${CSS.escape(u)}"]`).value; send("password", u, { password: pw }); S.panel[u] = null; }
    else if (b.dataset.k === "delete") { const w = root.querySelector(`input[data-wipe="${CSS.escape(u)}"]`); send("delete", u, { wipe: w ? w.checked : true }); S.panel[u] = null; }
    else if (b.dataset.k === "reject") { if (confirm(`Recusar e apagar o pedido de ${u}?`)) send("reject", u); return; }
    else if (b.dataset.k === "block") { if (confirm(`Bloquear ${u}? A pessoa sai em até 1 minuto.`)) send("block", u); return; }
    else if (b.dataset.k) { send(b.dataset.k, u); return; }
    root._fs = false; draw();
  };
  root.oninput = (e) => { if (e.target.classList.contains("search")) { S.q = e.target.value; root._fs = true; draw(); } };
}
