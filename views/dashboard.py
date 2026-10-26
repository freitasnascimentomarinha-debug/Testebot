"""Painel geral: resumo dos bots de cripto (futuros e spot)."""
from pathlib import Path

import streamlit as st

from core import events, events_pt, paper, positions_view, wallet_view
from core.profiles import PROFILES
from core.settings import load_settings
import json
from datetime import datetime

from core.storage import backend, export_all, import_all, load_json
from core.ui import cached_ticker

st.title("📊 Cripto Robô")
mode = paper.wallet_config()["mode"]
st.caption("Bots operando com cotações reais — "
           + ("todos na mesma **carteira única**, junto com as suas ordens manuais." if mode == "única"
              else "cada um com a sua **banca separada**."))

_DIR = Path(__file__).resolve().parent.parent / "core"


@st.cache_resource(show_spinner=False)
def _component():
    return st.components.v2.component("tb_dashboard", css=(_DIR / "wallet_ui.css").read_text(encoding="utf-8"),
                                      js=(_DIR / "dashboard.js").read_text(encoding="utf-8"))


PAGES = {"day": "futuros", "swing": "spot", "carteira": "carteira", "eventos": "eventos"}   # endereço (url_path) de cada página


@st.fragment(run_every=60)
def _dashboard():
    cards, positions, seen, accts = [], [], set(), {}
    for key in ("day", "swing"):
        profile = PROFILES[key]
        cfg = load_settings(key)
        acc_id = paper.account_id(key)
        acct = accts.setdefault(acc_id, paper.get_account(acc_id))
        prices = {}
        for sym in {p["symbol"] for p in acct["positions"]} | {cfg["symbol"]}:
            try:
                prices[sym] = cached_ticker(sym, profile.market).last
            except Exception:  # noqa: BLE001
                pass
        cards.append({"key": key, "cfg": cfg, "stats": paper.stats(acct, prices, bot=key)})
        for p in acct["positions"]:
            if p["id"] not in seen:
                seen.add(p["id"])
                c = positions_view.card_data(p, prices.get(p["symbol"], p["entry"]))
                positions.append({k: c.get(k) for k in ("symbol", "side", "entry", "price_now", "net", "net_pct", "who")})
    if mode == "única":
        acct = next(iter(accts.values()))
        equity = paper.stats(acct, {p["symbol"]: p["price_now"] for p in positions})
        curve = acct["equity_curve"]
    else:   # bancas separadas: soma os números (a curva fica na Carteira, banca por banca)
        each = [paper.stats(a, {p["symbol"]: p["price_now"] for p in positions}) for a in accts.values()]
        equity = {k: sum(x[k] for x in each) for k in ("equity", "invested", "total_pnl", "pnl_today", "trades_today", "open_positions", "unrealized_net", "trades")}
        equity["total_pnl_pct"] = equity["total_pnl"] / equity["invested"] * 100 if equity["invested"] else 0.0
        equity["win_rate"] = sum(x["win_rate"] * x["trades"] for x in each) / equity["trades"] if equity["trades"] else 0.0
        curve = []
    evs = events.ai_context(events_pt.localize(events.peek()))
    data = wallet_view.dashboard_data(cards, curve, equity, load_json("decisions.json", {}) or {}, positions, evs, mode)
    res = _component()(key="tb-dashboard", data=data, on_go_change=lambda: None)
    ev = getattr(res, "go", None)
    if ev and ev.get("uid") != st.session_state.get("_dash_uid"):
        st.session_state["_dash_uid"] = ev.get("uid")
        if ev.get("page") in PAGES:   # o menu lateral (core/nav.py) faz a troca no começo da próxima execução
            st.session_state["_nav_to"] = PAGES[ev["page"]]
            st.rerun(scope="app")


_dashboard()

with st.expander("Como funciona o fluxo de decisão"):
    st.markdown("""
1. **Dados reais** — candles e cotação da Binance (futuros USDⓈ-M ou spot), com fallback para a OKX.
2. **Habilidades de programação** — 9 regras determinísticas (tendência, momentum, MACD, Bollinger, SuperTrend,
   VWAP, volume/OBV, estrutura de topos/fundos e suportes/resistências) votam de −1 a +1 com pesos por estilo.
3. **Bot do momento** — no fechamento de cada candle, no tempo gráfico em uso, entra o bot do **ranking** com melhor
   desempenho no contexto do gráfico. O ranking é refeito sozinho toda semana com o mercado recente.
4. **IA (via OpenRouter)** — resume o que está acontecendo no mercado e dá uma dica útil, no tom da personalidade
   escolhida. Opcionalmente, também confirma ou veta a ativação do bot naquele momento.
5. **Dimensionamento** — a posição é calculada pela sua *perda máxima por trade* (sem bloqueios por metas ou limites diários).
6. **Execução** — ordem enviada à conta de operação escolhida na barra lateral. Hoje: conta demo da plataforma (simulada);
   Stops e alvos são monitorados com as máximas e mínimas reais de cada candle.
""")

with st.expander("💾 Backup e restauração dos dados"):
    st.caption(f"Armazenamento atual: **{backend().name}**. O backup inclui contas simuladas, configurações e logs.")
    c1, c2 = st.columns(2)
    c1.download_button("⬇️ Baixar backup (JSON)", json.dumps(export_all(), ensure_ascii=False, default=str, indent=1),
                       file_name=f"tradebot_backup_{datetime.now():%Y%m%d_%H%M}.json", mime="application/json")
    up = c2.file_uploader("Restaurar backup", type="json")
    if up and c2.button("Restaurar (substitui os dados atuais)", type="primary"):
        n = import_all(json.load(up))
        st.success(f"{n} conjuntos de dados restaurados.")
        st.rerun()


from core import accounts  # noqa: E402
from core.storage import get_secret  # noqa: E402

if not accounts.enabled() and not get_secret("APP_PASSWORD"):
    st.caption("🔓 Acesso aberto: qualquer pessoa com o link entra. Para exigir usuário e senha com aprovação do administrador, "
               "veja docs/contas_e_supabase.md.")

from core import credentials  # noqa: E402
from core.auth import current_user  # noqa: E402

if accounts.enabled() and current_user() and credentials.configured() and not credentials.status(current_user()):
    st.info("🔗 Você ainda não conectou a sua corretora. Cadastre a chave de API em **Minha conta** (opcional por enquanto: as ordens "
            "são simuladas).")
