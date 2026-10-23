"""Saída "surfar a tendência": só stop, sem alvo.

O stop acompanha o preço a uma distância fixa (``trail_atr`` × ATR da entrada) e, opcionalmente, vai para o
ponto de equilíbrio (entrada + taxas) depois de ``be_r`` × o risco inicial a favor. Nunca se afasta do preço.
O mesmo cálculo é usado pelo backtest, pela simulação rápida e pela corretora simulada."""
from __future__ import annotations


def step(side: int, entry: float, stop: float, best: float, hi: float, lo: float, dist: float, risk: float,
         be_r: float, fee: float) -> tuple[float, float]:
    """Atualiza (stop, melhor preço) ao fim de um candle em que o stop não foi atingido.

    ``side`` = +1 comprado / −1 vendido; ``fee`` em fração (0,0005 = 0,05%) por lado."""
    best = max(best, hi) if side == 1 else min(best, lo)
    cand = best - side * dist
    if be_r and side * (best - entry) >= be_r * risk:
        be = entry * (1 + side * 2 * fee)
        cand = max(cand, be) if side == 1 else min(cand, be)
    return (max(stop, cand) if side == 1 else min(stop, cand)), best
