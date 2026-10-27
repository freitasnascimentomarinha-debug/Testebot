"""Calculadora de trade e gestor de risco.

Tudo é calculado em USDT. O mesmo modelo serve para spot (alavancagem 1x =
margem igual ao valor nocional) e para futuros/margem (margem = nocional ÷
alavancagem).
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

from core import leverage as lev_rules

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
    fx: float = 1.0           # conversão da moeda de cotação (sempre 1: tudo em USDT)

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


# Valor mínimo (nocional) de uma ordem nos futuros USDT-M da Binance; as demais moedas aceitam 5 USDT
MIN_NOTIONAL = {"BTCUSDT": 100.0, "ETHUSDT": 20.0}


def risk_budget(cfg: dict, equity: float) -> float:
    if cfg.get("risk_mode") == "% do saldo":
        return max(0.0, equity * float(cfg["max_loss_pct"]) / 100)
    return float(cfg["max_loss_usdt"])


def effective_leverage(cfg: dict) -> float:
    return float(cfg["leverage"]) if cfg.get("leverage_on") else 1.0


def calculate(side: str, entry: float, stop: float | None, take_profit: float | None, *,
              leverage: float = 1.0, fee_pct: float = 0.1, qty: float | None = None,
              risk_usdt: float | None = None, margin_usdt: float | None = None,
              available: float | None = None, symbol: str | None = None, market: str = "futures",
              margin_mode: str = "Isolada", fx: float | None = None) -> TradeCalc:
    """Dimensiona a posição.

    Prioridade do tamanho: ``qty`` explícita → ``risk_usdt`` (perda máxima,
    exige stop) → ``margin_usdt`` (valor a alocar).
    """
    warnings: list[str] = []
    fx = 1.0
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
            per_unit_loss = (stop_dist + fee * (entry + stop)) * fx
            qty = risk_usdt / per_unit_loss
        elif margin_usdt:
            qty = margin_usdt * lev / (entry * fx)
        else:
            qty = 0.0
    if available is not None and qty * entry * fx / lev * (1 + fee * lev) > available:
        max_qty = available / ((entry / lev + fee * entry) * fx)
        warnings.append(f"Quantidade reduzida pelo saldo disponível ({available:,.2f} USDT).")
        qty = max_qty
    if symbol and market == "futures" and lev > 1:
        cap = lev_rules.max_notional(symbol, lev)
        if cap and qty * entry > cap:
            warnings.append(f"Pela tabela da Binance, com {lev:g}× a posição máxima em {symbol} é "
                            f"{cap:,.0f} USDT — quantidade reduzida.")
            qty = cap / entry
    qty = round_qty(qty, entry)

    notional = qty * entry * fx
    margin = notional / lev
    fees_open = notional * fee
    risk = qty * stop_dist * fx + fees_open + qty * stop * fx * fee if stop_dist else float("nan")
    reward = (qty * abs(take_profit - entry) * fx - fees_open - qty * take_profit * fx * fee) if take_profit else float("nan")
    rr = reward / risk if stop_dist and take_profit and risk > 0 else None
    breakeven = entry * (1 + sign * 2 * fee)
    if symbol:
        free = (available - margin - fees_open) if available is not None else 0.0
        liq = lev_rules.liquidation_price(side=side, entry=entry, qty=qty, leverage=lev, market=market,
                                          symbol=symbol, margin_mode=margin_mode, free_balance=free, fx=fx)
    else:
        liq = liquidation_price(side, entry, lev) if lev > 1 or side == "SELL" else None

    if liq and stop and ((side == "BUY" and stop <= liq) or (side == "SELL" and stop >= liq)):
        warnings.append(f"O stop está além do preço de liquidação estimado ({liq:,.4f}). Reduza a alavancagem.")
    if symbol and market == "futures" and 0 < qty * entry < MIN_NOTIONAL.get(symbol, 5.0):
        warnings.append(f"Posição de {qty * entry:,.2f} USDT abaixo do mínimo da Binance para {symbol} "
                        f"({MIN_NOTIONAL.get(symbol, 5.0):g} USDT): aumente o risco por trade ou a banca.")
    if qty <= 0:
        warnings.append("Quantidade resultante igual a zero — ajuste risco, stop ou saldo.")

    return TradeCalc(
        side=side, entry=entry, stop=stop, take_profit=take_profit, qty=qty, notional=notional,
        margin=margin, leverage=lev, risk_usdt=risk, reward_usdt=reward, rr=rr,
        fees_usdt=fees_open * 2, breakeven=breakeven, liquidation=liq,
        stop_pct=(stop_dist / entry * 100) if stop_dist else None,
        tp_pct=(abs(take_profit - entry) / entry * 100) if take_profit else None,
        warnings=warnings, fx=fx,
    )


@dataclass
class RiskCheck:
    """Validação da ordem. A plataforma NÃO bloqueia operações por metas, limites diários ou risco:retorno mínimo:
    só impede o que é impossível de enviar (sem stop para dimensionar, venda a descoberto sem margem, alavancagem
    acima do máximo da Binance ou quantidade zero). Avisos informativos ficam em ``notes``."""
    allowed: bool
    reasons: list[str]
    calc: TradeCalc | None = None
    notes: list[str] = field(default_factory=list)

    def add(self, reason: str) -> None:
        self.reasons.append(reason)
        self.allowed = False


LIQ_BUFFER = 1.25   # a liquidação fica pelo menos 25% mais longe que o stop


def safe_leverage(symbol: str, entry: float, stop: float, wanted: float) -> float:
    """Maior alavancagem (até ``wanted``) em que a liquidação, na margem isolada, fica além do stop com folga.

    A posição liquida quando a perda chega à margem menos a manutenção: distância ≈ 1/alavancagem − taxa de manutenção."""
    dist = abs(entry - stop) / entry
    if dist <= 0:
        return wanted
    try:
        mmr = lev_rules.brackets(symbol)[0][0].mmr
    except Exception:  # noqa: BLE001 - sem a tabela da Binance: manutenção típica
        mmr = 0.005
    cap = math.floor(1 / (dist * LIQ_BUFFER + mmr))
    return float(max(1, min(int(wanted), cap)))


def check_trade(cfg: dict, account_stats: dict, side: str, entry: float, stop: float | None,
                take_profit: float | None, market: str, trailing: bool = False) -> RiskCheck:
    """Dimensiona a ordem pela perda máxima por trade e valida só o que é tecnicamente impossível."""
    chk = RiskCheck(allowed=True, reasons=[])
    lev = effective_leverage(cfg)
    s = account_stats
    if market == "futures" and stop and lev > 1 and cfg.get("auto_leverage", True):
        safe = safe_leverage(cfg["symbol"], entry, stop, lev)
        if safe < lev:   # a perda continua sendo a definida pelo stop; só a margem usada aumenta
            chk.notes.append(f"Alavancagem ajustada de {lev:g}× para {safe:g}× para a liquidação ficar além do stop.")
            lev = safe

    if side == "SELL" and market == "spot" and not cfg.get("leverage_on"):
        chk.add("Venda a descoberto no spot exige a opção de alavancagem/margem ligada.")
    if side == "SELL" and not cfg.get("allow_short", True):
        chk.add("Operações vendidas (short) estão desativadas nas configurações.")
    if not stop:
        chk.add("A ordem precisa de stop loss para o tamanho da posição ser calculado pela perda máxima por trade.")

    budget = risk_budget(cfg, s["equity"])
    calc = calculate(side, entry, stop, take_profit, leverage=lev, fee_pct=float(cfg["fee_pct"]),
                     risk_usdt=budget, available=s["available"], symbol=cfg["symbol"], market=market,
                     margin_mode=cfg["margin_mode"]) if stop else None
    chk.calc = calc
    if calc:
        if calc.qty <= 0:
            chk.add("Quantidade resultante igual a zero — ajuste a perda máxima, o stop ou o saldo.")
        for w in calc.warnings:
            if "reduzida" in w or "Quantidade resultante" in w:
                chk.notes.append(w)
            else:
                chk.add(w)
    max_lev = lev_rules.max_leverage(cfg["symbol"], market, cfg["margin_mode"])
    if lev > max_lev:
        chk.add(f"Alavancagem {lev:g}× acima do máximo permitido pela Binance para {cfg['symbol']} ({max_lev}×).")
    return chk
