"""Dados de mercado de várias corretoras pelo ccxt (candles, cotação, financiamento, lista de pares e volume).

A corretora dos dados é uma escolha da conta (Minha conta → Fonte de dados). Binance usa os provedores nativos de ``core/data.py``;
as demais passam por aqui e, se falharem, ``core/data.py`` volta para Binance/OKX. As ordens continuam simuladas: isto só alimenta
os gráficos, o bot e a varredura com os preços da corretora escolhida.
"""
from __future__ import annotations

import time

import pandas as pd

from core.storage import current_user, load_json, save_json

SETTING_FILE = "data_source.json"
DEFAULT = "binance"
# id → (nome, id do ccxt no spot, id do ccxt nos futuros perpétuos ou None)
EXCHANGES = {
    "binance": ("Binance", "binance", "binanceusdm"),
    "bybit": ("Bybit", "bybit", "bybit"),
    "okx": ("OKX", "okx", "okx"),
    "coinbase": ("Coinbase", "coinbase", None),
    "kraken": ("Kraken", "kraken", None),
    "kucoin": ("KuCoin", "kucoin", "kucoinfutures"),
    "bitget": ("Bitget", "bitget", "bitget"),
    "gate": ("Gate", "gate", "gate"),
    "mexc": ("MEXC", "mexc", "mexc"),
    "htx": ("HTX", "htx", "htx"),
    "bingx": ("BingX", "bingx", "bingx"),
}
QUOTES = ("USDT", "USDC", "USD")   # Coinbase e Kraken negociam em USD/USDC; as demais, em USDT
_clients: dict = {}
_markets_at: dict = {}
MARKETS_TTL = 6 * 3600
_sel_cache: dict = {}
SEL_TTL = 30


class ExchangeError(RuntimeError):
    pass


def label(ex: str) -> str:
    return EXCHANGES.get(ex, (ex,))[0]


def supports(ex: str, market: str) -> bool:
    return ex in EXCHANGES and (market == "spot" or EXCHANGES[ex][2] is not None)


def selected() -> str:
    """Corretora escolhida pelo usuário (guardada por conta; vale para a página e para o worker)."""
    user = current_user()
    hit = _sel_cache.get(user)
    if hit and time.time() - hit[0] < SEL_TTL:
        return hit[1]
    ex = (load_json(SETTING_FILE, {}) or {}).get("exchange", DEFAULT)
    ex = ex if ex in EXCHANGES else DEFAULT
    _sel_cache[user] = (time.time(), ex)
    return ex


def select(ex: str) -> None:
    if ex not in EXCHANGES:
        raise ValueError("Corretora desconhecida.")
    save_json(SETTING_FILE, {"exchange": ex})
    _sel_cache[current_user()] = (time.time(), ex)


def _make(cid: str, swap: bool):
    import ccxt

    return getattr(ccxt, cid)({"enableRateLimit": True, "timeout": 10000, "options": {"defaultType": "swap" if swap else "spot"}})


def client(ex: str, market: str):
    if not supports(ex, market):
        raise ExchangeError(f"{label(ex)} não tem {'futuros perpétuos' if market == 'futures' else 'spot'} neste sistema.")
    key = (ex, market)
    if key not in _clients:
        cid = EXCHANGES[ex][2] if market == "futures" else EXCHANGES[ex][1]
        _clients[key] = _make(cid, market == "futures")
    c = _clients[key]
    if time.time() - _markets_at.get(key, 0) > MARKETS_TTL:
        c.load_markets()
        _markets_at[key] = time.time()
    return c


def market_symbol(ex: str, market: str, symbol: str) -> str:
    """BTCUSDT → símbolo do ccxt na corretora (BTC/USDT, BTC/USDT:USDT, BTC/USD…). Erro se o par não existe lá."""
    symbol = symbol.upper().strip()
    c = client(ex, market)
    base = next((symbol[: -len(q)] for q in QUOTES if symbol.endswith(q)), None)
    if not base:
        raise ExchangeError(f"Par inválido: {symbol}")
    for q in QUOTES:
        cand = f"{base}/{q}:{q}" if market == "futures" else f"{base}/{q}"
        if cand in c.markets and c.markets[cand].get("active") is not False:
            return cand
    raise ExchangeError(f"{symbol} não existe em {label(ex)}.")


