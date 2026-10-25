"""Ações pedidas pelo gráfico em tempo real (ordem limite, mover stop/alvo, zerar, cancelar).

O gráfico roda no navegador e avisa a página por ``postMessage``; nada do que vem de lá é confiável: cada pedido é validado aqui (ativo e
mercado da página, números finitos, preço perto do mercado, posição/ordem existentes naquele mercado) e passa pelas mesmas regras da
boleta. Sem dependência do Streamlit, para ser testado.
"""
from __future__ import annotations

import math

from core import execution, risk
from core.broker import get_broker
from core.profiles import BotProfile

MAX_DEVIATION = 0.30   # ordem limite a mais de 30% do preço atual é recusada (provável erro de clique)


def _num(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) and x > 0 else None


def handle(profile: BotProfile, cfg: dict, ev: dict, price: float | None, atr: float | None) -> tuple[bool, str]:
    """Executa o pedido do gráfico. Devolve ``(mudou_algo, mensagem)``; mensagem vazia = nada a mostrar."""
    if not isinstance(ev, dict) or ev.get("tb") != 1:
        return False, ""
    if str(ev.get("symbol", "")).upper() != str(cfg["symbol"]).upper() or ev.get("market") != profile.market:
        return False, "Pedido ignorado: veio de um gráfico de outro ativo ou mercado."
    if (why := execution.orders_problem()):
        return False, why
    broker = get_broker(profile.key)
    acct = broker.account()
    kind = ev.get("kind")
    positions = {p["id"]: p for p in acct["positions"] if p.get("market") == profile.market and p["symbol"] == cfg["symbol"]}

    if kind == "limit":
        side, limit = ev.get("side"), _num(ev.get("price"))
        if side not in ("BUY", "SELL") or limit is None or not price or not atr:
            return False, "Pedido de ordem inválido."
        if side == "SELL" and profile.market != "futures":
            return False, "No spot só é possível comprar."
        if abs(limit / price - 1) > MAX_DEVIATION:
            return False, f"Preço limite muito longe do mercado ({limit:g} contra {price:g}): ordem não criada."
        sign = 1 if side == "BUY" else -1
        sl, tp = limit - sign * atr * float(cfg["atr_sl_mult"]), limit + sign * atr * float(cfg["atr_tp_mult"])
        sl, tp = risk.round_price(sl, price), risk.round_price(tp, price)
        check = risk.check_trade(cfg, broker.stats({cfg["symbol"]: price}), side, limit, sl, tp, profile.market)
        if check.reasons or not check.calc:
            return False, "Ordem não criada: " + "; ".join(check.reasons or ["tamanho zero"])
        calc = check.calc
        broker.place_order(symbol=cfg["symbol"], market=profile.market, side=side, qty=calc.qty, order_type="LIMIT", price=price,
                           limit_price=limit, stop_loss=sl, take_profit=tp, leverage=risk.effective_leverage(cfg),
                           fee_pct=float(cfg["fee_pct"]), slippage_pct=float(cfg["slippage_pct"]), source="manual",
                           max_loss_planned=calc.risk_usdt, margin_mode=cfg["margin_mode"], fx=calc.fx)
        return True, f"Ordem limite {'de compra' if side == 'BUY' else 'de venda'} criada em {limit:g} ({calc.qty:g}, stop {sl:g}, alvo {tp:g})."

    if kind == "protect":
        pos = positions.get(str(ev.get("id")))
        if pos is None:
            return False, "Posição não encontrada."
        sl, tp = ev.get("stop_loss"), ev.get("take_profit")
        sl, tp = (_num(sl) if sl else None), (_num(tp) if tp else None)
        long = pos["side"] == "BUY"
        if (sl and (sl >= pos["entry"] if long else sl <= pos["entry"])) or (tp and (tp <= pos["entry"] if long else tp >= pos["entry"])):
            return False, "Stop ou alvo do lado errado da entrada: não alterado."
        broker.update_protection(pos["id"], sl, tp)
        return True, "Stop e alvo atualizados."

    if kind == "close":
        pos = positions.get(str(ev.get("id")))
        if pos is None or not price:
            return False, "Posição não encontrada."
        tr = broker.close_position(pos["id"], price, "Manual (gráfico)")
        return True, f"Posição encerrada: {tr['pnl']:+.2f} USDT."

    if kind == "cancel_order":
        oid = str(ev.get("id"))
        if not any(o["id"] == oid and o.get("market") == profile.market for o in acct["orders"]):
            return False, "Ordem não encontrada."
        broker.cancel_order(oid)
        return True, "Ordem limite cancelada."
    return False, ""


def handle_card(profile: BotProfile, ev: dict, price_for) -> tuple[bool, str]:
    """Ações dos cards das posições abertas (atualizar stop/alvo, encerrar): valida como as do gráfico, em qualquer ativo do mercado."""
    if not isinstance(ev, dict) or ev.get("kind") not in ("protect", "close"):
        return False, ""
    if (why := execution.orders_problem()):
        return False, why
    broker = get_broker(profile.key)
    pos = next((p for p in broker.account()["positions"] if p["id"] == str(ev.get("id")) and p.get("market") == profile.market), None)
    if pos is None:
        return False, "Posição não encontrada."
    if ev["kind"] == "protect":
        sl, tp = ev.get("stop_loss"), ev.get("take_profit")
        sl, tp = (_num(sl) if sl else None), (_num(tp) if tp else None)
        long = pos["side"] == "BUY"
        if (sl and (sl >= pos["entry"] if long else sl <= pos["entry"])) or (tp and (tp <= pos["entry"] if long else tp >= pos["entry"])):
            return False, "Stop ou alvo do lado errado da entrada: não alterado."
        broker.update_protection(pos["id"], sl, tp)
        return True, "Stop e alvo atualizados."
    price = price_for(pos["symbol"])
    if not price:
        return False, "Sem cotação agora para encerrar a posição."
    tr = broker.close_position(pos["id"], price, "Manual")
    return True, f"Posição encerrada: {tr['pnl']:+.2f} USDT."
