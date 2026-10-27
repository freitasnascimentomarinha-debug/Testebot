"""Modelo de machine learning (protótipo, inspirado no FreqAI): mais um voto para os bots e um filtro de "não opere agora".

* **Features**: os votos das habilidades (``v_*`` de ``core/fastsim.py``), retornos, volatilidade, RSI, ADX, MACD, posição nas
  Bandas, distância às médias, volume relativo e o comportamento recente do BTC (o mercado segue o BTC).
* **Alvos** (``TARGETS``): direção nas próximas ``H`` velas, direção num horizonte 3× maior e "barreira" (o que o preço toca primeiro:
  +1,5 ATR ou −1,5 ATR). Velas neutras ficam fora do treino.
* **Algoritmos** (``ALGOS``): LightGBM, XGBoost, CatBoost, gradient boosting, florestas e regressão logística do scikit-learn — os que
  estiverem instalados. O torneio (``core/ml_tournament.py``) escolhe o campeão de cada mercado/tempo gráfico e de cada contexto.
* **Índice de dissimilaridade (DI)**: distância do candle atual ao vizinho mais próximo dos dados de treino, comparada com a
  distância típica entre os próprios dados de treino. Acima do limite, o mercado está diferente de tudo o que o modelo viu:
  a previsão não vale e, com o filtro ligado, o bot fica de fora.
* **Walk-forward**: no backtest o modelo é re-treinado a cada ``step_days`` só com o passado, como aconteceria ao vivo.
* **Ao vivo**: re-treino 1x por dia por mercado/tempo gráfico, salvo no banco (``ml_models.json``).
"""
from __future__ import annotations

import base64
import pickle
import threading
import time
import zlib
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from core import fastsim
from core.storage import load_json, locked_update

FILE = "ml_models.json"
HORIZON = {"1m": 15, "3m": 10, "5m": 12, "15m": 8, "30m": 6, "1h": 6, "2h": 4, "4h": 4, "6h": 3, "12h": 3, "1d": 3}
TRAIN_DAYS = {"5m": 60, "15m": 135, "1h": 270, "4h": 720, "1d": 1500}   # 3× o original: no laboratório, mais histórico foi o que mais ajudou
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


EXTRA_SYMBOLS = ("ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT", "TRXUSDT", "LTCUSDT", "BCHUSDT", "NEARUSDT", "ATOMUSDT",
                 "UNIUSDT", "ETCUSDT", "FILUSDT", "APTUSDT", "ARBUSDT")   # moedas a mais só para treinar (mais exemplos de mercado)


