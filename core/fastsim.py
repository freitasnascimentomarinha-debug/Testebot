"""Simulação rápida (vetorizada) das personalidades.

Reproduz exatamente o mesmo resultado de ``core.backtest.run`` — mesmos votos das
habilidades, mesmos filtros, stop/alvo e regra de saída — mas calcula os votos de
todos os candles de uma vez com numpy, em vez de chamar cada habilidade candle a
candle. Isso torna o backtest de 40 dias em 5 minutos (~11.500 candles) questão de
segundos e permite simular muitos bots sobre os mesmos votos (calculadora, ranking).

A equivalência com o backtest original é verificada em ``tests/test_core.py``.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

from core import indicators as ind
from core.trail import step as trail_step

SKILL_KEYS = ("tendencia", "momentum", "macd", "bollinger", "supertrend", "vwap", "volume", "estrutura",
              "suporte_resistencia", "rompimento", "reversao", "ichimoku", "estocastico", "adx", "fibonacci")
WARMUP = 210


def _shift(a: np.ndarray, k: int) -> np.ndarray:
    out = np.full_like(a, np.nan, dtype=float)
    if k < len(a):
        out[k:] = a[:-k] if k else a
    return out


def _roll(a: np.ndarray, w: int, fn) -> np.ndarray:
    """Janela móvel terminando em i (inclusive)."""
    out = np.full(len(a), np.nan)
    if len(a) >= w:
        out[w - 1:] = fn(sliding_window_view(a, w), axis=1)
    return out


def _swings(high: np.ndarray, low: np.ndarray, k: int = 3) -> tuple[np.ndarray, np.ndarray]:
    """Topos/fundos com k candles de cada lado (mesma regra de ``indicators.swing_points``)."""
    n = len(high)
    top = np.zeros(n, bool)
    bot = np.zeros(n, bool)
    if n >= 2 * k + 1:
        top[k:n - k] = high[k:n - k] == sliding_window_view(high, 2 * k + 1).max(axis=1)
        bot[k:n - k] = low[k:n - k] == sliding_window_view(low, 2 * k + 1).min(axis=1)
    return np.flatnonzero(top), np.flatnonzero(bot)


def compute_votes(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Votos das habilidades (colunas ``v_<chave>``) e o suporte/resistência mais próximos
    (``sup``/``res``) de cada candle fechado. ``df`` deve vir de ``indicators.compute``."""
    g = {c: df[c].to_numpy(dtype=float) for c in (
        "open", "high", "low", "close", "volume", "ema_fast", "ema_slow", "ema_trend", "rsi", "macd", "macd_signal",
        "macd_hist", "bb_up", "bb_mid", "bb_low", "atr", "adx", "di_plus", "di_minus", "stoch_k", "stoch_d", "vwap",
        "obv", "st_dir", "vol_sma", "ichi_tenkan", "ichi_kijun", "ichi_span_a", "ichi_span_b")}
    o, h, l, c, vol = g["open"], g["high"], g["low"], g["close"], g["volume"]
    n = len(c)
    ob, os_ = float(cfg["rsi_ob"]), float(cfg["rsi_os"])
    v = {}

    # tendência (EMAs)
    ef, es, et = g["ema_fast"], g["ema_slow"], g["ema_trend"]
    pef, pes = _shift(ef, 1), _shift(es, 1)
    t = np.where(ef > es, 0.4, -0.4) + np.where(c > et, 0.35, -0.35)
    t = t + 0.25 * np.sign(es / _shift(es, 5) - 1)
    t = t + np.where((pef <= pes) & (pes < ef), 0.2, np.where((pef >= pes) & (pes > ef), -0.2, 0.0))
    v["tendencia"] = t

    # momentum (RSI) + divergência em 30 candles
    rsi = g["rsi"]
    neutral = ~((rsi >= ob) | (rsi <= os_))
    m = np.where(rsi >= ob, -0.6, np.where(rsi <= os_, 0.6, (rsi - 50) / 50))
    m = m + 0.3 * np.sign(rsi - _shift(rsi, 3)) * np.where(neutral, 0.5, 1.0)
    cmax, cmin = _roll(c, 30, np.nanmax), _roll(c, 30, np.nanmin)
    rmax, rmin = _roll(rsi, 30, np.nanmax), _roll(rsi, 30, np.nanmin)
    m = m + np.where((c >= cmax * 0.999) & (rsi < rmax - 5), -0.3, np.where((c <= cmin * 1.001) & (rsi > rmin + 5), 0.3, 0.0))
    v["momentum"] = m

    # MACD
    hist = g["macd_hist"]
    v["macd"] = (np.where(g["macd"] > g["macd_signal"], 0.5, -0.5) + np.where(hist > _shift(hist, 1), 0.3, -0.3)
                 + np.where(g["macd"] > 0, 0.2, -0.2))

    # Bandas de Bollinger
    up, mid, lo_b, adx = g["bb_up"], g["bb_mid"], g["bb_low"], g["adx"]
    width = (up - lo_b) / mid * 100
    avg_w = _roll(width, 100, np.mean)
    with np.errstate(invalid="ignore", divide="ignore"):
        pos = np.where(up != lo_b, (c - lo_b) / (up - lo_b), 0.5)
    v["bollinger"] = np.where(width < avg_w * 0.6, 0.0,
                              np.where(pos > 1, np.where(adx > 25, 0.4, -0.5),
                                       np.where(pos < 0, np.where(adx > 25, -0.4, 0.5), (0.5 - pos) * 0.6)))

    # SuperTrend (virada nos últimos 4 candles)
    d = g["st_dir"]
    changed = (d != _shift(d, 1)).astype(float)
    flips = _roll(changed, 4, np.max) > 0
    v["supertrend"] = d * np.where(flips, 1.0, 0.7)

    # VWAP
    vw = g["vwap"]
    with np.errstate(invalid="ignore", divide="ignore"):
        v["vwap"] = np.where(np.isnan(vw), 0.0, np.tanh((c / vw - 1) * 100 / 0.5) * 0.8)

    # Volume / OBV
    vs = g["vol_sma"]
    with np.errstate(invalid="ignore", divide="ignore"):
        rel = np.where((vs != 0) | np.isnan(vs), vol / vs, 1.0)
    v["volume"] = np.sign(c - o) * np.minimum(rel, 2) / 2 * 0.6 + np.sign(g["obv"] - _shift(g["obv"], 9)) * 0.3

    # rompimento (Donchian 20) e reversão à média
    hi20 = _shift(_roll(h, 20, np.max), 1)
    lo20 = _shift(_roll(l, 20, np.min), 1)
    vol_ok = np.where((vs != 0) & ~np.isnan(vs), vol > vs * 1.2, np.where(np.isnan(vs), vol > vs * 1.2, False))
    with np.errstate(invalid="ignore", divide="ignore"):
        pos20 = np.where(hi20 != lo20, (c - lo20) / (hi20 - lo20), 0.5)
    v["rompimento"] = np.where(c > hi20, np.where(vol_ok, 0.9, 0.5),
                               np.where(c < lo20, np.where(vol_ok, -0.9, -0.5), (pos20 - 0.5) * 0.4))
    rv = np.where(c <= lo_b, 0.5, np.where(c >= up, -0.5, 0.0)) + np.where(rsi <= os_, 0.5, np.where(rsi >= ob, -0.5, 0.0))
    v["reversao"] = np.where(adx > 30, rv * 0.4, rv)

    # Ichimoku
    sa, sb, tk, kj = g["ichi_span_a"], g["ichi_span_b"], g["ichi_tenkan"], g["ichi_kijun"]
    top_c, bot_c = np.fmax(sa, sb), np.fmin(sa, sb)
    ichi = (np.where(c > top_c, 0.5, np.where(c < bot_c, -0.5, 0.0)) + np.where(tk > kj, 0.3, -0.3)
            + np.where(sa > sb, 0.2, -0.2))
    v["ichimoku"] = np.where(np.isnan(sa) | np.isnan(sb), 0.0, ichi)

    # Estocástico
    k, dd = g["stoch_k"], g["stoch_d"]
    pk, pd_ = _shift(k, 1), _shift(dd, 1)
    cu, cd = (pk <= pd_) & (k > dd), (pk >= pd_) & (k < dd)
    sto = np.where(cu, np.where(k < 30, 0.8, 0.4), np.where(cd, np.where(k > 70, -0.8, -0.4),
                                                           np.where(k < 20, 0.3, np.where(k > 80, -0.3, 0.0))))
    v["estocastico"] = np.where(np.isnan(k) | np.isnan(dd), 0.0, sto)

    # ADX / DMI
    strength = np.minimum(1.0, np.maximum(0.0, np.nan_to_num((adx - 15) / 20, nan=0.0)))
    v["adx"] = np.where(g["di_plus"] > g["di_minus"], 1.0, -1.0) * strength

    # Fibonacci (última perna de 100 candles)
    fib = np.zeros(n)
    if n >= 100:
        wh, wl = sliding_window_view(h, 100), sliding_window_view(l, 100)
        hi_i, lo_i = wh.argmax(axis=1), wl.argmin(axis=1)
        hi, lo = wh.max(axis=1), wl.min(axis=1)
        cc, oo = c[99:], o[99:]
        rng = hi - lo
        bull = cc > oo
        up_leg = lo_i < hi_i
        with np.errstate(invalid="ignore", divide="ignore"):
            retr = np.where(up_leg, (hi - cc) / rng, (cc - lo) / rng)
        sign = np.where(up_leg, 1.0, -1.0)
        confirm = np.where(up_leg, bull, ~bull)
        val = np.where((retr >= 0.382) & (retr <= 0.618),
                       0.6 + np.where(confirm, 0.3, 0.0) + np.where(retr >= 0.5, 0.1, 0.0),
                       np.where((retr >= 0.236) & (retr < 0.382), 0.3, np.where(retr > 0.786, -0.4, 0.0)))
        fib[99:] = np.where(rng <= 0, 0.0, sign * val)
    v["fibonacci"] = fib

    # Estrutura de mercado e suporte/resistência (precisam dos topos/fundos confirmados)
    tops, bots = _swings(h, l, 3)
    est = np.zeros(n)
    sr = np.zeros(n)
    sup = np.full(n, np.nan)
    res = np.full(n, np.nan)
    atr = g["atr"]
    for i in range(WARMUP, n):
        # estrutura: topos/fundos com j em [i-146, i-3] (janela de 150 candles)
        a_t, b_t = bisect_left(tops, i - 146), bisect_right(tops, i - 3)
        a_b, b_b = bisect_left(bots, i - 146), bisect_right(bots, i - 3)
        if b_t - a_t >= 2 and b_b - a_b >= 2:
            hh = h[tops[b_t - 1]] > h[tops[b_t - 2]]
            hl = l[bots[b_b - 1]] > l[bots[b_b - 2]]
            est[i] = 0.5 * (1 if hh else -1) + 0.5 * (1 if hl else -1)
        # suporte/resistência: mesma clusterização de indicators.support_resistance (janela de 300)
        a_t, b_t = bisect_left(tops, i - 296), bisect_right(tops, i - 3)
        a_b, b_b = bisect_left(bots, i - 296), bisect_right(bots, i - 3)
        points = sorted([float(x) for x in h[tops[a_t:b_t]]] + [float(x) for x in l[bots[a_b:b_b]]])
        if not points:
            continue
        tol = float(atr[i]) * 0.6 or float(c[i]) * 0.003
        clusters = [[points[0]]]
        for p in points[1:]:
            if p - np.mean(clusters[-1]) <= tol:
                clusters[-1].append(p)
            else:
                clusters.append([p])
        means = [float(np.mean(cl)) for cl in clusters]
        price = float(c[i])
        below = [m_ for m_ in means if m_ < price]
        above = [m_ for m_ in means if m_ >= price]
        s_lv = max(below) if below else None
        r_lv = min(above) if above else None
        sup[i] = s_lv if s_lv is not None else np.nan
        res[i] = r_lv if r_lv is not None else np.nan
        val = 0.0
        if s_lv and (price - s_lv) < atr[i]:
            val += 0.5
        if r_lv and (r_lv - price) < atr[i]:
            val -= 0.5
        sr[i] = val
    v["estrutura"] = est
    v["suporte_resistencia"] = sr

    out = pd.DataFrame({"time": df["time"].to_numpy(), "open": o, "high": h, "low": l, "close": c, "volume": vol,
                        "vol_sma": vs, "atr": atr, "adx": adx, "rsi": rsi, "ema_trend": et,
                        "regime": df["regime"].to_numpy(),
                        "htf_dir": df["htf_dir"].to_numpy(dtype=float) if "htf_dir" in df else np.zeros(n),
                        "mtf_dir": df["mtf_dir"].to_numpy(dtype=float) if "mtf_dir" in df else np.zeros(n)})
    for key in SKILL_KEYS:
        arr = np.clip(v[key], -1, 1)
        arr[:WARMUP] = np.nan
        out["v_" + key] = arr
    out["sup"], out["res"] = sup, res
    return out


