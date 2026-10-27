"""Torneio de modelos: vários algoritmos × vários alvos, testados com re-treino (walk-forward) em cada mercado e tempo gráfico.

Cada combinação (algoritmo + alvo) é re-treinada a cada ``STEP_DAYS`` só com o passado e prevê o período seguinte. Nas velas de
teste ela opera sozinha: compra quando a chance de alta passa de ``THR`` (e, nos futuros, vende quando fica abaixo de ``1 − THR``),
sai como o alvo manda (fim do prazo ou a barreira tocada) e paga as taxas. O resultado é medido no geral e por contexto do gráfico:

* **Campeão geral** — melhor retorno mensal com pelo menos ``MIN_TRADES`` operações, positivo **nas duas metades** do teste;
* **Campeão de cada contexto** — melhor resultado médio por operação naquele contexto, com ``MIN_CTX_TRADES`` operações e
  positivo nas duas metades do teste (escolher o melhor entre dezenas de combinações premia a sorte; a confirmação na
  outra metade filtra boa parte dela).

Os bots de regras (e de grade/DCA) do mesmo mercado/tempo gráfico entram no placar nas mesmas velas e com o mesmo tamanho de
posição, para comparar regras escritas à mão com modelos aprendidos — mas só modelos viram campeões.

O modelo ao vivo (``core/ml.py``) usa o campeão geral e troca para o campeão do contexto quando o gráfico está nele. O torneio roda
sozinho 1x por semana (em segundo plano) e pode ser forçado na aba 🧪 Modelo ML.
"""
from __future__ import annotations

import os
import threading
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from core import fastsim, ml
from core.storage import load_json, locked_update

FILE = "ml_tournament.json"
INTERVALS = ("15m", "1h", "4h")
TEST_DAYS = {"15m": 45, "1h": 60, "4h": 120}
STEP_DAYS = {"15m": 7, "1h": 14, "4h": 30}
THR = 0.55
MIN_TRADES = 20
MIN_CTX_TRADES = 25
EVERY_DAYS = 7
RUN_STALE = 3 * 3600
CTX_GROUPS = {
    "tendencia": ("📈 Tendência", ("tendencia_alta", "tendencia_baixa")),
    "rompimento": ("🚀 Rompimento", ("rompimento_alta", "rompimento_baixa")),
    "reversao": ("🔄 Reversão", ("reversao_alta", "reversao_baixa")),
    "pullback": ("↩️ Pullback", ("pullback_alta", "pullback_baixa")),
    "lateral": ("↔️ Lateral e testes", ("lateral", "suporte_teste", "resistencia_teste")),
    "fluxo": ("🌊 Fluxo", ("fluxo_comprador", "fluxo_vendedor")),
    "indefinido": ("❔ Indefinido", ("indefinido",)),
}
_REGIME_GROUP = {r: g for g, (_, rs) in CTX_GROUPS.items() for r in rs}
_running: set = set()
_lock = threading.Lock()


def group_of(regime_key: str | None) -> str:
    return _REGIME_GROUP.get(str(regime_key or ""), "indefinido")


def combo(algo: str, target: str) -> str:
    return f"{algo}|{target}"


def combo_label(key: str | None) -> str:
    if not key:
        return "—"
    a, t = key.split("|")
    return f"{ml.algo_label(a)} · {ml.TARGETS.get(t, t)}"


def _key(market: str, interval: str) -> str:
    return f"{market}|{interval}"


# ------------------------------------------------------------------------------ simulação das operações
def trades(p: np.ndarray, out: pd.DataFrame, regimes: np.ndarray, start: int, short: bool, thr: float = THR) -> list[tuple[int, float, str]]:
    """Operações sem sobreposição a partir das previsões ``p``: (vela de entrada, resultado em %, grupo de contexto)."""
    longs, shorts, exits = out["long"].to_numpy(), out["short"].to_numpy(), out["exit"].to_numpy()
    res, i, n = [], start, len(p)
    while i < n:
        pi = p[i]
        side = None
        if np.isfinite(pi):
            if pi >= thr and np.isfinite(longs[i]):
                side = longs
            elif short and pi <= 1 - thr and np.isfinite(shorts[i]):
                side = shorts
        if side is None:
            i += 1
            continue
        res.append((i, float(side[i] * 100), group_of(regimes[i])))
        i = int(exits[i]) + 1
    return res


