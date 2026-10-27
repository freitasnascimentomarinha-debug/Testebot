"""Dados dos componentes da página Bots (ranking, biblioteca e calculadora). Sem Streamlit, para ser testado."""
from __future__ import annotations

from core import fastsim, personalities as P, regime
from core.strategy import SKILLS

SKILL_NAMES = {k: v[0] for k, v in SKILLS.items()}


def rr_label(p: dict) -> str:
    if p.get("trail_atr"):
        return "sem alvo (surfa)"
    sl, tp = float(p.get("sl_atr") or 1), float(p.get("tp_atr") or 1)
    r = tp / sl
    if r >= 1:
        return f"{r:.1f}:1".replace(".0:", ":").replace(".", ",")
    return f"1:{1 / r:.1f}".replace(".0", "").replace(".", ",")


def rank_data(rows: list[dict], history, *, note: str = "", busy: str | None = None, focus: str | None = None) -> dict:
    """Linhas do ranking diário com o histórico (para as mini curvas) e a ordem dos tempos gráficos."""
    out = []
    for r in rows:
        out.append({k: r.get(k) for k in ("id", "name", "market", "interval", "builtin", "kind", "status", "d1", "d7", "d30", "per_symbol",
                                          "live_trades", "live_pnl")}
                   | {"updated": (r.get("updated") or "")[:16].replace("T", " "), "history": history(r["id"])[-30:]})
    return {"rows": out, "order": {i: -v for i, v in fastsim.PER_DAY.items()}, "note": note, "busy": busy, "focus": focus}


def _filters_text(p: dict) -> str:
    f = p.get("filters", {})
    out = [P.FILTERS[k] for k, v in f.items() if v and k in P.FILTERS]
    if f.get("adx_min"):
        out.append(f"ADX ≥ {f['adx_min']}")
    if f.get("adx_max"):
        out.append(f"ADX ≤ {f['adx_max']}")
    if f.get("vol_mult"):
        out.append(f"Volume ≥ {f['vol_mult']:g}× a média")
    return ", ".join(out)


def library_data(bots: list[dict], live: dict, can_edit, perf: dict | None = None) -> dict:
    """Cards da biblioteca (tipos simples). Grade/DCA usam o último mês do ranking diário (``perf``) no lugar da pesquisa."""
    from core import grid_dca

    out = []
    for p in bots:
        if p.get("kind"):
            e = (perf or {}).get(p["id"]) or {}
            w = e.get("d30") or {}
            research = ({"monthly_pct": w.get("ret_pct"), "ret_pct": w.get("ret_pct"), "period_label": "últimos 30 dias", "win_pct": w.get("win_pct"),
                         "dd_pct": w.get("dd_pct"), "status": None, "trades_month": w.get("trades"), "pos_coins": w.get("positive")} if w else None)
            q = p["params"]
            out.append({"id": p["id"], "name": p["name"], "style": p.get("bot"), "interval": p["home"]["interval"], "market": p["home"]["market"],
                        "rr": f"{q['levels']} degraus" if p["kind"] == "grid" else f"alvo {q['tp_pct']:g}%", "specialty": p.get("specialty", ""), "tip": p.get("tip", ""),
                        "contexts_only": ", ".join(regime.label(c) for c in q.get("contexts") or []), "research": research, "builtin": True,
                        "author": "", "can_edit": False, "editable": False, "kind": p["kind"],
                        "live_trades": 0, "live_win": None, "live_pnl": None, "description": grid_dca.describe(p), "direction": "Só compra",
                        "exit": "venda em cada degrau / stop da grade" if p["kind"] == "grid" else "alvo sobre o preço médio / stop / prazo",
                        "skills": "—", "filters": ", ".join(f"{grid_dca.PARAM_LABELS.get(k, k)}: {v}" for k, v in q.items() if k != "contexts"),
                        "per_symbol": [[k.replace("USDT", ""), v] for k, v in (e.get("per_symbol") or {}).items()], "contexts": []})
            continue
        rs = p.get("research") or {}
        lv = live.get(p["id"], {})
        style = {"long": "long"}.get(p.get("bot"), p.get("bot")) or ("day" if "futures" in (p.get("markets") or []) else "swing")
        market = rs.get("market") or (p.get("home") or {}).get("market") or ("futures" if "futures" in (p.get("markets") or ["futures"])[:1] else "spot")
        research = None
        if rs.get("monthly_pct") is not None:
            research = {k: rs.get(k) for k in ("monthly_pct", "ret_pct", "period_label", "win_pct", "dd_pct", "status", "trades_month", "pos_coins")}
        out.append({
            "id": p["id"], "name": p["name"], "style": style, "interval": rs.get("interval") or (p.get("home") or {}).get("interval") or p.get("tested_interval") or "",
            "market": market, "rr": rr_label(p), "specialty": p.get("specialty", ""), "tip": p.get("tip") or p.get("summary", ""),
            "contexts_only": ", ".join(regime.label(c) for c in (p.get("filters") or {}).get("contexts") or []),
            "research": research, "builtin": bool(p.get("builtin")), "author": p.get("author", ""), "can_edit": bool(can_edit(p)),
            "live_trades": lv.get("live_trades") or 0, "live_win": lv.get("live_win_rate"), "live_pnl": lv.get("live_pnl"),
            "description": p.get("description", ""), "direction": P.DIRECTIONS.get(p.get("direction", "misto"), ""), "exit": P.exit_text(p),
            "skills": ", ".join(f"{SKILL_NAMES.get(k, k)} ({w:g})" for k, w in sorted((p.get("skills") or {}).items(), key=lambda x: -x[1])),
            "filters": _filters_text(p),
            "per_symbol": [[k.replace("USDT", ""), v] for k, v in (rs.get("per_symbol") or {}).items()],
            "contexts": sorted([{"label": regime.label(k), "n": v.get("n"), "win_pct": v.get("win_pct"), "avg_r": v.get("avg_r")}
                                for k, v in (rs.get("contexts") or {}).items() if v.get("n")], key=lambda c: -(c["avg_r"] or 0)),
        })
    return {"bots": out}