def signals(vt: pd.DataFrame, p: dict, cfg: dict) -> np.ndarray:
    """Direção (+1, −1, 0) que ``strategy.analyze`` daria em cada candle fechado."""
    w = {k: wk for k, wk in (p.get("skills") or {}).items() if wk > 0 and "v_" + k in vt}   # "ml" só existe com o modelo (core/ml.py)
    tot = sum(w.values()) or 1
    score = sum(np.nan_to_num(vt["v_" + k].to_numpy()) * wk for k, wk in w.items()) / tot * 100
    adx = vt["adx"].to_numpy()
    lateral = adx < 18
    f = p.get("filters") or {}
    if not f.get("ignore_regime"):
        score = np.where(lateral, score * 0.7, score)
    th = float(p.get("threshold", 25))
    d = np.where(score >= th, 1, np.where(score <= -th, -1, 0))
    if p.get("direction") == "compra":
        d = np.where(d < 0, 0, d)
    elif p.get("direction") == "venda":
        d = np.where(d > 0, 0, d)
    c, et, rsi = vt["close"].to_numpy(), vt["ema_trend"].to_numpy(), vt["rsi"].to_numpy()
    if f.get("trend_ema"):
        d = np.where(((d == 1) & (c < et)) | ((d == -1) & (c > et)), 0, d)
    if float(f.get("adx_min") or 0):
        d = np.where(adx < float(f["adx_min"]), 0, d)
    if float(f.get("adx_max") or 0):
        d = np.where(adx > float(f["adx_max"]), 0, d)
    if f.get("avoid_lateral"):
        d = np.where(lateral, 0, d)
    if f.get("volume_confirm"):
        d = np.where(~(vt["volume"].to_numpy() > vt["vol_sma"].to_numpy()), 0, d)
    if f.get("rsi_guard"):
        d = np.where(((d == 1) & (rsi > float(cfg["rsi_ob"]))) | ((d == -1) & (rsi < float(cfg["rsi_os"]))), 0, d)
    vm = float(f.get("vol_mult") or 0)
    if vm:
        d = np.where(~(vt["volume"].to_numpy() > vt["vol_sma"].to_numpy() * vm), 0, d)
    if f.get("htf_trend"):
        hd = vt["htf_dir"].to_numpy()
        d = np.where(((d == 1) & (hd != 1)) | ((d == -1) & (hd != -1)), 0, d)
    if f.get("mtf_trend"):
        md = vt["mtf_dir"].to_numpy()
        d = np.where(((d == 1) & (md != 1)) | ((d == -1) & (md != -1)), 0, d)
    ctx = cfg.get("context_filter") or f.get("contexts")
    if ctx:
        d = np.where(np.isin(vt["regime"].to_numpy(), list(ctx)), d, 0)
    if p.get("ml_filter") and "ml_block" in vt:   # filtro do modelo: mercado diferente do que ele conhece → fica de fora
        d = np.where(vt["ml_block"].to_numpy(dtype=bool), 0, d)
    return d


