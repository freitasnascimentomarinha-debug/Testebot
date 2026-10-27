"""Modelo de machine learning (protótipo, inspirado no FreqAI): mais um voto para os bots e um filtro de "não opere agora".

* **Features**: os votos das habilidades (``v_*`` de ``core/fastsim.py``), retornos, volatilidade, RSI, ADX, MACD, posição nas
  Bandas, distância às médias, volume relativo e o comportamento recente do BTC (o mercado segue o BTC).
* **Alvo**: o preço sobe ou cai além do custo das taxas nas próximas ``H`` velas (velas neutras ficam fora do treino).
* **Modelo**: LightGBM (ou, se não estiver instalado, uma regressão logística em numpy). Treinado com várias moedas juntas.
* **Índice de dissimilaridade (DI)**: distância do candle atual ao vizinho mais próximo dos dados de treino, comparada com a
  distância típica entre os próprios dados de treino. Acima do limite, o mercado está diferente de tudo o que o modelo viu:
  a previsão não vale e, com o filtro ligado, o bot fica de fora.
* **Walk-forward**: no backtest o modelo é re-treinado a cada ``step_days`` só com o passado, como aconteceria ao vivo.
* **Ao vivo**: re-treino 1x por dia por mercado/tempo gráfico, salvo no banco (``ml_models.json``).
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from core import fastsim
from core.storage import load_json, locked_update

FILE = "ml_models.json"
HORIZON = {"1m": 15, "3m": 10, "5m": 12, "15m": 8, "30m": 6, "1h": 6, "2h": 4, "4h": 4, "6h": 3, "12h": 3, "1d": 3}
TRAIN_DAYS = {"5m": 20, "15m": 45, "1h": 90, "4h": 240, "1d": 720}
DI_QUANTILE = 0.98
DI_SAMPLE = 2000
VOTE_GAIN = 4.0          # p = 0,75 → voto +1
_models: dict = {}
_lock = threading.Lock()
_training: set = set()


# ------------------------------------------------------------------------------ features e alvo
def _btc_feats(btc: pd.DataFrame | None) -> pd.DataFrame | None:
    if btc is None or not len(btc):
        return None
    c = btc["close"].astype(float)
    out = pd.DataFrame({"time": btc["time"], "btc_r1": np.log(c).diff(), "btc_r4": np.log(c).diff(4), "btc_r12": np.log(c).diff(12)})
    if "rsi" in btc:
        out["btc_rsi"] = btc["rsi"].astype(float) / 100
    return out.sort_values("time")


def features(vt: pd.DataFrame, btc: pd.DataFrame | None = None) -> pd.DataFrame:
    """Uma linha por candle (mesmo índice de ``vt``)."""
    c = vt["close"].astype(float)
    atr = vt["atr"].astype(float).replace(0, np.nan)
    f = pd.DataFrame(index=vt.index)
    for k in fastsim.SKILL_KEYS:
        if f"v_{k}" in vt:
            f[f"v_{k}"] = vt[f"v_{k}"].astype(float)
    lc = np.log(c)
    f["r1"], f["r3"], f["r12"] = lc.diff(), lc.diff(3), lc.diff(12)
    f["atr_pct"] = atr / c
    f["rsi"] = vt["rsi"].astype(float) / 100
    f["adx"] = vt["adx"].astype(float) / 100
    f["d_ema_trend"] = (c - vt["ema_trend"].astype(float)) / atr
    for col in ("htf_dir", "mtf_dir"):
        if col in vt:
            f[col] = vt[col].astype(float)
    if {"di_plus", "di_minus"} <= set(vt.columns):   # colunas extras quando ``vt`` vem direto dos indicadores
        f["di"] = (vt["di_plus"].astype(float) - vt["di_minus"].astype(float)) / 100
    if "macd_hist" in vt:
        f["macd_h"] = vt["macd_hist"].astype(float) / atr
    f["range_pos"] = (c - vt["low"].rolling(20).min()) / (vt["high"].rolling(20).max() - vt["low"].rolling(20).min()).replace(0, np.nan)
    f["vol_rel"] = np.log((vt["volume"].astype(float) / vt["vol_sma"].astype(float).replace(0, np.nan)).clip(lower=1e-3))
    if "taker_ratio" in vt and vt["taker_ratio"].notna().any():
        f["taker"] = vt["taker_ratio"].astype(float)
    b = _btc_feats(btc)
    if b is not None:
        m = pd.merge_asof(vt[["time"]].reset_index().sort_values("time"), b, on="time", direction="backward").set_index("index").sort_index()
        for col in b.columns:
            if col != "time":
                f[col] = m[col].to_numpy()
    return f.replace([np.inf, -np.inf], np.nan)


def labels(vt: pd.DataFrame, interval: str, fee_pct: float) -> pd.Series:
    """1 = subiu além do custo nas próximas H velas · 0 = caiu além do custo · NaN = neutro ou sem futuro ainda."""
    h = HORIZON.get(interval, 6)
    c = vt["close"].astype(float)
    fwd = c.shift(-h) / c - 1
    cost = 2 * fee_pct / 100 * 1.5
    return pd.Series(np.where(fwd > cost, 1.0, np.where(fwd < -cost, 0.0, np.nan)), index=vt.index).where(fwd.notna())


# ------------------------------------------------------------------------------ modelo
class Model:
    def __init__(self, cols: list[str]):
        self.cols, self.kind, self.booster, self.w = cols, None, None, None
        self.mu = self.sd = None
        self.ref = self.di_thr = None
        self.meta: dict = {}

    def _x(self, X: pd.DataFrame) -> np.ndarray:
        return X.reindex(columns=self.cols).to_numpy(dtype=float)

    def _z(self, x: np.ndarray) -> np.ndarray:
        return np.nan_to_num((x - self.mu) / self.sd)

    def fit(self, X: pd.DataFrame, y: np.ndarray, seed: int = 7) -> "Model":
        x = self._x(X)
        self.mu, self.sd = np.nanmean(x, axis=0), np.nanstd(x, axis=0)
        self.sd[~np.isfinite(self.sd) | (self.sd == 0)] = 1.0
        self.mu[~np.isfinite(self.mu)] = 0.0
        try:
            import lightgbm as lgb

            self.booster = lgb.train({"objective": "binary", "learning_rate": 0.05, "num_leaves": 15, "min_data_in_leaf": 40,
                                      "feature_fraction": 0.8, "bagging_fraction": 0.8, "bagging_freq": 1, "lambda_l2": 1.0,
                                      "verbose": -1, "seed": seed, "num_threads": 2}, lgb.Dataset(x, y), num_boost_round=200)
            self.kind = "lightgbm"
        except (ImportError, OSError):   # sem LightGBM (ou sem a libgomp do sistema): regressão logística em numpy
            z = np.c_[self._z(x), np.ones(len(x))]
            w = np.zeros(z.shape[1])
            for _ in range(400):
                p = 1 / (1 + np.exp(-z @ w))
                w -= 0.1 * (z.T @ (p - y) / len(y) + 1e-3 * np.r_[w[:-1], 0])
            self.w, self.kind = w, "logistica"
        # referência do índice de dissimilaridade: amostra do treino e a distância típica até o vizinho mais próximo
        rng = np.random.default_rng(seed)
        zs = self._z(x)
        self.ref = zs[rng.choice(len(zs), min(DI_SAMPLE, len(zs)), replace=False)]
        own = _nn_dist(self.ref, self.ref, exclude_self=True)
        self.scale = float(np.median(own)) or 1.0
        self.di_thr = float(np.quantile(own / self.scale, DI_QUANTILE))
        return self

    def proba(self, X: pd.DataFrame) -> np.ndarray:
        x = self._x(X)
        if self.kind == "lightgbm":
            return self.booster.predict(x)
        z = np.c_[self._z(x), np.ones(len(x))]
        return 1 / (1 + np.exp(-z @ self.w))

    def di(self, X: pd.DataFrame) -> np.ndarray:
        return _nn_dist(self._z(self._x(X)), self.ref) / self.scale

    def importance(self, top: int = 10) -> list[tuple[str, float]]:
        if self.kind == "lightgbm":
            g = self.booster.feature_importance("gain")
        else:
            g = np.abs(self.w[:-1])
        tot = float(np.sum(g)) or 1.0
        return sorted(((c, float(v) / tot) for c, v in zip(self.cols, g)), key=lambda t: -t[1])[:top]

    # ---- guardar no banco (JSON)
    def dump(self) -> dict:
        d = {"cols": self.cols, "kind": self.kind, "mu": self.mu.tolist(), "sd": self.sd.tolist(), "ref": np.round(self.ref, 4).tolist(),
             "scale": self.scale, "di_thr": self.di_thr, "meta": self.meta}
        d["model"] = self.booster.model_to_string() if self.kind == "lightgbm" else self.w.tolist()
        return d

    @classmethod
    def load(cls, d: dict) -> "Model":
        m = cls(d["cols"])
        m.kind, m.mu, m.sd, m.ref = d["kind"], np.array(d["mu"]), np.array(d["sd"]), np.array(d["ref"])
        m.scale, m.di_thr, m.meta = d["scale"], d["di_thr"], d.get("meta", {})
        if m.kind == "lightgbm":
            import lightgbm as lgb

            m.booster = lgb.Booster(model_str=d["model"])
        else:
            m.w = np.array(d["model"])
        return m


def _nn_dist(q: np.ndarray, ref: np.ndarray, exclude_self: bool = False, chunk: int = 512) -> np.ndarray:
    """Distância de cada linha de ``q`` ao vizinho mais próximo em ``ref`` (força bruta em blocos)."""
    out = np.empty(len(q))
    r2 = (ref ** 2).sum(1)
    for i in range(0, len(q), chunk):
        b = q[i:i + chunk]
        d2 = (b ** 2).sum(1)[:, None] + r2[None, :] - 2 * b @ ref.T
        if exclude_self:
            np.fill_diagonal(d2[:, i:i + len(b)], np.inf) if len(b) else None
        out[i:i + chunk] = np.sqrt(np.maximum(d2.min(1), 0))
    return out


def vote(p: np.ndarray | float) -> np.ndarray | float:
    return np.clip((np.asarray(p) - 0.5) * VOTE_GAIN, -1, 1)


def auc(y: np.ndarray, p: np.ndarray) -> float | None:
    y, p = np.asarray(y), np.asarray(p)
    pos, neg = p[y == 1], p[y == 0]
    if not len(pos) or not len(neg):
        return None
    r = pd.Series(np.r_[pos, neg]).rank().to_numpy()
    return float((r[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


# ------------------------------------------------------------------------------ walk-forward (backtest com re-treino)
def walk_forward(frames: dict[str, pd.DataFrame], interval: str, fee_pct: float, *, train_days: float, step_days: float,
                 test_days: float, btc: pd.DataFrame | None = None, progress=None) -> dict[str, pd.DataFrame]:
    """Para cada moeda devolve ``vt`` com ``ml_p`` (probabilidade de alta), ``v_ml`` (voto), ``ml_di`` e ``ml_block`` nas velas de teste.
    O modelo de cada passo só vê velas cujo alvo já estava conhecido antes do início do passo."""
    h = HORIZON.get(interval, 6)
    step = pd.Timedelta(seconds=fastsim_sec(interval))
    data = {}
    for sym, vt in frames.items():
        vt = vt.copy()
        X = features(vt, None if sym == "BTCUSDT" else btc)
        vt["_y"] = labels(vt, interval, fee_pct)
        data[sym] = (vt, X)
    end = max(vt["time"].iloc[-1] for vt, _ in data.values())
    start = end - pd.Timedelta(days=test_days)
    cuts = list(pd.date_range(start, end, freq=pd.Timedelta(days=step_days)))
    for vt, _ in data.values():
        vt["ml_p"], vt["ml_di"] = np.nan, np.nan
    cols = None
    for k, t0 in enumerate(cuts):
        t1 = t0 + pd.Timedelta(days=step_days)
        tr_from, tr_to = t0 - pd.Timedelta(days=train_days), t0 - step * h      # o alvo de cada vela de treino já era conhecido em t0
        Xs, ys = [], []
        for vt, X in data.values():
            m = (vt["time"] >= tr_from) & (vt["time"] < tr_to) & vt["_y"].notna() & (vt.index >= fastsim.WARMUP)
            Xs.append(X[m])
            ys.append(vt.loc[m, "_y"].to_numpy())
        Xtr = pd.concat(Xs)
        if cols is None:
            cols = list(Xtr.columns)
        y = np.concatenate(ys)
        if len(y) < 300 or y.min() == y.max():
            continue
        model = Model(cols).fit(Xtr, y)
        for vt, X in data.values():
            m = (vt["time"] >= t0) & (vt["time"] < t1)
            if m.any():
                vt.loc[m, "ml_p"] = model.proba(X[m])
                vt.loc[m, "ml_di"] = model.di(X[m])
                vt.loc[m, "_thr"] = model.di_thr
        if progress:
            progress((k + 1) / len(cuts), f"Treino {k + 1}/{len(cuts)} · {len(y)} velas")
    out = {}
    for sym, (vt, _) in data.items():
        vt["v_ml"] = vote(vt["ml_p"].fillna(0.5))
        vt["ml_block"] = (vt["ml_di"] > vt.get("_thr", np.inf)).fillna(False).to_numpy()
        out[sym] = vt
    return out


def fastsim_sec(interval: str) -> float:
    return 86400 / fastsim.PER_DAY[interval]


def evaluate(frames: dict[str, pd.DataFrame], test_days: float) -> dict:
    """Qualidade das previsões nas velas de teste (fora do treino)."""
    ys, ps, blocks = [], [], []
    for vt in frames.values():
        start = vt["time"].iloc[-1] - pd.Timedelta(days=test_days)
        m = (vt["time"] >= start) & vt["ml_p"].notna()
        blocks.append(vt.loc[m, "ml_block"].to_numpy())
        mm = m & vt["_y"].notna()
        ys.append(vt.loc[mm, "_y"].to_numpy())
        ps.append(vt.loc[mm, "ml_p"].to_numpy())
    y, p, b = np.concatenate(ys) if ys else np.array([]), np.concatenate(ps) if ps else np.array([]), np.concatenate(blocks) if blocks else np.array([])
    if not len(y):
        return {"n": 0}
    conf = (p > 0.55) | (p < 0.45)
    return {"n": int(len(y)), "auc": auc(y, p), "acc": float(np.mean((p > 0.5) == (y == 1))),
            "acc_conf": float(np.mean((p[conf] > 0.5) == (y[conf] == 1))) if conf.any() else None, "conf_share": float(conf.mean()),
            "base_up": float(y.mean()), "blocked_share": float(b.mean()) if len(b) else 0.0}


def compare_bots(frames: dict[str, pd.DataFrame], bots: list[dict], market: str, test_days: float, weight: float = 1.0) -> list[dict]:
    """Cada bot nas mesmas velas de teste: sem ML, com o filtro, com o voto e com os dois."""
    from core.backtest import compound

    rows = []
    for p in bots:
        res = {}
        for label, extra in (("base", {}), ("filtro", {"ml_filter": True}), ("voto", {"ml_vote": weight}), ("ambos", {"ml_filter": True, "ml_vote": weight})):
            pp = {**p, **extra}
            if "ml_vote" in extra:
                pp["skills"] = {**(p.get("skills") or {}), "ml": weight}
            rs, rets, dds = [], [], []
            for vt in frames.values():   # cada moeda com a própria banca (1% de risco por operação); o retorno é a média
                cfg = vt.attrs.get("cfg")
                start = vt["time"].iloc[-1] - pd.Timedelta(days=test_days)
                one = [t["r"] for t in fastsim.simulate(vt, {**pp, "direction": "compra"} if market == "spot" else pp, cfg, start_time=start)]
                ret, dd = compound(one, 1.0) if one else (0.0, 0.0)
                rs += one
                rets.append(float(ret))
                dds.append(float(dd))
            res[label] = {"n": len(rs), "win": float(np.mean([r > 0 for r in rs]) * 100) if rs else 0.0, "avg_r": float(np.mean(rs)) if rs else 0.0,
                          "ret": float(np.mean(rets)) if rets else 0.0, "dd": max(dds, default=0.0)}
        rows.append({"id": p["id"], "name": p["name"], **res})
    return rows


# ------------------------------------------------------------------------------ ao vivo
def _key(market: str, interval: str) -> str:
    return f"{market}|{interval}"


def get(market: str, interval: str) -> Model | None:
    k = _key(market, interval)
    with _lock:
        if k in _models:
            return _models[k]
    d = (load_json(FILE, {}) or {}).get(k)
    if not d:
        return None
    try:
        m = Model.load(d)
    except Exception:  # noqa: BLE001 - modelo salvo com outra versão: será re-treinado
        return None
    with _lock:
        _models[k] = m
    return m


def status(market: str, interval: str) -> dict | None:
    d = (load_json(FILE, {}) or {}).get(_key(market, interval))
    return (d or {}).get("meta")


def train_live(market: str, interval: str, getter=None, symbols=None, progress=None) -> Model:
    """Treina com os dias mais recentes (várias moedas + BTC) e guarda no banco."""
    from core import personalities as P, ranking

    if getter is None:
        from core.data import get_klines as getter
    days = TRAIN_DAYS.get(interval, 60)
    symbols = list(symbols or P.PERIOD_SYMBOLS)
    frames = {}
    for k, sym in enumerate(symbols, start=1):
        try:
            vt, cfg = ranking.votes_for(sym, interval, market, days, getter)
            frames[sym] = vt
        except Exception:  # noqa: BLE001
            continue
        if progress:
            progress(k / len(symbols) * 0.7, f"Candles de {sym}")
    if not frames:
        raise RuntimeError("Sem candles para treinar agora.")
    btc = frames.get("BTCUSDT")
    fee = float(cfg["fee_pct"])
    Xs, ys, old, new = [], [], [], []
    for sym, vt in frames.items():
        X, y = features(vt, None if sym == "BTCUSDT" else btc), labels(vt, interval, fee)
        m = (y.notna() & (vt.index >= fastsim.WARMUP)).to_numpy()
        Xs.append(X[m])
        ys.append(y[m].to_numpy())
        cut = int(m.sum() * 0.85)   # os últimos 15% de cada moeda medem a qualidade num período que o modelo não viu
        old.append(np.arange(m.sum()) < cut)
        new.append(np.arange(m.sum()) >= cut + HORIZON.get(interval, 6))
    Xtr, y, old, new = pd.concat(Xs), np.concatenate(ys), np.concatenate(old), np.concatenate(new)
    hold = Model(list(Xtr.columns)).fit(Xtr[old], y[old])
    a = auc(y[new], hold.proba(Xtr[new]))
    model = Model(list(Xtr.columns)).fit(Xtr, y)
    model.meta = {"trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "rows": int(len(y)), "days": days,
                  "symbols": list(frames), "kind": model.kind, "auc_holdout": a, "base_up": float(y.mean()),
                  "importance": model.importance(8), "horizon": HORIZON.get(interval, 6)}
    dump = model.dump()

    def _apply(data):
        data[_key(market, interval)] = dump

    locked_update(FILE, {}, _apply)
    with _lock:
        _models[_key(market, interval)] = model
    if progress:
        progress(1.0, "Modelo treinado")
    return model


def is_due(market: str, interval: str, now: datetime | None = None) -> bool:
    s = status(market, interval)
    return not s or datetime.fromisoformat(s["trained_at"]).date() < (now or datetime.now(timezone.utc)).date()


def refresh_if_due(market: str, interval: str) -> bool:
    """Re-treino diário em segundo plano (nunca segura a análise)."""
    import os

    k = _key(market, interval)
    if "PYTEST_CURRENT_TEST" in os.environ or k in _training or not is_due(market, interval):
        return False
    _training.add(k)

    def _run():
        try:
            train_live(market, interval)
        except Exception:  # noqa: BLE001
            pass
        finally:
            _training.discard(k)

    threading.Thread(target=_run, daemon=True).start()
    return True


_btc_cache: dict = {}


def predict_live(df: pd.DataFrame, cfg: dict, market: str, getter=None) -> dict | None:
    """Previsão para o último candle fechado de ``df`` (saída de ``engine.prepare``): probabilidade de alta, voto e DI."""
    model = get(market, cfg["interval"])
    if model is None:
        return None
    vt = fastsim.compute_votes(df.copy(), cfg)
    btc = None
    if str(cfg["symbol"]).upper() != "BTCUSDT":
        key = (market, cfg["interval"])
        hit = _btc_cache.get(key)
        if not hit or time.time() - hit[0] > 60:
            try:
                if getter is None:
                    from core.data import get_klines as getter
                from core import indicators as ind

                raw = getter("BTCUSDT", cfg["interval"], 200, market)
                hit = (time.time(), ind.compute(raw, cfg))
                _btc_cache[key] = hit
            except Exception:  # noqa: BLE001
                hit = None
        btc = hit[1] if hit else None
    X = features(vt, btc).iloc[[-2]]   # último candle fechado
    p = float(model.proba(X)[0])
    di = float(model.di(X)[0])
    return {"p_up": round(p, 4), "vote": float(vote(p)), "di": round(di, 3), "di_thr": round(model.di_thr, 3), "outlier": bool(di > model.di_thr),
            "trained_at": model.meta.get("trained_at"), "auc": model.meta.get("auc_holdout")}
