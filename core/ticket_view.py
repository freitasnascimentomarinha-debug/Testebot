"""Dados e ação da boleta (core/ticket.js). Sem Streamlit, para ser testado.

O navegador só envia o formulário (lado, tipo, preços, tamanho); a calculadora de risco roda aqui, e o envio recalcula tudo do zero:
nada do que vem do componente é confiável.
"""
from __future__ import annotations

import math

from core import execution, risk
from core.broker import get_broker
from core.profiles import BotProfile

MAX_DEVIATION = 0.30


def _num(v, default: float | None = None) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return x if math.isfinite(x) and x > 0 else default


def clean_form(profile: BotProfile, cfg: dict, form: dict | None, price: float, atr: float | None, budget: float, available: float,
               max_lev: int = 125) -> dict:
    """Formulário saneado, com padrões para o que faltar (venda só em futuros com short liberado)."""
    form = form if isinstance(form, dict) else {}
    can_short = profile.market == "futures" and bool(cfg.get("allow_short"))
    side = "SELL" if form.get("side") == "SELL" and can_short else "BUY"
    otype = "LIMIT" if form.get("type") == "LIMIT" else "MARKET"
    entry = (_num(form.get("limit")) or price) if otype == "LIMIT" else price
    sign = 1 if side == "BUY" else -1
    a = atr or price * 0.01
    auto = form.get("auto", True) is not False
    sl = _num(form.get("sl")) if not auto else None
    tp = _num(form.get("tp")) if not auto else None
    sl = sl or risk.round_price(entry - sign * a * float(cfg["atr_sl_mult"]), price)
    tp = tp or risk.round_price(entry + sign * a * float(cfg["atr_tp_mult"]), price)
    if profile.market == "spot":
        lev, margin = 1, cfg["margin_mode"]
    else:   # alavancagem e margem desta ordem: partem das do bot, mas a boleta tem as próprias
        lev = int(min(max(1, _num(form.get("lev"), float(risk.effective_leverage(cfg))) or 1), max_lev))
        margin = form.get("margin") if form.get("margin") in ("Isolada", "Cruzada") else cfg["margin_mode"]
    return {"lev": lev, "margin": margin, "side": side, "type": otype, "limit": entry, "auto": auto, "sl": sl, "tp": tp,
            "sizing": "VALUE" if form.get("sizing") == "VALUE" else "RISK",
            "risk": _num(form.get("risk"), round(budget, 2)), "value": _num(form.get("value"), round(min(500.0, available), 2))}


def calculate(profile: BotProfile, cfg: dict, f: dict, available: float):
    kw = dict(leverage=f["lev"], fee_pct=float(cfg["fee_pct"]), available=available, symbol=cfg["symbol"],
              market=profile.market, margin_mode=f["margin"])
    if f["sizing"] == "RISK":
        return risk.calculate(f["side"], f["limit"], f["sl"], f["tp"], risk_usdt=f["risk"], **kw)
    return risk.calculate(f["side"], f["limit"], f["sl"], f["tp"], margin_usdt=f["value"], **kw)


def view(profile: BotProfile, cfg: dict, form: dict | None, price: float, atr: float | None, stats: dict, max_lev: int = 125) -> dict:
    """Tudo o que a boleta mostra (tipos simples)."""
    f = clean_form(profile, cfg, form, price, atr, risk.risk_budget(cfg, stats["equity"]), stats["available"], max_lev)
    c = calculate(profile, cfg, f, stats["available"])
    spot = profile.market == "spot"
    blocked = execution.orders_problem()
    return {
        "symbol": cfg["symbol"], "base": cfg["symbol"].removesuffix("USDT"), "spot": spot, "price": price,
        "can_short": not spot and bool(cfg.get("allow_short")), "form": f,
        "leverage": None if spot else c.leverage, "margin_mode": None if spot else f["margin"], "max_lev": max_lev,
        "available": stats["available"], "blocked": blocked or "",
        "calc": {"qty": c.qty, "notional": c.notional, "margin": c.margin, "risk": c.risk_usdt, "reward": c.reward_usdt, "rr": c.rr,
                 "stop_pct": c.stop_pct, "tp_pct": c.tp_pct, "fees": c.fees_usdt, "breakeven": c.breakeven,
                 "liquidation": c.liquidation, "warnings": list(c.warnings)},
    }


def submit(profile: BotProfile, cfg: dict, form: dict, price: float | None, atr: float | None, max_lev: int = 125) -> tuple[bool, str]:
    """Envia a ordem da boleta. Devolve ``(enviou, mensagem)``."""
    if not price or not isinstance(form, dict):
        return False, "Sem cotação para enviar a ordem."
    if (why := execution.orders_problem()):
        return False, why
    broker = get_broker(profile.key)
    s = broker.stats({cfg["symbol"]: price})
    f = clean_form(profile, cfg, form, price, atr, risk.risk_budget(cfg, s["equity"]), s["available"], max_lev)
    if form.get("side") == "SELL" and f["side"] != "SELL":
        return False, "Venda a descoberto só em Futuros, com short liberado."
    if f["type"] == "LIMIT" and abs(f["limit"] / price - 1) > MAX_DEVIATION:
        return False, f"Preço limite muito longe do mercado ({f['limit']:g} contra {price:g})."
    c = calculate(profile, cfg, f, s["available"])
    if c.qty <= 0:
        return False, "Tamanho zero: ajuste o valor ou os níveis de stop e alvo."
    check = risk.check_trade({**cfg, "leverage_on": True, "leverage": f["lev"], "margin_mode": f["margin"]}, s, f["side"], f["limit"], f["sl"], f["tp"], profile.market)
    if check.reasons:
        return False, "; ".join(check.reasons)
    try:
        out = broker.place_order(symbol=cfg["symbol"], market=profile.market, side=f["side"], qty=c.qty,
                                 order_type=f["type"], price=price, limit_price=f["limit"] if f["type"] == "LIMIT" else None,
                                 stop_loss=f["sl"], take_profit=f["tp"], leverage=f["lev"],
                                 fee_pct=float(cfg["fee_pct"]), slippage_pct=float(cfg["slippage_pct"]), source="manual",
                                 max_loss_planned=c.risk_usdt, margin_mode=f["margin"], fx=c.fx)
    except ValueError as exc:
        return False, str(exc)
    return True, f"Ordem {str(out['status']).lower()}: {'compra' if f['side'] == 'BUY' else 'venda'} de {c.qty:g} {cfg['symbol']}."