def market_frame(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """O mercado como um todo, vela a vela: retorno médio das moedas, quantas estão acima da média longa e a dispersão entre elas."""
    parts = []
    for sym, vt in frames.items():
        c = vt["close"].astype(float)
        parts.append(pd.DataFrame({"time": vt["time"], "sym": sym, "r1": np.log(c).diff(), "r12": np.log(c).diff(12),
                                   "above": (c > vt["ema_trend"].astype(float)).astype(float)}))
    d = pd.concat(parts)
    g = d.groupby("time")
    out = pd.DataFrame({"mkt_r1": g["r1"].mean(), "mkt_r12": g["r12"].mean(), "mkt_breadth": g["above"].mean(),
                        "mkt_disp": g["r12"].std(), "mkt_n": g["sym"].count()})
    out = out[out["mkt_n"] >= max(2, int(len(frames) * 0.6))].drop(columns="mkt_n")   # só velas com a maioria das moedas
    out["mkt_r48"] = out["mkt_r1"].rolling(48, min_periods=24).sum()
    return out.reset_index().sort_values("time")


def features(vt: pd.DataFrame, btc: pd.DataFrame | None = None, market: pd.DataFrame | None = None, extra: bool = False) -> pd.DataFrame:
    """Uma linha por candle (mesmo índice de ``vt``). ``extra`` liga o conjunto ampliado (prazos mais longos, volatilidade,
    horário e o mercado como um todo, de ``market_frame``)."""
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
    if extra:
        r1 = lc.diff()
        f["r48"], f["r96"] = lc.diff(48), lc.diff(96)
        f["vol24"] = r1.rolling(24).std()
        f["vol_ratio"] = r1.rolling(12).std() / r1.rolling(96).std().replace(0, np.nan)
        f["d_hi100"] = (c - vt["high"].rolling(100).max()) / atr
        f["d_lo100"] = (c - vt["low"].rolling(100).min()) / atr
        f["vol_z"] = (np.log(vt["volume"].astype(float).clip(lower=1e-9)) - np.log(vt["volume"].astype(float).clip(lower=1e-9)).rolling(96).mean()) \
            / np.log(vt["volume"].astype(float).clip(lower=1e-9)).rolling(96).std().replace(0, np.nan)
        hour = vt["time"].dt.hour + vt["time"].dt.minute / 60
        f["h_sin"], f["h_cos"] = np.sin(2 * np.pi * hour / 24), np.cos(2 * np.pi * hour / 24)
        f["dow"] = vt["time"].dt.dayofweek / 6
        if market is not None and len(market):
            mm = pd.merge_asof(vt[["time"]].reset_index().sort_values("time"), market, on="time", direction="backward").set_index("index").sort_index()
            for col in market.columns:
                if col != "time":
                    f[col] = mm[col].to_numpy()
            f["rel_r12"] = f["r12"] - f["mkt_r12"]        # força da moeda contra o mercado
            f["rel_r48"] = f["r48"] - f["mkt_r48"]
    return f.replace([np.inf, -np.inf], np.nan)


TARGETS = {
    "direcao": "Direção nas próximas velas",
    "tendencia": "Direção num prazo 3× maior",
    "barreira": "Toca +1,5 ATR antes de −1,5 ATR",
}
BARRIER_ATR = 1.5


def horizon(interval: str, target: str = "direcao") -> int:
    h = HORIZON.get(interval, 6)
    return h if target == "direcao" else 3 * h


def outcomes(vt: pd.DataFrame, interval: str, fee_pct: float, target: str = "direcao") -> pd.DataFrame:
    """Para uma entrada no fechamento de cada vela: rótulo do alvo (``y``), resultado de uma compra e de uma venda (fração, já
    com as taxas) e o índice da vela de saída. Sem futuro suficiente: ``y`` e resultados NaN."""
    c = vt["close"].to_numpy(dtype=float)
    n, h = len(c), horizon(interval, target)
    fee = 2 * fee_pct / 100
    idx = np.arange(n)
    ex = np.minimum(idx + h, n - 1)
    if target == "barreira":
        hi, lo = vt["high"].to_numpy(dtype=float), vt["low"].to_numpy(dtype=float)
        k = BARRIER_ATR * vt["atr"].to_numpy(dtype=float)
        hit = np.full(n, np.nan)              # 1 = barreira de cima primeiro · 0 = de baixo · 2 = as duas na mesma vela
        open_ = np.isfinite(k) & (k > 0)
        for j in range(1, h + 1):
            t = np.minimum(idx + j, n - 1)
            valid = open_ & (idx + j < n)
            up, dn = valid & (hi[t] >= c + k), valid & (lo[t] <= c - k)
            hit[up & ~dn], hit[dn & ~up], hit[up & dn] = 1.0, 0.0, 2.0
            ex = np.where(up | dn, t, ex)
            open_ &= ~(up | dn)
        y = np.where(hit == 2, np.nan, hit)
        step = k / c
        timeout = open_ & (idx + h < n)       # nenhuma barreira no prazo: sai no fechamento
        drift = np.where(timeout, c[ex] / c - 1, np.nan)
        long_r = np.select([hit == 1, hit == 0, hit == 2, timeout], [step, -step, -step, drift], np.nan)
        short_r = np.select([hit == 1, hit == 0, hit == 2, timeout], [-step, step, -step, -drift], np.nan)   # as duas: perde nos dois lados
    else:
        fwd = np.full(n, np.nan)
        fwd[: n - h] = c[h:] / c[: n - h] - 1
        cost = fee * 1.5
        y = np.where(fwd > cost, 1.0, np.where(fwd < -cost, 0.0, np.nan))
        long_r, short_r = fwd, -fwd
    return pd.DataFrame({"y": y, "long": long_r - fee, "short": short_r - fee, "exit": ex}, index=vt.index)


def labels(vt: pd.DataFrame, interval: str, fee_pct: float, target: str = "direcao") -> pd.Series:
    """1 = subiu (ou tocou a barreira de cima primeiro) · 0 = caiu · NaN = neutro ou sem futuro ainda."""
    return outcomes(vt, interval, fee_pct, target)["y"]


# ------------------------------------------------------------------------------ algoritmos
def _make(algo: str, seed: int):
    """Estimador no padrão do scikit-learn (fit / predict_proba)."""
    if algo == "xgboost":
        from xgboost import XGBClassifier

        return XGBClassifier(n_estimators=250, max_depth=4, learning_rate=0.05, subsample=0.8, colsample_bytree=0.8, min_child_weight=20,
                             reg_lambda=1.0, n_jobs=2, random_state=seed, verbosity=0)
    if algo == "catboost":
        from catboost import CatBoostClassifier

        return CatBoostClassifier(iterations=300, depth=5, learning_rate=0.05, l2_leaf_reg=3, random_seed=seed, verbose=False, thread_count=2,
                                  allow_writing_files=False)
    if algo == "hgb":
        from sklearn.ensemble import HistGradientBoostingClassifier

        return HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=40, l2_regularization=1.0,
                                              random_state=seed)
    if algo == "floresta":
        from sklearn.ensemble import RandomForestClassifier

        return RandomForestClassifier(n_estimators=150, max_depth=7, min_samples_leaf=40, max_features="sqrt", n_jobs=2, random_state=seed)
    if algo == "extra":
        from sklearn.ensemble import ExtraTreesClassifier

        return ExtraTreesClassifier(n_estimators=150, max_depth=8, min_samples_leaf=40, max_features="sqrt", n_jobs=2, random_state=seed)
    if algo == "logistica":
        from sklearn.linear_model import LogisticRegression

        return LogisticRegression(C=0.3, max_iter=500)
    raise ValueError(algo)


