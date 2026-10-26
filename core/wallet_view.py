"""Dados dos componentes do Painel e da Carteira (core/dashboard.js e core/wallet.js). Sem Streamlit, para ser testado."""
from __future__ import annotations

import math
from collections import defaultdict

from core.profiles import PROFILES

ORIGIN = {"manual": "Você (manual)", "ia": "Bot (IA)"}


def _f(v, d: int = 4):
    """Número seguro para JSON (infinito/NaN viram None)."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) or math.isinf(v) else round(v, d)


def stats_view(s: dict) -> dict:
    out = {k: _f(v) for k, v in s.items() if isinstance(v, (int, float))}
    out["profit_factor_inf"] = s.get("profit_factor") == float("inf")
    return out


def curve_view(curve: list[dict], equity_now: float | None = None, limit: int = 400) -> list[list]:
    """[[iso, banca], ...] (no máximo ``limit`` pontos, sempre com o primeiro e o atual)."""
    pts = [[c["time"], _f(c["equity"], 2)] for c in curve if c.get("equity") is not None]
    if len(pts) > limit:
        step = len(pts) / limit
        pts = [pts[int(i * step)] for i in range(limit - 1)] + [pts[-1]]
    if equity_now is not None:
        from datetime import datetime, timezone

        pts.append([datetime.now(timezone.utc).isoformat(timespec="seconds"), _f(equity_now, 2)])
    return pts


def bot_name(b) -> str:
    return PROFILES[b].name if b in PROFILES else "—"


def origin(src) -> str:
    return ORIGIN.get(src, "Bot (regras)")


def _summary(trades: list[dict]) -> dict:
    wins = [t["pnl"] for t in trades if t["pnl"] > 0]
    losses = [t["pnl"] for t in trades if t["pnl"] <= 0]
    return {"n": len(trades), "win_pct": _f(len(wins) / len(trades) * 100, 1) if trades else 0, "pnl": _f(sum(t["pnl"] for t in trades), 2),
            "avg_win": _f(sum(wins) / len(wins), 2) if wins else 0, "avg_loss": _f(sum(losses) / len(losses), 2) if losses else 0,
            "pf": _f(sum(wins) / abs(sum(losses)), 2) if losses and sum(losses) else None}


def wallet_data(acct: dict, s: dict, *, brl: float | None, mode: str, label: str) -> dict:
    hist = sorted(acct.get("history", []), key=lambda t: t.get("closed", ""))
    daily: dict[str, list] = defaultdict(list)
    for t in hist:
        daily[t["closed"][:10]].append(t)
    acc = 0.0
    days = []
    for d in sorted(daily):
        ts = daily[d]
        pnl = sum(t["pnl"] for t in ts)
        acc += pnl
        days.append({"date": d, "n": len(ts), "wins": sum(t["pnl"] > 0 for t in ts), "pnl": _f(pnl, 2), "fees": _f(sum(t.get("fees_total", 0) for t in ts), 2),
                     "acc": _f(acc, 2)})
    by_origin: dict[str, list] = defaultdict(list)
    by_bot: dict[str, list] = defaultdict(list)
    for t in hist:
        by_origin[origin(t.get("source"))].append(t)
        by_bot[bot_name(t.get("bot"))].append(t)
    trades = [{"opened": t.get("opened"), "closed": t.get("closed"), "bot": bot_name(t.get("bot")), "origin": origin(t.get("source")),
               "symbol": t.get("symbol"), "side": t.get("side"), "qty": _f(t.get("qty"), 8), "entry": _f(t.get("entry"), 8), "exit": _f(t.get("exit"), 8),
               "lev": _f(t.get("leverage"), 1), "reason": t.get("reason", ""), "fees": _f(t.get("fees_total"), 2), "pnl": _f(t.get("pnl"), 2),
               "pct": _f(t.get("pnl_pct_margin"), 2), "personality": (t.get("personality") or {}).get("name") if isinstance(t.get("personality"), dict) else t.get("personality_name")}
              for t in reversed(hist[-500:])]
    ledger = [{"time": e.get("time"), "type": e.get("type"), "bot": bot_name(e.get("bot")), "symbol": e.get("symbol", ""), "amount": _f(e.get("amount"), 2),
               "bank": _f(e.get("bank"), 2), "detail": e.get("detail", "")} for e in reversed(acct.get("ledger", [])[-500:])]
    return {"label": label, "mode": mode, "brl": _f(brl, 4), "created": (acct.get("created") or "")[:10], "initial": _f(acct.get("initial"), 2),
            "stats": stats_view(s), "curve": curve_view(acct.get("equity_curve", []), s.get("equity")), "daily": days,
            "by_origin": {k: _summary(v) for k, v in by_origin.items()}, "by_bot": {k: _summary(v) for k, v in by_bot.items()},
            "trades": trades, "ledger": ledger}


def dashboard_data(cards: list[dict], curve: list[dict], equity: dict, decisions: dict, positions: list[dict], events: list[dict], mode: str) -> dict:
    """``cards``: [{key, stats, cfg}] por bot; ``decisions``: {bot: [entradas do log]}; ``positions``: já resumidas."""
    rows = [{"bot": bot_name(k), **{f: e.get(f) for f in ("time", "symbol", "interval", "decision", "source", "confidence", "approved", "executed",
                                                           "reasoning", "personality", "price")}}
            for k, v in decisions.items() if k in PROFILES for e in v]
    rows.sort(key=lambda r: r.get("time") or "", reverse=True)
    out_cards = []
    for c in cards:
        p, cfg = PROFILES[c["key"]], c["cfg"]
        out_cards.append({"key": c["key"], "icon": p.icon, "name": p.name, "market": p.market_label, "symbol": cfg["symbol"], "interval": cfg["interval"],
                          "autopilot": bool(cfg.get("autopilot")), "leverage": (f"{cfg['leverage']}×" if cfg.get("leverage_on") else "sem alavancagem"),
                          "stats": stats_view(c["stats"])})
    return {"mode": mode, "equity": stats_view(equity), "curve": curve_view(curve, equity.get("equity")), "cards": out_cards,
            "decisions": [{**r, "confidence": _f(r.get("confidence"), 0), "price": _f(r.get("price"), 8)} for r in rows[:40]],
            "positions": positions, "events": events[:4]}


MODE_DESC = {"simulada": "Ordens simuladas com preços reais, na carteira da plataforma. Sem risco e sem precisar de chave.",
             "demo": "Ordens na conta de testes (testnet) da corretora escolhida, com dinheiro de teste. Precisa de uma chave da testnet.",
             "real": "Ordens na sua conta real da corretora escolhida. Use só depois de testar bem na demo."}


def exchanges_view(selected: str, keys: dict | None = None) -> list[dict]:
    """Cartões das corretoras: em uso, se tem futuros e se já há chave salva (últimos 4 caracteres)."""
    from core import exchanges

    keys = keys or {}
    return [{"key": k, "label": v[0], "futures": v[2] is not None, "selected": k == selected, "key_saved": (keys.get(k) or {}).get("last4")}
            for k, v in exchanges.EXCHANGES.items()]


def account_data(*, user: str, admin: bool, created: str, storage: str, mode: str, modes: dict, warn, bank: float, bots: list[dict],
                 ai: dict | None, exchanges: list[dict] | None = None) -> dict:
    """``warn(mode)``: motivo de a conta ainda não poder ser usada (ou None); ``bots``: [{name, cfg, personality}]."""
    out_bots = []
    for b in bots:
        c = b["cfg"]
        out_bots.append({"name": b["name"], "symbol": c["symbol"], "interval": c["interval"], "autopilot": bool(c.get("autopilot")),
                         "risk": f"{c['max_loss_pct']:g}% do saldo" if c.get("risk_mode") == "% do saldo" else f"{c['max_loss_usdt']:g} USDT",
                         "leverage": f"{c['leverage']:g}×" if c.get("leverage_on") else "sem", "personality": b["personality"],
                         "scan": f"a cada {c.get('scan_minutes', 15):g} min · {c.get('scan_count', 15)} moedas" if c.get("scan_on", True) else "só a moeda da tela"})
    return {"user": {"name": user, "admin": admin, "created": (created or "")[:10], "storage": storage}, "mode": mode,
            "modes": [{"key": k, "label": v, "desc": MODE_DESC.get(k, ""), "warn": (warn(k) or "").replace("**", "") or None} for k, v in modes.items()],
            "bank": _f(bank, 2), "bots": out_bots, "ai": ai, "exchanges": exchanges or []}
