// Tela de login do Cripto Robô (componente do Streamlit): mascote, entrar e pedir conta. Usuário e senha vão ao Python só ao enviar,
// e é o Python que confere tudo (tentativas, bloqueio e aprovação do administrador).
export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const root = parentElement.querySelector(".lg") || parentElement.appendChild(Object.assign(document.createElement("div"), { className: "lg" }));
  const S = root.state || (root.state = { tab: data.tab || "in" });
  if (data.tab && data.tabNonce !== root._nonce) { root._nonce = data.tabNonce; S.tab = data.tab; }
  const accounts = data.mode === "contas";
  const msg = (m) => m ? `<div class="msg ${esc(m.kind)}">${esc(m.text)}</div>` : "";
  const hi = ["Bora operar? 🚀", "Mercado aberto 24/7!", "Stop antes do alvo 😉", "HODL com gestão de risco!"][Math.floor(Date.now() / 6e4) % 4];
  const signin = `<form data-f="in">${accounts ? `<label class="f">Usuário<input name="user" autocomplete="username" value="${esc(data.last_user || "")}" required></label>` : ""}
      <label class="f">Senha<input name="pw" type="password" autocomplete="current-password" required></label>
      <label class="chk"><input type="checkbox" name="remember" checked> Manter conectado neste navegador${accounts ? " (14 dias)" : ""}</label>
      <button class="go" type="submit">Entrar</button></form>`;
  const signup = !data.signup_open ? `<div class="msg warn">O cadastro de novas contas está fechado.</div>` : `<form data-f="up">
      <label class="f">Escolha um usuário<input name="user" autocomplete="username" placeholder="3 a 20 letras minúsculas, números, . - _" required></label>
      <label class="f">Senha (mínimo 8 caracteres)<input name="pw" type="password" autocomplete="new-password" required></label>
      <label class="f">Repita a senha<input name="pw2" type="password" autocomplete="new-password" required></label>
      <label class="f">Seu nome (para o administrador reconhecer você)<input name="note" maxlength="80"></label>
      ${data.needs_code ? `<label class="f">Código de convite<input name="code" type="password"></label>` : ""}
      <button class="go" type="submit">Pedir conta</button></form>`;
  function render() {
    root.innerHTML = `<div class="box">
      <div class="hero"><span class="bubble">${esc(hi)}</span>${data.mascot}<h1>${esc(data.name)}</h1>
        <p>Bots que leem o gráfico, escolhem a melhor estratégia para o momento e operam por você — com a IA explicando cada passo.</p>
        <div class="feats"><span>⚡ Futuros e spot</span><span>🧠 IA que decide e explica</span><span>🏆 Ranking diário de bots</span><span>🔮 Sentimento do mercado</span></div></div>
      <div class="form"><div><h2>${S.tab === "up" ? "Criar conta" : "Bem-vindo de volta"}</h2><p class="sub">${accounts ? (S.tab === "up" ? "O administrador precisa autorizar o seu acesso." : "Entre com o seu usuário e senha.") : "Acesso restrito: digite a senha."}</p></div>
        ${accounts ? `<div class="tabs"><button data-tab="in" class="${S.tab !== "up" ? "on" : ""}">Entrar</button><button data-tab="up" class="${S.tab === "up" ? "on" : ""}">Pedir conta</button></div>` : ""}
        ${msg(data.message)}
        ${S.tab === "up" && accounts ? signup : signin}
        <p class="foot">🔒 Conexão protegida · suas chaves de API ficam criptografadas</p></div></div>`;
    const first = root.querySelector("form input"); if (first && !root._focused) { first.focus(); root._focused = true; }
  }
  render();
  root.onclick = (e) => { const b = e.target.closest("button[data-tab]"); if (b) { S.tab = b.dataset.tab; root._focused = false; render(); } };
  root.onsubmit = (e) => {
    e.preventDefault();
    const f = e.target, v = Object.fromEntries(new FormData(f).entries());
    f.querySelector(".go").disabled = true;
    const uid = Date.now() + "-" + Math.random();
    if (f.dataset.f === "up") setTriggerValue("signup", { user: v.user || "", pw: v.pw || "", pw2: v.pw2 || "", note: v.note || "", code: v.code || "", uid });
    else setTriggerValue("login", { user: v.user || "", pw: v.pw || "", remember: !!v.remember, uid });
  };
}