def calc_view(res: dict) -> dict:
    """Números da calculadora a partir do resultado da simulação (o mesmo dicionário guardado na sessão)."""
    import pandas as pd

    rows = res["rows"]
    pnl = res["bank"] - res["bank0"]
    ret = pnl / res["bank0"] * 100
    wins = [t["resultado"] for t in rows if t["resultado"] > 0]
    losses = [t["resultado"] for t in rows if t["resultado"] <= 0]
    gw, gl = sum(wins), -sum(losses)
    curve = ([[int(pd.Timestamp(rows[0]["entrada"]).timestamp() * 1000), res["bank0"]]] if rows else []) + \
        [[int(pd.Timestamp(c["time"]).timestamp() * 1000), c["Banca (USDT)"]] for c in res["curve"]]
    return {"bot": res["bot"], "itv": res["itv"], "market": res["market"], "days": res["days"], "risk": res["risk"], "comp": res["comp"], "kind": res.get("kind"),
            "bank0": res["bank0"], "bank": res["bank"], "pnl": pnl, "ret": ret,
            "monthly": ((1 + ret / 100) ** (30 / res["days"]) - 1) * 100 if res["bank"] > 0 else -100.0,
            "n": len(rows), "wins": len(wins), "losses": len(losses), "max_dd": res["max_dd"],
            "pf": (gw / gl) if gl else ("inf" if gw else None), "best": max(wins, default=0.0), "worst": min(losses, default=0.0), "curve": curve}


def _compare(rows: list[dict]) -> dict | None:
    """Regras × ML no mesmo teste: melhor, mediana e quantos ficaram positivos em cada família."""
    import statistics

    out = {}
    for fam in ("ml", "regra"):
        xs = [r for r in rows if r["family"] == fam and r["n"]]
        if not xs:
            return None
        best = max(xs, key=lambda r: r["monthly"])
        out[fam] = {"best_ok": best["halves"][0] is not None and min(best["halves"]) > 0, "best": best["algo"], "best_target": best["target"], "best_monthly": best["monthly"], "n": len(xs),
                    "median": round(statistics.median(r["monthly"] for r in xs), 2), "positive": sum(r["monthly"] > 0 for r in xs),
                    "both_halves": sum(min(r["halves"]) > 0 for r in xs if r["halves"][0] is not None)}
    return out


def tourney_data(results: dict, sel: tuple[str, str] | None = None, busy: list[str] | None = None) -> dict:
    """Torneio de modelos (core/ml_tournament.py) em tipos simples: um bloco por mercado/tempo gráfico já rodado."""
    from core import ml, ml_tournament as T

    out = []
    for key, r in sorted(results.items(), key=lambda kv: (kv[1]["market"], -fastsim.PER_DAY.get(kv[1]["interval"], 0))):
        rows = [{"combo": x["combo"], "family": x.get("family", "ml"),
                 "algo": ml.algo_label(x["algo"]) if x.get("family", "ml") == "ml" else x["algo"],
                 "target": ml.TARGETS.get(x["target"], x["target"]), "auc": x["auc"],
                 "n": x["n"], "win": x["win"], "avg": x["avg"], "monthly": x["monthly"], "pf": x["pf"], "halves": x.get("halves") or [None, None],
                 "ctx": {g: x["contexts"].get(g) for g in T.CTX_GROUPS}} for x in r["rows"]]
        out.append({"key": key, "market": r["market"], "interval": r["interval"], "ran_at": r["ran_at"][:16].replace("T", " "),
                    "test_days": r["test_days"], "train_days": r["train_days"], "step_days": r["step_days"],
                    "symbols": [s.replace("USDT", "") for s in r["symbols"]], "champion": r.get("champion"),
                    "by_ctx": r.get("by_ctx") or {}, "rows": rows, "compare": _compare(rows)})
    return {"results": out, "sel": "|".join(sel) if sel else None, "busy": busy or [], "thr": T.THR, "min_trades": T.MIN_TRADES,
            "groups": [[g, lab] for g, (lab, _) in T.CTX_GROUPS.items()]}


def lab_data(results: dict, sel: tuple[str, str] | None = None, busy: list[str] | None = None) -> dict:
    """Laboratório de treino (``ml_tournament.lab_run``): cada variante comparada com a base, no mesmo teste."""
    out = []
    for key, r in sorted(results.items(), key=lambda kv: (kv[1]["market"], -fastsim.PER_DAY.get(kv[1]["interval"], 0))):
        vs = r["variants"]
        base = vs.get("base") or {}
        rows = []
        for k, v in vs.items():
            d_mon = None if k == "base" or not base else round(v["mon_med"] - base["mon_med"], 2)
            d_auc = None if k == "base" or not base or v["auc_med"] is None or base.get("auc_med") is None else round(v["auc_med"] - base["auc_med"], 3)
            better = None if d_mon is None else (d_mon > 0 and v["confirmed"] >= base.get("confirmed", 0))
            rows.append({"key": k, **v, "d_mon": d_mon, "d_auc": d_auc, "better": better})
        out.append({"key": key, "market": r["market"], "interval": r["interval"], "ran_at": r["ran_at"][:16].replace("T", " "),
                    "test_days": r["test_days"], "rows": rows})
    from core import ml_tournament as T

    return {"results": out, "sel": "|".join(sel) if sel else None, "busy": busy or [], "min_trades": T.MIN_TRADES}
