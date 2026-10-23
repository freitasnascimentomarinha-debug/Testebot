"""Tendência do tempo gráfico maior (multi-timeframe).

Ex.: um bot de 15 minutos só compra quando o gráfico de 4 horas está comprador e só
vende quando está vendedor. Para não olhar o futuro, cada candle do tempo menor usa
apenas o último candle do tempo maior **já fechado** no momento em que ele fecha.

Direção do tempo maior (por candle fechado):
* comprador (+1): fechamento acima da EMA 50 e EMA 21 acima da EMA 50;
* vendedor  (−1): fechamento abaixo da EMA 50 e EMA 21 abaixo da EMA 50;
* lateral    (0): demais casos.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from core.indicators import ema

# Tempo maior usado para cada tempo de entrada
HTF_OF = {"1m": "15m", "3m": "1h", "5m": "1h", "15m": "4h", "30m": "4h", "1h": "4h", "2h": "1d", "4h": "1d",
          "6h": "1d", "12h": "1w", "1d": "1w"}
SECONDS = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400,
           "6h": 21600, "12h": 43200, "1d": 86400, "3d": 259200, "1w": 604800}
CANDLES_NEEDED = 120  # candles do tempo maior para as médias estabilizarem


def htf_candles(ltf_interval: str, ltf_candles: int) -> int:
    """Quantos candles do tempo maior cobrem o mesmo período (+ aquecimento)."""
    htf = HTF_OF[ltf_interval]
    return int(ltf_candles * SECONDS[ltf_interval] / SECONDS[htf]) + CANDLES_NEEDED


def direction(htf_df: pd.DataFrame) -> pd.Series:
    c = htf_df["close"]
    e21, e50 = ema(c, 21), ema(c, 50)
    up = (c > e50) & (e21 > e50)
    down = (c < e50) & (e21 < e50)
    out = pd.Series(np.where(up, 1, np.where(down, -1, 0)), index=htf_df.index, dtype=float)
    out.iloc[:50] = 0.0  # médias ainda instáveis
    return out


def attach(df: pd.DataFrame, htf_raw: pd.DataFrame, ltf_interval: str) -> pd.DataFrame:
    """Adiciona a coluna ``htf_dir`` ao DataFrame do tempo menor (alinhamento causal)."""
    htf = HTF_OF[ltf_interval]
    h = htf_raw[["time", "close"]].copy().sort_values("time").reset_index(drop=True)
    h["htf_dir"] = direction(h)
    h["close_time"] = h["time"] + pd.Timedelta(seconds=SECONDS[htf])
    left = pd.DataFrame({"close_time": df["time"] + pd.Timedelta(seconds=SECONDS[ltf_interval]),
                         "_i": np.arange(len(df))})
    merged = pd.merge_asof(left.sort_values("close_time"), h[["close_time", "htf_dir"]].sort_values("close_time"),
                           on="close_time", direction="backward").sort_values("_i")
    out = df.copy()
    out["htf_dir"] = merged["htf_dir"].fillna(0.0).to_numpy()
    return out
