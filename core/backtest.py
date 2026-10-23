"""Backtest rápido de uma personalidade sobre candles reais.

Simula as habilidades de programação (sem chamar a IA, para não gastar
tokens): a cada candle fechado, se não houver posição e o plano indicar
entrada, entra na abertura do candle seguinte; stop e alvo são verificados
com máximas e mínimas (stop primeiro quando ambos cabem no mesmo candle);
posições abertas há mais de ``max_hold`` candles saem no fechamento.

Resultados em R (múltiplos do risco), o que torna o teste independente do
tamanho da banca: +2R = ganhou 2× o que arriscou.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from core import indicators as ind
from core.profiles import BotProfile
from core.strategy import analyze
from core.trail import step as trail_step


def run(df_raw: pd.DataFrame, cfg: dict, profile: BotProfile, personality: dict, *, fee_pct: float | None = None,
        max_hold: int = 100, warmup: int = 210, htf_raw: pd.DataFrame | None = None,
        mtf_raw: pd.DataFrame | None = None) -> dict:
    df = ind.compute(df_raw, cfg).reset_index(drop=True)
    if htf_raw is not None or mtf_raw is not None:
        from core.htf import attach

        df = attach(df, htf_raw, cfg["interval"], mtf_raw)
    fee = (cfg["fee_pct"] if fee_pct is None else fee_pct) / 100
    cfg_bt = {**cfg, "allow_short": True, "leverage_on": True}  # direção é controlada pela personalidade
    trades: list[dict] = []
    pos = None
    i = warmup
    n = len(df)
    while i < n - 1:
        row = df.iloc[i]
        if pos:
            long = pos["side"] == "BUY"
            hit_sl = row.low <= pos["sl"] if long else row.high >= pos["sl"]
            hit_tp = row.high >= pos["tp"] if long else row.low <= pos["tp"]
            exit_price, reason = None, None
            if hit_sl:
                exit_price, reason = pos["sl"], "Stop" if not pos["trail"] else "Stop móvel"
            elif pos["trail"]:
                pos["sl"], pos["best"] = trail_step(1 if long else -1, pos["entry"], pos["sl"], pos["best"], row.high,
                                                    row.low, pos["trail"], pos["risk"], pos["be_r"], fee)
            elif hit_tp:
                exit_price, reason = pos["tp"], "Alvo"
            elif i - pos["i"] >= max_hold and not pos["trail"]:
                exit_price, reason = row.close, "Tempo"
            if exit_price is not None:
                sign = 1 if long else -1
                risk = pos["risk"]
                r = (sign * (exit_price - pos["entry"]) - fee * (pos["entry"] + exit_price)) / risk
                trades.append({"entrada": pos["time"], "saida": row.time, "lado": "Compra" if long else "Venda",
                               "preco_entrada": pos["entry"], "preco_saida": exit_price, "motivo": reason, "r": r})
                pos = None
            i += 1
            continue
        plan = analyze(df.iloc[: i + 1], cfg_bt, profile, personality, live=False)
        if plan.direction in ("BUY", "SELL") and plan.stop_loss:
            nxt = df.iloc[i + 1]
            entry = float(nxt.open)
            sign = 1 if plan.direction == "BUY" else -1
            sl_dist = abs(plan.entry - plan.stop_loss)
            tp_dist = abs(plan.take_profit - plan.entry) if plan.take_profit else 0.0
            pos = {"side": plan.direction, "entry": entry, "sl": entry - sign * sl_dist, "tp": entry + sign * tp_dist,
                   "i": i + 1, "time": nxt.time, "risk": sl_dist, "trail": plan.trail_dist or 0.0,
                   "be_r": plan.be_r, "best": entry}
            i += 1  # o candle de entrada já é verificado no próximo laço
            continue
        i += 1

    rs = [t["r"] for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    equity, peak, max_dd = 0.0, 0.0, 0.0
    curve = []
    for t in trades:
        equity += t["r"]
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
        curve.append({"time": t["saida"], "r_acumulado": equity})
    return {
        "personality": personality["id"], "personality_name": personality["name"], "symbol": cfg["symbol"],
        "interval": cfg["interval"], "market": profile.market, "candles": n,
        "period": f"{df.time.iloc[warmup]:%d/%m/%Y} a {df.time.iloc[-1]:%d/%m/%Y}",
        "trades": len(trades), "win_rate": len(wins) / len(rs) * 100 if rs else 0.0,
        "avg_r": sum(rs) / len(rs) if rs else 0.0, "total_r": sum(rs),
        "profit_factor": sum(wins) / abs(sum(losses)) if losses and sum(losses) else None,
        "max_dd_r": max_dd, "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "detail": trades, "curve": curve,
    }


PER_DAY = {"5m": 288, "15m": 96, "30m": 48, "1h": 24, "4h": 6, "1d": 1}


def compound(rs: list[float], risk_pct: float = 1.0) -> tuple[float, float]:
    """Retorno composto (%) e pior queda da banca (%) arriscando ``risk_pct``
    da banca em cada operação: cada operação multiplica a banca por
    (1 + risco × R). Ex.: +2R com 1% de risco → +2%; stop (−1R) → −1%."""
    equity = peak = 1.0
    max_dd = 0.0
    for r in rs:
        equity *= max(0.0, 1 + risk_pct / 100 * r)
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak)
    return (equity - 1) * 100, max_dd * 100


def period_return(df_raw: pd.DataFrame, cfg: dict, profile: BotProfile, personality: dict, *, days: int = 40,
                  risk_pct: float = 1.0) -> dict:
    """Backtest restrito aos últimos ``days`` dias (o restante serve de aquecimento
    dos indicadores) e o retorno composto correspondente."""
    window = days * PER_DAY[cfg["interval"]]
    res = run(df_raw, cfg, profile, personality, warmup=max(210, len(df_raw) - window))
    ret, dd = compound([t["r"] for t in res["detail"]], risk_pct)
    return {"symbol": cfg["symbol"], "trades": res["trades"], "win_rate": res["win_rate"], "avg_r": res["avg_r"],
            "total_r": res["total_r"], "return_pct": ret, "max_dd_pct": dd, "period": res["period"]}