ALGOS = {   # nome · biblioteca que precisa estar instalada
    "lightgbm": ("LightGBM", "lightgbm"),
    "xgboost": ("XGBoost", "xgboost"),
    "catboost": ("CatBoost", "catboost"),
    "hgb": ("Gradient Boosting (scikit-learn)", "sklearn"),
    "floresta": ("Random Forest", "sklearn"),
    "extra": ("Extra Trees", "sklearn"),
    "logistica": ("Regressão logística", None),
}


def available_algos() -> list[str]:
    import importlib.util

    out = []
    for k, (_, lib) in ALGOS.items():
        if lib is None or importlib.util.find_spec(lib) is not None:
            out.append(k)
    return out


def algo_label(k: str | None) -> str:
    return ALGOS.get(k or "", (k or "—", None))[0]


# ------------------------------------------------------------------------------ modelo
class Model:
    def __init__(self, cols: list[str], algo: str = "lightgbm", target: str = "direcao"):
        self.cols, self.kind, self.booster, self.w, self.est = cols, None, None, None, None
        self.algo, self.target = algo, target
        self.mu = self.sd = None
        self.ref = self.di_thr = None
        self.meta: dict = {}

    def _x(self, X: pd.DataFrame) -> np.ndarray:
        return X.reindex(columns=self.cols).to_numpy(dtype=float)

    def _z(self, x: np.ndarray) -> np.ndarray:
        return np.nan_to_num((x - self.mu) / self.sd)

    def fit(self, X: pd.DataFrame, y: np.ndarray, seed: int = 7, di: bool = True) -> "Model":
        x = self._x(X)
        self.mu, self.sd = np.nanmean(x, axis=0), np.nanstd(x, axis=0)
        self.sd[~np.isfinite(self.sd) | (self.sd == 0)] = 1.0
        self.mu[~np.isfinite(self.mu)] = 0.0
        algo = self.algo if self.algo in available_algos() else "lightgbm"
        if algo == "logistica" and "sklearn" not in {ALGOS[a][1] for a in available_algos()}:
            algo = "logistica_np"
        if algo == "lightgbm":
            try:
                import lightgbm as lgb

                self.booster = lgb.train({"objective": "binary", "learning_rate": 0.05, "num_leaves": 15, "min_data_in_leaf": 40,
                                          "feature_fraction": 0.8, "bagging_fraction": 0.8, "bagging_freq": 1, "lambda_l2": 1.0,
                                          "verbose": -1, "seed": seed, "num_threads": 2}, lgb.Dataset(x, y), num_boost_round=200)
                self.kind = "lightgbm"
            except (ImportError, OSError):   # sem LightGBM (ou sem a libgomp do sistema): regressão logística em numpy
                algo = "logistica_np"
        if algo == "logistica_np":
            z = np.c_[self._z(x), np.ones(len(x))]
            w = np.zeros(z.shape[1])
            for _ in range(400):
                p = 1 / (1 + np.exp(-z @ w))
                w -= 0.1 * (z.T @ (p - y) / len(y) + 1e-3 * np.r_[w[:-1], 0])
            self.w, self.kind = w, "logistica_np"
        elif algo != "lightgbm":
            self.est = _make(algo, seed).fit(self._xin(x, algo), y.astype(int))
            self.kind = algo
        return self._fit_di(x, seed) if di else self

    def _xin(self, x: np.ndarray, kind: str) -> np.ndarray:
        """Florestas e logística do scikit-learn não aceitam NaN: recebem os dados padronizados (NaN → média)."""
        return self._z(x) if kind in ("floresta", "extra", "logistica") else x

    def _fit_di(self, x: np.ndarray, seed: int) -> "Model":
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
        if self.est is not None:
            return self.est.predict_proba(self._xin(x, self.kind))[:, 1]
        z = np.c_[self._z(x), np.ones(len(x))]
        return 1 / (1 + np.exp(-z @ self.w))

    def di(self, X: pd.DataFrame) -> np.ndarray:
        return _nn_dist(self._z(self._x(X)), self.ref) / self.scale

    def importance(self, top: int = 10) -> list[tuple[str, float]]:
        if self.kind == "lightgbm":
            g = self.booster.feature_importance("gain")
        elif self.est is not None:
            g = np.abs(self.est.coef_[0]) if self.kind == "logistica" else getattr(self.est, "feature_importances_", None)
            if g is None:   # o gradient boosting do scikit-learn não tem importância pronta
                return []
        else:
            g = np.abs(self.w[:-1])
        g = np.asarray(g, dtype=float)
        tot = float(np.sum(g)) or 1.0
        return sorted(((c, float(v) / tot) for c, v in zip(self.cols, g)), key=lambda t: -t[1])[:top]

    # ---- guardar no banco (JSON)
    def dump(self) -> dict:
        d = {"cols": self.cols, "kind": self.kind, "algo": self.algo, "target": self.target, "mu": self.mu.tolist(), "sd": self.sd.tolist(),
             "ref": np.round(self.ref, 4).tolist(), "scale": self.scale, "di_thr": self.di_thr, "meta": self.meta}
        if self.kind == "lightgbm":
            d["model"] = self.booster.model_to_string()
        elif self.est is not None:   # demais bibliotecas: pickle comprimido em texto
            d["model"] = base64.b64encode(zlib.compress(pickle.dumps(self.est), 6)).decode()
        else:
            d["model"] = self.w.tolist()
        return d

    @classmethod
    def load(cls, d: dict) -> "Model":
        m = cls(d["cols"], d.get("algo", "lightgbm"), d.get("target", "direcao"))
        m.kind, m.mu, m.sd, m.ref = d["kind"], np.array(d["mu"]), np.array(d["sd"]), np.array(d["ref"])
        m.scale, m.di_thr, m.meta = d["scale"], d["di_thr"], d.get("meta", {})
        if m.kind == "lightgbm":
            import lightgbm as lgb

            m.booster = lgb.Booster(model_str=d["model"])
        elif isinstance(d["model"], str):
            m.est = pickle.loads(zlib.decompress(base64.b64decode(d["model"])))   # noqa: S301 - gerado pelo próprio sistema
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
                 test_days: float, btc: pd.DataFrame | None = None, progress=None, algo: str = "lightgbm",
                 target: str = "direcao") -> dict[str, pd.DataFrame]:
    """Para cada moeda devolve ``vt`` com ``ml_p`` (probabilidade de alta), ``v_ml`` (voto), ``ml_di`` e ``ml_block`` nas velas de teste.
    O modelo de cada passo só vê velas cujo alvo já estava conhecido antes do início do passo."""
    h = horizon(interval, target)
    step = pd.Timedelta(seconds=fastsim_sec(interval))
    data = {}
    for sym, vt in frames.items():
        vt = vt.copy()
        X = features(vt, None if sym == "BTCUSDT" else btc)
        vt["_y"] = labels(vt, interval, fee_pct, target)
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
        model = Model(cols, algo, target).fit(Xtr, y)
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