def _stats(rs: list[float], n_sym: int, test_days: float) -> dict:
    if not rs:
        return {"n": 0, "win": 0.0, "avg": 0.0, "ret": 0.0, "monthly": 0.0, "pf": None}
    a = np.asarray(rs)
    gain, loss = a[a > 0].sum(), -a[a < 0].sum()
    ret = float(a.sum() / max(n_sym, 1))
    return {"n": int(len(a)), "win": round(float((a > 0).mean() * 100), 1), "avg": round(float(a.mean()), 3), "ret": round(ret, 2),
            "monthly": round(ret * 30 / test_days, 2), "pf": round(float(gain / loss), 2) if loss > 0 else None}


def _summary(tr: list[tuple[int, float, str]], n_sym: int, test_days: float) -> dict:
    """Operações (metade do teste 1/2, resultado em %, grupo de contexto) → números do placar, no geral e por contexto."""
    st = _stats([r for _, r, _ in tr], n_sym, test_days)
    ctx = {}
    for g in CTX_GROUPS:
        rs = [(k, r) for k, r, gg in tr if gg == g]
        c = _stats([r for _, r in rs], n_sym, test_days)
        h = [[r for k, r in rs if k == kk] for kk in (1, 2)]
        ctx[g] = {"n": c["n"], "avg": c["avg"], "win": c["win"], "ret": c["ret"], "auc": None,
                  "halves": [round(float(np.mean(x)), 3) if len(x) >= 5 else None for x in h]}
    return {**st, "halves": [round(float(sum(r for k, r, _ in tr if k == kk)) / max(n_sym, 1), 2) for kk in (1, 2)], "contexts": ctx}


def rule_bots(market: str, interval: str) -> list[dict]:
    """Bots de regras (prontos e criados pelos usuários) e de grade/DCA deste mercado/tempo gráfico: entram no torneio para comparação."""
    from core import bot_performance

    return [p for p in bot_performance.tracked() if bot_performance.home(p) == (market, interval)]


def _rule_trades(p: dict, vt: pd.DataFrame, cfg: dict, market: str, interval: str, start, mid) -> list[tuple[int, float, str]]:
    """Operações de um bot de regras nas velas de teste, com a banca inteira em cada operação (igual aos modelos)."""
    from core import grid_dca

    if p.get("kind"):
        raw = grid_dca.simulate(p, vt, interval, float(cfg["fee_pct"]), start_time=start)["trades"]
        pct = [float(t["r"]) for t in raw]           # grade/DCA: % da banca da sessão
    else:
        days = (vt["time"].iloc[-1] - start) / pd.Timedelta(days=1)
        raw = fastsim.period_trades(vt, cfg, p, days=days, market=market)
        fee = float(cfg["fee_pct"]) / 100
        pct = [((1 if t["lado"] == "Compra" else -1) * (t["preco_saida"] - t["preco_entrada"]) - fee * (t["preco_entrada"] + t["preco_saida"]))
               / t["preco_entrada"] * 100 for t in raw]
    out = []
    for t, r in zip(raw, pct):
        i = max(0, int(vt["time"].searchsorted(t["entrada"])) - 1)     # vela do sinal
        out.append((1 if t["entrada"] < mid else 2, r, group_of(vt["regime"].iloc[i])))
    return out