def simulate(vt: pd.DataFrame, p: dict, cfg: dict, *, start_time=None, max_hold: int = 100) -> list[dict]:
    """Operações (mesma regra de ``backtest.run``) a partir de ``start_time``.

    Com ``trail_atr`` na personalidade a operação não tem alvo: o stop acompanha o preço (``core/trail.py``)
    e a posição só sai pelo stop."""
    d = signals(vt, p, cfg)
    o, h, l, c = (vt[k].to_numpy() for k in ("open", "high", "low", "close"))
    atr, sup, res, times = vt["atr"].to_numpy(), vt["sup"].to_numpy(), vt["res"].to_numpy(), vt["time"]
    fee = float(cfg["fee_pct"]) / 100
    slm, tpm = float(p.get("sl_atr") or cfg["atr_sl_mult"]), float(p.get("tp_atr") or cfg["atr_tp_mult"])
    trail, be_r = float(p.get("trail_atr") or 0), float(p.get("be_r") or 0)
    n = len(c)
    i = WARMUP
    if start_time is not None:
        i = max(WARMUP, int(times.searchsorted(start_time)))
    trades, pos = [], None
    while i < n - 1:
        if pos is not None:
            side, entry, sl, tp, i0, te, risk0, dist, best = pos
            hit_sl = l[i] <= sl if side == 1 else h[i] >= sl
            if trail:
                ex, why = (sl, "Stop" if abs(sl - (entry - side * risk0)) < 1e-12 else "Stop móvel") if hit_sl else (None, None)
            else:
                hit_tp = h[i] >= tp if side == 1 else l[i] <= tp
                ex, why = (sl, "Stop") if hit_sl else (tp, "Alvo") if hit_tp else (
                    (c[i], "Tempo") if i - i0 >= max_hold else (None, None))
            if ex is not None:
                trades.append({"entrada": te, "saida": times.iloc[i], "lado": "Compra" if side == 1 else "Venda",
                               "preco_entrada": entry, "preco_saida": ex, "motivo": why,
                               "r": (side * (ex - entry) - fee * (entry + ex)) / risk0})
                pos = None
            elif trail:
                sl, best = trail_step(side, entry, sl, best, h[i], l[i], dist, risk0, be_r, fee)
                pos = (side, entry, sl, tp, i0, te, risk0, dist, best)
            i += 1
            continue
        s = d[i]
        if s != 0:
            price = c[i]
            sl_dist = max(atr[i] * slm, price * fee * 8)
            tp_dist = sl_dist * tpm / slm
            sl_p = price - s * sl_dist
            lv = sup[i] if s == 1 else res[i]
            if not np.isnan(lv):
                cand = lv - s * atr[i] * 0.3
                if sl_dist < abs(price - cand) < sl_dist * 1.3:
                    sl_p = cand
            entry = o[i + 1]
            sd = abs(price - sl_p)
            pos = (s, entry, entry - s * sd, entry + s * tp_dist, i + 1, times.iloc[i + 1], sd, trail * atr[i], entry)
            i += 1
            continue
        i += 1
    return trades


