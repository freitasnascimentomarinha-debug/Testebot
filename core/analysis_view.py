"""Dados da aba "Análise do bot" (core/analysis.js). Sem Streamlit, para ser testado.

Mostra fatos medidos e o que falta para o bot agir: nada de dicas genéricas. A IA entra só com a leitura dela (quando foi consultada)
e com as decisões de saída das posições abertas.
"""
from __future__ import annotations

import time

from core import advisor, personalities, regime, sentiment

HEAD = {"BUY": ("Oportunidade de compra", "up"), "SELL": ("Oportunidade de venda", "dn"), "HOLD": ("Sem oportunidade agora", "mut"),
        "CLOSE": ("Sinal contrário: encerrando a posição", "warn")}


def _strip(text: str) -> str:
    """Tira os prefixos entre colchetes ("[Sinal das regras: HOLD]") que o motor coloca no início da explicação."""
    text = (text or "").strip()
    while text.startswith("["):
        end = text.find("]")
        if end < 0:
            break
        text = text[end + 1:].strip()
    return text


def drivers(plan: dict, weights: dict, top: int = 4) -> list[dict]:
    """As habilidades que mais pesam no placar (a favor ou contra), com a leitura de cada uma."""
    rows = []
    for sk in plan.get("skills") or []:
        w = float(weights.get(sk["key"], 1.0))
        rows.append({"name": sk["name"], "vote": round(float(sk["vote"]), 2), "weight": w, "detail": sk.get("detail", ""), "pull": float(sk["vote"]) * w})
    rows.sort(key=lambda r: -abs(r["pull"]))
    return [{k: v for k, v in r.items() if k != "pull"} for r in rows[:top]]


def view(profile, cfg: dict, rep, *, on: bool, next_at: float | None, now: float | None = None) -> dict | None:
    if rep is None or rep.viewed is None:
        return None
    res, d = rep.viewed, rep.viewed.decision
    adv = d.advice or {}
    plan = res.plan or {}
    persona = personalities.get((res.personality or {}).get("id")) or {}
    threshold = float(persona.get("threshold", 25))
    title, tone = HEAD.get(d.decision, HEAD["HOLD"])
    ctx = str(plan.get("context") or "indefinido")
    ctx_name, ctx_rule = regime.REGIMES.get(ctx, regime.REGIMES["indefinido"]) if ctx in regime.REGIMES else ("", "")
    out = {
        "title": title, "tone": tone, "symbol": res.symbol, "interval": res.interval, "bot": (res.personality or {}).get("name"),
        "when": (res.time or "")[11:16], "context": {"name": ctx_name, "rule": ctx_rule}, "bias": adv.get("vies"),
        "summary": adv.get("resumo") or "", "facts": adv.get("leitura_tecnica") or [],
        "score": {"value": plan.get("score", 0.0), "needed": threshold, "direction": plan.get("direction", "HOLD")},
        "drivers": drivers(plan, persona.get("skills") or profile.skill_weights),
        "blocks": [b.strip() for b in (plan.get("note") or "").replace("Filtro", "|Filtro").split("|") if b.strip()],
        "why": _strip(d.reasoning) if d.source == "ia" else "",
        "bot_note": (adv.get("bot") or {}).get("motivo", ""),
        "trigger": advisor.describe_plan(adv["plano"], res.symbol, res.interval) if adv.get("plano") else "",
        "entry": None, "exits": list(getattr(rep, "exit_views", []) or []),
        "executed": [{"symbol": e["symbol"], "action": e["action"], "status": e["status"]} for e in rep.executed],
        "opportunities": [{"symbol": o.symbol, "side": o.decision.decision, "bot": (o.personality or {}).get("name", ""),
                           "entry": o.decision.entry or o.price, "stop": o.decision.stop_loss, "target": o.decision.take_profit}
                          for o in rep.opportunities],
        "scan": {"on": on, "scanned": rep.scanned, "last": (getattr(rep, "scan_time", "") or "")[11:16],
                 "next_in_min": None if not on or not next_at else max(0, round((next_at - (time.time() if now is None else now)) / 60)),
                 "minutes": cfg.get("scan_minutes")},
        "notes": rep.notes[:3], "ai": d.source == "ia", "sentiment": sentiment.for_symbol(res.symbol, res.price) if d.source == "ia" else None,
    }
    if d.decision in ("BUY", "SELL") and res.check and res.check.calc:
        c = res.check.calc
        out["entry"] = {"price": d.entry or res.price, "stop": d.stop_loss, "target": d.take_profit, "qty": c.qty, "risk": c.risk_usdt}
    return out