def get_bundle(market: str, interval: str) -> tuple[Model, dict[str, Model]] | None:
    """(modelo principal, {grupo de contexto: modelo campeão naquele contexto})."""
    k = _key(market, interval)
    with _lock:
        if k in _models:
            return _models[k]
    d = (load_json(FILE, {}) or {}).get(k)
    if not d:
        return None
    try:
        main = Model.load(d)
        loaded = {c: Model.load(x) for c, x in (d.get("ctx_models") or {}).items()}
        ctx = {g: loaded[c] for g, c in (d.get("by_ctx") or {}).items() if c in loaded}
    except Exception:  # noqa: BLE001 - modelo salvo com outra versão: será re-treinado
        return None
    with _lock:
        _models[k] = (main, ctx)
    return main, ctx


def get(market: str, interval: str) -> Model | None:
    b = get_bundle(market, interval)
    return b[0] if b else None


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
    from core import ml_tournament as T

    champ, by_ctx = T.champions(market, interval)    # campeões do último torneio (sem torneio: LightGBM · direção)
    main_c = champ or T.combo("lightgbm", "direcao")
    combos = [main_c] + [c for c in dict.fromkeys(by_ctx.values()) if c != main_c][:3]
    feats = {sym: features(vt, None if sym == "BTCUSDT" else btc) for sym, vt in frames.items()}
    cols = sorted(set().union(*(f.columns for f in feats.values())))
    trained = {}
    for n_c, c in enumerate(combos):
        algo, target = c.split("|")
        Xs, ys, old, new = [], [], [], []
        for sym, vt in frames.items():
            y = labels(vt, interval, fee, target)
            m = (y.notna() & (vt.index >= fastsim.WARMUP)).to_numpy()
            Xs.append(feats[sym].reindex(columns=cols)[m])
            ys.append(y[m].to_numpy())
            cut = int(m.sum() * 0.85)   # os últimos 15% de cada moeda medem a qualidade num período que o modelo não viu
            old.append(np.arange(m.sum()) < cut)
            new.append(np.arange(m.sum()) >= cut + horizon(interval, target))
        Xtr, y, old, new = pd.concat(Xs), np.concatenate(ys), np.concatenate(old), np.concatenate(new)
        hold = Model(cols, algo, target).fit(Xtr[old], y[old], di=False)
        model = Model(cols, algo, target).fit(Xtr, y)
        model.meta = {"trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "rows": int(len(y)), "days": days,
                      "symbols": list(frames), "kind": model.kind, "algo": algo, "target": target, "combo": c,
                      "auc_holdout": auc(y[new], hold.proba(Xtr[new])), "base_up": float(y.mean()),
                      "importance": model.importance(8), "horizon": horizon(interval, target)}
        trained[c] = model
        if progress:
            progress(0.7 + 0.3 * (n_c + 1) / len(combos), f"Treinado: {T.combo_label(c)}")
    model = trained[main_c]
    ctx_map = {g: c for g, c in by_ctx.items() if c in trained}
    model.meta.update({"from_tournament": bool(champ), "by_ctx": ctx_map})
    dump = model.dump()
    dump["ctx_models"] = {c: m_.dump() for c, m_ in trained.items() if c != main_c}
    dump["by_ctx"] = {g: c for g, c in ctx_map.items() if c != main_c}

    def _apply(data):
        data[_key(market, interval)] = dump

    locked_update(FILE, {}, _apply)
    with _lock:
        _models[_key(market, interval)] = (model, {g: trained[c] for g, c in dump["by_ctx"].items()})
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
    bundle = get_bundle(market, cfg["interval"])
    if bundle is None:
        return None
    from core import ml_tournament as T

    vt = fastsim.compute_votes(df.copy(), cfg)
    group = T.group_of(vt["regime"].iloc[-2] if "regime" in vt else None)
    model = bundle[1].get(group) or bundle[0]     # o campeão do contexto atual, se o torneio achou um
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
            "trained_at": model.meta.get("trained_at"), "auc": model.meta.get("auc_holdout"),
            "modelo": T.combo_label(model.meta.get("combo") or combo_of(model)), "contexto": T.CTX_GROUPS[group][0],
            "do_contexto": model is not bundle[0]}


def combo_of(model: Model) -> str:
    return f"{model.algo}|{model.target}"