def prepare(df_raw: pd.DataFrame, cfg: dict, htf_raw: pd.DataFrame | None = None,
            mtf_raw: pd.DataFrame | None = None) -> pd.DataFrame:
    df = ind.compute(df_raw, cfg).reset_index(drop=True)
    if htf_raw is not None or mtf_raw is not None:
        from core.htf import attach

        df = attach(df, htf_raw, cfg["interval"], mtf_raw)
    return compute_votes(df, cfg)


PER_DAY = {"1m": 1440, "3m": 480, "5m": 288, "15m": 96, "30m": 48, "1h": 24, "2h": 12, "4h": 6, "6h": 4, "12h": 2,
           "1d": 1, "3d": 1 / 3, "1w": 1 / 7}


def bot_for(market: str, interval: str) -> str:
    """Configuração-base usada nos testes: futuros → Day Trade; spot diário → Long; demais spot → Swing."""
    return "day" if market == "futures" else ("long" if interval in ("1d", "3d", "1w") else "swing")


def period_trades(vt: pd.DataFrame, cfg: dict, p: dict, *, days: float, market: str) -> list[dict]:
    """Operações dos últimos ``days`` dias (spot sem margem: só compra)."""
    if market == "spot":
        p = {**p, "direction": "compra"}
    start = vt["time"].iloc[-1] - pd.Timedelta(days=days)
    return simulate(vt, p, cfg, start_time=start)


def period_result(vt: pd.DataFrame, cfg: dict, p: dict, *, days: float, market: str, risk_pct: float = 1.0,
                  symbol: str = "") -> dict:
    from core.backtest import compound

    trades = period_trades(vt, cfg, p, days=days, market=market)
    rs = [t["r"] for t in trades]
    ret, dd = compound(rs, risk_pct)
    return {"symbol": symbol, "trades": len(rs), "win_rate": float(np.mean([r > 0 for r in rs]) * 100) if rs else 0.0,
            "avg_r": float(np.mean(rs)) if rs else 0.0, "total_r": float(sum(rs)), "return_pct": float(ret),
            "max_dd_pct": float(dd), "period": f"últimos {days:g} dias"}
