// Cards das posições abertas (componente do Streamlit, JavaScript puro). Os números vêm prontos do Python (core/positions_view.py);
// as ações (atualizar stop/alvo, encerrar) voltam ao Python como valores de gatilho, que valida tudo antes de agir.
export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  const root = parentElement.querySelector(".cards") || parentElement.appendChild(Object.assign(document.createElement("div"), { className: "cards" }));
  const nf = (v, d = 2) => (v == null || Number.isNaN(v)) ? "—" : Number(v).toLocaleString("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d });
  const px = (v) => v == null ? "—" : nf(v, Math.abs(v) >= 100 ? 2 : Math.abs(v) >= 1 ? 4 : 6);
  const sg = (v, d = 2) => (v >= 0 ? "+" : "−") + nf(Math.abs(v), d);
  const cls = (v) => (v > 0 ? "up" : v < 0 ? "dn" : "");
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // faixa visual: stop ── entrada ── alvo, com a posição do preço agora
  function ladder(c) {
    const lo = c.stop ? c.stop.price : null, hi = c.target ? c.target.price : null;
    const vals = [c.entry, c.price_now, lo, hi].filter((x) => x != null);
    let min = Math.min(...vals), max = Math.max(...vals);
    if (max === min) { min -= 1; max += 1; }
    const pad = (max - min) * 0.06; min -= pad; max += pad;
    const at = (v) => Math.max(0, Math.min(100, ((v - min) / (max - min)) * 100));
    const a = at(c.entry), b = at(c.price_now);
    const fillL = Math.min(a, b), fillW = Math.abs(b - a);
    const good = (c.net >= 0);
    return `<div class="ladder">
      <div class="track">
        ${lo != null ? `<span class="zone zlo" style="left:0;width:${at(lo)}%"></span>` : ""}
        ${hi != null ? `<span class="zone zhi" style="left:${at(hi)}%;right:0"></span>` : ""}
        <span class="fill ${good ? "up" : "dn"}" style="left:${fillL}%;width:${fillW}%"></span>
        ${lo != null ? `<span class="tick sl" style="left:${at(lo)}%"><i>🛑</i></span>` : ""}
        <span class="tick en" style="left:${a}%"><i>entrada</i></span>
        ${hi != null ? `<span class="tick tp" style="left:${at(hi)}%"><i>🎯</i></span>` : ""}
        <span class="now ${good ? "up" : "dn"}" style="left:${b}%"><i>${px(c.price_now)}</i></span>
      </div>
      <div class="lad-l">
        <span class="dn">${c.stop ? `Stop ${px(c.stop.price)} · ${sg(c.stop.net)} USDT` : "sem stop"}</span>
        <span class="mut">Entrada ${px(c.entry)}</span>
        <span class="up">${c.target ? `Alvo ${px(c.target.price)} · ${sg(c.target.net)} USDT` : "sem alvo"}</span>
      </div></div>`;
  }

  const stat = (label, value, sub = "", tone = "", tip = "") =>
    `<div class="stat" ${tip ? `title="${esc(tip)}"` : ""}><span class="k">${label}</span><b class="${tone}">${value}</b>${sub ? `<small class="${tone}">${sub}</small>` : ""}</div>`;

  function card(c) {
    const coin = esc(c.base_asset), long = c.side === "BUY";
    const tgt = c.target, stp = c.stop;
    const stats = [];
    if (c.spot) {
      stats.push(stat("Valor investido", nf(c.cost) + " USDT", "", "", "Quanto foi pago na compra, sem contar as taxas."));
      stats.push(stat("Moedas compradas", nf(c.qty, c.qty >= 100 ? 2 : 6).replace(/,?0+$/, "") + " " + coin));
    } else {
      stats.push(stat("Valor da posição", nf(c.cost) + " USDT", "", "", "Quantidade × preço de entrada."));
      stats.push(stat("Quantidade", nf(c.qty, 6).replace(/,?0+$/, "") + " " + coin));
    }
    stats.push(stat("Preço de entrada", px(c.entry)));
    stats.push(stat("Preço agora", px(c.price_now), sg(c.move_pct) + "% desde a entrada", cls(c.move_pct)));
    stats.push(stat(c.spot ? "Venda esperada (alvo)" : "Alvo (saída com lucro)", tgt ? px(tgt.price) : "sem alvo",
      tgt ? sg(tgt.per_coin) + " USDT por " + coin + " (" + sg(tgt.pct_price) + "%)" : "", tgt ? "up" : "mut"));
    stats.push(stat("Se bater o alvo", tgt ? sg(tgt.net) + " USDT" : "—", tgt ? sg(tgt.pct) + "%" : "", tgt ? "up" : "mut", "Lucro líquido total, já com as taxas."));
    stats.push(stat("Stop (limite de perda)", stp ? px(stp.price) : "sem stop",
      stp ? sg(stp.per_coin) + " USDT por " + coin + " (" + sg(stp.pct_price) + "%)" : "", stp ? "dn" : "mut"));
    stats.push(stat("Se bater o stop", stp ? sg(stp.net) + " USDT" : "—", stp ? sg(stp.pct) + "%" : "", stp ? "dn" : "mut", "Resultado líquido total, já com as taxas."));
    stats.push(stat("Risco : retorno", c.rr ? "1 : " + nf(c.rr) : "—"));
    stats.push(stat("Taxas (entrada + saída est.)", nf(c.fees_open + c.fees_close) + " USDT", "paga " + nf(c.fees_open) + " · saída " + nf(c.fees_close)));
    if (c.spot) stats.push(stat("Valor agora", nf(c.value_now) + " USDT", "", "", "Moedas × preço atual: o que a venda renderia, antes da taxa."));
    else {
      stats.push(stat("Margem", nf(c.margin) + " USDT", "", "", "Saldo travado nesta posição."));
      stats.push(stat("Alavancagem", nf(c.leverage, 0) + "× " + esc(c.margin_mode || "")));
      stats.push(stat("Preço de liquidação", c.liquidation ? px(c.liquidation) : "—", "", "warn", "Se o preço chegar aqui, a margem é perdida."));
      stats.push(stat("Funding pago", nf(c.funding) + " USDT"));
    }
    return `<article class="card ${long ? "long" : "short"}" data-id="${esc(c.id)}">
      <header>
        <div class="title"><span class="badge ${long ? "up" : "dn"}">${long ? "COMPRA" : "VENDA"}</span><h3>${esc(c.symbol)}</h3>
          <span class="chip">${c.spot ? "Spot" : "Futuros " + nf(c.leverage, 0) + "×"}</span></div>
        <div class="who"><span class="chip bot">${esc(c.who)}</span><span class="mut">aberta ${esc(c.opened_ago)} · ${esc(c.opened_at)}</span></div>
      </header>
      <section class="hero">
        <div><span class="k">Resultado agora (líquido)</span>
          <div class="big ${cls(c.net)}">${sg(c.net)} <small>USDT</small></div></div>
        <span class="pill ${cls(c.net)}">${sg(c.net_pct)}% ${c.spot ? "do valor investido" : "da margem"}</span>
        <div class="why">${c.note ? "💬 " + esc(c.note) : ""}</div>
      </section>
      ${ladder(c)}
      <section class="stats">${stats.join("")}</section>
      <footer>
        <label>Stop <input class="in-sl" type="number" step="any" value="${c.stop ? c.stop.price : ""}" placeholder="sem stop"></label>
        <label>Alvo <input class="in-tp" type="number" step="any" value="${c.target ? c.target.price : ""}" placeholder="sem alvo"></label>
        <button class="btn upd">Atualizar stop/alvo</button>
        <button class="btn close">${c.spot ? "Vender tudo agora" : "Zerar posição"}</button>
      </footer></article>`;
  }

  const cards = (data && data.cards) || [];
  root.innerHTML = cards.length ? cards.map(card).join("") : `<p class="empty">Nenhuma posição aberta.</p>`;
  const onClick = (e) => {
    const btn = e.target.closest("button"); if (!btn) return;
    const el = btn.closest(".card"), id = el.dataset.id, c = cards.find((x) => x.id === id);
    if (btn.classList.contains("upd")) {
      const sl = parseFloat(el.querySelector(".in-sl").value), tp = parseFloat(el.querySelector(".in-tp").value);
      setTriggerValue("action", { kind: "protect", id, stop_loss: Number.isFinite(sl) ? sl : null, take_profit: Number.isFinite(tp) ? tp : null, uid: Date.now() + "-" + Math.random() });
    } else if (btn.classList.contains("close") && confirm((c.spot ? "Vender tudo" : "Zerar a posição") + " em " + c.symbol + " a mercado?\nResultado aproximado: " + sg(c.net) + " USDT")) {
      setTriggerValue("action", { kind: "close", id, uid: Date.now() + "-" + Math.random() });
    }
  };
  root.onclick = onClick;   // um só ouvinte por contêiner: a função roda de novo a cada atualização dos dados e não pode empilhar confirmações
}
