"""Ranking semanal automático dos bots.

A cada 7 dias, para o mercado (futuros ou spot) e o tempo gráfico em que o bot está operando, todos os bots treinados ali são
simulados de novo sobre os candles mais recentes (5 moedas, as mesmas da página Personalidades). O resultado — retorno, queda
máxima, acerto, selo e desempenho por contexto de mercado — substitui a pesquisa antiga na hora de escolher o bot: assim o
ranking acompanha a performance real do mercado e as estratégias se adaptam quando o mercado muda.

Dados insuficientes (poucas operações na janela) não derrubam um bot: ele mantém o selo da pesquisa original.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import numpy as np

from core import fastsim, htf, personalities as P
from core.settings import default_settings
from core.profiles import PROFILES
from core.storage import load_json, locked_update

RANK_FILE = "weekly_ranking.json"
MAX_AGE_DAYS = 7
MIN_TRADES = 12          # operações (somando as moedas) para o resultado semanal valer mais que a pesquisa original
# Janela simulada por tempo gráfico: o suficiente para haver operações sem baixar milhares de candles
WINDOW_DAYS = {"1m": 3, "3m": 7, "5m": 10, "15m": 30, "30m": 30, "1h": 40, "2h": 60, "4h": 90, "6h": 120, "12h": 180,
               "1d": 365, "3d": 365, "1w": 365}


def _key(market: str, interval: str) -> str:
    return f"{market}|{interval}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def load() -> dict:
    return load_json(RANK_FILE, {}) or {}


def entry(market: str, interval: str) -> dict | None:
    return load().get(_key(market, interval))


def age_days(market: str, interval: str, now: datetime | None = None) -> float | None:
    e = entry(market, interval)
    if not e:
        return None
    return ((now or _now()) - datetime.fromisoformat(e["updated"])).total_seconds() / 86400


def is_stale(market: str, interval: str, now: datetime | None = None) -> bool:
    age = age_days(market, interval, now)
    return age is None or age >= MAX_AGE_DAYS


def next_update(market: str, interval: str) -> datetime | None:
    e = entry(market, interval)
    return datetime.fromisoformat(e["updated"]) + timedelta(days=MAX_AGE_DAYS) if e else None


# ------------------------------------------------------------------------------ cálculo
def votes_for(symbol: str, interval: str, market: str, days: float, getter):
    """Votos de todas as habilidades nos últimos ``days`` dias (+ aquecimento) — calculado uma vez por moeda."""
    cfg = {**default_settings(PROFILES[fastsim.bot_for(market, interval)]), "symbol": symbol, "interval": interval}
    n = int(days * fastsim.PER_DAY[interval]) + 260
    raw = getter(symbol, interval, n, market)
    try:  # tendência dos tempos maiores (para os bots com esses filtros)
        htf_raw = getter(symbol, htf.HTF_OF[interval], htf.htf_candles(interval, n), market)
    except Exception:  # noqa: BLE001
        htf_raw = None
    try:
        mtf_raw = (getter(symbol, htf.MTF_OF[interval], int(n * htf.SECONDS[interval] / htf.SECONDS[htf.MTF_OF[interval]])
                          + htf.CANDLES_NEEDED, market) if interval in htf.MTF_OF else None)
    except Exception:  # noqa: BLE001
        mtf_raw = None
    return fastsim.prepare(raw, cfg, htf_raw, mtf_raw), cfg


def simulate_bot(votes: dict, persona: dict, market: str, days: float, risk_pct: float = 1.0) -> dict:
    """Resultado do bot nas moedas já calculadas: retorno médio, queda, acerto e R médio por contexto de mercado."""
    from core.backtest import compound

    per_symbol, by_ctx = [], {}
    for sym, (vt, cfg) in votes.items():
        trades = fastsim.period_trades(vt, cfg, persona, days=days, market=market)
        rs = [t["r"] for t in trades]
        ret, dd = compound(rs, risk_pct)
        per_symbol.append({"symbol": sym, "ret": float(ret), "dd": float(dd), "trades": len(rs), "wins": sum(r > 0 for r in rs)})
        times = vt["time"]
        regimes = vt["regime"].to_numpy()
        for t in trades:  # contexto do candle em que o sinal fechou (o anterior à entrada)
            i = max(0, int(times.searchsorted(t["entrada"])) - 1)
            by_ctx.setdefault(str(regimes[i]), []).append(t["r"])
    n_tr = sum(r["trades"] for r in per_symbol)
    ret = float(np.mean([r["ret"] for r in per_symbol])) if per_symbol else 0.0
    return {
        "ret_pct": round(ret, 2), "monthly_pct": round(ret * 30 / days, 2), "dd_pct": round(max((r["dd"] for r in per_symbol), default=0.0), 1),
        "win_pct": round(sum(r["wins"] for r in per_symbol) / n_tr * 100, 1) if n_tr else 0.0, "trades": n_tr,
        "positive": sum(r["ret"] > 0 for r in per_symbol), "symbols": len(per_symbol),
        "per_symbol": {r["symbol"]: round(r["ret"], 2) for r in per_symbol},
        "contexts": {c: {"n": len(v), "avg_r": round(float(np.mean(v)), 3), "win_pct": round(float(np.mean([x > 0 for x in v]) * 100), 1),
                         "ret_pct": round(compound(v)[0], 2)} for c, v in by_ctx.items()},
    }


def status_of(res: dict, previous: str | None) -> str | None:
    """Selo semanal. Com poucas operações a janela não prova nada: vale o selo anterior."""
    if res["trades"] < MIN_TRADES:
        return previous
    if res["ret_pct"] > 0 and res["positive"] >= max(1, round(res["symbols"] * 0.6)):
        return "aprovado"
    return "ressalva" if res["ret_pct"] > 0 else "fraco"


def refresh(market: str, interval: str, getter=None, progress=None) -> dict:
    """Recalcula e salva o ranking semanal de todos os bots treinados neste mercado e tempo gráfico."""
    if getter is None:
        from core.data import get_klines as getter
    days = WINDOW_DAYS.get(interval, 30)
    bots = [p for p in P.BUILTINS if (p.get("research") or {}).get("market") == market and p["research"].get("interval") == interval]
    votes = {}
    for k, sym in enumerate(P.PERIOD_SYMBOLS, start=1):
        try:
            votes[sym] = votes_for(sym, interval, market, days, getter)
        except Exception:  # noqa: BLE001 - moeda sem dados agora: segue com as outras
            continue
        if progress:
            progress(k / len(P.PERIOD_SYMBOLS) * 0.7, f"Candles de {sym} prontos")
    if not votes:
        raise RuntimeError("Sem candles para atualizar o ranking agora.")
    results = {}
    for k, p in enumerate(bots, start=1):
        res = simulate_bot(votes, p, market, days)
        res["status"] = status_of(res, p["research"].get("status"))
        results[p["id"]] = res
        if progress:
            progress(0.7 + 0.3 * k / max(len(bots), 1), p["name"])
    order = sorted(results, key=lambda i: -results[i]["monthly_pct"])
    rec = {"updated": _now().isoformat(timespec="seconds"), "days": days, "symbols": list(votes), "results": results, "order": order}

    def _apply(data):
        data[_key(market, interval)] = rec

    locked_update(RANK_FILE, {}, _apply)
    return rec


_failed_at: dict[str, float] = {}
RETRY_AFTER = 3600  # após uma falha (ex.: sem candles agora), só tenta de novo daqui a 1 hora


def refresh_if_stale(market: str, interval: str, getter=None, progress=None) -> bool:
    """Atualiza o ranking quando passou uma semana. Devolve True se recalculou; nunca derruba quem chama."""
    key = _key(market, interval)
    if not is_stale(market, interval) or time.time() - _failed_at.get(key, 0) < RETRY_AFTER:
        return False
    try:
        refresh(market, interval, getter, progress)
        _failed_at.pop(key, None)
        return True
    except Exception:  # noqa: BLE001 - sem rede: tenta de novo mais tarde
        _failed_at[key] = time.time()
        return False


# ------------------------------------------------------------------------------ uso na escolha do bot
def overlay(p: dict, rank: dict | None = None) -> dict:
    """A pesquisa do bot com os números da última atualização semanal por cima (quando houver amostra suficiente)."""
    rs = p.get("research") or {}
    if not rs or p.get("portfolio"):   # carteira comprovada: vale a validação em três períodos, não a janela de 40 dias
        return p
    e = (rank if rank is not None else load()).get(_key(rs.get("market", ""), rs.get("interval", "")))
    res = (e or {}).get("results", {}).get(p["id"])
    if not res or res["trades"] < MIN_TRADES:
        return p
    fresh = {**rs, "ret_pct": res["ret_pct"], "monthly_pct": res["monthly_pct"], "win_pct": res["win_pct"], "dd_pct": res["dd_pct"],
             "status": res["status"] or rs.get("status"), "contexts": {**(rs.get("contexts") or {}), **res["contexts"]},
             "period_label": f"últimos {e['days']:g} dias", "tested_at": e["updated"][:10], "weekly": True}
    return {**p, "research": fresh}


def leaderboard(market: str, interval: str, top: int = 5) -> list[dict]:
    """Os melhores bots do ranking semanal (para exibir)."""
    e = entry(market, interval)
    if not e:
        return []
    rows = []
    for pid in e["order"][:top]:
        p = P.get(pid)
        if p:
            rows.append({"id": pid, "name": p["name"], **e["results"][pid]})
    return rows