# ------------------------------------------------------------------------------ dados
def klines(ex: str, symbol: str, interval: str, limit: int, market: str):
    """Candles [ms, o, h, l, c, volume] mais antigos primeiro. Pagina quando a corretora limita o tamanho da resposta."""
    from core.data import INTERVAL_SECONDS

    c = client(ex, market)
    if interval not in (c.timeframes or {}):
        raise ExchangeError(f"{label(ex)} não oferece o tempo gráfico {interval}.")
    sym = market_symbol(ex, market, symbol)
    step = INTERVAL_SECONDS[interval] * 1000
    since = int(time.time() * 1000) - (limit + 2) * step
    rows: dict[int, list] = {}
    for _ in range(max(2, limit // 100 + 2)):
        batch = c.fetch_ohlcv(sym, interval, since=since, limit=min(limit, 1000))
        if not batch:
            break
        for r in batch:
            rows[int(r[0])] = r
        nxt = int(batch[-1][0]) + step
        if nxt <= since or len(rows) >= limit + 1 or nxt > time.time() * 1000:
            break
        since = nxt
    out = [rows[t] for t in sorted(rows)][-limit:]
    if not out:
        raise ExchangeError(f"{label(ex)} não devolveu candles de {symbol}.")
    return out


def ticker(ex: str, symbol: str, market: str):
    from core.data import Ticker

    c = client(ex, market)
    t = c.fetch_ticker(market_symbol(ex, market, symbol))
    last = float(t["last"])
    pct = t.get("percentage")
    if pct is None and t.get("open"):
        pct = (last / float(t["open"]) - 1) * 100
    return Ticker(symbol.upper(), last, float(pct or 0.0), float(t.get("high") or last), float(t.get("low") or last),
                  float(t.get("quoteVolume") or 0.0), f"{label(ex)} {'Perpétuo' if market == 'futures' else 'Spot'}")


def funding(ex: str, symbol: str) -> float | None:
    """Taxa de financiamento atual (em %) do perpétuo na corretora, ou None."""
    try:
        r = client(ex, "futures").fetch_funding_rate(market_symbol(ex, "futures", symbol))
        v = r.get("fundingRate")
        return None if v is None else float(v) * 100
    except Exception:  # noqa: BLE001
        return None


def _tickers(ex: str, market: str) -> dict:
    return client(ex, market).fetch_tickers()


def table(ex: str, market: str) -> dict[str, tuple[float, float, float]]:
    """{símbolo interno: (preço, %24h, volume em USDT)} de todos os pares cotados em USDT (em USD/USDC se a corretora só tem esses)."""
    c = client(ex, market)
    raw = _tickers(ex, market)
    counts = {q: sum(1 for m in c.markets.values() if m.get("quote") == q) for q in QUOTES}
    quote_pref = max(counts, key=counts.get)   # a moeda de cotação com mais pares (USDT na maioria; USD na Coinbase)
    out = {}
    for sym, t in raw.items():
        m = c.markets.get(sym) or {}
        if m.get("quote") != quote_pref or (market == "futures" and not m.get("swap")) or (market == "spot" and not m.get("spot")):
            continue
        if not t.get("last"):
            continue
        last = float(t["last"])
        pct = t.get("percentage")
        if pct is None and t.get("open"):
            pct = (last / float(t["open"]) - 1) * 100
        out[m["base"] + "USDT"] = (last, float(pct or 0.0), float(t.get("quoteVolume") or 0.0))
    return out


def symbols(ex: str, market: str) -> list[str]:
    """Pares da corretora do maior para o menor volume de 24 h."""
    t = table(ex, market)
    return [s for s, _ in sorted(((s, v[2]) for s, v in t.items()), key=lambda x: -x[1])]
