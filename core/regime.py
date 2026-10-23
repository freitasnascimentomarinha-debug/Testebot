"""Contexto do gráfico (regime de mercado) candle a candle.

Classifica cada candle fechado em um contexto **somente quando há sinal claro**;
caso contrário, "indefinido". Usa apenas dados passados (causal), então serve
tanto para o gráfico ao vivo quanto para backtests.

Prioridade quando mais de um sinal aparece: rompimento → reversão → pullback →
tendência → lateral.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

REGIMES: dict[str, tuple[str, str]] = {
    "rompimento_alta": ("🚀 Rompimento de alta", "Fechou acima da máxima de 20 candles com volume ≥ 1,5× a média."),
    "rompimento_baixa": ("💥 Rompimento de baixa", "Fechou abaixo da mínima de 20 candles com volume ≥ 1,5× a média."),
    "reversao_alta": ("🔄 Reversão para alta (fundo)", "RSI ≤ 30 com o preço tocando a banda inferior de Bollinger."),
    "reversao_baixa": ("🔃 Reversão para baixa (topo)", "RSI ≥ 70 com o preço tocando a banda superior de Bollinger."),
    "pullback_alta": ("↩️ Pullback em tendência de alta", "Tendência de alta (EMA lenta > EMA 200) com recuo abaixo da EMA rápida e RSI 35–55."),
    "pullback_baixa": ("↪️ Pullback em tendência de baixa", "Tendência de baixa (EMA lenta < EMA 200) com repique acima da EMA rápida e RSI 45–65."),
    "tendencia_alta": ("📈 Tendência de alta", "ADX ≥ 25, +DI > −DI e preço > EMA lenta > EMA 200."),
    "tendencia_baixa": ("📉 Tendência de baixa", "ADX ≥ 25, −DI > +DI e preço < EMA lenta < EMA 200."),
    "lateral": ("↔️ Lateralidade", "ADX < 18 e Bandas de Bollinger mais estreitas que o normal."),
    "indefinido": ("❔ Sem sinal claro", "Nenhum dos contextos acima com sinal claro."),
}
ORDER = list(REGIMES)


def label(key: str) -> str:
    return REGIMES.get(key, (key, ""))[0]


def classify(df: pd.DataFrame) -> pd.Series:
    """Série com a chave do contexto de cada candle (requer as colunas de ``indicators.compute``)."""
    c, h, l = df["close"], df["high"], df["low"]
    ef, es, et = df["ema_fast"], df["ema_slow"], df["ema_trend"]
    adx, dip, dim, rsi = df["adx"], df["di_plus"], df["di_minus"], df["rsi"]
    width = (df["bb_up"] - df["bb_low"]) / df["bb_mid"]
    width_med = width.rolling(100, min_periods=30).median()
    don_hi = h.shift(1).rolling(20).max()
    don_lo = l.shift(1).rolling(20).min()
    vol_spike = df["volume"] > 1.5 * df["vol_sma"]

    conds = [
        ("rompimento_alta", (c > don_hi) & vol_spike),
        ("rompimento_baixa", (c < don_lo) & vol_spike),
        ("reversao_alta", (rsi <= 30) & (l <= df["bb_low"])),
        ("reversao_baixa", (rsi >= 70) & (h >= df["bb_up"])),
        ("pullback_alta", (es > et) & (c > et) & (c < ef) & rsi.between(35, 55)),
        ("pullback_baixa", (es < et) & (c < et) & (c > ef) & rsi.between(45, 65)),
        ("tendencia_alta", (adx >= 25) & (dip > dim) & (c > es) & (es > et)),
        ("tendencia_baixa", (adx >= 25) & (dim > dip) & (c < es) & (es < et)),
        ("lateral", (adx < 18) & (width < width_med)),
    ]
    out = np.full(len(df), "indefinido", dtype=object)
    assigned = np.zeros(len(df), dtype=bool)
    for key, cond in conds:
        m = cond.fillna(False).to_numpy() & ~assigned
        out[m] = key
        assigned |= m
    return pd.Series(out, index=df.index)
