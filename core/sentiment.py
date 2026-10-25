"""Sentimento das criptomoedas lido do Polymarket (mercado de previsões), para a IA.

Os mercados de preço do Polymarket ("Bitcoin acima de $X no dia Y", "Bitcoin chega a $X em outubro") embutem a probabilidade que
apostadores com dinheiro real dão a cada nível de preço. Disso saem dois números úteis para contextualizar a análise:
  • preço mediano implícito: onde o mercado dá 50% de chance de o preço estar acima na data de vencimento (contra o preço de hoje);
  • chances de tocar um nível acima ou abaixo do preço (+3% / −3%) até o vencimento.
É contexto auxiliar, nunca um gatilho de entrada: sem mercado para a moeda (ou sem rede), devolve None e nada muda. Dados públicos,
sem chave; guardados por 10 minutos.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone

import requests

SEARCH = "https://gamma-api.polymarket.com/public-search"
TTL = 600
FAIL_TTL = 300
TIMEOUT = 6
NAMES = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "XRP": "xrp", "BNB": "bnb", "DOGE": "dogecoin", "ADA": "cardano",
         "AVAX": "avalanche", "LINK": "chainlink", "LTC": "litecoin", "TRX": "tron", "SUI": "sui", "TON": "toncoin", "DOT": "polkadot"}
_cache: dict[str, tuple[float, dict | None]] = {}
_PRICE = re.compile(r"\$\s?([\d][\d,]*(?:\.\d+)?)\s?([kKmM])?")


def parse_price(text: str) -> float | None:
    m = _PRICE.search(text or "")
    if not m:
        return None
    v = float(m.group(1).replace(",", ""))
    return v * {"k": 1e3, "m": 1e6}.get((m.group(2) or "").lower(), 1)


def kind_of(question: str) -> str | None:
    """above (preço acima de X no vencimento) · up (toca X para cima) · down (toca X para baixo)."""
    q = (question or "").lower()
    if re.search(r"\b(dip|fall|drop|crash)\b", q):
        return "down"
    if re.search(r"\b(reach|hit|touch)\b", q):
        return "up"
    if re.search(r"\babove\b|\bgreater than\b|\bover\b", q):
        return "above"
    return None


def _yes(market: dict) -> float | None:
    try:
        prices = market.get("outcomePrices")
        prices = json.loads(prices) if isinstance(prices, str) else prices
        outcomes = market.get("outcomes")
        outcomes = json.loads(outcomes) if isinstance(outcomes, str) else outcomes
        i = [str(o).lower() for o in outcomes].index("yes") if outcomes else 0
        return float(prices[i])
    except (TypeError, ValueError, IndexError, KeyError):
        return None


def _end(event: dict) -> datetime | None:
    try:
        return datetime.fromisoformat(str(event.get("endDate")).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _ladder(event: dict, kinds: tuple[str, ...]) -> list[tuple[float, float, str]]:
    """(preço, probabilidade de "Sim", tipo) dos mercados abertos do evento, do menor para o maior preço."""
    rows = []
    for m in event.get("markets") or []:
        if m.get("closed") or m.get("active") is False:
            continue
        k, p, y = kind_of(m.get("question", "")), parse_price(m.get("question", "")), _yes(m)
        if k in kinds and p and y is not None:
            rows.append((p, y, k))
    return sorted(rows)


def implied_median(ladder: list[tuple[float, float, str]]) -> float | None:
    """Preço em que a chance de "acima" cruza 50% (interpolado entre dois níveis vizinhos)."""
    pts = [(p, y) for p, y, _ in ladder]
    for (p1, y1), (p2, y2) in zip(pts, pts[1:]):
        if y1 >= 0.5 >= y2 and y1 != y2:
            return p1 + (p2 - p1) * (y1 - 0.5) / (y1 - y2)
    return None


def summarize(events: list[dict], base: str, price: float, now: datetime | None = None) -> dict | None:
    """Resumo do sentimento para a moeda a partir dos eventos do Polymarket (pura: sem rede)."""
    now = now or datetime.now(timezone.utc)
    word = NAMES.get(base, base.lower())
    live = []
    for e in events:
        end = _end(e)
        if end and end > now and word in (e.get("title") or "").lower():
            live.append((end, e))
    live.sort(key=lambda x: x[0])
    out: dict = {"fonte": "Polymarket", "ativo": base, "preco_de_referencia": price}
    # preço mediano implícito: o vencimento mais próximo com uma escada "acima de X" que cruze 50%
    for end, e in live:
        lad = _ladder(e, ("above",))
        med = implied_median(lad) if len(lad) >= 4 else None
        if med:
            out["mediana_implicita"] = {"preco": round(med, 6), "vs_preco_pct": round((med / price - 1) * 100, 2),
                                        "vence_em": end.strftime("%d/%m %H:%M UTC"), "volume_24h_usd": round(float(e.get("volume24hr") or 0))}
            break
    # chance de tocar +3% / −3% até o vencimento mais próximo (até 45 dias) que tenha os dois lados
    for end, e in live:
        if (end - now).days > 45:
            continue
        lad = _ladder(e, ("up", "down"))
        ups = [(p, y) for p, y, k in lad if k == "up" and p >= price * 1.03]
        downs = [(p, y) for p, y, k in lad if k == "down" and p <= price * 0.97]
        if ups and downs:
            up, down = min(ups), max(downs)
            out["toque"] = {"alta": {"nivel": up[0], "chance_pct": round(up[1] * 100, 1)}, "queda": {"nivel": down[0], "chance_pct": round(down[1] * 100, 1)},
                            "vence_em": end.strftime("%d/%m %H:%M UTC")}
            break
    if "mediana_implicita" not in out and "toque" not in out:
        return None
    score = 0.0
    if "mediana_implicita" in out:
        score += out["mediana_implicita"]["vs_preco_pct"]
    if "toque" in out:
        score += (out["toque"]["alta"]["chance_pct"] - out["toque"]["queda"]["chance_pct"]) / 10
    out["vies"] = "altista" if score > 0.4 else "baixista" if score < -0.4 else "neutro"
    parts = []
    if "mediana_implicita" in out:
        m = out["mediana_implicita"]
        parts.append(f"o mercado de previsões vê {base} mediano em {m['preco']:,.2f} até {m['vence_em']} ({m['vs_preco_pct']:+.2f}% contra o preço atual)")
    if "toque" in out:
        t = out["toque"]
        parts.append(f"chance de tocar {t['alta']['nivel']:,.0f} ({t['alta']['chance_pct']:g}%) contra {t['queda']['nivel']:,.0f} ({t['queda']['chance_pct']:g}%)")
    out["leitura"] = f"Sentimento {out['vies']}: " + "; ".join(parts) + "."
    return out


def _fetch(base: str) -> list[dict]:
    r = requests.get(SEARCH, params={"q": NAMES.get(base, base.lower()), "events_status": "active", "limit_per_type": 25, "sort": "volume_24hr"},
                     timeout=TIMEOUT, headers={"User-Agent": "TradeBotPlatform/1.0"})
    r.raise_for_status()
    return r.json().get("events") or []


def peek(symbol: str) -> dict | None:
    """Sentimento já guardado (sem rede): usado pela faixa de cotações, que não pode esperar a consulta."""
    hit = _cache.get(str(symbol).upper().removesuffix("USDT"))
    return hit[1] if hit and time.time() - hit[0] < TTL else None


_pending: set[str] = set()


def warm(prices: dict[str, float]) -> None:
    """Busca em segundo plano o sentimento dos pares ainda sem dados (um de cada vez); aparece na próxima atualização da faixa."""
    import threading

    todo = [(s, p) for s, p in prices.items() if str(s).upper().removesuffix("USDT") in NAMES and p
            and (str(s).upper().removesuffix("USDT") not in _cache or time.time() - _cache[str(s).upper().removesuffix("USDT")][0] >= TTL)
            and s not in _pending]
    if not todo:
        return
    _pending.update(s for s, _ in todo)

    def _run():
        for s, p in todo:
            try:
                for_symbol(s, p)
            finally:
                _pending.discard(s)

    threading.Thread(target=_run, daemon=True).start()


def for_symbol(symbol: str, price: float | None, fetch=None) -> dict | None:
    """Sentimento do Polymarket para o par (ex.: BTCUSDT). None sem mercado, sem preço ou sem rede (nunca levanta erro)."""
    base = str(symbol).upper().removesuffix("USDT")
    if not price or not base:
        return None
    hit = _cache.get(base)
    if hit and time.time() - hit[0] < (TTL if hit[1] is not None else FAIL_TTL):
        return hit[1]
    try:
        res = summarize((fetch or _fetch)(base), base, float(price))
    except Exception:  # noqa: BLE001 - Polymarket fora do ar não pode atrapalhar a análise
        res = None
    _cache[base] = (time.time(), res)
    return res
