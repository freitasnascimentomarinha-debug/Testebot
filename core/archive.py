"""Candles históricos do arquivo público da Binance (data.binance.vision), para a pesquisa de bots.

Traz futuros USDⓈ-M e spot com o volume comprador agressivo (taker buy), e funciona mesmo onde a API (api/fapi.binance.com) é bloqueada.
Os arquivos são mensais (meses fechados) e diários (mês corrente); ficam em cache em disco. O dia corrente só aparece no dia seguinte.
"""
from __future__ import annotations

import io
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import requests

from core.storage import DATA_DIR

BASE = "https://data.binance.vision/data"
PATH = {"futures": "futures/um", "spot": "spot"}
CACHE = DATA_DIR / "archive_cache"
COLS = ["time", "open", "high", "low", "close", "volume", "close_time", "quote_volume", "count", "taker_buy", "taker_quote", "ignore"]
_session = requests.Session()
_session.headers.update({"User-Agent": "TradeBotPlatform/1.0"})


def _fetch(url: str, cache_name: str) -> bytes | None:
    """Conteúdo do arquivo (do cache ou baixado); ``None`` se ainda não foi publicado (404)."""
    f = CACHE / cache_name
    if f.exists():
        return f.read_bytes()
    resp = _session.get(url, timeout=30)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(resp.content)
    return resp.content


def _read(blob: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        raw = z.read(z.namelist()[0])
    df = pd.read_csv(io.BytesIO(raw), header=None, names=COLS, usecols=range(len(COLS)))
    df = df[pd.to_numeric(df["time"], errors="coerce").notna()]                  # alguns arquivos trazem cabeçalho
    df["time"] = df["time"].astype("int64")
    df["time"] = df["time"].where(df["time"] < 10 ** 14, df["time"] // 1000)      # spot a partir de 2025 usa microssegundos
    return df


def _name(market: str, symbol: str, interval: str, stamp: str, kind: str) -> tuple[str, str]:
    rel = f"{PATH[market]}/{kind}/klines/{symbol}/{interval}/{symbol}-{interval}-{stamp}.zip"
    return f"{BASE}/{rel}", rel.replace("/", "_")


def _month(market: str, symbol: str, interval: str, year: int, month: int, today: date) -> list[pd.DataFrame]:
    """Um mês: o arquivo mensal se já saiu; senão, os diários disponíveis."""
    if (year, month) < (today.year, today.month):
        url, name = _name(market, symbol, interval, f"{year}-{month:02d}", "monthly")
        blob = _fetch(url, name)
        if blob:
            return [_read(blob)]
    first = date(year, month, 1)
    last = min(today - timedelta(days=1), (date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)))
    days = [first + timedelta(days=i) for i in range((last - first).days + 1)]

    def one(d: date):
        url, name = _name(market, symbol, interval, d.isoformat(), "daily")
        blob = _fetch(url, name)
        return _read(blob) if blob else None

    with ThreadPoolExecutor(8) as ex:
        return [x for x in ex.map(one, days) if x is not None]


def klines(symbol: str, interval: str, limit: int = 500, market: str = "futures", now: datetime | None = None) -> pd.DataFrame:
    """Últimos ``limit`` candles fechados do arquivo (mesmas colunas de ``core.data.get_klines``, mais ``taker_buy``)."""
    symbol = symbol.upper().strip()
    today = (now or datetime.now(timezone.utc)).date()
    frames: list[pd.DataFrame] = []
    year, month, rows = today.year, today.month, 0
    for _ in range(40):                                  # no máximo ~3 anos para trás
        got = _month(market, symbol, interval, year, month, today)
        frames = got + frames
        rows += sum(len(g) for g in got)
        if rows >= limit:
            break
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    if not frames:
        raise RuntimeError(f"{symbol}: sem arquivo de {interval} em {market} no data.binance.vision")
    df = pd.concat(frames, ignore_index=True).drop_duplicates("time").sort_values("time").tail(limit)
    out = pd.DataFrame({"time": pd.to_datetime(df["time"].astype("int64"), unit="ms", utc=True)})
    for col in ("open", "high", "low", "close", "volume", "taker_buy"):
        out[col] = df[col].astype(float).to_numpy()
    out = out.reset_index(drop=True)
    out.attrs["source"] = "Binance (arquivo público)"
    return out
