"""Pesquisa de bots por contexto de mercado (backtest).

Para cada mercado (futuros e spot), tempo gráfico (5m, 15m, 1h, 4h), contexto do gráfico e lado (comprado/vendido) procura, em
candles reais, um bot que dê **resultado positivo naquele contexto** — e só publica o que passar nas três provas:

1. **Busca**: primeiros 2/3 do período, nas 6 moedas de maior volume;
2. **Validação**: último 1/3 do período, nas mesmas 6 moedas;
3. **Prova final**: as 4 moedas seguintes em volume, que não participaram da escolha.

Aprovado = R médio por operação positivo nas três provas, amostra mínima em cada uma, retorno composto (1% de risco por operação,
com taxas) positivo na busca e na validação e a maioria das moedas no verde. Célula sem candidato que passe fica **sem bot** (é
relatado, nunca preenchido com um bot ruim).

Contextos: lateralidade, tendência, reversão, rompimento, suporte/resistência e fluxo de ordens. O "livro de ofertas" histórico não
existe para backtest; o fluxo de ordens usa o **volume comprador/vendedor agressivo** (taker) que a Binance informa em cada candle.
O spot só opera comprado (não há venda a descoberto).

Uso: ``python tools/pesquisa/gerar_bots.py`` (precisa de acesso à Binance). A lógica fica aqui para ser testada.
"""
from __future__ import annotations

import itertools
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from core import fastsim, ranking
from core.backtest import compound

OUT_FILE = Path(__file__).resolve().parent / "context_bots.json"
AUTHOR = "Pesquisa por contexto · out/2026"
INTERVALS = ("5m", "15m", "1h", "4h")
MARKET_SIDES = {"futures": ("long", "short"), "spot": ("long",)}
DAYS = {"5m": 60, "15m": 120, "1h": 240, "4h": 540}          # período de backtest por tempo gráfico
N_SEARCH, N_UNSEEN = 6, 4                                     # moedas da busca/validação e da prova final
# amostra mínima (operações): busca, validação, prova final
MIN_TRADES = {"5m": (40, 20, 20), "15m": (30, 15, 15), "1h": (25, 12, 12), "4h": (15, 8, 8)}
MIN_AVG_R = 0.05                 # aprovado: R médio por operação nas três provas
MIN_POS_COINS = 0.6
RESSALVA_AVG_R, RESSALVA_POS_COINS = 0.02, 0.5   # ressalva: ainda positivo nas três provas, mas com margem menor

