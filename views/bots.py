"""Galeria de bots especialistas: um card por bot com especialidade, dica rápida,
desempenho simulado (com % estimada ao mês) e desempenho real."""
import pandas as pd
import streamlit as st

from core import personalities as P
from core.profiles import PROFILES
from core.settings import load_settings, save_settings
from core.strategy import SKILLS

st.title("🤖 Bots especialistas")
st.caption("Cada bot é especialista em um estilo, timeframe, indicador e relação risco:retorno. O desempenho simulado "
           "vem de testes com candles reais (1% da banca arriscado por operação, com taxas); o real vem das operações "
           "feitas pelos bots na carteira simulada. Resultado passado não garante resultado futuro.")

SKILL_NAMES = {k: v[0] for k, v in SKILLS.items()}
STYLE = {"day": "⚡ Day trade", "swing": "🌊 Swing", "long": "🏔️ Longo prazo"}


def rr_label(p: dict) -> str:
    sl, tp = float(p.get("sl_atr") or 1), float(p.get("tp_atr") or 1)
    r = tp / sl
    if r >= 1:
        return f"{r:.1f}:1".replace(".0:", ":").replace(".", ",")
    return f"1:{1 / r:.1f}".replace(".0", "").replace(".", ",")


def activate(p: dict, bot: str) -> None:
    cfg = load_settings(bot)
    cfg["personality"] = p["id"]
    st.session_state[f"{bot}__personality"] = p["id"]
    msg = f"{p['name']} ativado no {PROFILES[bot].name}."
    tested = p.get("tested_interval")
    if tested and tested in PROFILES[bot].intervals:
        cfg["interval"] = tested
        st.session_state[f"{bot}__interval"] = tested
        msg += f" Timeframe: {tested}."
    save_settings(bot, cfg)
    st.toast(msg, icon="✅")


live = {r["id"]: r for r in P.ranking()}
bots = [p for p in P.list_all() if p.get("research", {}).get("monthly_pct") is not None or not p.get("builtin")]

# ------------------------------------------------------------------ filtros
c1, c2, c3, c4 = st.columns([1.2, 1.6, 1.2, 1.2])
style_f = c1.multiselect("Estilo", list(STYLE), format_func=STYLE.get, placeholder="Todos")
skills_f = c2.multiselect("Indicador", sorted({k for p in bots for k in p.get("skills", {})}),
                          format_func=lambda k: SKILL_NAMES.get(k, k), placeholder="Todos")
rr_f = c3.multiselect("Risco:retorno", sorted({rr_label(p) for p in bots}), placeholder="Todos")
order = c4.selectbox("Ordenar por", ["% ao mês", "Acerto", "Menor queda", "Operações reais"])
only_ok = st.toggle("Mostrar só os aprovados na prova final (moedas que o teste não viu)", value=False)

view = []
for p in bots:
    rs = p.get("research", {})
    if style_f and p.get("bot") not in style_f:
        continue
    if skills_f and not set(skills_f) & set(p.get("skills", {})):
        continue
    if rr_f and rr_label(p) not in rr_f:
        continue
    if only_ok and rs.get("status") != "aprovado":
        continue
    view.append(p)
key = {"% ao mês": lambda p: -(p.get("research", {}).get("monthly_pct") or -999),
       "Acerto": lambda p: -(p.get("research", {}).get("win_pct") or 0),
       "Menor queda": lambda p: p.get("research", {}).get("dd_pct") or 999,
       "Operações reais": lambda p: -(live.get(p["id"], {}).get("live_trades") or 0)}[order]
view.sort(key=key)

ok = sum(1 for p in bots if p.get("research", {}).get("status") == "aprovado")
st.caption(f"{len(view)} de {len(bots)} bots · {ok} aprovados na prova final")

