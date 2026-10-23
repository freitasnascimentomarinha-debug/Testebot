"""Dados de mercado reais a partir de APIs públicas gratuitas (sem chave).

Ordem de tentativa (a primeira que responder é usada):

* Futuros: Binance USDⓈ-M (fapi) → OKX perpétuo (SWAP) → Binance Spot
* Spot:    Binance (api) → Binance espelho público (data-api.binance.vision) → OKX

Alguns provedores bloqueiam certos países/servidores (HTTP 451/403); o
fallback garante que a plataforma continue com dados reais.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import pandas as pd
import requests

TIMEOUT = 10
_session = requests.Session()
_session.headers.update({"User-Agent": "TradeBotPlatform/1.0"})

BINANCE_SPOT = ("https://api.binance.com", "https://data-api.binance.vision")
BINANCE_FUT = "https://fapi.binance.com"
OKX = "https://www.okx.com"

_OKX_BAR = {
    "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1H", "2h": "2H", "4h": "4H", "6h": "6Hutc", "12h": "12Hutc",
    "1d": "1Dutc", "3d": "3Dutc", "1w": "1Wutc", "1M": "1Mutc",
}

INTERVAL_SECONDS = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200,
    "4h": 14400, "6h": 21600, "12h": 43200, "1d": 86400, "3d": 259200, "1w": 604800, "1M": 2592000,
}

COLUMNS = ["time", "open", "high", "low", "close", "volume"]


class MarketDataError(RuntimeError):
    pass


@dataclass
class Ticker:
    symbol: str
    last: float
    change_pct: float
    high: float
    low: float
    volume_quote: float
    source: str


def _get(url: str, params: dict | None = None):
    resp = _session.get(url, params=params, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


_MULT_PREFIX = (("1000000", 1_000_000), ("1M", 1_000_000), ("1000", 1_000))


def okx_base(symbol: str) -> tuple[str, int]:
    """Moeda-base na OKX e multiplicador de contrato da Binance
    (ex.: 1000PEPEUSDT → PEPE, 1000)."""
    base = symbol.upper().removesuffix("USDT")
    for prefix, mult in _MULT_PREFIX:
        if base.startswith(prefix) and len(base) > len(prefix) and not base[len(prefix)].isdigit():
            return base[len(prefix):], mult
    return base, 1


def _okx_inst(symbol: str, market: str) -> str:
    base, _ = okx_base(symbol)
    return f"{base}-USDT-SWAP" if market == "futures" else f"{base}-USDT"


_ct_cache: dict[str, float] = {}


def okx_contract_value(symbol: str) -> float:
    """Quantidade da moeda-base em um contrato perpétuo da OKX."""
    inst = _okx_inst(symbol, "futures")
    if inst not in _ct_cache:
        data = _get(OKX + "/api/v5/public/instruments", {"instType": "SWAP", "instId": inst})
        _ct_cache[inst] = float(data["data"][0]["ctVal"]) if data.get("data") else 1.0
    return _ct_cache[inst]


def _frame(rows: list[list], source: str) -> pd.DataFrame:
    df = pd.DataFrame([r[:6] for r in rows], columns=COLUMNS)
    df["time"] = pd.to_datetime(df["time"].astype("int64"), unit="ms", utc=True)
    for col in COLUMNS[1:]:
        df[col] = df[col].astype(float)
    df = df.drop_duplicates("time").sort_values("time").reset_index(drop=True)
    df.attrs["source"] = source
    return df


def _binance_klines(base: str, path: str, symbol: str, interval: str, limit: int, cap: int) -> list:
    rows: list = []
    end_time = None
    remaining = limit
    while remaining > 0:
        params = {"symbol": symbol, "interval": interval, "limit": min(remaining, cap)}
        if end_time:
            params["endTime"] = end_time
        batch = _get(base + path, params)
        if not batch:
            break
        rows = batch + rows
        remaining -= len(batch)
        end_time = batch[0][0] - 1
        if len(batch) < params["limit"]:
            break
    return rows


def _okx_klines(symbol: str, interval: str, limit: int, market: str) -> list:
    inst = _okx_inst(symbol, market)
    bar = _OKX_BAR[interval]
    rows: list = []
    after = None
    endpoint = "/api/v5/market/candles"
    while len(rows) < limit:
        params = {"instId": inst, "bar": bar, "limit": 300 if endpoint.endswith("candles") else 100}
        if after:
            params["after"] = after
        data = _get(OKX + endpoint, params)
        if data.get("code") != "0":
            raise MarketDataError(data.get("msg") or "OKX error")
        batch = data["data"]
        if not batch:
            break
        rows.extend(batch)  # OKX devolve do mais novo para o mais antigo
        after = batch[-1][0]
        endpoint = "/api/v5/market/history-candles"
    rows = rows[:limit]
    _, mult = okx_base(symbol)
    vol_idx = 6 if market == "futures" else 5  # perpétuo: volume em moeda-base (não em contratos)
    return [[int(r[0]), float(r[1]) * mult, float(r[2]) * mult, float(r[3]) * mult, float(r[4]) * mult,
             float(r[vol_idx]) / mult] for r in reversed(rows)]


def get_klines(symbol: str, interval: str, limit: int = 500, market: str = "spot") -> pd.DataFrame:
    """Candles OHLCV em UTC. ``df.attrs['source']`` informa o provedor usado."""
    symbol = symbol.upper().strip()
    errors = []
    attempts = []
    if market == "futures":
        attempts.append(("Binance Futuros", lambda: _binance_klines(BINANCE_FUT, "/fapi/v1/klines", symbol, interval, limit, 1500)))
        attempts.append(("OKX Perpétuo", lambda: _okx_klines(symbol, interval, limit, "futures")))
    for base in BINANCE_SPOT:
        attempts.append((f"Binance Spot ({base.split('//')[1]})",
                         lambda base=base: _binance_klines(base, "/api/v3/klines", symbol, interval, limit, 1000)))
    if market == "spot":
        attempts.append(("OKX Spot", lambda: _okx_klines(symbol, interval, limit, "spot")))

    for name, fn in attempts:
        try:
            rows = fn()
            if rows:
                return _frame(rows, name)
        except Exception as exc:  # noqa: BLE001 - tentamos o próximo provedor
            errors.append(f"{name}: {exc}")
    raise MarketDataError("Não foi possível obter candles. " + " | ".join(errors))


def get_ticker(symbol: str, market: str = "spot") -> Ticker:
    symbol = symbol.upper().strip()
    errors = []

    def binance(base: str, path: str, name: str):
        d = _get(base + path, {"symbol": symbol})
        return Ticker(symbol, float(d["lastPrice"]), float(d["priceChangePercent"]), float(d["highPrice"]),
                      float(d["lowPrice"]), float(d["quoteVolume"]), name)

    attempts = []
    if market == "futures":
        attempts.append(("Binance Futuros", lambda: binance(BINANCE_FUT, "/fapi/v1/ticker/24hr", "Binance Futuros")))
        attempts.append(("OKX Perpétuo", lambda: _okx_ticker(symbol, "futures")))
    for base in BINANCE_SPOT:
        attempts.append(("Binance Spot", lambda base=base: binance(base, "/api/v3/ticker/24hr", "Binance Spot")))
    if market == "spot":
        attempts.append(("OKX Spot", lambda: _okx_ticker(symbol, "spot")))
    for name, fn in attempts:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - tentamos o próximo provedor
            errors.append(f"{name}: {exc}")
    raise MarketDataError("Não foi possível obter cotação. " + " | ".join(errors))


def _okx_ticker(symbol: str, market: str) -> Ticker:
    data = _get(OKX + "/api/v5/market/ticker", {"instId": _okx_inst(symbol, market)})
    if data.get("code") != "0" or not data["data"]:
        raise MarketDataError(data.get("msg") or "sem dados")
    d = data["data"][0]
    _, mult = okx_base(symbol)
    last, open24 = float(d["last"]) * mult, float(d["open24h"]) * mult
    vol_quote = float(d.get("volCcy24h", 0)) * (last / mult if market == "futures" else 1)
    return Ticker(symbol, last, (last / open24 - 1) * 100 if open24 else 0.0, float(d["high24h"]) * mult,
                  float(d["low24h"]) * mult, vol_quote, "OKX Perpétuo" if market == "futures" else "OKX Spot")


def get_funding_rate(symbol: str) -> float | None:
    """Taxa de financiamento atual do perpétuo (em %), quando disponível."""
    try:
        d = _get(BINANCE_FUT + "/fapi/v1/premiumIndex", {"symbol": symbol})
        return float(d["lastFundingRate"]) * 100
    except Exception:  # noqa: BLE001
        pass
    try:
        d = _get(OKX + "/api/v5/public/funding-rate", {"instId": _okx_inst(symbol, "futures")})
        return float(d["data"][0]["fundingRate"]) * 100
    except Exception:  # noqa: BLE001
        return None


def last_closed_candle_time(df: pd.DataFrame, interval: str) -> pd.Timestamp:
    """Horário de abertura do último candle já fechado."""
    now = pd.Timestamp(time.time(), unit="s", tz="UTC")
    last = df["time"].iloc[-1]
    if last + pd.Timedelta(seconds=INTERVAL_SECONDS[interval]) <= now:
        return last
    return df["time"].iloc[-2]


def list_symbols(market: str) -> list[str]:
    """Todos os pares em USDT negociáveis no mercado (spot: por volume)."""
    if market == "futures":
        from core.leverage import futures_symbols

        symbols = futures_symbols()
        if symbols:
            return symbols
        data = _get(OKX + "/api/v5/public/instruments", {"instType": "SWAP"})
        return sorted(i["instId"].split("-")[0] + "USDT" for i in data["data"] if i["instId"].endswith("-USDT-SWAP"))
    for base in BINANCE_SPOT:
        try:
            rows = _get(base + "/api/v3/ticker/24hr", {"type": "MINI"})
            rows = [r for r in rows if r["symbol"].endswith("USDT") and float(r["quoteVolume"]) > 0]
            return [r["symbol"] for r in sorted(rows, key=lambda r: -float(r["quoteVolume"]))]
        except Exception:  # noqa: BLE001
            continue
    data = _get(OKX + "/api/v5/market/tickers", {"instType": "SPOT"})
    return [d["instId"].replace("-", "") for d in data["data"] if d["instId"].endswith("-USDT")]


def get_usdt_brl() -> float | None:
    """Cotação do dólar cripto em reais (USDT/BRL), para exibir a banca em R$."""
    try:
        return get_ticker("USDTBRL", "spot").last
    except Exception:  # noqa: BLE001
        return None