CONTEXTS = {
    "lateralidade": {
        "label": "Lateralidade", "emoji": "↔️", "bot_tip": "Compra o fundo e vende o topo da faixa quando o preço anda de lado.",
        "regimes": {"long": ["lateral"], "short": ["lateral"]},
        "archetypes": [{"bollinger": 1.5, "reversao": 1.5, "suporte_resistencia": 1.0}, {"momentum": 1.5, "bollinger": 1.0},
                       {"estocastico": 2.0, "bollinger": 1.0}]},
    "tendencia": {
        "label": "Tendência", "emoji": "📈", "bot_tip": "Entra a favor da tendência forte, nos recuos.",
        "regimes": {"long": ["tendencia_alta", "pullback_alta"], "short": ["tendencia_baixa", "pullback_baixa"]},
        "archetypes": [{"tendencia": 1.5, "supertrend": 1.5, "macd": 1.0}, {"supertrend": 1.5, "estocastico": 2.0},
                       {"tendencia": 1.0, "adx": 1.5, "volume": 0.5}]},
    "reversao": {
        "label": "Reversão", "emoji": "🔄", "bot_tip": "Aposta no repique quando o preço esticou demais.",
        "regimes": {"long": ["reversao_alta"], "short": ["reversao_baixa"]},
        "archetypes": [{"reversao": 2.0, "momentum": 1.0, "bollinger": 1.0}, {"momentum": 1.5, "estocastico": 1.5, "fibonacci": 1.0}]},
    "rompimento": {
        "label": "Rompimento", "emoji": "🚀", "bot_tip": "Entra quando o preço rompe a faixa com volume.",
        "regimes": {"long": ["rompimento_alta"], "short": ["rompimento_baixa"]},
        "archetypes": [{"rompimento": 2.0, "volume": 1.0}, {"rompimento": 1.5, "adx": 1.0, "bollinger": 0.5},
                       {"volume": 1.5, "rompimento": 2.0, "supertrend": 0.5}]},
    "suporte_resistencia": {
        "label": "Suporte e resistência", "emoji": "🧱", "bot_tip": "Opera a reação do preço ao tocar suporte ou resistência.",
        "regimes": {"long": ["suporte_teste"], "short": ["resistencia_teste"]},
        "archetypes": [{"suporte_resistencia": 2.0, "momentum": 1.0}, {"suporte_resistencia": 1.5, "reversao": 1.0, "fibonacci": 1.0},
                       {"estrutura": 1.5, "suporte_resistencia": 1.5}]},
    "fluxo_ordens": {
        "label": "Fluxo de ordens", "emoji": "🌊", "bot_tip": "Segue a agressão compradora ou vendedora (volume taker) com volume forte.",
        "regimes": {"long": ["fluxo_comprador"], "short": ["fluxo_vendedor"]},
        "archetypes": [{"volume": 2.0, "momentum": 1.0}, {"volume": 1.5, "macd": 1.0, "tendencia": 0.5}, {"volume": 2.0, "estrutura": 1.0}]},
}
THRESHOLDS = (10, 20, 30, 45)
# (stop ATR, alvo ATR): stops largos diluem as taxas nos tempos curtos (a taxa pesa mais quanto menor o ATR)
EXITS = ((1.0, 1.5), (1.0, 2.0), (1.5, 3.0), (2.0, 3.0), (2.0, 4.0), (3.0, 3.0), (4.0, 6.0), (5.0, 5.0))
FILTERS = ({}, {"trend_ema": True}, {"volume_confirm": True}, {"adx_min": 20})
SIDE_WORD = {"long": "Compra", "short": "Venda"}


def bot_id(market: str, interval: str, context: str, side: str) -> str:
    return f"ctx_{market}_{interval}_{context}_{side}"


def candidates(context: str, side: str, fast: bool = False):
    """Variações de bot para o contexto: arquétipos de habilidades × limiar × stop/alvo × filtros."""
    spec = CONTEXTS[context]
    thresholds, exits, filters = (THRESHOLDS[1::2], EXITS[1::2], FILTERS[:2]) if fast else (THRESHOLDS, EXITS, FILTERS)
    for skills, th, (sl, tp), flt in itertools.product(spec["archetypes"], thresholds, exits, filters):
        yield {"direction": "compra" if side == "long" else "venda", "skills": dict(skills), "threshold": th, "sl_atr": sl, "tp_atr": tp,
               "filters": {**flt, "contexts": list(spec["regimes"][side])}}


# ------------------------------------------------------------------------------ simulação
@dataclass
class CellData:
    """Votos (candles) das moedas de um mercado e tempo gráfico."""
    market: str
    interval: str
    days: int
    search: dict = field(default_factory=dict)     # moeda -> (vt, cfg)
    unseen: dict = field(default_factory=dict)


def load_cell(market: str, interval: str, universe: list[str], getter, days: int | None = None) -> CellData:
    """Baixa as moedas na ordem do volume até completar 6 (busca/validação) + 4 (prova final); moeda sem dados é pulada."""
    cell = CellData(market, interval, days or DAYS[interval])
    for sym in universe:
        if len(cell.search) >= N_SEARCH and len(cell.unseen) >= N_UNSEEN:
            break
        try:
            votes = ranking.votes_for(sym, interval, market, cell.days, getter)
        except Exception:  # noqa: BLE001 - moeda sem dados neste mercado: segue com as outras
            continue
        (cell.search if len(cell.search) < N_SEARCH else cell.unseen)[sym] = votes
    return cell


def _trades(vt, cfg, p, market):
    """Operações do bot na moeda, com o contexto (regime) do candle do sinal."""
    trades = fastsim.simulate(vt, p, cfg)
    if not trades:
        return []
    times, regimes = vt["time"], vt["regime"].to_numpy()
    for t in trades:
        i = max(0, int(times.searchsorted(t["entrada"])) - 1)
        t["regime"] = str(regimes[i])
    return trades