# ------------------------------------------------------------------------------ torneio
def run(market: str, interval: str, getter=None, symbols=None, algos=None, targets=None, progress=None,
        test_days: float | None = None, train_days: float | None = None, step_days: float | None = None, include_bots: bool = True,
        train_symbols=None, extra_features: bool = False, save_result: bool = True) -> dict:
    """Roda o torneio num mercado/tempo gráfico, salva no banco e devolve o resultado.

    ``train_symbols``: moedas a mais usadas só no treino (o teste continua nas ``symbols``). ``extra_features``: conjunto ampliado
    de features (``ml.features(..., extra=True)``)."""
    from core import personalities as P, ranking

    if getter is None:
        from core.data import get_klines as getter
    algos = [a for a in (algos or ml.available_algos()) if a in ml.ALGOS]
    targets = list(targets or ml.TARGETS)
    test_days = float(test_days or TEST_DAYS.get(interval, 60))
    train_days = float(train_days or ml.TRAIN_DAYS.get(interval, 60))
    step_days = float(step_days or STEP_DAYS.get(interval, 14))
    symbols = list(symbols or P.PERIOD_SYMBOLS)
    extra_syms = [s for s in (train_symbols or []) if s not in symbols]
    frames, cfg = {}, None
    every = symbols + extra_syms
    for k, sym in enumerate(every, start=1):
        try:
            vt, cfg_ = ranking.votes_for(sym, interval, market, train_days + test_days + 2, getter)
            frames[sym] = vt.reset_index(drop=True)
            cfg = cfg if sym in extra_syms and cfg else cfg_
        except Exception:  # noqa: BLE001 - moeda sem candles agora: segue com as outras
            pass
        if progress:
            progress(k / len(every) * 0.15, f"Candles de {sym}")
    test_syms = [s for s in symbols if s in frames]
    if not test_syms:
        raise RuntimeError("Sem candles para o torneio agora.")
    fee = float(cfg["fee_pct"])
    btc = frames.get("BTCUSDT")
    mkt = ml.market_frame(frames) if extra_features else None
    feats = {s: ml.features(vt, None if s == "BTCUSDT" else btc, mkt, extra=extra_features) for s, vt in frames.items()}
    cols = sorted(set().union(*(f.columns for f in feats.values())))
    feats = {s: f.reindex(columns=cols) for s, f in feats.items()}
    outs = {(s, t): ml.outcomes(vt, interval, fee, t) for s, vt in frames.items() for t in targets}
    preds = {(a, t): {s: np.full(len(frames[s]), np.nan) for s in test_syms} for a in algos for t in targets}

    end = max(frames[s]["time"].iloc[-1] for s in test_syms)
    start = end - pd.Timedelta(days=test_days)
    cuts = list(pd.date_range(start, end, freq=pd.Timedelta(days=step_days)))
    bar_sec = pd.Timedelta(seconds=ml.fastsim_sec(interval))
    total, done = len(cuts) * len(targets) * len(algos), 0
    for t0 in cuts:
        t1 = t0 + pd.Timedelta(days=step_days)
        for tg in targets:
            tr_to = t0 - bar_sec * ml.horizon(interval, tg)       # o alvo de cada vela de treino já era conhecido em t0
            Xs, ys = [], []
            for s, vt in frames.items():
                y = outs[(s, tg)]["y"]
                m = ((vt["time"] >= t0 - pd.Timedelta(days=train_days)) & (vt["time"] < tr_to) & y.notna() & (vt.index >= fastsim.WARMUP)).to_numpy()
                Xs.append(feats[s][m])
                ys.append(y[m].to_numpy())
            Xtr, y = pd.concat(Xs), np.concatenate(ys)
            for a in algos:
                done += 1
                if len(y) >= 300 and y.min() != y.max():
                    model = ml.Model(cols, a, tg).fit(Xtr, y, di=False)
                    for s in test_syms:
                        vt = frames[s]
                        m = ((vt["time"] >= t0) & (vt["time"] < t1)).to_numpy()
                        if m.any():
                            preds[(a, tg)][s][m] = model.proba(feats[s][m])
                if progress:
                    progress(0.15 + 0.8 * done / total, f"{ml.algo_label(a)} · {ml.TARGETS[tg]} · corte {t0:%d/%m}")

    rows = []
    for (a, tg), by_sym in preds.items():
        ys_, ps_, all_tr, ctx_y, ctx_p = [], [], [], {}, {}
        for s in test_syms:
            vt = frames[s]
            p, out = by_sym[s], outs[(s, tg)]
            first = int(vt["time"].searchsorted(start))
            m = np.isfinite(p) & out["y"].notna().to_numpy()
            m[:first] = False
            ys_.append(out["y"].to_numpy()[m])
            ps_.append(p[m])
            regimes = vt["regime"].astype(str).to_numpy()
            for g, yy, pp in zip((group_of(r) for r in regimes[m]), out["y"].to_numpy()[m], p[m]):
                ctx_y.setdefault(g, []).append(yy)
                ctx_p.setdefault(g, []).append(pp)
            mid = int(vt["time"].searchsorted(start + pd.Timedelta(days=test_days / 2)))
            all_tr += [(1 if i < mid else 2, r, g) for i, r, g in trades(p, out, regimes, first, market == "futures")]
        y_all, p_all = np.concatenate(ys_), np.concatenate(ps_)
        sm = _summary(all_tr, len(test_syms), test_days)
        for g in CTX_GROUPS:
            if len(ctx_y.get(g, [])) >= 50:
                au = ml.auc(np.array(ctx_y[g]), np.array(ctx_p[g]))
                sm["contexts"][g]["auc"] = None if au is None else round(au, 3)
        au = ml.auc(y_all, p_all) if len(y_all) else None
        rows.append({"combo": combo(a, tg), "family": "ml", "algo": a, "target": tg, "auc": None if au is None else round(au, 3),
                     "obs": int(len(y_all)), **sm})
    # bots de regras nas mesmas velas, mesmo período e mesmo tamanho de posição (só comparação: não viram campeões do modelo)
    mid_t = start + pd.Timedelta(days=test_days / 2)
    for p in (rule_bots(market, interval) if include_bots else []):
        tr = []
        for s_ in test_syms:
            vt = frames[s_]
            try:
                tr += _rule_trades(p, vt, cfg, market, interval, start, mid_t)
            except Exception:  # noqa: BLE001 - um bot com problema não derruba o torneio
                continue
        rows.append({"combo": f"bot:{p['id']}", "family": "regra", "algo": p["name"],
                     "target": {"grid": "Grade", "dca": "DCA"}.get(p.get("kind"), "Bot de regras"), "auc": None, "obs": 0,
                     **_summary(tr, len(test_syms), test_days)})
    rows.sort(key=lambda r: (r["n"] >= MIN_TRADES, r["monthly"], r["auc"] or 0), reverse=True)
    ml_rows = [r for r in rows if r["family"] == "ml"]
    champ = next((r["combo"] for r in ml_rows if r["n"] >= MIN_TRADES and r["monthly"] > 0 and min(r["halves"]) > 0), None)
    by_ctx = {}
    for g in CTX_GROUPS:
        cands = [r for r in ml_rows if r["contexts"][g]["n"] >= MIN_CTX_TRADES and r["contexts"][g]["avg"] > 0
                 and all(h is not None and h > 0 for h in r["contexts"][g]["halves"])]
        if cands:
            by_ctx[g] = max(cands, key=lambda r: (r["contexts"][g]["avg"], r["contexts"][g]["n"]))["combo"]
    result = {"ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "market": market, "interval": interval,
              "test_days": test_days, "train_days": train_days, "step_days": step_days, "symbols": test_syms, "thr": THR,
              "train_symbols": [s for s in frames if s not in test_syms], "extra_features": extra_features,
              "algos": algos, "targets": targets, "rows": rows, "champion": champ, "by_ctx": by_ctx}
    if save_result:
        save(market, interval, result)
    if progress:
        progress(1.0, "Torneio concluído")
    return result


