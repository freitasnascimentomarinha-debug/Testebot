"""Corretora simulada (paper trading) com preços reais.

Cada bot tem sua própria subconta para que o desempenho de cada estratégia seja
medido de forma independente. A interface pública (``place_order``,
``close_position``, ``cancel_order``, ``sync``) é a mesma que um executor real
da Binance deverá implementar (ver ``core/broker.py``).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pandas as pd

from core.risk import liquidation_price
from core.storage import load_json, locked_update

ACCOUNT_FILE = "paper_accounts.json"
INITIAL_BALANCE = 10_000.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_account(initial: float = INITIAL_BALANCE) -> dict:
    return {"initial": initial, "balance": initial, "positions": [], "orders": [], "history": [],
            "equity_curve": [{"time": _now(), "equity": initial}], "created": _now()}


def _account(data: dict, bot: str) -> dict:
    if bot not in data:
        data[bot] = _new_account()
    return data[bot]


def _pnl(pos: dict, price: float) -> float:
    sign = 1 if pos["side"] == "BUY" else -1
    return sign * (price - pos["entry"]) * pos["qty"]


def get_account(bot: str) -> dict:
    data = load_json(ACCOUNT_FILE, {}) or {}
    return data.get(bot) or _new_account()


def reset_account(bot: str, initial: float = INITIAL_BALANCE) -> None:
    def _apply(data):
        data[bot] = _new_account(initial)

    locked_update(ACCOUNT_FILE, {}, _apply)


def _open_position(acct: dict, order: dict, fill_price: float, fee_pct: float) -> dict:
    notional = fill_price * order["qty"]
    fee = notional * fee_pct / 100
    margin = notional / order["leverage"]
    if margin + fee > acct["balance"] + 1e-9:
        raise ValueError(f"Saldo insuficiente: margem {margin:,.2f} + taxa {fee:,.2f} > saldo {acct['balance']:,.2f} USDT")
    acct["balance"] -= margin + fee
    pos = {
        "id": uuid.uuid4().hex[:8], "symbol": order["symbol"], "market": order["market"], "side": order["side"],
        "qty": order["qty"], "entry": fill_price, "leverage": order["leverage"], "margin": margin,
        "stop_loss": order.get("stop_loss"), "take_profit": order.get("take_profit"),
        "liquidation": liquidation_price(order["side"], fill_price, order["leverage"]) if order["leverage"] > 1 else None,
        "fee_pct": fee_pct, "fees_paid": fee, "opened": _now(), "last_check": _now(),
        "source": order.get("source", "manual"), "note": order.get("note", ""),
        "max_loss_planned": order.get("max_loss_planned"),
    }
    acct["positions"].append(pos)
    return pos


def place_order(bot: str, *, symbol: str, market: str, side: str, qty: float, order_type: str = "MARKET",
                price: float, limit_price: float | None = None, stop_loss: float | None = None,
                take_profit: float | None = None, leverage: float = 1.0, fee_pct: float = 0.1,
                slippage_pct: float = 0.0, source: str = "manual", note: str = "",
                max_loss_planned: float | None = None) -> dict:
    """Envia uma ordem simulada. ``price`` é o último preço real de mercado."""
    if qty <= 0:
        raise ValueError("Quantidade deve ser maior que zero.")
    order = {"id": uuid.uuid4().hex[:8], "symbol": symbol, "market": market, "side": side, "qty": qty,
             "type": order_type, "limit_price": limit_price, "stop_loss": stop_loss, "take_profit": take_profit,
             "leverage": max(1.0, float(leverage)), "fee_pct": fee_pct, "created": _now(), "source": source,
             "note": note, "max_loss_planned": max_loss_planned}

    def _apply(data):
        acct = _account(data, bot)
        if order_type == "LIMIT" and limit_price:
            margin = limit_price * qty / order["leverage"]
            if margin > acct["balance"]:
                raise ValueError("Saldo insuficiente para a ordem limitada.")
            acct["orders"].append(order)
            return {"status": "PENDENTE", "order": order}
        slip = price * slippage_pct / 100 * (1 if side == "BUY" else -1)
        pos = _open_position(acct, order, price + slip, fee_pct)
        return {"status": "EXECUTADA", "position": pos}

    return locked_update(ACCOUNT_FILE, {}, _apply)


def _close(acct: dict, pos: dict, price: float, reason: str) -> dict:
    fee = price * pos["qty"] * pos["fee_pct"] / 100
    gross = _pnl(pos, price)
    gross = max(gross, -pos["margin"])  # perda limitada à margem (liquidação)
    acct["balance"] += pos["margin"] + gross - fee
    net = gross - fee - pos["fees_paid"]
    trade = {**pos, "exit": price, "closed": _now(), "reason": reason, "gross_pnl": gross,
             "fees_total": fee + pos["fees_paid"], "pnl": net,
             "pnl_pct_margin": net / pos["margin"] * 100 if pos["margin"] else 0.0}
    acct["positions"] = [p for p in acct["positions"] if p["id"] != pos["id"]]
    acct["history"].append(trade)
    return trade


def close_position(bot: str, position_id: str, price: float, reason: str = "Manual") -> dict | None:
    def _apply(data):
        acct = _account(data, bot)
        pos = next((p for p in acct["positions"] if p["id"] == position_id), None)
        return _close(acct, pos, price, reason) if pos else None

    return locked_update(ACCOUNT_FILE, {}, _apply)


def cancel_order(bot: str, order_id: str) -> None:
    def _apply(data):
        acct = _account(data, bot)
        acct["orders"] = [o for o in acct["orders"] if o["id"] != order_id]

    locked_update(ACCOUNT_FILE, {}, _apply)


def update_protection(bot: str, position_id: str, stop_loss: float | None, take_profit: float | None) -> None:
    def _apply(data):
        for p in _account(data, bot)["positions"]:
            if p["id"] == position_id:
                p["stop_loss"], p["take_profit"] = stop_loss, take_profit

    locked_update(ACCOUNT_FILE, {}, _apply)


def sync(bot: str, symbol: str, candles: pd.DataFrame, last_price: float) -> list[dict]:
    """Processa ordens limitadas, stops, alvos e liquidações usando as máximas e
    mínimas reais dos candles desde a última verificação. Quando stop e alvo
    cabem no mesmo candle, assume-se o stop (premissa conservadora).
    Devolve a lista de eventos ocorridos."""
    events: list[dict] = []

    def _apply(data):
        acct = _account(data, bot)
        for order in list(acct["orders"]):
            if order["symbol"] != symbol:
                continue
            since = candles[candles["time"] >= pd.Timestamp(order["created"]).floor("min")]
            lo = min(since["low"].min() if len(since) else last_price, last_price)
            hi = max(since["high"].max() if len(since) else last_price, last_price)
            lp = order["limit_price"]
            if (order["side"] == "BUY" and lo <= lp) or (order["side"] == "SELL" and hi >= lp):
                acct["orders"].remove(order)
                try:
                    pos = _open_position(acct, order, lp, order["fee_pct"])
                    events.append({"type": "Ordem limitada executada", "position": pos})
                except ValueError as exc:
                    events.append({"type": "Ordem cancelada", "detail": str(exc)})

        for pos in list(acct["positions"]):
            if pos["symbol"] != symbol:
                continue
            since = candles[candles["time"] >= pd.Timestamp(pos["last_check"]).floor("min")]
            if pd.Timestamp(pos["last_check"]) <= pd.Timestamp(pos["opened"]):
                since = since.iloc[-1:]  # na abertura, só o candle atual conta
            lo = min(since["low"].min() if len(since) else last_price, last_price)
            hi = max(since["high"].max() if len(since) else last_price, last_price)
            long = pos["side"] == "BUY"
            sl, tp, liq = pos.get("stop_loss"), pos.get("take_profit"), pos.get("liquidation")
            adverse = []
            if liq and ((long and lo <= liq) or (not long and hi >= liq)):
                adverse.append((liq, "Liquidação"))
            if sl and ((long and lo <= sl) or (not long and hi >= sl)):
                adverse.append((sl, "Stop loss"))
            hit = None
            if adverse:  # o nível mais próximo da entrada é atingido primeiro
                hit = max(adverse) if long else min(adverse)
            elif tp and ((long and hi >= tp) or (not long and lo <= tp)):
                hit = (tp, "Take profit")
            if hit:
                events.append({"type": hit[1], "trade": _close(acct, pos, hit[0], hit[1])})
            else:
                pos["last_check"] = _now()

        equity = equity_of(acct, {symbol: last_price})
        curve = acct["equity_curve"]
        if not curve or (pd.Timestamp(_now()) - pd.Timestamp(curve[-1]["time"])).total_seconds() >= 300 or events:
            curve.append({"time": _now(), "equity": equity})
            del curve[:-2000]

    locked_update(ACCOUNT_FILE, {}, _apply)
    return events


def equity_of(acct: dict, prices: dict[str, float]) -> float:
    eq = acct["balance"]
    for p in acct["positions"]:
        price = prices.get(p["symbol"], p["entry"])
        eq += p["margin"] + max(_pnl(p, price), -p["margin"])
    return eq


def stats(acct: dict, prices: dict[str, float]) -> dict:
    """Indicadores de desempenho e controle das metas diárias."""
    today = datetime.now(timezone.utc).date().isoformat()
    hist = acct["history"]
    closed_today = [t for t in hist if t["closed"][:10] == today]
    opened_today = [t for t in hist if t["opened"][:10] == today] + [p for p in acct["positions"] if p["opened"][:10] == today]
    wins = [t["pnl"] for t in hist if t["pnl"] > 0]
    losses = [t["pnl"] for t in hist if t["pnl"] <= 0]
    unrealized = sum(max(_pnl(p, prices.get(p["symbol"], p["entry"])), -p["margin"]) for p in acct["positions"])
    equity = equity_of(acct, prices)
    curve = [c["equity"] for c in acct["equity_curve"]] + [equity]
    peak, max_dd = curve[0], 0.0
    for v in curve:
        peak = max(peak, v)
        max_dd = max(max_dd, (peak - v) / peak * 100 if peak else 0)
    return {
        "equity": equity, "available": acct["balance"], "unrealized": unrealized,
        "unrealized_net": sum(max(_pnl(p, prices.get(p["symbol"], p["entry"])), -p["margin"]) - p["fees_paid"]
                              - prices.get(p["symbol"], p["entry"]) * p["qty"] * p["fee_pct"] / 100
                              for p in acct["positions"]),
        "total_pnl": equity - acct["initial"], "total_pnl_pct": (equity / acct["initial"] - 1) * 100,
        "pnl_today": sum(t["pnl"] for t in closed_today), "trades_today": len(opened_today),
        "open_positions": len(acct["positions"]), "trades": len(hist),
        "win_rate": len(wins) / len(hist) * 100 if hist else 0.0,
        "profit_factor": sum(wins) / abs(sum(losses)) if losses and sum(losses) else (float("inf") if wins else 0.0),
        "avg_win": sum(wins) / len(wins) if wins else 0.0, "avg_loss": sum(losses) / len(losses) if losses else 0.0,
        "max_drawdown": max_dd,
    }
