"""Números de uma posição aberta para o card: valor investido, moedas, preços, resultado agora e no alvo/stop (em USDT e em % ),
taxas, tempo aberta e — só nos futuros — margem, alavancagem e liquidação. Sem dependência do Streamlit."""
from __future__ import annotations

from datetime import datetime, timezone

from core import paper


def _ago(opened: str, now: datetime | None = None) -> str:
    try:
        secs = int(((now or datetime.now(timezone.utc)) - datetime.fromisoformat(opened)).total_seconds())
    except (TypeError, ValueError):
        return "—"
    if secs < 90:
        return "agora há pouco"
    if secs < 3600:
        return f"há {secs // 60} min"
    if secs < 86400:
        return f"há {secs // 3600} h {secs % 3600 // 60:02d} min"
    return f"há {secs // 86400} d {secs % 86400 // 3600} h"


def who_opened(p: dict) -> str:
    """Quem deu a entrada: a personalidade do bot, ou 'ordem manual'."""
    if p.get("source") == "manual":
        return "✋ Ordem manual (você)"
    name = p.get("personality_name")
    return f"🤖 {name}" if name else "🤖 Bot (sem personalidade registrada)"


def summarize(p: dict, price_now: float, now: datetime | None = None) -> dict:
    spot = p.get("market") == "spot"
    sign = 1 if p["side"] == "BUY" else -1
    fx, fee = p.get("fx", 1.0), p["fee_pct"] / 100
    qty, entry = p["qty"], p["entry"]
    cost = entry * qty * fx                                   # quanto foi comprado/vendido (valor da entrada)
    value_now = price_now * qty * fx
    fees_open = float(p.get("fees_paid", 0.0))
    base = cost if spot else (p["margin"] or cost)            # % sobre o valor investido (spot) ou sobre a margem (futuros)

    def net_at(price: float) -> float:                       # resultado líquido se a posição fechar neste preço
        return paper.pnl_of(p, price) - fees_open - price * qty * fx * fee

    def level(price):
        if not price:
            return None
        n = net_at(price)
        return {"price": price, "per_coin": sign * (price - entry) * fx, "net": n, "pct": n / base * 100 if base else 0.0,
                "pct_price": sign * (price / entry - 1) * 100}

    stop, target = level(p.get("stop_loss")), level(p.get("take_profit"))
    net = net_at(price_now)
    rr = (abs(target["price"] - entry) / abs(entry - p["stop_loss"])) if target and stop and p["stop_loss"] != entry else None
    return {"spot": spot, "base_asset": p["symbol"].removesuffix("USDT"), "cost": cost, "qty": qty, "entry": entry, "price_now": price_now,
            "value_now": value_now, "move_pct": sign * (price_now / entry - 1) * 100, "net": net, "net_pct": net / base * 100 if base else 0.0,
            "gross": paper.pnl_of(p, price_now), "fees_open": fees_open, "fees_close": value_now * fee, "stop": stop, "target": target, "rr": rr,
            "margin": p["margin"], "leverage": p["leverage"], "margin_mode": p.get("margin_mode"), "liquidation": p.get("liquidation"),
            "funding": p.get("funding_paid", 0.0), "opened_ago": _ago(p.get("opened"), now), "who": who_opened(p)}


def card_data(p: dict, price_now: float, now: datetime | None = None) -> dict:
    """Tudo o que o card (core/position_cards.js) mostra, em tipos simples (JSON)."""
    v = summarize(p, price_now, now)
    opened = str(p.get("opened") or "")
    return {**v, "id": p["id"], "symbol": p["symbol"], "side": p["side"], "note": (p.get("note") or "")[:200],
            "opened_at": f"{opened[8:10]}/{opened[5:7]} {opened[11:16]} UTC" if len(opened) >= 16 else ""}
