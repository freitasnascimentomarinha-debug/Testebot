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
HTF_OF = {"1m": "15m", "3m": "1h", "5m": "4h", "15m": "4h", "30m": "4h", "1h": "4h", "2h": "1d", "4h": "1d",
          "6h": "1d", "12h": "1w", "1d": "1w"}
# Tempo intermediário (3ª camada: ex. 4h → 15m → entrada no 5m)
MTF_OF = {"1m": "5m", "3m": "15m", "5m": "15m"}
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


def _aligned(df: pd.DataFrame, raw: pd.DataFrame, raw_interval: str, ltf_interval: str) -> np.ndarray:
    h = raw[["time", "close"]].copy().sort_values("time").reset_index(drop=True)
    h["dir"] = direction(h)
    h["close_time"] = h["time"] + pd.Timedelta(seconds=SECONDS[raw_interval])
    left = pd.DataFrame({"close_time": df["time"] + pd.Timedelta(seconds=SECONDS[ltf_interval]),
                         "_i": np.arange(len(df))})
    merged = pd.merge_asof(left.sort_values("close_time"), h[["close_time", "dir"]].sort_values("close_time"),
                           on="close_time", direction="backward").sort_values("_i")
    return merged["dir"].fillna(0.0).to_numpy()


def attach(df: pd.DataFrame, htf_raw: pd.DataFrame | None, ltf_interval: str,
           mtf_raw: pd.DataFrame | None = None) -> pd.DataFrame:
    """Adiciona ``htf_dir`` (tempo maior) e ``mtf_dir`` (tempo intermediário) ao DataFrame do tempo menor
    (alinhamento causal)."""
    out = df.copy()
    if htf_raw is not None and len(htf_raw):
        out["htf_dir"] = _aligned(df, htf_raw, HTF_OF[ltf_interval], ltf_interval)
    if mtf_raw is not None and len(mtf_raw) and ltf_interval in MTF_OF:
        out["mtf_dir"] = _aligned(df, mtf_raw, MTF_OF[ltf_interval], ltf_interval)
    return out


def needs(filters: dict | None) -> tuple[bool, bool]:
    """(precisa do tempo maior, precisa do tempo intermediário) conforme os filtros da personalidade."""
    f = filters or {}
    return bool(f.get("htf_trend")), bool(f.get("mtf_trend"))


def frames(getter, symbol: str, interval: str, n: int, market: str, filters: dict | None):
    """Baixa os candles dos tempos maiores exigidos pelos filtros: (htf_raw, mtf_raw)."""
    want_h, want_m = needs(filters)
    h = getter(symbol, HTF_OF[interval], htf_candles(interval, n), market) if want_h and interval in HTF_OF else None
    m = (getter(symbol, MTF_OF[interval], int(n * SECONDS[interval] / SECONDS[MTF_OF[interval]]) + CANDLES_NEEDED, market)
         if want_m and interval in MTF_OF else None)
    return h, m
