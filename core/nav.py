"""Menu lateral em JavaScript (core/sidebar.js): navegação em grupos e moedas com preço e variação de 24 h."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from core import data as market_data
from core.profiles import SYMBOLS

_JS = Path(__file__).with_name("sidebar.js").read_text(encoding="utf-8")
_CSS = Path(__file__).with_name("sidebar.css").read_text(encoding="utf-8")
MARKET_PAGE = {"futures": ("futuros", "day"), "spot": ("spot", "swing")}   # mercado → (página, bot da página)
WATCH = SYMBOLS[:10]


@st.cache_resource(show_spinner=False)
def _component():
    return st.components.v2.component("tb_sidebar", css=_CSS, js=_JS)


_TJS = Path(__file__).with_name("ticker.js").read_text(encoding="utf-8")
_TCSS = Path(__file__).with_name("ticker.css").read_text(encoding="utf-8")


@st.cache_resource(show_spinner=False)
def _ticker_component():
    return st.components.v2.component("tb_ticker", css=_TCSS, js=_TJS)


def ticker_strip(bot: str, market: str, current: str) -> None:
    """Faixa de cotações em movimento no topo das páginas de mercado. Clicar numa moeda troca o ativo da página."""
    quotes = market_data.watch_prices(market, SYMBOLS)
    res = _ticker_component()(key=f"{bot}-ticker", data={"symbols": list(SYMBOLS), "market": market, "current": current,
                                                          "quotes": {s: list(q) for s, q in quotes.items()}}, on_pick_change=lambda: None)
    ev = getattr(res, "pick", None)
    if ev and ev.get("uid") != st.session_state.get(f"{bot}__tick_uid"):
        st.session_state[f"{bot}__tick_uid"] = ev.get("uid")
        if ev.get("symbol") in SYMBOLS:
            from core.ui import set_setting

            set_setting(bot, "symbol", ev["symbol"])
            st.rerun()


def market_of(path: str | None, last: str = "futures") -> str:
    """Mercado da lista de moedas: o da página aberta (Futuros/Spot) ou, em outras páginas, o último que foi usado."""
    return next((m for m, (p, _) in MARKET_PAGE.items() if p == path), last)


def groups(pages: dict, current_path: str) -> list[dict]:
    return [{"title": title, "items": [{"title": p.title, "icon": p.icon or "", "path": p.url_path, "active": p.url_path == current_path} for p in items]}
            for title, items in pages.items()]


def render(pages: dict, current) -> None:
    """Desenha o menu na barra lateral. Cliques viram uma navegação (e, nas moedas, a troca do ativo da página de mercado)."""
    index = {p.url_path: p for items in pages.values() for p in items}
    if (go := st.session_state.pop("_nav_to", None)) is not None:
        page = index.get(go)
        if page is not None:
            st.switch_page(page)

    @st.fragment(run_every=15)
    def _menu():
        path = getattr(current, "url_path", "")
        market = market_of(path, st.session_state.get("_wl_market", "futures"))
        st.session_state["_wl_market"] = market
        quotes = market_data.watch_prices(market, WATCH)
        watch = [{"symbol": s, "price": quotes[s][0], "pct": quotes[s][1]} for s in WATCH if s in quotes]
        payload = {"groups": groups(pages, path), "watch": watch, "market": market, "symbols": list(WATCH),
                   "watch_title": "Moedas · " + ("Futuros" if market == "futures" else "Spot") + " · 24 h"}
        res = _component()(key="tb-sidebar", data=payload, on_go_change=lambda: None)
        ev = getattr(res, "go", None)
        if ev and ev.get("uid") != st.session_state.get("_nav_uid"):
            st.session_state["_nav_uid"] = ev.get("uid")
            if ev.get("symbol") in SYMBOLS:   # clique numa moeda: abre a página do mercado já nela
                from core.ui import set_setting

                page_path, bot = MARKET_PAGE[market]
                set_setting(bot, "symbol", ev["symbol"])
                st.session_state["_nav_to"] = page_path
                st.rerun(scope="app")
            elif ev.get("path") is not None and ev["path"] != path:
                st.session_state["_nav_to"] = ev["path"]
                st.rerun(scope="app")

    _menu()
