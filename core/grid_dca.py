"""Bots de grade (grid) e de preço médio (DCA): outra espécie de bot, com simulador próprio.

* **Grid**: quando o gráfico entra no contexto escolhido (ex.: lateral), monta uma grade de ``levels`` faixas de preço em volta do
  preço (largura em ATR). Cada faixa compra no degrau de baixo e vende no de cima: ganha um pouco a cada vai-e-vem. A grade termina
  se o preço romper o stop abaixo da faixa (vende tudo), se sair por cima (já vendeu tudo), se o gráfico virar tendência forte
  (opcional) ou no prazo máximo.
* **DCA**: no contexto escolhido, compra uma parte e, a cada queda de ``step`` %, compra mais (ordens de segurança cada vez maiores),
  baixando o preço médio. Vende tudo quando o preço passa o médio + ``tp`` %. Stop opcional abaixo da primeira compra e prazo máximo.

Só compra (spot ou futuros sem alavancagem). Taxas em todas as execuções. Dentro de cada vela o preço percorre
abertura → mínima → máxima → fechamento (vela de alta) ou abertura → máxima → mínima → fechamento (vela de baixa).
Cada sessão (uma grade ou um ciclo de DCA) vira uma "operação" com o resultado em USDT e em % do capital da sessão.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TREND = ("tendencia_alta", "tendencia_baixa", "rompimento_alta", "rompimento_baixa")

# Parâmetros escolhidos por busca em 200 dias de dados (treino nos dias antigos, teste nos 60 mais recentes e em moedas que a busca não viu).
# Nenhuma combinação ganhou em todos os cortes: grade em 15m e 4h e DCA em 1h ficaram negativos nas moedas novas, e o ranking diário mostra isso.
PRESETS = [
    {"id": "grid_lateral_15m_spot", "kind": "grid", "name": "🕸️ Grid Lateral 15m", "home": {"market": "spot", "interval": "15m"},
     "params": {'levels': 6, 'range_atr': 14.0, 'stop_pct': 10.0, 'max_days': 7, 'contexts': ['lateral', 'suporte_teste', 'resistencia_teste'], 'exit_on_trend': False},
     "specialty": "Grade larga em lateral e testes de suporte/resistência · 15m", "tip": "Poucos degraus bem espaçados: cada venda paga a taxa com folga. Liga só fora de tendência."},
    {"id": "grid_lateral_1h_spot", "kind": "grid", "name": "🕸️ Grid Lateral 1h", "home": {"market": "spot", "interval": "1h"},
     "params": {'levels': 6, 'range_atr': 14.0, 'stop_pct': 5.0, 'max_days': 21, 'contexts': ['lateral', 'suporte_teste', 'resistencia_teste'], 'exit_on_trend': False},
     "specialty": "Grade larga em lateral · 1h", "tip": "Na busca de 200 dias foi a grade mais consistente: ganhou no treino, no teste e nas moedas novas."},
    {"id": "grid_lateral_4h_spot", "kind": "grid", "name": "🕸️ Grid Lateral 4h", "home": {"market": "spot", "interval": "4h"},
     "params": {'levels': 6, 'range_atr': 8.0, 'stop_pct': 2.0, 'max_days': 21, 'contexts': ['lateral'], 'exit_on_trend': False},
     "specialty": "Grade em lateralizações longas · 4h", "tip": "Para lateralizações de semanas, com stop curto logo abaixo da grade."},
    {"id": "grid_lateral_15m_fut", "kind": "grid", "name": "🕸️ Grid Lateral 15m (Futuros)", "home": {"market": "futures", "interval": "15m"},
     "params": {'levels': 6, 'range_atr': 14.0, 'stop_pct': 10.0, 'max_days': 7, 'contexts': ['lateral', 'suporte_teste', 'resistencia_teste'], 'exit_on_trend': False},
     "specialty": "Grade comprada em lateral · perpétuo 15m", "tip": "Mesma grade do spot, no contrato perpétuo e sem alavancagem."},
    {"id": "grid_lateral_1h_fut", "kind": "grid", "name": "🕸️ Grid Lateral 1h (Futuros)", "home": {"market": "futures", "interval": "1h"},
     "params": {'levels': 6, 'range_atr': 14.0, 'stop_pct': 5.0, 'max_days': 21, 'contexts': ['lateral', 'suporte_teste', 'resistencia_teste'], 'exit_on_trend': False},
     "specialty": "Grade comprada em lateral · perpétuo 1h", "tip": "Grade larga no perpétuo, sem alavancagem."},
    {"id": "dca_lateral_15m_spot", "kind": "dca", "name": "🪜 DCA Lateral 15m", "home": {"market": "spot", "interval": "15m"},
     "params": {'so_count': 4, 'step_pct': 2.0, 'step_scale': 1.3, 'vol_scale': 1.7, 'tp_pct': 2.0, 'sl_pct': 25.0, 'max_days': 4, 'contexts': ['lateral', 'suporte_teste']},
     "specialty": "Preço médio em lateral e suporte · 15m", "tip": "Ordens espaçadas e stop distante: segura quedas fundas e sai com 2% sobre o médio."},
    {"id": "dca_recuperacao_1h_spot", "kind": "dca", "name": "🪜 DCA Lateral 1h", "home": {"market": "spot", "interval": "1h"},
     "params": {'so_count': 6, 'step_pct': 1.0, 'step_scale': 1.3, 'vol_scale': 1.7, 'tp_pct': 1.0, 'sl_pct': 8.0, 'max_days': 10, 'contexts': ['lateral', 'suporte_teste']},
     "specialty": "Preço médio em lateral e suporte · 1h", "tip": "Alvo curto de 1% sobre o médio; muitas saídas pequenas."},
    {"id": "dca_recuperacao_4h_spot", "kind": "dca", "name": "🪜 DCA Recuperação 4h", "home": {"market": "spot", "interval": "4h"},
     "params": {'so_count': 6, 'step_pct': 1.0, 'step_scale': 1.3, 'vol_scale': 1.7, 'tp_pct': 1.0, 'sl_pct': 25.0, 'max_days': 30, 'contexts': ['reversao_alta', 'pullback_alta', 'suporte_teste']},
     "specialty": "Preço médio em correções de alta · 4h", "tip": "Liga em pullbacks e reversões; na busca de 200 dias foi o DCA que ganhou também nas moedas novas."},
    {"id": "dca_recuperacao_1h_fut", "kind": "dca", "name": "🪜 DCA Lateral 1h (Futuros)", "home": {"market": "futures", "interval": "1h"},
     "params": {'so_count': 6, 'step_pct': 1.0, 'step_scale': 1.3, 'vol_scale': 1.7, 'tp_pct': 1.0, 'sl_pct': 8.0, 'max_days': 10, 'contexts': ['lateral', 'suporte_teste']},
     "specialty": "Preço médio comprado · perpétuo 1h", "tip": "O mesmo DCA no perpétuo, sem alavancagem."},
]
_BY_ID = {p["id"]: p for p in PRESETS}
PARAM_LABELS = {"levels": "Degraus da grade", "range_atr": "Largura (± ATR)", "stop_pct": "Stop abaixo da grade (%)", "max_days": "Prazo máximo (dias)",
                "so_count": "Ordens de segurança", "step_pct": "Queda até a 1ª ordem (%)", "step_scale": "Aumento do degrau", "vol_scale": "Aumento do tamanho",
                "tp_pct": "Alvo sobre o preço médio (%)", "sl_pct": "Stop abaixo da 1ª compra (%)"}


def get(pid: str | None) -> dict | None:
    p = _BY_ID.get(pid or "")
    return None if p is None else {**p, "builtin": True, "bot": "swing" if p["home"]["market"] == "spot" else "day", "markets": [p["home"]["market"]]}


def all_bots() -> list[dict]:
    return [get(p["id"]) for p in PRESETS]


def describe(p: dict) -> str:
    q = p["params"]
    from core import regime

    ctx = ", ".join(regime.label(c) for c in q.get("contexts") or []) or "qualquer contexto"
    if p["kind"] == "grid":
        return (f"Grade de {q['levels']} degraus em ±{q['range_atr']:g} ATR do preço, ligada em: {ctx}. Stop {q['stop_pct']:g}% abaixo da grade, "
                f"prazo de {q['max_days']} dias" + (", desmonta se virar tendência." if q.get("exit_on_trend") else "."))
    return (f"Compra inicial + {q['so_count']} ordens de segurança (1ª a −{q['step_pct']:g}%, degraus ×{q['step_scale']:g}, tamanhos ×{q['vol_scale']:g}), "
            f"alvo de {q['tp_pct']:g}% sobre o preço médio, stop {q['sl_pct']:g}% abaixo da 1ª compra, prazo de {q['max_days']} dias. Ligado em: {ctx}.")


def _path(o, h, l, c):
    return (o, l, h, c) if c >= o else (o, h, l, c)


def _per_day(interval: str) -> float:
    from core.fastsim import PER_DAY

    return PER_DAY[interval]


# ------------------------------------------------------------------------------ grade
def simulate_grid(vt: pd.DataFrame, q: dict, interval: str, fee_pct: float, *, start_time=None, capital: float = 1000.0,
                  warmup: int = 210) -> dict:
    """Simula sessões de grade em sequência. Devolve {trades, curve, cycles} (curve: [tempo, patrimônio] por vela)."""
    o, h, l, c = (vt[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
    atr, reg, times = vt["atr"].to_numpy(dtype=float), vt["regime"].to_numpy(), vt["time"]
    fee = fee_pct / 100
    n = len(c)
    i = warmup if start_time is None else max(warmup, int(times.searchsorted(start_time)))
    max_bars = int(q["max_days"] * _per_day(interval))
    ctxs = set(q.get("contexts") or [])
    eq, trades, curve, cycles = capital, [], [], 0
    while i < n - 1:
        curve.append([times.iloc[i], eq])
        if (ctxs and reg[i] not in ctxs) or not np.isfinite(atr[i]):
            i += 1
            continue
        price, half = c[i], atr[i] * float(q["range_atr"])
        lower, upper = price - half, price + half
        if lower <= 0:
            i += 1
            continue
        lv = np.geomspace(lower, upper, int(q["levels"]) + 1)
        slot_usd = eq / int(q["levels"])
        holding = np.zeros(int(q["levels"]), dtype=bool)
        qty = np.zeros(int(q["levels"]))
        cash, start_eq, t0, made = eq, eq, times.iloc[i + 1], 0
        stop = lower * (1 - float(q["stop_pct"]) / 100)
        for j in range(len(holding)):          # degraus acima do preço: compra já (para poder vender subindo)
            if lv[j] >= price:
                qty[j] = slot_usd / price
                cash -= slot_usd * (1 + fee)
                holding[j] = True
        k, why, exit_px = i + 1, "Prazo", None
        while k < n:
            pts = _path(o[k], h[k], l[k], c[k])
            for a, b in zip(pts, pts[1:]):
                if b < a:   # descendo: compras nos degraus atravessados, depois o stop
                    for j in np.where(~holding & (lv[:-1] <= a) & (lv[:-1] >= b))[0]:
                        qty[j] = slot_usd / lv[j]
                        cash -= slot_usd * (1 + fee)
                        holding[j] = True
                    if b <= stop:
                        exit_px, why = stop, "Stop da grade"
                        break
                else:       # subindo: vendas no degrau de cima
                    for j in np.where(holding & (lv[1:] >= a) & (lv[1:] <= b))[0]:
                        cash += qty[j] * lv[j + 1] * (1 - fee)
                        qty[j], holding[j] = 0.0, False
                        made += 1
            if exit_px is not None:
                break
            if c[k] > upper and not holding.any():
                exit_px, why = c[k], "Saiu por cima"
                break
            if q.get("exit_on_trend") and reg[k] in TREND:
                exit_px, why = c[k], "Virou tendência"
                break
            if k - i >= max_bars:
                exit_px, why = c[k], "Prazo"
                break
            curve.append([times.iloc[k], cash + qty.sum() * c[k]])
            k += 1
        if exit_px is None:
            exit_px, k = c[n - 1], n - 1
        cash += qty.sum() * exit_px * (1 - fee)
        eq = cash
        cycles += made
        pnl = eq - start_eq
        trades.append({"entrada": t0, "saida": times.iloc[min(k, n - 1)], "lado": "Grade", "preco_entrada": price, "preco_saida": exit_px,
                       "motivo": f"{why} · {made} ciclos", "r": pnl / start_eq * 100, "resultado": pnl, "ciclos": made})
        i = k + 1
    curve.append([times.iloc[n - 1], eq])
    return {"trades": trades, "curve": curve, "cycles": cycles, "final": eq, "capital": capital}


# ------------------------------------------------------------------------------ DCA
def dca_plan(q: dict) -> tuple[list[float], list[float]]:
    """Quedas acumuladas (%) de cada ordem e a fração do capital de cada uma (a 1ª é a compra inicial)."""
    n = int(q["so_count"])
    devs, d, step = [0.0], 0.0, float(q["step_pct"])
    for s in range(n):
        d += step * float(q["step_scale"]) ** s
        devs.append(d)
    sizes = [1.0] + [float(q["vol_scale"]) ** (s + 1) for s in range(n)]
    tot = sum(sizes)
    return devs, [x / tot for x in sizes]


def simulate_dca(vt: pd.DataFrame, q: dict, interval: str, fee_pct: float, *, start_time=None, capital: float = 1000.0,
                 warmup: int = 210) -> dict:
    o, h, l, c = (vt[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
    reg, times = vt["regime"].to_numpy(), vt["time"]
    fee = fee_pct / 100
    n = len(c)
    i = warmup if start_time is None else max(warmup, int(times.searchsorted(start_time)))
    max_bars = int(q["max_days"] * _per_day(interval))
    ctxs = set(q.get("contexts") or [])
    devs, fracs = dca_plan(q)
    eq, trades, curve = capital, [], []
    while i < n - 2:
        curve.append([times.iloc[i], eq])
        if ctxs and reg[i] not in ctxs:
            i += 1
            continue
        base = o[i + 1]
        levels = [base * (1 - d / 100) for d in devs]
        start_eq = eq
        coins, cost = start_eq * fracs[0] / base, start_eq * fracs[0]   # compra inicial na abertura da vela seguinte ao sinal
        cash, filled = start_eq - cost * (1 + fee), 1
        sl = base * (1 - float(q["sl_pct"]) / 100) if q.get("sl_pct") else -np.inf
        t0, k, why, exit_px = times.iloc[i + 1], i + 1, "Prazo", None
        while k < n:
            pts = _path(o[k], h[k], l[k], c[k])
            for a, b in zip(pts[:-1], pts[1:]):
                if b < a:   # descendo: ordens de segurança atravessadas, depois o stop
                    while filled < len(levels) and levels[filled] >= b:
                        usd = start_eq * fracs[filled]
                        coins += usd / levels[filled]
                        cost += usd
                        cash -= usd * (1 + fee)
                        filled += 1
                    if b <= sl:
                        exit_px, why = sl, "Stop"
                        break
                else:       # subindo: alvo sobre o preço médio
                    tp = cost / coins * (1 + float(q["tp_pct"]) / 100)
                    if a <= tp <= b:
                        exit_px, why = tp, "Alvo"
                        break
            if exit_px is not None:
                break
            if k - (i + 1) >= max_bars:
                exit_px, why = c[k], "Prazo"
                break
            curve.append([times.iloc[k], cash + coins * c[k]])
            k += 1
        if exit_px is None:
            exit_px, k = c[n - 1], n - 1
        cash += coins * exit_px * (1 - fee)
        eq = cash
        pnl = eq - start_eq
        trades.append({"entrada": t0, "saida": times.iloc[min(k, n - 1)], "lado": "DCA", "preco_entrada": cost / coins if coins else base,
                       "preco_saida": exit_px, "motivo": f"{why} · {filled - 1} ordens de segurança", "r": pnl / start_eq * 100,
                       "resultado": pnl, "ordens": filled})
        i = k + 1
    curve.append([times.iloc[n - 1], eq])
    return {"trades": trades, "curve": curve, "final": eq, "capital": capital}


def simulate(p: dict, vt: pd.DataFrame, interval: str, fee_pct: float, **kw) -> dict:
    return (simulate_grid if p["kind"] == "grid" else simulate_dca)(vt, p["params"], interval, fee_pct, **kw)


def period_summary(p: dict, votes: dict, market: str, days: float, interval: str) -> dict:
    """Mesmo formato de ``ranking.simulate_bot`` (para o ranking diário): retorno médio das moedas, queda, acerto e sessões."""
    per, wins, n, dds, by_ctx = [], 0, 0, [], {}
    for sym, (vt, cfg) in votes.items():
        start = vt["time"].iloc[-1] - pd.Timedelta(days=days)
        res = simulate(p, vt, interval, float(cfg["fee_pct"]), start_time=start)
        eqs = np.array([e for _, e in res["curve"]]) if res["curve"] else np.array([res["capital"]])
        peak = np.maximum.accumulate(eqs)
        dds.append(float(np.max((peak - eqs) / peak) * 100) if len(eqs) else 0.0)
        per.append((sym, float((res["final"] / res["capital"] - 1) * 100)))
        n += len(res["trades"])
        wins += int(sum(t["resultado"] > 0 for t in res["trades"]))
        for t in res["trades"]:
            i = max(0, int(vt["time"].searchsorted(t["entrada"])) - 1)
            by_ctx.setdefault(str(vt["regime"].iloc[i]), []).append(float(t["r"]))
    ret = float(np.mean([r for _, r in per])) if per else 0.0
    return {"ret_pct": round(ret, 2), "monthly_pct": round(ret * 30 / days, 2), "dd_pct": round(max(dds, default=0.0), 1),
            "win_pct": round(wins / n * 100, 1) if n else 0.0, "trades": n, "positive": int(sum(r > 0 for _, r in per)), "symbols": len(per),
            "per_symbol": {s: round(r, 2) for s, r in per},
            "contexts": {k: {"n": len(v), "avg_r": round(float(np.mean(v)), 3), "win_pct": round(float(np.mean([x > 0 for x in v]) * 100), 1)}
                         for k, v in by_ctx.items()}}
