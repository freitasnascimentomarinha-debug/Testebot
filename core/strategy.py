"""Habilidades de análise ("skills") do bot.

Cada habilidade é uma regra de programação determinística que lê os
indicadores e devolve um voto de -1 (venda) a +1 (compra) com uma
justificativa. O conjunto vira um plano de trade inicial (entrada, stop e
alvo por ATR e suportes/resistências), que é entregue à IA para
interpretação. Assim a IA nunca opera "no escuro": ela recebe números
calculados e precisa justificar qualquer divergência.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from core import indicators as ind
from core.profiles import BotProfile


@dataclass
class SkillResult:
    key: str
    name: str
    vote: float        # -1 … +1
    detail: str


@dataclass
class RulePlan:
    direction: str            # BUY, SELL ou HOLD
    score: float              # -100 … +100
    entry: float
    stop_loss: float | None
    take_profit: float | None
    atr: float
    regime: str
    skills: list[SkillResult] = field(default_factory=list)
    levels: dict = field(default_factory=dict)
    note: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["skills"] = [asdict(s) for s in self.skills]
        return d


def _clip(x: float) -> float:
    return float(np.clip(x, -1, 1))


def skill_trend(df: pd.DataFrame, cfg: dict) -> SkillResult:
    r = df.iloc[-1]
    v = 0.0
    v += 0.4 if r.ema_fast > r.ema_slow else -0.4
    v += 0.35 if r.close > r.ema_trend else -0.35
    slope = (df["ema_slow"].iloc[-1] / df["ema_slow"].iloc[-6] - 1) * 100
    v += 0.25 * np.sign(slope)
    cross = ""
    prev = df.iloc[-2]
    if prev.ema_fast <= prev.ema_slow < r.ema_fast:
        cross, v = " Cruzamento de alta recente.", v + 0.2
    elif prev.ema_fast >= prev.ema_slow > r.ema_fast:
        cross, v = " Cruzamento de baixa recente.", v - 0.2
    return SkillResult("tendencia", "Tendência (EMAs)", _clip(v),
                       f"EMA{cfg['ema_fast']} {'>' if r.ema_fast > r.ema_slow else '<'} EMA{cfg['ema_slow']}; "
                       f"preço {'acima' if r.close > r.ema_trend else 'abaixo'} da EMA{cfg['ema_trend']}; "
                       f"inclinação {slope:+.2f}%.{cross}")


def skill_momentum(df: pd.DataFrame, cfg: dict) -> SkillResult:
    r = df.iloc[-1]
    ob, os_ = float(cfg["rsi_ob"]), float(cfg["rsi_os"])
    rsi_now, rsi_prev = r.rsi, df["rsi"].iloc[-4]
    if rsi_now >= ob:
        v, txt = -0.6, "sobrecomprado"
    elif rsi_now <= os_:
        v, txt = 0.6, "sobrevendido"
    else:
        v, txt = (rsi_now - 50) / 50, "neutro"
    v += 0.3 * np.sign(rsi_now - rsi_prev) * (0.5 if txt == "neutro" else 1)
    # Divergência simples: preço faz novo extremo e o RSI não confirma
    w = df.tail(30)
    div = ""
    if w["close"].iloc[-1] >= w["close"].max() * 0.999 and rsi_now < w["rsi"].max() - 5:
        div, v = " Divergência baixista.", v - 0.3
    elif w["close"].iloc[-1] <= w["close"].min() * 1.001 and rsi_now > w["rsi"].min() + 5:
        div, v = " Divergência altista.", v + 0.3
    stoch = f" Estocástico %K {r.stoch_k:.0f}." if cfg.get("stoch_on") and not np.isnan(r.stoch_k) else ""
    return SkillResult("momentum", "Momentum (RSI)", _clip(v), f"RSI {rsi_now:.1f} ({txt}).{div}{stoch}")


def skill_macd(df: pd.DataFrame, cfg: dict) -> SkillResult:
    r, p = df.iloc[-1], df.iloc[-2]
    v = 0.5 if r.macd > r.macd_signal else -0.5
    v += 0.3 if r.macd_hist > p.macd_hist else -0.3
    v += 0.2 if r.macd > 0 else -0.2
    return SkillResult("macd", "MACD", _clip(v),
                       f"MACD {r.macd:.4g} vs sinal {r.macd_signal:.4g}; histograma {'crescendo' if r.macd_hist > p.macd_hist else 'caindo'}.")


def skill_bollinger(df: pd.DataFrame, cfg: dict) -> SkillResult:
    r = df.iloc[-1]
    width = (r.bb_up - r.bb_low) / r.bb_mid * 100
    avg_width = ((df["bb_up"] - df["bb_low"]) / df["bb_mid"] * 100).tail(100).mean()
    pos = (r.close - r.bb_low) / (r.bb_up - r.bb_low) if r.bb_up != r.bb_low else 0.5
    squeeze = width < avg_width * 0.6
    if squeeze:
        v, txt = 0.0, "compressão (squeeze) — possível rompimento próximo"
    elif pos > 1:
        v, txt = (0.4 if r.adx > 25 else -0.5), "fechamento acima da banda superior"
    elif pos < 0:
        v, txt = (-0.4 if r.adx > 25 else 0.5), "fechamento abaixo da banda inferior"
    else:
        v, txt = (0.5 - pos) * 0.6, f"posição {pos * 100:.0f}% dentro das bandas"
    return SkillResult("bollinger", "Bandas de Bollinger", _clip(v), f"{txt}; largura {width:.2f}% (média {avg_width:.2f}%).")


def skill_supertrend(df: pd.DataFrame, cfg: dict) -> SkillResult:
    d = df["st_dir"]
    flips = d.ne(d.shift()).tail(5).iloc[1:].any()
    v = float(d.iloc[-1]) * (1.0 if flips else 0.7)
    return SkillResult("supertrend", "SuperTrend", _clip(v),
                       f"{'Alta' if d.iloc[-1] > 0 else 'Baixa'} (linha {df['st_line'].iloc[-1]:.6g})"
                       f"{' — virada recente' if flips else ''}.")


def skill_vwap(df: pd.DataFrame, cfg: dict) -> SkillResult:
    r = df.iloc[-1]
    if np.isnan(r.vwap):
        return SkillResult("vwap", "VWAP", 0.0, "Sem VWAP.")
    dist = (r.close / r.vwap - 1) * 100
    v = np.tanh(dist / 0.5) * 0.8
    return SkillResult("vwap", "VWAP diário", _clip(v), f"Preço {dist:+.2f}% em relação ao VWAP ({r.vwap:.6g}).")


def skill_volume(df: pd.DataFrame, cfg: dict) -> SkillResult:
    r = df.iloc[-1]
    rel = r.volume / r.vol_sma if r.vol_sma else 1
    candle = np.sign(r.close - r.open)
    obv_slope = np.sign(df["obv"].iloc[-1] - df["obv"].iloc[-10])
    v = candle * min(rel, 2) / 2 * 0.6 + obv_slope * 0.3
    return SkillResult("volume", "Volume/OBV", _clip(v),
                       f"Volume {rel:.2f}× a média de 20; OBV {'subindo' if obv_slope > 0 else 'caindo'}.")


def skill_structure(df: pd.DataFrame, cfg: dict) -> SkillResult:
    tops, bottoms = ind.swing_points(df.tail(150).reset_index(drop=True), 3, 3)
    if len(tops) < 2 or len(bottoms) < 2:
        return SkillResult("estrutura", "Estrutura de mercado", 0.0, "Topos/fundos insuficientes.")
    hh, hl = tops[-1][1] > tops[-2][1], bottoms[-1][1] > bottoms[-2][1]
    v = 0.5 * (1 if hh else -1) + 0.5 * (1 if hl else -1)
    label = {(True, True): "topos e fundos ascendentes", (False, False): "topos e fundos descendentes"}.get((hh, hl), "lateral/indefinida")
    return SkillResult("estrutura", "Estrutura de mercado", _clip(v), f"Estrutura {label}.")


def skill_levels(df: pd.DataFrame, cfg: dict, levels: dict) -> SkillResult:
    price, a = df["close"].iloc[-1], df["atr"].iloc[-1]
    sup = levels["supports"][0]["price"] if levels["supports"] else None
    res = levels["resistances"][0]["price"] if levels["resistances"] else None
    v, notes = 0.0, []
    if sup and (price - sup) < a:
        v += 0.5
        notes.append(f"perto do suporte {sup:.6g}")
    if res and (res - price) < a:
        v -= 0.5
        notes.append(f"perto da resistência {res:.6g}")
    for lv in cfg.get("user_levels", []):
        if lv.get("type") == "horizontal" and abs(price - lv["price"]) < a:
            notes.append(f"nível do usuário '{lv.get('label', '')}' {lv['price']:.6g}")
    return SkillResult("suporte_resistencia", "Suportes e resistências", _clip(v),
                       "; ".join(notes).capitalize() + "." if notes else "Preço longe dos níveis principais.")


SKILLS = (skill_trend, skill_momentum, skill_macd, skill_bollinger, skill_supertrend, skill_vwap, skill_volume, skill_structure)


def analyze(df: pd.DataFrame, cfg: dict, profile: BotProfile) -> RulePlan:
    """Executa todas as habilidades e monta o plano baseado em regras."""
    data = df.iloc[:-1] if len(df) > 50 else df  # usa somente candles fechados
    levels = ind.support_resistance(data)
    if cfg.get("pivots_on"):
        levels["pivots"] = ind.pivot_points(data)
    if cfg.get("fib_on"):
        levels["fibonacci"] = ind.fibonacci(data)
    results = [fn(data, cfg) for fn in SKILLS] + [skill_levels(data, cfg, levels)]

    weights = profile.skill_weights
    total_w = sum(weights.get(r.key, 1.0) for r in results) or 1
    score = sum(r.vote * weights.get(r.key, 1.0) for r in results) / total_w * 100

    last = data.iloc[-1]
    adx_val = float(last.adx)
    regime = "tendência forte" if adx_val >= 25 else "tendência fraca" if adx_val >= 18 else "lateral"
    if regime == "lateral":
        score *= 0.7  # sinais de tendência são menos confiáveis em lateralização

    threshold = 25
    direction = "BUY" if score >= threshold else "SELL" if score <= -threshold else "HOLD"
    note = ""
    if direction == "SELL" and not cfg.get("allow_short", True):
        direction, note = "HOLD", "Viés vendedor, mas operações vendidas estão desativadas: ficar de fora ou encerrar compras."
    if direction == "SELL" and profile.market == "spot" and not cfg.get("leverage_on"):
        direction, note = "HOLD", "Viés vendedor no spot sem margem: não abrir compras; encerrar posições compradas se houver."

    price = float(df["close"].iloc[-1])
    a = float(last.atr)
    sl = tp = None
    if direction != "HOLD":
        sign = 1 if direction == "BUY" else -1
        # Distância mínima do stop: evita trades em que as taxas dominam o risco
        sl_dist = max(a * float(cfg["atr_sl_mult"]), price * float(cfg["fee_pct"]) / 100 * 8)
        tp_dist = sl_dist * float(cfg["atr_tp_mult"]) / float(cfg["atr_sl_mult"])
        sl = price - sign * sl_dist
        tp = price + sign * tp_dist
        # Ajusta o stop para além do suporte/resistência mais próximo, se fizer sentido
        key = "supports" if direction == "BUY" else "resistances"
        if levels[key]:
            lv = levels[key][0]["price"]
            candidate = lv - sign * a * 0.3
            if sl_dist < abs(price - candidate) < sl_dist * 1.3:
                sl = candidate
    return RulePlan(direction, round(score, 1), price, sl, tp, a, regime, results, levels, note)


def market_snapshot(df: pd.DataFrame, n: int = 60) -> list[dict]:
    """Candles recentes resumidos para a IA (com indicadores principais)."""
    cols = ["time", "open", "high", "low", "close", "volume", "ema_fast", "ema_slow", "rsi", "macd_hist", "atr"]
    tail = df[cols].tail(n).copy()
    tail["time"] = tail["time"].dt.strftime("%Y-%m-%d %H:%M")
    return [{k: (round(v, 6) if isinstance(v, float) else v) for k, v in row.items()} for row in tail.to_dict("records")]