def evaluate(p: dict, cell: CellData, simulate=_trades) -> dict:
    """Operações do bot em todas as moedas da célula, separadas em busca, validação (mesmas moedas) e prova final (moedas inéditas)."""
    out = {"search": [], "valid": [], "unseen": [], "per_symbol": {}}
    for group, data in (("search", cell.search), ("unseen", cell.unseen)):
        for sym, (vt, cfg) in data.items():
            trades = simulate(vt, cfg, p, cell.market) if simulate is _trades else simulate(vt, cfg, p)
            out["per_symbol"][sym] = trades
            if group == "unseen":
                out["unseen"] += trades
                continue
            split = vt["time"].iloc[int(len(vt) * 2 / 3)]
            out["search"] += [t for t in trades if t["entrada"] < split]
            out["valid"] += [t for t in trades if t["entrada"] >= split]
    return out


def _avg(trades) -> float | None:
    return float(np.mean([t["r"] for t in trades])) if trades else None


def verdict(ev: dict, interval: str) -> dict:
    """Critérios de aprovação. ``tier`` = ``aprovado`` (R médio ≥ 0,05 nas três provas e 60% das moedas no verde), ``ressalva``
    (positivo nas três, mas com R médio ≥ 0,02 e metade das moedas no verde) ou ``None``. ``score`` = pior R médio das três provas."""
    need = MIN_TRADES[interval]
    n = (len(ev["search"]), len(ev["valid"]), len(ev["unseen"]))
    avgs = tuple(_avg(ev[k]) for k in ("search", "valid", "unseen"))
    coins = {s: t for s, t in ev["per_symbol"].items() if len(t) >= 3}
    pos = sum(1 for t in coins.values() if sum(x["r"] for x in t) > 0)
    ret_search = compound([t["r"] for t in ev["search"]])[0] if ev["search"] else 0.0
    ret_valid = compound([t["r"] for t in ev["valid"]])[0] if ev["valid"] else 0.0
    enough = all(x >= m for x, m in zip(n, need)) and all(a is not None for a in avgs) and bool(coins) and ret_search > 0 and ret_valid > 0
    share = pos / len(coins) if coins else 0.0
    tier = None
    if enough and all(a > MIN_AVG_R for a in avgs) and share >= MIN_POS_COINS:
        tier = "aprovado"
    elif enough and all(a >= RESSALVA_AVG_R for a in avgs) and share >= RESSALVA_POS_COINS:
        tier = "ressalva"
    return {"ok": tier is not None, "tier": tier, "n": n, "avg_r": avgs, "pos_coins": (pos, len(coins)), "ret_search": ret_search,
            "ret_valid": ret_valid, "score": min(avgs) if all(a is not None for a in avgs) else -9.0}


# ------------------------------------------------------------------------------ resultados no formato do app
def _group_stats(by_symbol: dict, search_syms, days: int) -> dict:
    """Números de um conjunto de operações por moeda (formato dos cards: acerto, R médio, retorno composto, queda, moedas no verde)."""
    allt = [t for ts in by_symbol.values() for t in ts]
    rets = {s: compound([t["r"] for t in ts]) for s, ts in by_symbol.items()}
    seen = [s for s in by_symbol if s in search_syms]
    new = [s for s in by_symbol if s not in search_syms]
    mean = lambda ss: float(np.mean([rets[s][0] for s in ss])) if ss else 0.0  # noqa: E731
    avg = lambda ts: round(float(np.mean([t["r"] for t in ts])), 3) if ts else 0.0  # noqa: E731
    ret = mean(list(by_symbol))
    seen_t = [t for s in seen for t in by_symbol[s]]
    new_t = [t for s in new for t in by_symbol[s]]
    return {"n": len(allt), "win_pct": round(float(np.mean([t["r"] > 0 for t in allt]) * 100), 1) if allt else 0.0, "avg_r": avg(allt),
            "seen_n": len(seen_t), "seen_avg_r": avg(seen_t), "new_n": len(new_t), "new_avg_r": avg(new_t),
            "ret_pct": round(ret, 2), "monthly_pct": round(((1 + ret / 100) ** (30 / days) - 1) * 100, 2),
            "ret_seen": round(mean(seen), 2), "ret_new": round(mean(new), 2),
            "dd_pct": round(max((r[1] for r in rets.values()), default=0.0), 1),
            "pos_coins": f"{sum(1 for r in rets.values() if r[0] > 0)}/{len(rets)}",
            "trades_month": round(len(allt) / max(len(by_symbol), 1) / days * 30, 1)}


