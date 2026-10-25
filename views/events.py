"""Eventos: painel do Polymarket (macro, política, commodities/índices e cripto) que se atualiza sozinho e abastece a IA."""
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

from core import events

_JS = (Path(__file__).resolve().parent.parent / "core" / "events.js").read_text(encoding="utf-8")
_CSS = (Path(__file__).resolve().parent.parent / "core" / "events.css").read_text(encoding="utf-8")


@st.cache_resource(show_spinner=False)
def _component():
    return st.components.v2.component("tb_events", css=_CSS, js=_JS)


st.title("📅 Eventos")
st.caption("O que o mercado de previsões (Polymarket) espera para Fed, eleições, commodities, índices e cripto. A lista se atualiza sozinha: "
           "eventos que vencem saem e os novos entram. Os marcados com 🤖 vão como contexto para a IA nas análises e nas decisões de saída.")


@st.fragment(run_every=300)
def _panel():
    evs = events.get()
    if not evs:
        st.info("Não consegui carregar os eventos agora (Polymarket sem resposta). Tento de novo em instantes.")
        return
    ai_ids = events.ids_for_ai(evs)
    data = {"events": [{**e, "ia": e["id"] in ai_ids} for e in evs], "categories": {k: v[0] for k, v in events.CATEGORIES.items()},
            "updated": datetime.now(timezone.utc).strftime("%H:%M UTC")}
    _component()(key="tb-events", data=data)


_panel()
