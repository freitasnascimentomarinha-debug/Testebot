"""Indicadores técnicos implementados em pandas puro (sem dependências extras)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()


def rma(s: pd.Series, n: int) -> pd.Series:
    """Média de Wilder (usada em RSI, ATR e ADX)."""
    return s.ewm(alpha=1 / n, adjust=False).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = rma(delta.clip(lower=0), n)
    loss = rma(-delta.clip(upper=0), n)
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(100.0).where(loss.notna())


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    line = ema(close, fast) - ema(close, slow)
    sig = ema(line, signal)
    return line, sig, line - sig


def bollinger(close: pd.Series, n: int = 20, k: float = 2.0):
    mid = sma(close, n)
    std = close.rolling(n).std(ddof=0)
    return mid + k * std, mid, mid - k * std


def true_range(df: pd.DataFrame) -> pd.Series:
    prev = df["close"].shift()
    return pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()], axis=1).max(axis=1)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return rma(true_range(df), n)


def stochastic(df: pd.DataFrame, k: int = 14, d: int = 3):
    low, high = df["low"].rolling(k).min(), df["high"].rolling(k).max()
    pct_k = 100 * (df["close"] - low) / (high - low).replace(0, np.nan)
    pct_k = pct_k.rolling(3).mean()
    return pct_k, pct_k.rolling(d).mean()


def adx(df: pd.DataFrame, n: int = 14):
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    tr = rma(true_range(df), n)
    plus_di = 100 * rma(plus_dm, n) / tr
    minus_di = 100 * rma(minus_dm, n) / tr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return rma(dx, n), plus_di, minus_di


def vwap(df: pd.DataFrame) -> pd.Series:
    """VWAP reiniciado a cada dia (UTC), como em day trade."""
    typical = (df["high"] + df["low"] + df["close"]) / 3
    day = df["time"].dt.floor("D")
    pv = (typical * df["volume"]).groupby(day).cumsum()
    vol = df["volume"].groupby(day).cumsum()
    return pv / vol.replace(0, np.nan)


def obv(df: pd.DataFrame) -> pd.Series:
    direction = np.sign(df["close"].diff()).fillna(0)
    return (direction * df["volume"]).cumsum()


def supertrend(df: pd.DataFrame, n: int = 10, mult: float = 3.0):
    """Retorna (linha, direção) — direção 1 = alta, -1 = baixa."""
    a = atr(df, n)
    hl2 = (df["high"] + df["low"]) / 2
    upper = (hl2 + mult * a).to_numpy()
    lower = (hl2 - mult * a).to_numpy()
    close = df["close"].to_numpy()
    final_up, final_low = upper.copy(), lower.copy()
    direction = np.ones(len(df))
    line = np.full(len(df), np.nan)
    for i in range(1, len(df)):
        final_up[i] = upper[i] if (upper[i] < final_up[i - 1] or close[i - 1] > final_up[i - 1]) else final_up[i - 1]
        final_low[i] = lower[i] if (lower[i] > final_low[i - 1] or close[i - 1] < final_low[i - 1]) else final_low[i - 1]
        if direction[i - 1] == -1 and close[i] > final_up[i - 1]:
            direction[i] = 1
        elif direction[i - 1] == 1 and close[i] < final_low[i - 1]:
            direction[i] = -1
        else:
            direction[i] = direction[i - 1]
        line[i] = final_low[i] if direction[i] == 1 else final_up[i]
    line[: n] = np.nan
    return pd.Series(line, index=df.index), pd.Series(direction, index=df.index)


def ichimoku(df: pd.DataFrame, tenkan: int = 9, kijun: int = 26, senkou: int = 52):
    mid = lambda n: (df["high"].rolling(n).max() + df["low"].rolling(n).min()) / 2  # noqa: E731
    t, k = mid(tenkan), mid(kijun)
    return t, k, ((t + k) / 2).shift(kijun), mid(senkou).shift(kijun)


def pivot_points(df: pd.DataFrame) -> dict:
    """Pivôs clássicos calculados com o dia (UTC) anterior completo."""
    daily = df.set_index("time").resample("1D").agg({"high": "max", "low": "min", "close": "last"}).dropna()
    if len(daily) < 2:
        return {}
    h, l, c = daily.iloc[-2][["high", "low", "close"]]
    p = (h + l + c) / 3
    return {"R3": h + 2 * (p - l), "R2": p + (h - l), "R1": 2 * p - l, "P": p,
            "S1": 2 * p - h, "S2": p - (h - l), "S3": l - 2 * (h - p)}


def swing_points(df: pd.DataFrame, left: int = 5, right: int = 5):
    """Topos e fundos (fractais) confirmados."""
    highs, lows = df["high"].to_numpy(), df["low"].to_numpy()
    tops, bottoms = [], []
    for i in range(left, len(df) - right):
        if highs[i] == highs[i - left: i + right + 1].max():
            tops.append((i, highs[i]))
        if lows[i] == lows[i - left: i + right + 1].min():
            bottoms.append((i, lows[i]))
    return tops, bottoms


def support_resistance(df: pd.DataFrame, max_levels: int = 4, lookback: int = 300) -> dict:
    """Agrupa topos/fundos próximos em zonas e devolve os níveis mais fortes
    abaixo (suportes) e acima (resistências) do preço atual."""
    data = df.tail(lookback).reset_index(drop=True)
    if len(data) < 20:
        return {"supports": [], "resistances": []}
    tops, bottoms = swing_points(data, 3, 3)
    points = sorted([p for _, p in tops + bottoms])
    if not points:
        return {"supports": [], "resistances": []}
    a = float(data["atr"].iloc[-1]) if "atr" in data else float(atr(data, 14).iloc[-1])
    tol = a * 0.6 or data["close"].iloc[-1] * 0.003
    clusters: list[list[float]] = [[points[0]]]
    for p in points[1:]:
        if p - np.mean(clusters[-1]) <= tol:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    levels = sorted(((float(np.mean(c)), len(c)) for c in clusters), key=lambda x: -x[1])
    price = float(data["close"].iloc[-1])
    sup = sorted([lv for lv in levels if lv[0] < price], key=lambda x: -x[0])[:max_levels]
    res = sorted([lv for lv in levels if lv[0] >= price], key=lambda x: x[0])[:max_levels]
    return {"supports": [{"price": p, "touches": t} for p, t in sup],
            "resistances": [{"price": p, "touches": t} for p, t in res]}


def fibonacci(df: pd.DataFrame, lookback: int = 150) -> dict:
    data = df.tail(lookback)
    hi_idx, lo_idx = data["high"].idxmax(), data["low"].idxmin()
    hi, lo = float(data["high"].max()), float(data["low"].min())
    uptrend = lo_idx < hi_idx  # fundo antes do topo → retração de alta
    ratios = (0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0)
    rng = hi - lo
    return {f"{r:.3f}": (hi - r * rng) if uptrend else (lo + r * rng) for r in ratios}


def compute(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Adiciona ao DataFrame todos os indicadores (os desligados também são
    calculados quando as habilidades do bot precisam deles)."""
    out = df.copy()
    c = out["close"]
    out["ema_fast"] = ema(c, int(cfg["ema_fast"]))
    out["ema_slow"] = ema(c, int(cfg["ema_slow"]))
    out["ema_trend"] = ema(c, int(cfg["ema_trend"]))
    out["bb_up"], out["bb_mid"], out["bb_low"] = bollinger(c, int(cfg["bb_period"]), float(cfg["bb_std"]))
    out["rsi"] = rsi(c, int(cfg["rsi_period"]))
    out["macd"], out["macd_signal"], out["macd_hist"] = macd(c, int(cfg["macd_fast"]), int(cfg["macd_slow"]), int(cfg["macd_signal"]))
    out["atr"] = atr(out, int(cfg["atr_period"]))
    out["adx"], out["di_plus"], out["di_minus"] = adx(out, int(cfg["adx_period"]))
    out["stoch_k"], out["stoch_d"] = stochastic(out, int(cfg["stoch_k"]), int(cfg["stoch_d"]))
    out["vwap"] = vwap(out)
    out["obv"] = obv(out)
    out["st_line"], out["st_dir"] = supertrend(out, int(cfg["st_period"]), float(cfg["st_mult"]))
    out["vol_sma"] = sma(out["volume"], 20)
    # Ichimoku é calculado sempre: a habilidade Ichimoku o usa mesmo com o indicador oculto no gráfico
    out["ichi_tenkan"], out["ichi_kijun"], out["ichi_span_a"], out["ichi_span_b"] = ichimoku(out)
    from core.regime import classify  # contexto do gráfico (usa as colunas acima)

    out["taker_ratio"] = out["taker_buy"] / out["volume"].replace(0, np.nan) if "taker_buy" in out else np.nan  # compra agressiva ÷ volume
    out["regime"] = classify(out)
    return out