# ------------------------------------------------------------------------------ banco e agenda
def load() -> dict:
    return load_json(FILE, {}) or {}


def get(market: str, interval: str) -> dict | None:
    return load().get(_key(market, interval))


def save(market: str, interval: str, result: dict) -> None:
    def _apply(data):
        data[_key(market, interval)] = result

    locked_update(FILE, {}, _apply)


def champions(market: str, interval: str) -> tuple[str | None, dict]:
    """(combinação campeã geral, {grupo de contexto: combinação}) do último torneio."""
    r = get(market, interval) or {}
    return r.get("champion"), dict(r.get("by_ctx") or {})


def is_due(market: str, interval: str, now: datetime | None = None) -> bool:
    r = get(market, interval)
    return not r or datetime.fromisoformat(r["ran_at"]) + timedelta(days=EVERY_DAYS) <= (now or datetime.now(timezone.utc))


def running(market: str | None = None, interval: str | None = None) -> bool:
    with _lock:
        if market is None:
            return bool(_running)
        return _key(market, interval) in _running


def running_keys() -> list[str]:
    with _lock:
        return sorted(_running)


def start(market: str, interval: str, getter=None, retrain: bool = True) -> bool:
    """Roda o torneio em segundo plano (e re-treina o modelo ao vivo com os campeões). Devolve False se já estiver rodando."""
    k = _key(market, interval)
    with _lock:
        if k in _running:
            return False
        _running.add(k)

    def _run():
        try:
            run(market, interval, getter=getter)
            if retrain:
                ml.train_live(market, interval, getter=getter)
        except Exception:  # noqa: BLE001 - sem rede: tenta de novo na próxima vez
            pass
        finally:
            with _lock:
                _running.discard(k)

    threading.Thread(target=_run, daemon=True).start()
    return True


