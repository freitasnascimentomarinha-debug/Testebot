"""Carteira simulada (paper trading) com preços reais.

Dois modos (escolhidos na página Carteira):

* **Carteira única** — uma banca compartilhada pelos três bots e pelas suas
  ordens manuais, como uma conta real. Cada operação registra o bot de origem.
* **Separada por bot** — cada bot tem a sua subconta, para comparar
  estratégias de forma independente.

Tudo o que mexe no saldo entra no **extrato** (aportes, retiradas, taxas,
resultados, financiamento dos futuros e liquidações), e a curva de patrimônio
é atualizada continuamente. A interface pública (``place_order``,
``close_position``, ``cancel_order``, ``sync``) é a mesma que o executor real
da Binance deverá implementar (ver ``core/broker.py``).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pandas as pd

from core import leverage as lev_rules
from core.storage import load_json, locked_update

ACCOUNT_FILE = "paper_accounts.json"
WALLET_FILE = "wallet.json"
SHARED_ACCOUNT = "carteira"
INITIAL_BALANCE = 1_000.0
FUNDING_HOURS = 8  # financiamento dos perpétuos a cada 8 h (00, 08 e 16 UTC)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ----------------------------------------------------------- configuração
def wallet_config() -> dict:
    cfg = load_json(WALLET_FILE, {}) or {}
    return {"mode": cfg.get("mode", "única")}


def set_wallet_mode(mode: str) -> None:
    def _apply(data):
        data["mode"] = mode

    locked_update(WALLET_FILE, {}, _apply)


def account_id(bot: str) -> str:
    return SHARED_ACCOUNT if wallet_config()["mode"] == "única" else bot


# ----------------------------------------------------------------- conta
def _new_account(initial: float = INITIAL_BALANCE) -> dict:
    now = _now()
    return {"initial": initial, "balance": initial, "positions": [], "orders": [], "history": [],
            "cashflows": [], "ledger": [{"time": now, "type": "Depósito inicial", "bot": "", "symbol": "",
                                         "amount": initial, "bank": initial, "detail": ""}],
            "equity_curve": [{"time": now, "equity": initial}], "created": now}


def _account(data: dict, acc: str) -> dict:
    if acc not in data:
        data[acc] = _new_account()
    acct = data[acc]
    acct.setdefault("cashflows", [])
    acct.setdefault("ledger", [])
    return acct


def _bank(acct: dict) -> float:
    """Banca realizada: saldo livre + margens em uso (sem o P&L em aberto)."""
    return acct["balance"] + sum(p["margin"] for p in acct["positions"])


def _log(acct: dict, kind: str, amount: float, *, bot: str = "", symbol: str = "", detail: str = "") -> None:
    acct["ledger"].append({"time": _now(), "type": kind, "bot": bot, "symbol": symbol, "amount": amount,
                           "bank": _bank(acct), "detail": detail})
    del acct["ledger"][:-5000]


def _loss_cap(acct: dict, pos: dict) -> float:
    """Perda máxima: a margem (isolada) ou margem + saldo livre (cruzada)."""
    return pos["margin"] + (max(acct["balance"], 0.0) if pos.get("margin_mode") == "Cruzada" else 0.0)


def _pnl(pos: dict, price: float) -> float:
    sign = 1 if pos["side"] == "BUY" else -1
    return sign * (price - pos["entry"]) * pos["qty"]


def get_account(acc: str) -> dict:
    data = load_json(ACCOUNT_FILE, {}) or {}
    acct = data.get(acc) or _new_account()
    acct.setdefault("cashflows", [])
    acct.setdefault("ledger", [])
    return acct


def reset_account(acc: str, initial: float = INITIAL_BALANCE) -> None:
    def _apply(data):
        data[acc] = _new_account(initial)

    locked_update(ACCOUNT_FILE, {}, _apply)


def cash_movement(acc: str, amount: float, note: str = "") -> None:
    """Aporte (valor positivo) ou retirada (valor negativo) na banca."""
    def _apply(data):
        acct = _account(data, acc)
        if amount < 0 and -amount > acct["balance"] + 1e-9:
            raise ValueError(f"Retirada maior que o saldo livre ({acct['balance']:,.2f} USDT).")
        acct["balance"] += amount
        acct["cashflows"].append({"time": _now(), "amount": amount, "note": note})
        _log(acct, "Aporte" if amount > 0 else "Retirada", amount, detail=note)
        acct["equity_curve"].append({"time": _now(), "equity": equity_of(acct, {})})

    locked_update(ACCOUNT_FILE, {}, _apply)


# ---------------------------------------------------------------- ordens
def _open_position(acct: dict, order: dict, fill_price: float, fee_pct: float) -> dict:
    notional = fill_price * order["qty"]
    fee = notional * fee_pct / 100
    margin = notional / order["leverage"]
    if margin + fee > acct["balance"] + 1e-9:
        raise ValueError(f"Saldo insuficiente: margem {margin:,.2f} + taxa {fee:,.2f} > saldo livre "
                         f"{acct['balance']:,.2f} USDT")
    liq = lev_rules.liquidation_price(
        side=order["side"], entry=fill_price, qty=order["qty"], leverage=order["leverage"], market=order["market"],
        symbol=order["symbol"], margin_mode=order.get("margin_mode", "Isolada"),
        free_balance=acct["balance"] - margin - fee)
    acct["balance"] -= margin + fee
    pos = {
        "id": uuid.uuid4().hex[:8], "bot": order.get("bot", ""), "symbol": order["symbol"], "market": order["market"],
        "side": order["side"], "qty": order["qty"], "entry": fill_price, "leverage": order["leverage"],
        "margin_mode": order.get("margin_mode", "Isolada"), "margin": margin,
        "stop_loss": order.get("stop_loss"), "take_profit": order.get("take_profit"), "liquidation": liq,
        "fee_pct": fee_pct, "fees_paid": fee, "funding_paid": 0.0, "opened": _now(), "last_check": _now(),
        "last_funding": _now(), "source": order.get("source", "manual"), "note": order.get("note", ""),
        "max_loss_planned": order.get("max_loss_planned"),
        "personality": (order.get("personality") or {}).get("id"),
        "personality_name": (order.get("personality") or {}).get("name"),
    }
    acct["positions"].append(pos)
    _log(acct, "Taxa de abertura", -fee, bot=pos["bot"], symbol=pos["symbol"],
         detail=f"{'Compra' if pos['side'] == 'BUY' else 'Venda'} {pos['qty']:g} @ {fill_price:.6g} · {pos['leverage']:g}×")
    return pos


def place_order(acc: str, *, symbol: str, market: str, side: str, qty: float, order_type: str = "MARKET",
                price: float, limit_price: float | None = None, stop_loss: float | None = None,
                take_profit: float | None = None, leverage: float = 1.0, fee_pct: float = 0.1,
                slippage_pct: float = 0.0, source: str = "manual", note: str = "",
                max_loss_planned: float | None = None, bot: str = "", margin_mode: str = "Isolada",
                personality: dict | None = None) -> dict:
    """Envia uma ordem simulada. ``price`` é o último preço real de mercado."""
    if qty <= 0:
        raise ValueError("Quantidade deve ser maior que zero.")
    order = {"id": uuid.uuid4().hex[:8], "bot": bot, "symbol": symbol, "market": market, "side": side, "qty": qty,
             "type": order_type, "limit_price": limit_price, "stop_loss": stop_loss, "take_profit": take_profit,
             "leverage": max(1.0, float(leverage)), "margin_mode": margin_mode, "fee_pct": fee_pct,
             "created": _now(), "source": source, "note": note, "max_loss_planned": max_loss_planned,
             "personality": personality}

    def _apply(data):
        acct = _account(data, acc)
        if order_type == "LIMIT" and limit_price:
            if limit_price * qty / order["leverage"] > acct["balance"]:
                raise ValueError("Saldo insuficiente para a ordem limitada.")
            acct["orders"].append(order)
            return {"status": "PENDENTE", "order": order}
        slip = price * slippage_pct / 100 * (1 if side == "BUY" else -1)
        return {"status": "EXECUTADA", "position": _open_position(acct, order, price + slip, fee_pct)}

    return locked_update(ACCOUNT_FILE, {}, _apply)


def _close(acct: dict, pos: dict, price: float, reason: str) -> dict:
    fee = price * pos["qty"] * pos["fee_pct"] / 100
    gross = max(_pnl(pos, price), -_loss_cap(acct, pos))
    if reason == "Liquidação":  # perde a margem isolada (ou o que restar da cruzada)
        fee = 0.0
        gross = -_loss_cap(acct, pos)
    acct["balance"] += pos["margin"] + gross - fee
    acct["positions"] = [p for p in acct["positions"] if p["id"] != pos["id"]]
    net = gross - fee - pos["fees_paid"] - pos.get("funding_paid", 0.0)
    trade = {**pos, "exit": price, "closed": _now(), "reason": reason, "gross_pnl": gross,
             "fees_total": fee + pos["fees_paid"], "pnl": net,
             "pnl_pct_margin": net / pos["margin"] * 100 if pos["margin"] else 0.0}
    acct["history"].append(trade)
    _log(acct, f"Resultado ({reason})", gross - fee, bot=pos["bot"], symbol=pos["symbol"],
         detail=f"Saída @ {price:.6g} · líquido da operação {net:+.2f}")
    return trade


def close_position(acc: str, position_id: str, price: float, reason: str = "Manual") -> dict | None:
    def _apply(data):
        acct = _account(data, acc)
        pos = next((p for p in acct["positions"] if p["id"] == position_id), None)
        return _close(acct, pos, price, reason) if pos else None

    return locked_update(ACCOUNT_FILE, {}, _apply)


def cancel_order(acc: str, order_id: str) -> None:
    def _apply(data):
        acct = _account(data, acc)
        acct["orders"] = [o for o in acct["orders"] if o["id"] != order_id]

    locked_update(ACCOUNT_FILE, {}, _apply)


def update_protection(acc: str, position_id: str, stop_loss: float | None, take_profit: float | None) -> None:
    def _apply(data):
        for p in _account(data, acc)["positions"]:
            if p["id"] == position_id:
                p["stop_loss"], p["take_profit"] = stop_loss, take_profit

    locked_update(ACCOUNT_FILE, {}, _apply)


def _funding_events(since: pd.Timestamp, until: pd.Timestamp) -> int:
    """Quantos horários de financiamento (00/08/16 UTC) passaram no intervalo."""
    step = pd.Timedelta(hours=FUNDING_HOURS)
    first = since.floor(f"{FUNDING_HOURS}h") + step
    return 0 if first > until else int((until - first) // step) + 1


def sync(acc: str, symbol: str, candles: pd.DataFrame, last_price: float,
         funding_rate_pct: float | None = None) -> list[dict]:
    """Processa ordens limitadas, stops, alvos, liquidações e financiamento,
    usando as máximas e mínimas reais dos candles desde a última verificação.
    Quando stop e alvo cabem no mesmo candle, assume-se o stop (premissa
    conservadora). Devolve a lista de eventos ocorridos."""
    events: list[dict] = []

    def _apply(data):
        acct = _account(data, acc)
        now = pd.Timestamp(_now())
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
            # Financiamento dos perpétuos: comprado paga taxa positiva, vendido recebe
            if pos["market"] == "futures" and funding_rate_pct is not None:
                n = _funding_events(pd.Timestamp(pos.get("last_funding", pos["opened"])), now)
                if n:
                    sign = 1 if pos["side"] == "BUY" else -1
                    cost = n * sign * last_price * pos["qty"] * funding_rate_pct / 100
                    acct["balance"] -= cost
                    pos["funding_paid"] = pos.get("funding_paid", 0.0) + cost
                    pos["last_funding"] = _now()
                    _log(acct, "Financiamento (funding)", -cost, bot=pos.get("bot", ""), symbol=symbol,
                         detail=f"{n}× taxa {funding_rate_pct:+.4f}%")
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
        if not curve or (now - pd.Timestamp(curve[-1]["time"])).total_seconds() >= 300 or events:
            curve.append({"time": _now(), "equity": equity})
            del curve[:-5000]

    locked_update(ACCOUNT_FILE, {}, _apply)
    return events


# ------------------------------------------------------------ indicadores
def equity_of(acct: dict, prices: dict[str, float]) -> float:
    eq = acct["balance"]
    for p in acct["positions"]:
        price = prices.get(p["symbol"], p["entry"])
        eq += p["margin"] + max(_pnl(p, price), -_loss_cap(acct, p))
    return eq


def invested(acct: dict) -> float:
    """Capital colocado: depósito inicial + aportes − retiradas."""
    return acct["initial"] + sum(c["amount"] for c in acct.get("cashflows", []))


def stats(acct: dict, prices: dict[str, float], bot: str | None = None, origin: str = "all") -> dict:
    """Indicadores de desempenho. Com ``bot``, as contagens (operações do dia,
    posições abertas, acerto) consideram só as operações feitas na página desse
    bot; ``origin`` filtra por quem decidiu ("bot" = IA/regras, "manual" = você,
    "all" = ambos). A banca (patrimônio e saldo livre) é sempre a da carteira."""
    def mine(x):
        if bot and x.get("bot", bot) != bot:
            return False
        manual = x.get("source") == "manual"
        return origin == "all" or (origin == "manual") == manual
    today = datetime.now(timezone.utc).date().isoformat()
    hist = [t for t in acct["history"] if mine(t)]
    positions = [p for p in acct["positions"] if mine(p)]
    closed_today = [t for t in hist if t["closed"][:10] == today]
    opened_today = [t for t in hist if t["opened"][:10] == today] + [p for p in positions if p["opened"][:10] == today]
    wins = [t["pnl"] for t in hist if t["pnl"] > 0]
    losses = [t["pnl"] for t in hist if t["pnl"] <= 0]

    def price_of(p):
        return prices.get(p["symbol"], p["entry"])

    unrealized = sum(max(_pnl(p, price_of(p)), -p["margin"]) for p in positions)
    unrealized_net = sum(max(_pnl(p, price_of(p)), -p["margin"]) - p["fees_paid"] - p.get("funding_paid", 0.0)
                         - price_of(p) * p["qty"] * p["fee_pct"] / 100 for p in positions)
    equity = equity_of(acct, prices)
    base = invested(acct)
    curve = [c["equity"] for c in acct["equity_curve"]] + [equity]
    peak, max_dd = curve[0], 0.0
    for v in curve:
        peak = max(peak, v)
        max_dd = max(max_dd, (peak - v) / peak * 100 if peak else 0)
    return {
        "equity": equity, "available": acct["balance"], "in_margin": sum(p["margin"] for p in acct["positions"]),
        "invested": base, "unrealized": unrealized, "unrealized_net": unrealized_net,
        "total_pnl": equity - base, "total_pnl_pct": (equity / base - 1) * 100 if base else 0.0,
        "pnl_today": sum(t["pnl"] for t in closed_today), "trades_today": len(opened_today),
        "open_positions": len(positions), "trades": len(hist),
        "win_rate": len(wins) / len(hist) * 100 if hist else 0.0,
        "profit_factor": sum(wins) / abs(sum(losses)) if losses and sum(losses) else (float("inf") if wins else 0.0),
        "avg_win": sum(wins) / len(wins) if wins else 0.0, "avg_loss": sum(losses) / len(losses) if losses else 0.0,
        "max_drawdown": max_dd,
    }
