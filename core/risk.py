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
              margin_mode: str = "Isolada") -> TradeCalc:
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
    if symbol and market == "futures" and lev > 1:
        cap = lev_rules.max_notional(symbol, lev)
        if cap and qty * entry > cap:
            warnings.append(f"Pela tabela da Binance, com {lev:g}× a posição máxima em {symbol} é "
                            f"{cap:,.0f} USDT — quantidade reduzida.")
            qty = cap / entry
    qty = round_qty(qty, entry)

    notional = qty * entry
    margin = notional / lev
    fees_open = notional * fee
    risk = qty * stop_dist + fees_open + qty * stop * fee if stop_dist else float("nan")
    reward = (qty * abs(take_profit - entry) - fees_open - qty * take_profit * fee) if take_profit else float("nan")
    rr = reward / risk if stop_dist and take_profit and risk > 0 else None
    breakeven = entry * (1 + sign * 2 * fee)
    if symbol:
        free = (available - margin - fees_open) if available is not None else 0.0
        liq = lev_rules.liquidation_price(side=side, entry=entry, qty=qty, leverage=lev, market=market,
                                          symbol=symbol, margin_mode=margin_mode, free_balance=free)
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
        warnings=warnings,
    )


# O que conta nos limites (configurável por bot em "Metas de operação")
TRADES_SCOPES = {
    "bot": "Só as operações do bot",
    "pagina": "Bot + minhas ordens nesta página",
}
PNL_SCOPES = {
    "bot": "Só as operações do bot",
    "pagina": "Bot + minhas ordens nesta página",
    "carteira": "Carteira inteira — todos os bots + minhas ordens",
}
MANUAL_MODES = {
    "livre": "Livres — os limites só geram aviso",
    "pnl": "Respeitam a meta de lucro e o limite de perda do dia",
    "todos": "Respeitam todos os limites (como o bot)",
}
# Categorias de bloqueio que valem para as ordens manuais em cada modo
MANUAL_BLOCKS = {"livre": {"regra"}, "pnl": {"regra", "pnl"}, "todos": {"regra", "pnl", "operacoes", "rr"}}


@dataclass
class RiskCheck:
    allowed: bool
    reasons: list[str]
    calc: TradeCalc | None = None
    kinds: list[str] = field(default_factory=list)  # categoria de cada motivo

    def add(self, kind: str, reason: str) -> None:
        self.reasons.append(reason)
        self.kinds.append(kind)
        self.allowed = False

    def blocking(self, kinds: set[str]) -> list[str]:
        return [r for r, k in zip(self.reasons, self.kinds) if k in kinds]

    def warnings(self, kinds: set[str]) -> list[str]:
        return [r for r, k in zip(self.reasons, self.kinds) if k not in kinds]


def check_trade(cfg: dict, account_stats: dict, side: str, entry: float, stop: float | None,
                take_profit: float | None, market: str, trailing: bool = False) -> RiskCheck:
    """Aplica todas as regras do usuário antes de enviar uma ordem.

    Categorias dos motivos: ``regra`` (stop ausente, short não permitido,
    alavancagem/liquidação), ``operacoes`` (meta de operações e posições
    simultâneas), ``pnl`` (meta de lucro e limite de perda do dia) e ``rr``."""
    chk = RiskCheck(allowed=True, reasons=[])
    lev = effective_leverage(cfg)
    s = account_stats

    if side == "SELL" and market == "spot" and not cfg.get("leverage_on"):
        chk.add("regra", "Venda a descoberto no spot exige a opção de alavancagem/margem ligada.")
    if side == "SELL" and not cfg.get("allow_short", True):
        chk.add("regra", "Operações vendidas (short) estão desativadas nas configurações.")
    if not stop:
        chk.add("regra", "Toda ordem precisa de stop loss para respeitar a perda máxima por trade.")
    scope = s.get("scope_trades", "")
    if s["trades_today"] >= int(cfg["max_trades_day"]):
        chk.add("operacoes", f"Meta de operações do dia atingida ({s['trades_today']}/{cfg['max_trades_day']}{scope}).")
    if s["open_positions"] >= int(cfg["max_open_positions"]):
        chk.add("operacoes", f"Número máximo de posições abertas atingido ({cfg['max_open_positions']}{scope}).")
    scope = s.get("scope_pnl", "")
    if s["pnl_today"] >= float(cfg["daily_profit_target"]) > 0:
        chk.add("pnl", f"Meta de lucro diária atingida ({s['pnl_today']:,.2f} USDT{scope}). Pausado até amanhã (UTC).")
    if -s["pnl_today"] >= float(cfg["daily_max_loss"]) > 0:
        chk.add("pnl", f"Limite de perda diária atingido ({s['pnl_today']:,.2f} USDT{scope}). Pausado até amanhã (UTC).")

    budget = risk_budget(cfg, s["equity"])
    calc = calculate(side, entry, stop, take_profit, leverage=lev, fee_pct=float(cfg["fee_pct"]),
                     risk_usdt=budget, available=s["available"], symbol=cfg["symbol"], market=market,
                     margin_mode=cfg["margin_mode"]) if stop else None
    chk.calc = calc
    if calc:
        if calc.rr is not None and calc.rr < float(cfg["min_rr"]):
            chk.add("rr", f"Relação risco:retorno {calc.rr:.2f} abaixo do mínimo configurado ({cfg['min_rr']}).")
        if take_profit is None and not trailing:
            chk.add("rr", "Defina um alvo (take profit) para validar a relação risco:retorno.")
        for w in calc.warnings:
            if "reduzida" not in w:
                chk.add("regra", w)
    max_lev = lev_rules.max_leverage(cfg["symbol"], market, cfg["margin_mode"])
    if lev > max_lev:
        chk.add("regra", f"Alavancagem {lev:g}× acima do máximo permitido pela Binance para {cfg['symbol']} ({max_lev}×).")
    return chk