def refresh_if_due(market: str, interval: str) -> bool:
    """Torneio semanal em segundo plano (nunca nos testes)."""
    if "PYTEST_CURRENT_TEST" in os.environ or not is_due(market, interval) or running(market, interval):
        return False
    return start(market, interval)



# ------------------------------------------------------------------------------ laboratório: mais dados de treino ajudam?
LAB_FILE = "ml_lab.json"
LAB_ALGOS = ("lightgbm", "xgboost", "catboost", "extra", "logistica")
LAB_HISTORY_MULT = 2


def lab_variants(interval: str) -> dict[str, dict]:
    """Variantes de treino comparadas no mesmo teste (mesmas moedas, mesmo período)."""
    long_days = ml.TRAIN_DAYS.get(interval, 60) * LAB_HISTORY_MULT
    return {
        "base": {"label": "Como hoje", "kw": {}},
        "moedas": {"label": f"+{len(ml.EXTRA_SYMBOLS)} moedas no treino", "kw": {"train_symbols": list(ml.EXTRA_SYMBOLS)}},
        "historico": {"label": f"Histórico {LAB_HISTORY_MULT}× maior ({long_days:g} dias)", "kw": {"train_days": long_days}},
        "features": {"label": "Mais informação por vela", "kw": {"extra_features": True}},
        "tudo": {"label": "Tudo junto", "kw": {"train_symbols": list(ml.EXTRA_SYMBOLS), "train_days": long_days, "extra_features": True}},
    }


def _lab_row(r: dict) -> dict:
    import statistics

    rows = r["rows"]
    aucs = [x["auc"] for x in rows if x["auc"] is not None]
    mon = [x["monthly"] for x in rows]
    best = max(rows, key=lambda x: x["monthly"])
    return {"auc_med": round(statistics.median(aucs), 3) if aucs else None, "auc_max": max(aucs) if aucs else None,
            "mon_med": round(statistics.median(mon), 2), "positive": sum(m > 0 for m in mon), "total": len(rows),
            "confirmed": sum(1 for x in rows if x["n"] >= MIN_TRADES and x["monthly"] > 0 and min(x["halves"]) > 0),
            "best": combo_label(best["combo"]), "best_monthly": best["monthly"], "champion": r["champion"],
            "train_days": r["train_days"], "coins": len(r["symbols"]) + len(r["train_symbols"])}


def lab_run(market: str, interval: str, getter=None, progress=None, algos=None, variants=None, **run_kw) -> dict:
    """Roda as variantes de treino no mesmo teste e salva a comparação (``ml_lab.json``)."""
    if getter is None:
        from core.data import get_klines

        cache: dict = {}

        def getter(sym, itv, n, mk):     # baixa cada série uma vez (as variantes pedem períodos diferentes)
            k = (sym, itv, mk)
            if k not in cache or len(cache[k]) < n:
                cache[k] = get_klines(sym, itv, n, mk)
            return cache[k].tail(n).reset_index(drop=True)
    vs = lab_variants(interval)
    keys = [k for k in vs if not variants or k in variants]
    out = {}
    for n_k, k in enumerate(keys):
        def _p(f, t, n_k=n_k, k=k):
            if progress:
                progress((n_k + f) / len(keys), f"{vs[k]['label']} · {t}")
        r = run(market, interval, getter=getter, algos=list(algos or [a for a in LAB_ALGOS if a in ml.available_algos()]), include_bots=False,
                save_result=False, progress=_p, **{**vs[k]["kw"], **run_kw})
        out[k] = {"label": vs[k]["label"], **_lab_row(r)}
    result = {"ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "market": market, "interval": interval,
              "test_days": float(run_kw.get("test_days") or TEST_DAYS.get(interval, 60)), "variants": out}

    def _apply(data):
        data[_key(market, interval)] = result

    locked_update(LAB_FILE, {}, _apply)
    return result


def lab_load() -> dict:
    return load_json(LAB_FILE, {}) or {}


def lab_start(market: str, interval: str) -> bool:
    k = "lab|" + _key(market, interval)
    with _lock:
        if k in _running:
            return False
        _running.add(k)

    def _run():
        try:
            lab_run(market, interval)
        except Exception:  # noqa: BLE001
            pass
        finally:
            with _lock:
                _running.discard(k)

    threading.Thread(target=_run, daemon=True).start()
    return True
