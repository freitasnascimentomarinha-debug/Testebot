"""Regras de alavancagem e liquidação no padrão da Binance.

* **Futuros USDⓈ-M**: faixas oficiais (``leverage brackets``) por par — a
  alavancagem máxima diminui conforme o tamanho da posição e cada faixa tem a
  sua taxa de margem de manutenção. Fonte: endpoint público do site da
  Binance; reserva: faixas da OKX; último recurso: faixas padrão.
* **Margem no spot** (Swing/Long): Binance Margin — Cruzada até 3× e Isolada
  até 10×, com liquidação quando o nível de margem chega a 1,1.

Fórmula de liquidação dos futuros (modo unidirecional, margem isolada), igual
à documentação da Binance::

    LP = (WB + cum − lado·qtd·entrada) / (qtd·MMR − lado·qtd)

onde WB é a margem disponível para a posição (isolada: a margem da posição;
cruzada: margem + saldo livre), ``cum`` a dedução de manutenção da faixa e
``lado`` = 1 (comprado) ou −1 (vendido).
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import requests

BINANCE_BRACKETS = "https://www.binance.com/bapi/futures/v1/friendly/future/common/brackets"
OKX_TIERS = "https://www.okx.com/api/v5/public/position-tiers"
CACHE_SECONDS = 6 * 3600

SPOT_MARGIN_MAX = {"Cruzada": 3, "Isolada": 10}
SPOT_LIQUIDATION_LEVEL = 1.1


@dataclass(frozen=True)
class Bracket:
    cap: float          # nocional máximo da faixa (USDT)
    max_leverage: int
    mmr: float          # taxa de margem de manutenção
    cum: float          # dedução de manutenção acumulada


DEFAULT_BRACKETS = (
    Bracket(50_000, 75, 0.0065, 0), Bracket(250_000, 50, 0.01, 175), Bracket(1_000_000, 25, 0.02, 2_675),
    Bracket(5_000_000, 10, 0.05, 32_675), Bracket(float("inf"), 5, 0.1, 282_675),
)

_cache: dict = {"time": 0.0, "data": {}, "source": ""}
_lock = threading.Lock()


def _load_binance() -> dict[str, tuple[Bracket, ...]]:
    resp = requests.get(BINANCE_BRACKETS, timeout=15)
    resp.raise_for_status()
    out = {}
    for item in resp.json()["data"]["brackets"]:
        out[item["symbol"]] = tuple(
            Bracket(float(b["bracketNotionalCap"]), int(b["maxOpenPosLeverage"]),
                    float(b["bracketMaintenanceMarginRate"]), float(b["cumFastMaintenanceAmount"]))
            for b in item["riskBrackets"])
    if not out:
        raise ValueError("lista vazia")
    return out


def _okx_brackets(symbol: str) -> tuple[Bracket, ...]:
    from core.data import okx_base

    base, mult = okx_base(symbol)
    data = requests.get(OKX_TIERS, params={"instType": "SWAP", "tdMode": "isolated", "instFamily": f"{base}-USDT"},
                        timeout=15).json()["data"]
    from core.data import okx_contract_value

    ct_val = okx_contract_value(symbol)
    price = None
    tiers = []
    cum = 0.0
    prev_cap, prev_mmr = 0.0, 0.0
    for t in data:
        if price is None:
            from core.data import get_ticker

            price = get_ticker(symbol, "futures").last
        cap = float(t["maxSz"]) * ct_val * price / mult
        mmr = float(t["mmr"])
        cum += prev_cap * (mmr - prev_mmr)
        tiers.append(Bracket(cap, int(float(t["maxLever"])), mmr, cum))
        prev_cap, prev_mmr = cap, mmr
    if not tiers:
        raise ValueError("sem faixas OKX")
    return tuple(tiers)


def brackets(symbol: str) -> tuple[tuple[Bracket, ...], str]:
    """Faixas do par e a fonte usada."""
    symbol = symbol.upper()
    with _lock:
        if time.time() - _cache["time"] > CACHE_SECONDS or not _cache["data"]:
            try:
                _cache.update(time=time.time(), data=_load_binance(), source="Binance")
            except Exception:  # noqa: BLE001
                _cache.update(time=time.time() - CACHE_SECONDS + 600, data={}, source="")
        if symbol in _cache["data"]:
            return _cache["data"][symbol], "Binance"
    try:
        return _okx_brackets(symbol), "OKX (reserva)"
    except Exception:  # noqa: BLE001
        return DEFAULT_BRACKETS, "padrão (sem conexão)"


def futures_symbols() -> list[str]:
    """Pares perpétuos USDT negociáveis na Binance Futuros."""
    brackets("BTCUSDT")  # garante o cache
    return sorted(s for s in _cache["data"] if s.endswith("USDT") and s.isalnum())


def max_leverage(symbol: str, market: str = "futures", margin_mode: str = "Isolada") -> int:
    if market != "futures":
        return SPOT_MARGIN_MAX.get(margin_mode, 3)
    return brackets(symbol)[0][0].max_leverage


def bracket_for(symbol: str, notional: float) -> Bracket:
    tiers = brackets(symbol)[0]
    return next((b for b in tiers if notional <= b.cap), tiers[-1])


def max_notional(symbol: str, leverage: float) -> float:
    """Maior posição permitida pela Binance para a alavancagem escolhida."""
    allowed = [b.cap for b in brackets(symbol)[0] if b.max_leverage >= leverage]
    return max(allowed) if allowed else 0.0


def liquidation_price(*, side: str, entry: float, qty: float, leverage: float, market: str, symbol: str,
                      margin_mode: str = "Isolada", free_balance: float = 0.0, fx: float = 1.0) -> float | None:
    if qty <= 0 or leverage <= 1 and market == "spot" and side == "BUY":
        return None
    notional = entry * qty
    if market == "futures":
        b = bracket_for(symbol, notional)
        wb = notional / leverage + (max(free_balance, 0.0) if margin_mode == "Cruzada" else 0.0)
        s = 1 if side == "BUY" else -1
        lp = (wb + b.cum - s * qty * entry) / (qty * b.mmr - s * qty)
        return max(lp, 0.0) if lp > 0 else None
    # Margem no spot: liquida quando ativos / dívida = 1,1
    if side == "BUY":
        borrowed = notional * (1 - 1 / leverage)
        return SPOT_LIQUIDATION_LEVEL * borrowed / qty if borrowed > 0 else None
    return entry * (1 + 1 / leverage) / SPOT_LIQUIDATION_LEVEL
