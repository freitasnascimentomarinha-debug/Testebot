"""Painel de eventos do Polymarket (macro, política, commodities/índices e cripto) e o resumo que vai para a IA.

Cada evento é um mercado de previsões com probabilidades dadas por apostadores com dinheiro real (Fed, eleições, recessão, ouro, petróleo...).
A lista é buscada na API pública (sem chave) em paralelo, guardada por 10 minutos e refeita sozinha: eventos que já venceram saem e
os novos entram conforme os dias passam. Para a IA vai só um resumo curto e já pronto (``ai_context``), lido do que está guardado,
sem esperar a rede.
"""
from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import requests

from core.sentiment import SEARCH, parse_price

TTL = 600
STALE_OK = 3600          # se a atualização falhar, os dados antigos valem por até 1 hora
TIMEOUT = 8
CATEGORIES = {
    "macro": ("🏦 Macro e juros", ["Fed decision", "Fed rate cuts", "US recession", "CPI inflation", "unemployment rate", "tariff"]),
    "geopolitica": ("🌍 Guerra e geopolítica", ["ceasefire", "Russia Ukraine", "Israel Iran", "Taiwan invade", "Hormuz", "nuclear deal", "NATO Russia"]),
    "politica": ("🗳️ Política e eleições", ["Brazil Presidential Election", "Presidential Election Winner 2028", "midterms Senate", "midterms House", "Trump", "Supreme Court"]),
    "commodities": ("🛢️ Commodities e índices", ["gold XAUUSD", "WTI crude oil", "S&P 500", "silver XAGUSD"]),
    "cripto": ("₿ Cripto", ["bitcoin", "ethereum", "solana", "crypto ETF"]),
}
# Palavras que o título precisa ter em cada categoria (as buscas trazem ruído: "o que Trump vai dizer no comício" aparece em "crypto")
KEYWORDS = {
    "macro": ("fed", "fomc", "interest rate", "rate cut", "rate hike", "inflation", "cpi", "recession", "unemployment", "gdp", "tariff", "jobs", "payroll", "treasury", "yield"),
    "commodities": ("gold", "silver", "oil", "crude", "wti", "brent", "s&p", "nasdaq", "dow jones", "copper", "natural gas", "xau", "xag", "spx"),
    "geopolitica": ("war", "ceasefire", "invade", "invasion", "ukraine", "russia", "israel", "iran", "gaza", "china", "taiwan", "nato", "sanction", "military",
                    "nuclear", "hormuz", "missile", "peace", "strait", "attack", "hamas", "hezbollah", "korea"),
    "cripto": ("bitcoin", "btc", "ethereum", "eth ", "solana", "crypto", "xrp", "dogecoin", "etf", "coinbase", "stablecoin", "microstrategy"),
}
NOISE = re.compile(r"\b(say|says|mention|tweet|post)\b|earnings call|vs\.", re.I)
AI_PICK = {"macro": 2, "geopolitica": 2, "politica": 2, "commodities": 1, "cripto": 1}   # quantos eventos de cada categoria resumem para a IA
MIN_VOL24 = 300.0
MIN_LIQ = 50_000.0
_state: dict = {"at": 0.0, "events": []}
_lock = threading.Lock()
_refreshing = threading.Event()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _end(e: dict) -> datetime | None:
    try:
        return datetime.fromisoformat(str(e.get("endDate")).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _prob(m: dict) -> float | None:
    try:
        prices = m.get("outcomePrices")
        prices = json.loads(prices) if isinstance(prices, str) else prices
        outcomes = m.get("outcomes")
        outcomes = json.loads(outcomes) if isinstance(outcomes, str) else outcomes
        i = [str(o).lower() for o in outcomes].index("yes") if outcomes else 0
        return float(prices[i])
    except (TypeError, ValueError, IndexError, KeyError):
        return None


def _label(m: dict) -> str:
    t = (m.get("groupItemTitle") or "").strip()
    if not t:
        t = re.sub(r"^Will (the )?", "", m.get("question", "")).rstrip("?")
        t = re.sub(r"^(win|be) ", "", t)
    return t[:52]


def card(e: dict, category: str, now: datetime | None = None) -> dict | None:
    """Evento do Polymarket → cartão simples (ou None se já venceu, está fechado ou tem pouco movimento)."""
    now = now or _now()
    end = _end(e)
    if e.get("closed") or e.get("active") is False or not end or end <= now:
        return None
    title = (e.get("title") or "").lower() + " "
    if NOISE.search(title) or (category in KEYWORDS and not any(k in title for k in KEYWORDS[category])):
        return None
    if float(e.get("volume24hr") or 0) < MIN_VOL24 and float(e.get("liquidity") or 0) < MIN_LIQ:
        return None
    rows = [(p, m) for m in e.get("markets") or [] if not m.get("closed") and m.get("active") is not False and (p := _prob(m)) is not None]
    if not rows:
        return None
    ladder = len(rows) >= 4 and sum(parse_price(m.get("question", "")) is not None for _, m in rows) >= 0.6 * len(rows)
    if len(rows) == 1:   # sim/não: mostra as duas pontas
        p = rows[0][0]
        opts = [("Sim", p), ("Não", 1 - p)]
    elif ladder:         # escada de preços: mostra os níveis mais incertos (perto de 50%)
        opts = [(_label(m), p) for p, m in sorted(rows, key=lambda r: abs(r[0] - 0.5))[:3]]
    else:
        opts = [(_label(m), p) for p, m in sorted(rows, key=lambda r: -r[0])[:4]]
    return {"id": str(e.get("id")), "titulo": e.get("title", ""), "categoria": category, "slug": e.get("slug", ""), "vence": end.isoformat(),
            "volume_24h": round(float(e.get("volume24hr") or 0)), "liquidez": round(float(e.get("liquidity") or 0)),
            "escada": ladder, "desc": re.sub(r"\s+", " ", e.get("description") or "")[:600], "opcoes": [{"nome": n, "pct": round(p * 100, 1)} for n, p in opts]}


def _search(q: str) -> list[dict]:
    r = requests.get(SEARCH, params={"q": q, "events_status": "active", "limit_per_type": 10, "sort": "volume_24hr"}, timeout=TIMEOUT,
                     headers={"User-Agent": "TradeBotPlatform/1.0"})
    r.raise_for_status()
    return r.json().get("events") or []


def build(raw_by_query: dict[str, tuple[str, list[dict]]], now: datetime | None = None) -> list[dict]:
    """Junta os resultados das buscas: sem repetidos, só eventos ainda abertos, por volume de 24 h (pura: sem rede)."""
    now = now or _now()
    seen, out = set(), []
    for q, (cat, events) in raw_by_query.items():
        for e in events:
            if e.get("id") in seen:
                continue
            c = card(e, cat, now)
            if c:
                seen.add(e.get("id"))
                out.append(c)
    out.sort(key=lambda c: -c["volume_24h"])
    return out


def refresh(search=None) -> list[dict]:
    """Busca tudo em paralelo e guarda. Se nada vier (sem rede), mantém o que já havia."""
    search = search or _search
    jobs = [(q, cat) for cat, (_, queries) in CATEGORIES.items() for q in queries]
    raw: dict[str, tuple[str, list[dict]]] = {}

    def _one(job):
        q, cat = job
        try:
            return q, (cat, search(q))
        except Exception:  # noqa: BLE001 - uma busca que falha não derruba as outras
            return q, (cat, [])

    with ThreadPoolExecutor(max_workers=8) as pool:
        for q, res in pool.map(_one, jobs):
            raw[q] = res
    events = build(raw)
    with _lock:
        if events or time.time() - _state["at"] > STALE_OK:
            _state.update(at=time.time(), events=events)
    return list(_state["events"])


def get(search=None) -> list[dict]:
    """Eventos atuais (busca de novo quando passaram 10 min). Eventos já vencidos saem na hora, mesmo com a lista em cache."""
    if time.time() - _state["at"] >= TTL:
        refresh(search)
    now = _now()
    return [c for c in _state["events"] if (_end({"endDate": c["vence"]}) or now) > now]


def peek() -> list[dict]:
    """Só o que está guardado, sem rede."""
    now = _now()
    return [c for c in _state["events"] if time.time() - _state["at"] < STALE_OK and (_end({"endDate": c["vence"]}) or now) > now]


def warm() -> None:
    """Atualiza em segundo plano quando a lista está velha (a análise nunca espera a rede)."""
    if time.time() - _state["at"] < TTL or _refreshing.is_set():
        return
    _refreshing.set()

    def _run():
        try:
            refresh()
        finally:
            _refreshing.clear()

    threading.Thread(target=_run, daemon=True).start()


def ensure() -> None:
    """Para quem roda sem a página aberta (worker): carrega na hora se nunca carregou; depois só renova em segundo plano."""
    if not _state["at"]:
        try:
            refresh()
        except Exception:  # noqa: BLE001
            pass
    else:
        warm()


def ai_context(events: list[dict] | None = None, now: datetime | None = None) -> list[dict]:
    """Resumo curto para a IA: os eventos de maior volume de cada categoria (sem escadas de preço de cripto, que já viram o sentimento)."""
    events = peek() if events is None else events
    now = now or _now()
    out, taken = [], {c: 0 for c in AI_PICK}
    for c in events:   # já vem por volume
        if c["escada"] and c["categoria"] == "cripto":
            continue
        if taken.get(c["categoria"], 99) >= AI_PICK.get(c["categoria"], 0):
            continue
        end = _end({"endDate": c["vence"]})
        taken[c["categoria"]] += 1
        out.append({"evento": c["titulo"], "categoria": CATEGORIES[c["categoria"]][0].split(" ", 1)[1],
                    "vence_em_dias": max(0, (end - now).days) if end else None,
                    "probabilidades": [{"opcao": o["nome"], "pct": o["pct"]} for o in c["opcoes"][:3]]})
    return out


def ids_for_ai(events: list[dict]) -> set[str]:
    titles = {x["evento"] for x in ai_context(events)}
    return {c["id"] for c in events if c["titulo"] in titles}
