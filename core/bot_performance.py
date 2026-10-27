"""Ranking diário dos bots: desempenho no dia, na semana e no mês, no mercado e tempo gráfico de cada bot.

Uma vez por dia (o primeiro acesso à página Bots ou o worker 24/7 dispara, em segundo plano) cada bot é simulado de novo com os candles
mais recentes em 5 moedas (só as regras, sem IA, com taxas, 1% de risco por operação) nas janelas de 1, 7 e 30 dias. O resultado é
salvo no banco (``bot_performance.json``, compartilhado por todos os usuários) com um histórico diário de até 90 dias. O backtest de
um bot pode ser forçado a qualquer momento (``refresh_bot``).
"""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone

from core import personalities as P, ranking
from core.storage import load_json, locked_update

FILE = "bot_performance.json"
WINDOWS = {"d1": 1, "d7": 7, "d30": 30}
LABELS = {"d1": "Dia", "d7": "Semana", "d30": "Mês"}
HISTORY_DAYS = 90
RUN_STALE = 3 * 3600          # uma atualização "em andamento" há mais de 3 h é dada como travada
_running = threading.Event()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def home(p: dict) -> tuple[str, str]:
    """Mercado e tempo gráfico em que o bot foi criado/testado (os criados pelo usuário guardam isso em ``home``)."""
    rs = p.get("research") or {}
    if rs.get("market") and rs.get("interval"):
        return rs["market"], rs["interval"]
    h = p.get("home") or {}
    return h.get("market") or (p.get("markets") or ["futures"])[0], h.get("interval") or "1h"


def tracked() -> list[dict]:
    """Bots do ranking: os de sinal (prontos e criados pelos usuários que a pessoa pode ver) e os de grade/DCA."""
    from core import grid_dca

    return [p for p in P.list_all() if p.get("skills")] + grid_dca.all_bots()


def get_bot(pid: str | None) -> dict | None:
    from core import grid_dca

    return P.get(pid) or grid_dca.get(pid)


def load() -> dict:
    data = load_json(FILE, {}) or {}
    data.setdefault("results", {})
    data.setdefault("history", {})
    return data


def last_update() -> datetime | None:
    u = load().get("updated")
    return datetime.fromisoformat(u) if u else None


def is_due(now: datetime | None = None) -> bool:
    """Ainda não rodou hoje (UTC)."""
    u = last_update()
    return u is None or u.date() < (now or _now()).date()


def compute(bots: list[dict], getter=None, progress=None) -> dict:
    """Simula os bots nas janelas de 1, 7 e 30 dias. Os candles de cada (mercado, tempo gráfico) são baixados uma vez só."""
    if getter is None:
        from core.data import get_klines as getter
    groups: dict[tuple[str, str], list[dict]] = {}
    for p in bots:
        groups.setdefault(home(p), []).append(p)
    out, done, total = {}, 0, max(1, len(bots))
    for (market, interval), members in groups.items():
        votes = {}
        for sym in P.PERIOD_SYMBOLS:
            try:
                votes[sym] = ranking.votes_for(sym, interval, market, max(WINDOWS.values()), getter)
            except Exception:  # noqa: BLE001 - moeda sem dados agora: segue com as outras
                continue
        stamp = _now().isoformat(timespec="seconds")
        for p in members:
            done += 1
            if not votes:
                continue
            entry = {"market": market, "interval": interval, "name": p["name"], "updated": stamp, "symbols": list(votes)}
            for key, days in WINDOWS.items():
                if p.get("kind"):   # grade/DCA: simulador próprio (core/grid_dca.py)
                    from core import grid_dca

                    r = grid_dca.period_summary(p, votes, market, days, interval)
                else:
                    r = ranking.simulate_bot(votes, p, market, days)
                entry[key] = {"ret_pct": float(r["ret_pct"]), "trades": int(r["trades"]), "win_pct": float(r["win_pct"]),
                              "dd_pct": float(r["dd_pct"]), "positive": int(r["positive"]), "symbols": int(r["symbols"])}
                if key == "d30":
                    entry["per_symbol"] = {k: float(v) for k, v in r["per_symbol"].items()}
            out[p["id"]] = entry
            if progress:
                progress(done / total, f"{p['name']} ({market} {interval})")
    return out


def save(results: dict, *, full: bool) -> None:
    """Grava os resultados e uma linha por dia no histórico de cada bot (o mesmo dia é sobrescrito)."""
    today = _now().date().isoformat()

    def _apply(data):
        data.setdefault("results", {}).update(results)
        hist = data.setdefault("history", {})
        for pid, e in results.items():
            rows = [h for h in hist.get(pid, []) if h.get("date") != today]
            rows.append({"date": today, **{k: e[k]["ret_pct"] for k in WINDOWS if k in e}})
            hist[pid] = rows[-HISTORY_DAYS:]
        if full:
            data["updated"] = _now().isoformat(timespec="seconds")
        if full:
            data.pop("running", None)

    locked_update(FILE, {}, _apply)


def refresh_all(getter=None, progress=None) -> dict:
    res = compute(tracked(), getter, progress)
    save(res, full=True)
    return res


def refresh_bot(pid: str, getter=None, progress=None) -> dict | None:
    """Backtest forçado de um bot: recalcula agora e salva (não muda a data da atualização diária geral)."""
    p = get_bot(pid)
    if not p:
        return None
    res = compute([p], getter, progress)
    if res:
        save(res, full=False)
    return res.get(pid)


def running() -> bool:
    if _running.is_set():
        return True
    r = load().get("running")
    return bool(r) and time.time() - datetime.fromisoformat(r).timestamp() < RUN_STALE


def _auto_enabled() -> bool:
    return "PYTEST_CURRENT_TEST" not in os.environ   # nos testes nada roda sozinho em segundo plano


def refresh_if_due(background: bool = True) -> bool:
    """Roda a atualização diária se ainda não rodou hoje. Devolve True se começou agora."""
    if not _auto_enabled() or not is_due() or running():
        return False
    _running.set()

    def _mark(data):
        data["running"] = _now().isoformat(timespec="seconds")

    locked_update(FILE, {}, _mark)

    def _run():
        try:
            refresh_all()
        except Exception:  # noqa: BLE001 - sem rede: tenta de novo no próximo acesso
            def _clear(data):
                data.pop("running", None)

            locked_update(FILE, {}, _clear)
        finally:
            _running.clear()

    if background:
        threading.Thread(target=_run, daemon=True).start()
    else:
        _run()
    return True


def rows(market: str | None = None, interval: str | None = None) -> list[dict]:
    """Linhas do ranking (para a página), já com o selo da pesquisa e o resultado real dos bots."""
    data = load()
    live = {r["id"]: r for r in P.ranking()}
    out = []
    for p in tracked():
        e = data["results"].get(p["id"])
        m, i = (e["market"], e["interval"]) if e else home(p)
        if (market and m != market) or (interval and i != interval):
            continue
        lv = live.get(p["id"], {})
        out.append({"id": p["id"], "name": p["name"], "market": m, "interval": i, "builtin": bool(p.get("builtin")), "kind": p.get("kind"),
                    "status": (p.get("research") or {}).get("status"), "updated": (e or {}).get("updated"),
                    **{k: (e or {}).get(k) for k in WINDOWS}, "per_symbol": (e or {}).get("per_symbol"),
                    "live_trades": lv.get("live_trades") or 0, "live_pnl": lv.get("live_pnl")})
    return out


def history(pid: str) -> list[dict]:
    return load()["history"].get(pid, [])