def research_block(ev: dict, cell: CellData, regimes: list[str], status: str = "aprovado") -> dict:
    days, search_syms = cell.days, set(cell.search)
    whole = _group_stats(ev["per_symbol"], search_syms, days)
    contexts = {}
    for rg in regimes:
        sub = {s: [t for t in ts if t["regime"] == rg] for s, ts in ev["per_symbol"].items()}
        contexts[rg] = _group_stats(sub, search_syms, days)
    return {"period_label": f"{days} dias", "period_days": days, "ret_pct": whole["ret_pct"], "monthly_pct": whole["monthly_pct"],
            "ret_seen": whole["ret_seen"], "ret_new": whole["ret_new"], "win_pct": whole["win_pct"], "dd_pct": whole["dd_pct"],
            "trades_month": whole["trades_month"], "pos_coins": whole["pos_coins"],
            "per_symbol": {s: round(compound([t["r"] for t in ts])[0], 2) for s, ts in ev["per_symbol"].items()},
            "tested_at": datetime.now(timezone.utc).strftime("%d/%m/%Y"), "market": cell.market, "interval": cell.interval,
            "status": status, "contexts": contexts,
            "best_contexts": [rg for rg, c in contexts.items() if c["avg_r"] > 0 and c["n"] >= 10]}


def build_bot(p: dict, market: str, interval: str, context: str, side: str, v: dict) -> dict:
    spec = CONTEXTS[context]
    word, mk = SIDE_WORD[side], ("" if market == "futures" else " (Spot)")
    rr = p["tp_atr"] / p["sl_atr"]
    return {
        "id": bot_id(market, interval, context, side), "name": f"{spec['emoji']} {spec['label']} · {word} {interval}{mk}", "author": AUTHOR,
        "specialty": f"{spec['label']} · {word.lower()} {interval} · {rr:g}:1", "tip": spec["bot_tip"], "summary": spec["bot_tip"],
        "description": f"{spec['bot_tip']} Só opera {word.lower()} e só quando o gráfico está em {spec['label'].lower()} "
                       f"({', '.join(p['filters']['contexts'])}), no {interval} de {'futuros' if market == 'futures' else 'spot'}. "
                       f"Stop {p['sl_atr']:g} ATR, alvo {p['tp_atr']:g} ATR. Provado em busca, validação e moedas inéditas "
                       f"(R médio {v['avg_r'][0]:+.2f} / {v['avg_r'][1]:+.2f} / {v['avg_r'][2]:+.2f})"
                       + ("; margem pequena — selo ressalva." if v.get("tier") == "ressalva" else "."),
        "bot": "day" if market == "futures" else "swing", "markets": [market], "tested_interval": interval,
        "timeframes": f"{interval} (testado)", "direction": p["direction"], "threshold": p["threshold"], "sl_atr": p["sl_atr"],
        "tp_atr": p["tp_atr"], "skills": p["skills"], "filters": p["filters"], "context_group": context, "side": side,
        "selection": {"busca_r": round(v["avg_r"][0], 3), "validacao_r": round(v["avg_r"][1], 3), "inedito_r": round(v["avg_r"][2], 3),
                      "busca_n": v["n"][0], "validacao_n": v["n"][1], "inedito_n": v["n"][2]},
    }


