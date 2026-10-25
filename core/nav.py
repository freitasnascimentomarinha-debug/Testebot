"""Menu lateral em JavaScript (core/sidebar.js) e a faixa de cotações em movimento das páginas de mercado (core/ticker.js)."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from core import data as market_data, sentiment
from core.profiles import SYMBOLS

_JS = Path(__file__).with_name("sidebar.js").read_text(encoding="utf-8")
_CSS = Path(__file__).with_name("sidebar.css").read_text(encoding="utf-8")


@st.cache_resource(show_spinner=False)
def _component():
    return st.components.v2.component("tb_sidebar", css=_CSS, js=_JS)


_TJS = Path(__file__).with_name("ticker.js").read_text(encoding="utf-8")
_TCSS = Path(__file__).with_name("ticker.css").read_text(encoding="utf-8")


@st.cache_resource(show_spinner=False)
def _ticker_component():
    return st.components.v2.component("tb_ticker", css=_TCSS, js=_TJS)


def ticker_strip(bot: str, market: str, current: str) -> None:
    """Faixa de cotações em movimento no topo das páginas de mercado, com o sentimento do Polymarket de cada moeda.
    Atualiza sozinha; clicar numa moeda troca o ativo da página."""

    @st.fragment(run_every=20)
    def _strip():
        quotes = market_data.watch_prices(market, SYMBOLS)
        sentiment.warm({s: q[0] for s, q in quotes.items()})   # busca em segundo plano; entra na próxima atualização
        sent = {}
        for s in quotes:
            r = sentiment.peek(s)
            if r:
                sent[s] = {"vies": r["vies"], "leitura": r["leitura"]}
        res = _ticker_component()(key=f"{bot}-ticker", data={"symbols": list(SYMBOLS), "market": market, "current": current,
                                                              "quotes": {s: list(q) for s, q in quotes.items()}, "sentiment": sent},
                                  on_pick_change=lambda: None)
        ev = getattr(res, "pick", None)
        if ev and ev.get("uid") != st.session_state.get(f"{bot}__tick_uid"):
            st.session_state[f"{bot}__tick_uid"] = ev.get("uid")
            if ev.get("symbol") in SYMBOLS:
                from core.ui import set_setting

                set_setting(bot, "symbol", ev["symbol"])
                st.rerun(scope="app")

    _strip()


def groups(pages: dict, current_path: str) -> list[dict]:
    return [{"title": title, "items": [{"title": p.title, "icon": p.icon or "", "path": p.url_path, "active": p.url_path == current_path} for p in items]}
            for title, items in pages.items()]


def render(pages: dict, current) -> None:
    """Desenha o menu na barra lateral. Cliques viram uma navegação."""
    index = {p.url_path: p for items in pages.values() for p in items}
    if (go := st.session_state.pop("_nav_to", None)) is not None:
        page = index.get(go)
        if page is not None:
            st.switch_page(page)

    path = getattr(current, "url_path", "")
    res = _component()(key="tb-sidebar", data={"groups": groups(pages, path)}, on_go_change=lambda: None)
    ev = getattr(res, "go", None)
    if ev and ev.get("uid") != st.session_state.get("_nav_uid"):
        st.session_state["_nav_uid"] = ev.get("uid")
        if ev.get("path") is not None and ev["path"] != path:
            st.session_state["_nav_to"] = ev["path"]
            st.rerun()