# --------------------------------------------------------------------- cards
in_use = {b: load_settings(b).get("personality") for b in PROFILES}
cols = st.columns(3)
for n, p in enumerate(view):
    rs = p.get("research", {})
    lv = live.get(p["id"], {})
    bot = p.get("bot") or ("day" if "futures" in p.get("markets", []) else "swing")
    with cols[n % 3].container(border=True):
        st.markdown(f"#### {p['name']}")
        market = "Futuros" if "futures" in p.get("markets", ["futures"])[:1] else "Spot"
        badges = [STYLE.get(bot, bot), p.get("tested_interval") or p.get("timeframes", ""), market,
                  f"R:R {rr_label(p)}"]
        st.markdown(" ".join(f"`{b}`" for b in badges if b))
        st.caption(f"**{p.get('specialty', '')}**")
        st.markdown(f"💡 {p.get('tip') or p.get('summary', '')}")
        if rs:
            m1, m2 = st.columns(2)
            m1.metric("Ao mês (simulado)", f"{rs['monthly_pct']:+.1f}%",
                      f"{rs['ret_pct']:+.1f}% em {rs['period_label']}",
                      help="Estimativa mensal composta a partir do período simulado: "
                           "(1 + retorno do período)^(30 ÷ dias) − 1, média de 10 moedas, 1% de risco por operação.")
            m2.metric("Acerto", f"{rs['win_pct']:.0f}%", f"pior queda −{rs['dd_pct']:.0f}%", delta_color="off")
            status = {"aprovado": "✅ Aprovado na prova final", "ressalva": "🟡 Aprovado com ressalva",
                      "fraco": "⚠️ Fraco no período"}.get(rs.get("status"), "")
            st.caption(f"{status} · ~{rs['trades_month']:.0f} operações/mês · {rs['pos_coins']} moedas positivas")
        if lv.get("live_trades"):
            st.caption(f"📊 Real: {lv['live_trades']} operações · acerto {lv['live_win_rate']:.0f}% · "
                       f"{(lv['live_avg_r'] or 0):+.2f}R por operação · {lv['live_pnl']:+.2f} USDT")
        else:
            st.caption("📊 Real: ainda sem operações — ative para começar a medir.")
        using = [PROFILES[b].name for b, pid in in_use.items() if pid == p["id"]]
        b1, b2 = st.columns([1.2, 1])
        label = "✅ Em uso" if bot in in_use and in_use[bot] == p["id"] else f"Ativar no {PROFILES[bot].name}"
        if b1.button(label, key=f"act_{p['id']}", type="primary", width="stretch", disabled=label.startswith("✅")):
            activate(p, bot)
            st.rerun()
        with b2.popover("Detalhes", width="stretch"):
            st.markdown(p.get("description", ""))
            st.markdown("**Indicadores (peso):** " + ", ".join(
                f"{SKILL_NAMES.get(k, k)} ({w:g})" for k, w in sorted(p.get("skills", {}).items(), key=lambda x: -x[1])))
            f = p.get("filters", {})
            filt = [P.FILTERS[k] for k, v in f.items() if v and k in P.FILTERS]
            if f.get("adx_min"):
                filt.append(f"ADX ≥ {f['adx_min']}")
            if f.get("adx_max"):
                filt.append(f"ADX ≤ {f['adx_max']}")
            st.markdown(f"**Direção:** {P.DIRECTIONS[p.get('direction', 'misto')]} · **Stop/alvo:** "
                        f"{p.get('sl_atr')}× / {p.get('tp_atr')}× ATR · **Filtros:** {', '.join(filt) or 'nenhum'}")
            if rs.get("per_symbol"):
                st.markdown(f"**Simulação ({rs['period_label']}, até {rs['tested_at']}):**")
                st.dataframe(pd.DataFrame([{"Moeda": k.replace("USDT", ""), "Retorno": v}
                                           for k, v in rs["per_symbol"].items()]),
                             hide_index=True, column_config={"Retorno": st.column_config.NumberColumn(format="%+.1f%%")})
                st.caption(f"Moedas da busca: {rs['ret_seen']:+.1f}% · moedas inéditas (prova final): "
                           f"{rs['ret_new']:+.1f}%.")
            if using:
                st.caption("Em uso no: " + ", ".join(using))

if not view:
    st.info("Nenhum bot com esses filtros.")
