// Boleta (componente do Streamlit, JavaScript puro). O formulário é montado uma vez e mantido entre as atualizações (para não perder
// o foco ao digitar); o resumo vem do Python (core/ticket_view.py), que faz todas as contas. Ações voltam como valores de gatilho.
export default function (component) {
  const { data, parentElement, setStateValue, setTriggerValue } = component;
  const nf = (v, d = 2) => (v == null || Number.isNaN(v)) ? "—" : Number(v).toLocaleString("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d });
  const px = (v) => v == null ? "—" : nf(v, Math.abs(v) >= 100 ? 2 : Math.abs(v) >= 1 ? 4 : 6);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  let root = parentElement.querySelector(".tk");
  const d = data, f = d.form;
  if (!root || root.dataset.sig !== d.symbol + "|" + d.can_short) {
    root = root || parentElement.appendChild(Object.assign(document.createElement("div"), { className: "tk" }));
    root.dataset.sig = d.symbol + "|" + d.can_short;
    root.innerHTML = `
      <div class="seg sides"><button data-side="BUY" class="buy">Comprar</button>${d.can_short ? `<button data-side="SELL" class="sell">Vender</button>` : ""}</div>
      <div class="seg types"><button data-type="MARKET">Mercado</button><button data-type="LIMIT">Limitada</button></div>
      <label class="fld lim"><span>Preço limite</span><input data-f="limit" type="number" step="any"><em>USDT</em></label>
      <label class="chk"><input type="checkbox" data-f="auto"><span>Stop e alvo automáticos (ATR)</span></label>
      <div class="two"><label class="fld sl"><span>Stop loss</span><input data-f="sl" type="number" step="any"></label>
        <label class="fld tp"><span>Take profit</span><input data-f="tp" type="number" step="any"></label></div>
      <div class="seg sizing"><button data-sizing="RISK">Perda máxima</button><button data-sizing="VALUE">${d.spot ? "Valor a investir" : "Margem"}</button></div>
      <label class="fld amt"><span class="amt-l"></span><input data-f="amount" type="number" step="any"><em>USDT</em></label>
      <div class="sum"></div><div class="warns"></div>
      <button class="send"></button><p class="blocked"></p>`;
    root.querySelector('[data-f="limit"]').value = f.limit;
    root.querySelector('[data-f="sl"]').value = f.sl;
    root.querySelector('[data-f="tp"]').value = f.tp;
    root.querySelector('[data-f="auto"]').checked = f.auto;
    root.querySelector('[data-f="amount"]').value = f.sizing === "RISK" ? f.risk : f.value;
    root.state = { ...f };
  }
  const st = root.state;
  const q = (s) => root.querySelector(s);
  const form = () => ({ side: st.side, type: st.type, auto: st.auto, sizing: st.sizing, limit: +q('[data-f="limit"]').value || null,
    sl: +q('[data-f="sl"]').value || null, tp: +q('[data-f="tp"]').value || null,
    risk: st.sizing === "RISK" ? +q('[data-f="amount"]').value || null : st.risk, value: st.sizing === "VALUE" ? +q('[data-f="amount"]').value || null : st.value });
  let timer;
  const push = () => { clearTimeout(timer); timer = setTimeout(() => setStateValue("form", form()), 350); };

  // estado visual (não mexe nos campos em que o usuário está digitando)
  const active = parentElement.activeElement || (parentElement.getRootNode && parentElement.getRootNode().activeElement);
  const setVal = (sel, v) => { const el = q(sel); if (el !== active) el.value = v; };
  root.querySelectorAll("[data-side]").forEach((b) => b.classList.toggle("on", b.dataset.side === st.side));
  root.querySelectorAll("[data-type]").forEach((b) => b.classList.toggle("on", b.dataset.type === st.type));
  root.querySelectorAll("[data-sizing]").forEach((b) => b.classList.toggle("on", b.dataset.sizing === st.sizing));
  q(".lim").style.display = st.type === "LIMIT" ? "" : "none";
  q('[data-f="sl"]').disabled = q('[data-f="tp"]').disabled = st.auto;
  if (st.auto) { setVal('[data-f="sl"]', f.sl); setVal('[data-f="tp"]', f.tp); }
  q(".amt-l").textContent = st.sizing === "RISK" ? "Perda máxima no stop" : (d.spot ? "Valor a investir" : "Margem a alocar");

  const c = d.calc, long = f.side === "BUY";
  const row = (k, v, tone = "") => `<div><span>${k}</span><b class="${tone}">${v}</b></div>`;
  q(".sum").innerHTML =
    `<div class="hero"><div><span>Quantidade</span><b>${nf(c.qty, c.qty >= 100 ? 2 : 6).replace(/,?0+$/, "")} ${esc(d.base)}</b></div>
       <div><span>${d.spot ? "Valor da compra" : "Valor da posição"}</span><b>${nf(c.notional)} USDT</b></div></div>
     <div class="pl"><div class="dn"><span>Se bater o stop</span><b>−${nf(c.risk)} USDT</b><small>${nf(c.stop_pct)}%</small></div>
       <div class="up"><span>Se bater o alvo</span><b>+${nf(c.reward)} USDT</b><small>${nf(c.tp_pct)}%</small></div></div>
     <div class="rows">${row("Risco : retorno", c.rr ? "1 : " + nf(c.rr) : "—")}${row("Taxas (ida e volta)", nf(c.fees) + " USDT")}
       ${row("Ponto de equilíbrio", px(c.breakeven))}${d.spot ? "" : row("Margem", nf(c.margin) + " USDT · " + nf(d.leverage, 0) + "× " + esc(d.margin_mode))}
       ${c.liquidation ? row("Liquidação", px(c.liquidation), "warn") : ""}${row("Saldo livre", nf(d.available) + " USDT")}</div>`;
  q(".warns").innerHTML = (c.warnings || []).map((w) => `<p>⚠️ ${esc(w)}</p>`).join("");
  const send = q(".send");
  send.className = "send " + (st.side === "BUY" ? "buy" : "sell");
  send.textContent = (st.side === "BUY" ? "Comprar " : "Vender ") + d.base + (st.type === "LIMIT" ? " (limitada)" : " a mercado");
  send.disabled = c.qty <= 0 || !!d.blocked;
  q(".blocked").textContent = d.blocked || "";

  root.onclick = (e) => {
    const b = e.target.closest("button"); if (!b) return;
    if (b.dataset.side) { st.side = b.dataset.side; push(); }
    else if (b.dataset.type) { st.type = b.dataset.type; push(); }
    else if (b.dataset.sizing) { st.risk = form().risk; st.value = form().value; st.sizing = b.dataset.sizing; q('[data-f="amount"]').value = st.sizing === "RISK" ? st.risk : st.value; push(); }
    else if (b.classList.contains("send") && !b.disabled) setTriggerValue("send", { ...form(), uid: Date.now() + "-" + Math.random() });
    root.querySelectorAll("[data-side]").forEach((x) => x.classList.toggle("on", x.dataset.side === st.side));
    root.querySelectorAll("[data-type]").forEach((x) => x.classList.toggle("on", x.dataset.type === st.type));
    root.querySelectorAll("[data-sizing]").forEach((x) => x.classList.toggle("on", x.dataset.sizing === st.sizing));
    q(".lim").style.display = st.type === "LIMIT" ? "" : "none";
  };
  root.oninput = (e) => { if (e.target.dataset.f === "auto") { st.auto = e.target.checked; q('[data-f="sl"]').disabled = q('[data-f="tp"]').disabled = st.auto; } push(); };
}