def search_cell(cell: CellData, context: str, side: str, fast: bool = False, simulate=_trades) -> dict:
    """Melhor bot aprovado da célula (ou ``None``) e o relato do que foi testado."""
    best, best_v, tested, passed = None, None, 0, 0
    min_signals = MIN_TRADES[cell.interval][0]
    for p in candidates(context, side, fast):
        # triagem barata: sem sinais suficientes no contexto não vale simular candle a candle
        if simulate is _trades:
            n_sig = sum(int((fastsim.signals(vt, p, cfg) != 0).sum()) for vt, cfg in list(cell.search.values()))
            if n_sig < min_signals:
                continue
        tested += 1
        ev = evaluate(p, cell, simulate)
        v = verdict(ev, cell.interval)
        if v["ok"]:
            passed += 1
            if best is None or (v["tier"] == "aprovado", v["score"]) > (best_v["tier"] == "aprovado", best_v["score"]):
                best, best_v, best_ev = p, v, ev
    row = {"market": cell.market, "interval": cell.interval, "context": context, "side": side, "tested": tested, "passed": passed}
    if best is None:
        return {"row": {**row, "status": "sem bot aprovado"}, "bot": None, "research": None}
    bot = build_bot(best, cell.market, cell.interval, context, side, best_v)
    research = research_block(best_ev, cell, best["filters"]["contexts"], best_v["tier"])
    return {"row": {**row, "status": research["status"], "avg_r": best_v["avg_r"], "n": best_v["n"], "monthly_pct": research["monthly_pct"],
                    "pos_coins": research["pos_coins"]}, "bot": bot, "research": research}


def run(markets=("futures", "spot"), intervals=INTERVALS, contexts=tuple(CONTEXTS), *, universe, getter, fast: bool = False,
        days: dict | None = None, log=print) -> dict:
    """Pesquisa completa. ``universe(market)`` devolve as moedas por volume; ``getter`` baixa os candles."""
    bots, research, rows = [], {}, []
    for market in markets:
        coins = universe(market)
        for interval in intervals:
            log(f"[{market} {interval}] baixando candles de {min(len(coins), N_SEARCH + N_UNSEEN)} moedas…")
            cell = load_cell(market, interval, coins, getter, (days or {}).get(interval))
            if len(cell.search) < 3 or len(cell.unseen) < 2:
                log(f"[{market} {interval}] poucos dados: célula ignorada")
                rows += [{"market": market, "interval": interval, "context": c, "side": s, "tested": 0, "passed": 0, "status": "sem dados"}
                         for c in contexts for s in MARKET_SIDES[market]]
                continue
            for context in contexts:
                for side in MARKET_SIDES[market]:
                    res = search_cell(cell, context, side, fast)
                    rows.append(res["row"])
                    if res["bot"]:
                        bots.append(res["bot"])
                        research[res["bot"]["id"]] = res["research"]
                    log(f"  {context:<20} {side:<5} → {res['row']['status']} ({res['row']['passed']}/{res['row']['tested']} candidatos)")
    return {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "bots": bots, "research": research, "report": rows}


def save(result: dict, path: Path = OUT_FILE) -> None:
    path.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")


def report_markdown(result: dict) -> str:
    """Tabela de resultados: cada célula, o desempenho do bot aprovado nas três provas ou 'sem bot aprovado'."""
    lines = ["# Bots por contexto — pesquisa", "", f"Gerado em {result['generated']}. Aprovado = R médio positivo na busca, na validação e nas "
             "moedas inéditas (veja `core/context_research.py`).", "",
             "| Mercado | Tempo | Contexto | Lado | Situação | R busca | R validação | R inéditas | ≈ ao mês | Moedas + | Candidatos que passaram |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in result["report"]:
        if "avg_r" in r:
            a = r["avg_r"]
            lines.append(f"| {r['market']} | {r['interval']} | {CONTEXTS[r['context']]['label']} | {SIDE_WORD[r['side']]} | ✅ {r['status']} | "
                         f"{a[0]:+.2f} | {a[1]:+.2f} | {a[2]:+.2f} | {r['monthly_pct']:+.1f}% | {r['pos_coins']} | {r['passed']}/{r['tested']} |")
        else:
            lines.append(f"| {r['market']} | {r['interval']} | {CONTEXTS[r['context']]['label']} | {SIDE_WORD[r['side']]} | ❌ {r['status']} | "
                         f"— | — | — | — | — | {r['passed']}/{r['tested']} |")
    return "\n".join(lines) + "\n"
