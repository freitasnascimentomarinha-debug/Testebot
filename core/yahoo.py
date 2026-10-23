"""Dados de forex, commodities, índices e ações da B3 pelo Yahoo Finance (API pública, sem chave).

Os dados são "ao vivo" no sentido de que o candle atual é atualizado a cada consulta, mas o Yahoo pode atrasar algumas cotações
(em geral ~15 min na B3 e em alguns índices; forex e futuros de commodities costumam ser quase em tempo real). Histórico: intradiário
até 60 dias (5/15/30 min), 2 anos (1 h) e vários anos (diário). Não é uma API oficial: pode oscilar ou limitar requisições, por isso há
cache curto compartilhado, nova tentativa e dois hosts."""
from __future__ import annotations

import threading
import time

import pandas as pd
import requests

HOSTS = ("https://query1.finance.yahoo.com", "https://query2.finance.yahoo.com")
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; TradeBotPlatform/1.0)", "Accept": "application/json"}
CACHE_SECONDS = 8
_cache: dict = {}
_lock = threading.Lock()
_session = requests.Session()
_session.headers.update(HEADERS)

# intervalo da plataforma → (intervalo do Yahoo, reamostrar para)
_INTERVAL = {"1m": ("1m", None), "5m": ("5m", None), "15m": ("15m", None), "30m": ("30m", None), "1h": ("60m", None),
             "2h": ("60m", "2h"), "4h": ("60m", "4h"), "1d": ("1d", None), "1w": ("1wk", None)}


class YahooError(RuntimeError):
    pass


def _range(interval: str, limit: int) -> str:
    if interval == "1m":
        return "7d"
    if interval in ("5m",):
        return "30d" if limit <= 1500 else "60d"
    if interval in ("15m", "30m"):
        return "60d"
    if interval in ("1h", "2h", "4h"):
        return "6mo" if limit <= 800 * (1 if interval == "1h" else (2 if interval == "2h" else 4)) // 2 else "2y"
    if interval == "1d":
        return "5y" if limit <= 1200 else "10y"
    return "10y"


def _fetch(path: str, params: dict) -> dict:
    last = None
    for attempt in range(3):
        for host in HOSTS:
            try:
                resp = _session.get(host + path, params=params, timeout=12)
                if resp.status_code == 200:
                    return resp.json()
                last = f"HTTP {resp.status_code}"
                if resp.status_code == 404:
                    raise YahooError("símbolo não encontrado no Yahoo Finance")
            except requests.RequestException as exc:
                last = type(exc).__name__
        time.sleep(0.6 * (attempt + 1))
    raise YahooError(f"Yahoo Finance indisponível agora ({last})")


def _chart(symbol: str, interval: str, rng: str) -> dict:
    key = (symbol, interval, rng)
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < CACHE_SECONDS:
            return hit[1]
    data = _fetch(f"/v8/finance/chart/{requests.utils.quote(symbol, safe='')}", {"interval": interval, "range": rng, "includePrePost": "false"})
    res = (data.get("chart") or {}).get("result")
    if not res:
        err = (data.get("chart") or {}).get("error") or {}
        raise YahooError(err.get("description") or "sem dados para este símbolo")
    with _lock:
        _cache[key] = (now, res[0])
        if len(_cache) > 400:
            for k in sorted(_cache, key=lambda k: _cache[k][0])[:100]:
                del _cache[k]
    return res[0]


def klines(symbol: str, interval: str, limit: int = 500) -> pd.DataFrame:
    """Candles (time = abertura, UTC; open, high, low, close, volume), do mais antigo ao atual."""
    y_itv, resample = _INTERVAL[interval]
    r = _chart(symbol, y_itv, _range(interval, limit))
    ts = r.get("timestamp") or []
    q = ((r.get("indicators") or {}).get("quote") or [{}])[0]
    if not ts or not q.get("close"):
        raise YahooError("sem candles para este símbolo e intervalo")
    df = pd.DataFrame({"time": pd.to_datetime(ts, unit="s", utc=True), "open": q["open"], "high": q["high"], "low": q["low"],
                       "close": q["close"], "volume": q.get("volume") or [0] * len(ts)})
    df = df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0.0)
    grid = {"1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min", "1h": "1h"}.get(interval)
    if grid and len(df):  # o candle em formação vem com o horário do último negócio: alinha ao início do período
        df.loc[df.index[-1], "time"] = df["time"].iloc[-1].floor(grid)
        df = df.drop_duplicates("time", keep="last").reset_index(drop=True)
    if resample:
        g = df.set_index("time").resample(resample, label="left", closed="left")
        df = g.agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["open"]).reset_index()
    if not len(df):
        raise YahooError("sem candles válidos")
    df.attrs["no_volume"] = bool(df["volume"].sum() == 0)
    if df.attrs["no_volume"]:
        df["volume"] = 1.0  # forex não tem volume centralizado: volume constante deixa os votos de volume neutros
    df.attrs["source"] = "Yahoo Finance"
    return df.tail(limit).reset_index(drop=True)


def quote(symbol: str) -> dict:
    """Cotação atual e resumo do dia."""
    r = _chart(symbol, "1m", "1d")
    m = r.get("meta") or {}
    last = m.get("regularMarketPrice")
    if last is None:
        raise YahooError("sem cotação para este símbolo")
    prev = m.get("chartPreviousClose") or m.get("previousClose") or last
    return {"last": float(last), "prev_close": float(prev), "high": float(m.get("regularMarketDayHigh") or last),
            "low": float(m.get("regularMarketDayLow") or last), "volume": float(m.get("regularMarketVolume") or 0),
            "currency": m.get("currency"), "market_time": float(m.get("regularMarketTime") or 0), "name": m.get("longName") or m.get("shortName")}
