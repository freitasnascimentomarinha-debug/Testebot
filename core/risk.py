"""Calculadora de trade e gestor de risco.

Tudo é calculado em USDT. O mesmo modelo serve para spot (alavancagem 1x =
margem igual ao valor nocional) e para futuros/margem (margem = nocional ÷
alavancagem).
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

MAINT_MARGIN_RATE = 0.004  # taxa de manutenção típica dos perpétuos (faixa inicial)


@dataclass
class TradeCalc:
    side: str
    entry: float
    stop: float | None
    take_profit: float | None
    qty: float
    notional: float
    margin: float
    leverage: float
    risk_usdt: float          # perda se o stop for atingido (inclui taxas)
    reward_usdt: float        # ganho se o alvo for atingido (líquido de taxas)
    rr: float | None
    fees_usdt: float
    breakeven: float
    liquidation: float | None
    stop_pct: float | None
    tp_pct: float | None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def round_qty(qty: float, price: float) -> float:
    """Arredonda a quantidade para um passo coerente com o preço do ativo."""
    if qty <= 0 or price <= 0:
        return 0.0
    decimals = max(0, min(8, int(math.ceil(math.log10(price))) + 1))
    factor = 10 ** decimals
    return math.floor(qty * factor) / factor


def round_price(value: float, ref: float) -> float:
    if value is None:
        return None
    decimals = max(2, 6 - int(math.floor(math.log10(abs(ref)))) if ref else 2)
    return round(value, min(decimals, 8))


def liquidation_price(side: str, entry: float, leverage: float, mmr: float = MAINT_MARGIN_RATE) -> float | None:
    """Estimativa de liquidação em margem isolada."""
    if leverage <= 1:
        return None if side == "BUY" else entry * (2 - mmr)  # venda a descoberto 1x
    if side == "BUY":
        return entry * (1 - 1 / leverage + mmr)
    return entry * (1 + 1 / leverage - mmr)


def risk_budget(cfg: dict, equity: float) -> float:
    if cfg.get("risk_mode") == "% do saldo":
        return max(0.0, equity * float(cfg["max_loss_pct"]) / 100)
    return float(cfg["max_loss_usdt"])


def effective_leverage(cfg: dict) -> float:
    return float(cfg["leverage"]) if cfg.get("leverage_on") else 1.0


def calculate(side: str, entry: float, stop: float | None, take_profit: float | None, *,
              leverage: float = 1.0, fee_pct: float = 0.1, qty: float | None = None,
              risk_usdt: float | None = None, margin_usdt: float | None = None,
              available: float | None = None) -> TradeCalc:
    """Dimensiona a posição.

    Prioridade do tamanho: ``qty`` explícita → ``risk_usdt`` (perda máxima,
    exige stop) → ``margin_usdt`` (valor a alocar).
    """
    warnings: list[str] = []
    fee = fee_pct / 100
    sign = 1 if side == "BUY" else -1
    lev = max(1.0, float(leverage))
    stop_dist = abs(entry - stop) if stop else None

    if stop and ((side == "BUY" and stop >= entry) or (side == "SELL" and stop <= entry)):
        warnings.append("O stop está do lado errado do preço de entrada.")
        stop_dist = None
    if take_profit and ((side == "BUY" and take_profit <= entry) or (side == "SELL" and take_profit >= entry)):
        warnings.append("O alvo está do lado errado do preço de entrada.")

    if qty is None:
        if risk_usdt and stop_dist:
            per_unit_loss = stop_dist + fee * (entry + stop)
            qty = risk_usdt / per_unit_loss
        elif margin_usdt:
            qty = margin_usdt * lev / entry
        else:
            qty = 0.0
    if available is not None and qty * entry / lev * (1 + fee * lev) > available:
        max_qty = available / (entry / lev + fee * entry)
        warnings.append(f"Quantidade reduzida pelo saldo disponível ({available:,.2f} USDT).")
        qty = max_qty
    qty = round_qty(qty, entry)

    notional = qty * entry
    margin = notional / lev
    fees_open = notional * fee
    risk = qty * stop_dist + fees_open + qty * stop * fee if stop_dist else float("nan")
    reward = (qty * abs(take_profit - entry) - fees_open - qty * take_profit * fee) if take_profit else float("nan")
    rr = reward / risk if stop_dist and take_profit and risk > 0 else None
    breakeven = entry * (1 + sign * 2 * fee)
    liq = liquidation_price(side, entry, lev) if lev > 1 or side == "SELL" else None

    if liq and stop and ((side == "BUY" and stop <= liq) or (side == "SELL" and stop >= liq)):
        warnings.append(f"O stop está além do preço de liquidação estimado ({liq:,.4f}). Reduza a alavancagem.")
    if qty <= 0:
        warnings.append("Quantidade resultante igual a zero — ajuste risco, stop ou saldo.")

    return TradeCalc(
        side=side, entry=entry, stop=stop, take_profit=take_profit, qty=qty, notional=notional,
        margin=margin, leverage=lev, risk_usdt=risk, reward_usdt=reward, rr=rr,
        fees_usdt=fees_open * 2, breakeven=breakeven, liquidation=liq,
        stop_pct=(stop_dist / entry * 100) if stop_dist else None,
        tp_pct=(abs(take_profit - entry) / entry * 100) if take_profit else None,
        warnings=warnings,
    )


@dataclass
class RiskCheck:
    allowed: bool
    reasons: list[str]
    calc: TradeCalc | None = None


def check_trade(cfg: dict, account_stats: dict, side: str, entry: float, stop: float | None,
                take_profit: float | None, market: str) -> RiskCheck:
    """Aplica todas as regras do usuário antes de enviar uma ordem."""
    reasons: list[str] = []
    lev = effective_leverage(cfg)

    if side == "SELL" and market == "spot" and not cfg.get("leverage_on"):
        reasons.append("Venda a descoberto no spot exige a opção de alavancagem/margem ligada.")
    if side == "SELL" and not cfg.get("allow_short", True):
        reasons.append("Operações vendidas (short) estão desativadas nas configurações.")
    if not stop:
        reasons.append("Toda ordem precisa de stop loss para respeitar a perda máxima por trade.")
    if account_stats["trades_today"] >= int(cfg["max_trades_day"]):
        reasons.append(f"Meta de operações do dia atingida ({account_stats['trades_today']}/{cfg['max_trades_day']}).")
    if account_stats["pnl_today"] >= float(cfg["daily_profit_target"]) > 0:
        reasons.append(f"Meta de lucro diária atingida ({account_stats['pnl_today']:,.2f} USDT). Bot pausado até amanhã.")
    if -account_stats["pnl_today"] >= float(cfg["daily_max_loss"]) > 0:
        reasons.append(f"Limite de perda diária atingido ({account_stats['pnl_today']:,.2f} USDT). Bot pausado até amanhã.")
    if account_stats["open_positions"] >= int(cfg["max_open_positions"]):
        reasons.append(f"Número máximo de posições abertas atingido ({cfg['max_open_positions']}).")

    budget = risk_budget(cfg, account_stats["equity"])
    calc = calculate(side, entry, stop, take_profit, leverage=lev, fee_pct=float(cfg["fee_pct"]),
                     risk_usdt=budget, available=account_stats["available"]) if stop else None
    if calc:
        if calc.rr is not None and calc.rr < float(cfg["min_rr"]):
            reasons.append(f"Relação risco:retorno {calc.rr:.2f} abaixo do mínimo configurado ({cfg['min_rr']}).")
        if take_profit is None:
            reasons.append("Defina um alvo (take profit) para validar a relação risco:retorno.")
        reasons.extend(w for w in calc.warnings if "reduzida" not in w)
    return RiskCheck(allowed=not reasons, reasons=reasons, calc=calc)
