"""Valida a carteira comprovada (core/portfolio.py) em três períodos e salva os números em core/portfolio_bots.json.

    python tools/pesquisa/validar_carteira.py

Cada bot é simulado com ``core/fastsim.py`` (as mesmas regras do robô, com taxas) nas 10 moedas da varredura:

* jun–dez/2025 e mai–out/2026: períodos que a escolha dos bots não usou;
* dez/2025–mai/2026: período em que a família de rompimento foi escolhida (referência).

Também simula a carteira inteira (os bots juntos, risco de 1% da banca por operação). Precisa de acesso à Binance.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core import data, fastsim, portfolio, ranking  # noqa: E402
from core.backtest import compound  # noqa: E402

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "ADAUSDT", "LINKUSDT", "AVAXUSDT", "LTCUSDT"]
PERIODS = [  # (rótulo, início, fim, fora da escolha?)
    ("jun–dez/2025", "2025-06-28", "2025-12-26", True),
    ("dez/2025–mai/2026", "2025-12-26", "2026-05-30", False),
    ("mai–out/2026", "2026-05-30", "2026-10-20", True),
]
DAYS = 495


def _ts(x: str) -> pd.Timestamp:
    return pd.Timestamp(x, tz="UTC")


def trades_in(vt: pd.DataFrame, cfg: dict, p: dict, t0: str, t1: str) -> list[dict]:
    return [t for t in fastsim.simulate(vt, p, cfg, start_time=_ts(t0)) if t["entrada"] < _ts(t1)]


def research_block(p: dict, votes: dict, interval: str) -> dict:
    validation, per_symbol, all_rs, dds = [], {}, [], []
    for label, t0, t1, oos in PERIODS:
        rets, rs, pos = [], [], 0
        for sym, (vt, cfg) in votes.items():
            r = [t["r"] for t in trades_in(vt, cfg, p, t0, t1)]
            ret, dd = compound(r, 1.0) if r else (0.0, 0.0)
            rets.append(ret)
            dds.append(dd)
            pos += ret > 0
            rs += r
            per_symbol.setdefault(sym, []).extend(r)
        months = (_ts(t1) - _ts(t0)).days / 30.4
        ret = float(np.mean(rets))
        validation.append({"label": label, "out_of_sample": oos, "trades": len(rs), "win_pct": round(float(np.mean([x > 0 for x in rs]) * 100), 1),
                           "avg_r": round(float(np.mean(rs)), 3), "ret_pct": round(ret, 2),
                           "monthly_pct": round(((1 + ret / 100) ** (1 / months) - 1) * 100, 2), "pos_coins": f"{pos}/{len(votes)}"})
        all_rs += rs
    total_months = sum((_ts(t1) - _ts(t0)).days / 30.4 for _, t0, t1, _ in PERIODS)
    ps = {s: round(compound(r, 1.0)[0], 2) for s, r in per_symbol.items()}
    return {"period_label": "16 meses em 3 períodos", "period_days": int(total_months * 30.4),
            "monthly_pct": round(float(np.mean([v["monthly_pct"] for v in validation])), 2),
            "ret_pct": round(float(np.mean(list(ps.values()))), 2), "win_pct": round(float(np.mean([x > 0 for x in all_rs]) * 100), 1),
            "dd_pct": round(max(dds, default=0.0), 1), "trades_month": round(len(all_rs) / len(votes) / total_months, 1),
            "pos_coins": f"{sum(v > 0 for v in ps.values())}/{len(ps)}", "per_symbol": ps, "status": "aprovado",
            "market": "futures", "interval": interval, "contexts": {}, "best_contexts": [], "validation": validation,
            "tested_at": pd.Timestamp.now(tz="UTC").strftime("%d/%m/%Y"), "portfolio": True}


def portfolio_sim(trades: list[dict], risk_pct: float = portfolio.RISK_PCT) -> dict:
    """Banca de 100 com os bots juntos: risco de ``risk_pct`` da banca no momento da entrada; resultado somado no fechamento."""
    ev = sorted([(t["entrada"], 0, i) for i, t in enumerate(trades)] + [(t["saida"], 1, i) for i, t in enumerate(trades)],
                key=lambda e: (e[0], e[1]))
    bank, risk, eq = 100.0, {}, []
    for when, kind, i in ev:
        if kind == 0:
            risk[i] = bank * risk_pct / 100
        else:
            bank += risk[i] * trades[i]["r"]
            eq.append((when, bank))
    e = pd.Series([b for _, b in eq], index=pd.DatetimeIndex([t for t, _ in eq]))
    out = {"final": round(float(e.iloc[-1]), 2), "periods": []}
    for label, t0, t1, oos in PERIODS:
        before = e[e.index < _ts(t0)]
        start = float(before.iloc[-1]) if len(before) else 100.0
        seg = e[(e.index >= _ts(t0)) & (e.index < _ts(t1))]
        out["periods"].append({"label": label, "out_of_sample": oos,
                               "ret_pct": round((float(seg.iloc[-1]) / start - 1) * 100, 1) if len(seg) else 0.0})
    m = e.resample("ME").last().ffill()
    ms = (m.to_numpy() / np.r_[100.0, m.to_numpy()[:-1]] - 1) * 100
    peak = e.cummax()
    out.update({"dd_pct": round(float(((peak - e) / peak).max() * 100), 1), "months": len(ms), "months_up": int((ms > 0).sum()),
                "median_month_pct": round(float(np.median(ms)), 2), "worst_month_pct": round(float(ms.min()), 1), "risk_pct": risk_pct})
    return out


def main() -> None:
    cache: dict = {}

    def getter(sym, itv, n, mk):
        k = (sym, itv)
        if k not in cache or len(cache[k]) < n:
            cache[k] = data.get_klines(sym, itv, n, mk)
        return cache[k].tail(n).reset_index(drop=True)

    research, all_trades = {}, []
    for d, p in zip(portfolio.DEFINITIONS, portfolio.personalities()):
        votes = {}
        for sym in SYMBOLS:
            votes[sym] = ranking.votes_for(sym, d["interval"], d["market"], DAYS, getter)
            print(f"{d['interval']} {sym} pronto", flush=True)
        research[d["id"]] = research_block(p, votes, d["interval"])
        for sym, (vt, cfg) in votes.items():
            all_trades += trades_in(vt, cfg, p, PERIODS[0][1], PERIODS[-1][2])
        print(d["name"], json.dumps(research[d["id"]]["validation"], ensure_ascii=False), flush=True)
    out = {"generated": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"), "research": research,
           "portfolio": {"futures": portfolio_sim(all_trades)}}
    portfolio.FILE.write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print("carteira:", json.dumps(out["portfolio"], ensure_ascii=False))


if __name__ == "__main__":
    main()
