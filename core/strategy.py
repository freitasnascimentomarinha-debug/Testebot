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


def skill_breakout(df: pd.DataFrame, cfg: dict) -> SkillResult:
    """Rompimento do canal de Donchian (20) confirmado por volume."""
    w = df.iloc[-21:-1]
    r = df.iloc[-1]
    hi, lo = w["high"].max(), w["low"].min()
    vol_ok = r.volume > r.vol_sma * 1.2 if r.vol_sma else False
    if r.close > hi:
        v, txt = (0.9 if vol_ok else 0.5), f"rompeu a máxima de 20 candles ({hi:.6g})"
    elif r.close < lo:
        v, txt = (-0.9 if vol_ok else -0.5), f"perdeu a mínima de 20 candles ({lo:.6g})"
    else:
        pos = (r.close - lo) / (hi - lo) if hi != lo else 0.5
        v, txt = (pos - 0.5) * 0.4, f"dentro do canal ({pos * 100:.0f}% da faixa)"
    return SkillResult("rompimento", "Rompimento (Donchian 20)", _clip(v),
                       f"Preço {txt}{'; volume confirma' if vol_ok else ''}.")


def skill_mean_reversion(df: pd.DataFrame, cfg: dict) -> SkillResult:
    """Reversão à média: extremos de Bollinger + RSI apontam volta à média."""
    r = df.iloc[-1]
    v, notes = 0.0, []
    if r.close <= r.bb_low:
        v += 0.5
        notes.append("abaixo da banda inferior")
    elif r.close >= r.bb_up:
        v -= 0.5
        notes.append("acima da banda superior")
    if r.rsi <= float(cfg["rsi_os"]):
        v += 0.5
        notes.append(f"RSI {r.rsi:.0f} sobrevendido")
    elif r.rsi >= float(cfg["rsi_ob"]):
        v -= 0.5
        notes.append(f"RSI {r.rsi:.0f} sobrecomprado")
    if r.adx > 30:
        v *= 0.4  # tendência forte: reversão é arriscada
        notes.append("tendência forte reduz o sinal")
    return SkillResult("reversao", "Reversão à média", _clip(v),
                       ("; ".join(notes) or "Preço sem extremos").capitalize() + ".")


def skill_ichimoku(df: pd.DataFrame, cfg: dict) -> SkillResult:
    r = df.iloc[-1]
    if np.isnan(r.get("ichi_span_a", np.nan)) or np.isnan(r.get("ichi_span_b", np.nan)):
        return SkillResult("ichimoku", "Ichimoku", 0.0, "Dados insuficientes.")
    top, bottom = max(r.ichi_span_a, r.ichi_span_b), min(r.ichi_span_a, r.ichi_span_b)
    v = 0.5 if r.close > top else -0.5 if r.close < bottom else 0.0
    v += 0.3 if r.ichi_tenkan > r.ichi_kijun else -0.3
    v += 0.2 if r.ichi_span_a > r.ichi_span_b else -0.2
    pos = "acima" if r.close > top else "abaixo" if r.close < bottom else "dentro"
    return SkillResult("ichimoku", "Ichimoku", _clip(v),
                       f"Preço {pos} da nuvem; Tenkan {'>' if r.ichi_tenkan > r.ichi_kijun else '<'} Kijun.")


def skill_stochastic(df: pd.DataFrame, cfg: dict) -> SkillResult:
    r, p = df.iloc[-1], df.iloc[-2]
    if np.isnan(r.stoch_k) or np.isnan(r.stoch_d):
        return SkillResult("estocastico", "Estocástico", 0.0, "Dados insuficientes.")
    v = 0.0
    cross_up, cross_dn = p.stoch_k <= p.stoch_d and r.stoch_k > r.stoch_d, p.stoch_k >= p.stoch_d and r.stoch_k < r.stoch_d
    if cross_up:
        v = 0.8 if r.stoch_k < 30 else 0.4
    elif cross_dn:
        v = -0.8 if r.stoch_k > 70 else -0.4
    else:
        v = 0.3 if r.stoch_k < 20 else -0.3 if r.stoch_k > 80 else 0.0
    txt = "cruzamento de alta" if cross_up else "cruzamento de baixa" if cross_dn else "sem cruzamento"
    return SkillResult("estocastico", "Estocástico", _clip(v), f"%K {r.stoch_k:.0f} / %D {r.stoch_d:.0f}, {txt}.")


def skill_adx(df: pd.DataFrame, cfg: dict) -> SkillResult:
    r = df.iloc[-1]
    strength = min(1.0, max(0.0, (r.adx - 15) / 20))
    v = (1 if r.di_plus > r.di_minus else -1) * strength
    return SkillResult("adx", "ADX / DMI", _clip(v),
                       f"ADX {r.adx:.0f}; +DI {r.di_plus:.0f} {'>' if r.di_plus > r.di_minus else '<'} −DI {r.di_minus:.0f}.")


def skill_fibonacci(df: pd.DataFrame, cfg: dict) -> SkillResult:
    """Retração de Fibonacci da última perna (100 candles): compra na zona 38,2%–61,8%
    de uma perna de alta e vende na mesma zona de uma perna de baixa."""
    w = df.tail(100)
    highs, lows = w["high"].to_numpy(), w["low"].to_numpy()
    hi_i, lo_i = int(highs.argmax()), int(lows.argmin())
    hi, lo = highs[hi_i], lows[lo_i]
    rng = hi - lo
    r = df.iloc[-1]
    if rng <= 0:
        return SkillResult("fibonacci", "Fibonacci", 0.0, "Sem perna definida.")
    bullish_candle = r.close > r.open
    if lo_i < hi_i:  # perna de alta: mede a retração a partir do topo
        retr = (hi - r.close) / rng
        sign, leg = 1, "alta"
        confirm = bullish_candle
    else:  # perna de baixa: mede o repique a partir do fundo
        retr = (r.close - lo) / rng
        sign, leg = -1, "baixa"
        confirm = not bullish_candle
    if 0.382 <= retr <= 0.618:
        v = 0.6 + (0.3 if confirm else 0.0) + (0.1 if retr >= 0.5 else 0.0)
        zone = "na zona 38,2%–61,8%"
    elif 0.236 <= retr < 0.382:
        v, zone = 0.3, "na zona rasa 23,6%–38,2%"
    elif retr > 0.786:
        v, zone = -0.4, "além de 78,6% (perna invalidada)"
    else:
        v, zone = 0.0, f"em {retr * 100:.0f}% da perna"
    return SkillResult("fibonacci", "Fibonacci", _clip(sign * v),
                       f"Perna de {leg} {lo:.6g}–{hi:.6g}; preço {zone}{'; candle confirma' if confirm and v > 0.5 else ''}.")


# Registro de habilidades: chave → (nome, função)
SKILLS = {
    "tendencia": ("Tendência (EMAs)", skill_trend),
    "momentum": ("Momentum (RSI)", skill_momentum),
    "macd": ("MACD", skill_macd),
    "bollinger": ("Bandas de Bollinger", skill_bollinger),
    "supertrend": ("SuperTrend", skill_supertrend),
    "vwap": ("VWAP diário", skill_vwap),
    "volume": ("Volume/OBV", skill_volume),
    "estrutura": ("Estrutura de mercado", skill_structure),
    "suporte_resistencia": ("Suportes e resistências", None),  # usa os níveis calculados
    "rompimento": ("Rompimento (Donchian 20)", skill_breakout),
    "reversao": ("Reversão à média", skill_mean_reversion),
    "ichimoku": ("Ichimoku", skill_ichimoku),
    "estocastico": ("Estocástico", skill_stochastic),
    "adx": ("ADX / DMI", skill_adx),
    "fibonacci": ("Fibonacci (retração)", skill_fibonacci),
}


def analyze(df: pd.DataFrame, cfg: dict, profile: BotProfile, personality: dict | None = None,
            live: bool = True) -> RulePlan:
    """Executa as habilidades e monta o plano baseado em regras.

    ``personality`` (ver ``core/personalities.py``) define pesos das
    habilidades, limiar de entrada, direção permitida, filtros e stop/alvo.
    ``live=True`` descarta o último candle (ainda em formação)."""
    data = df.iloc[:-1] if live and len(df) > 50 else df
    levels = ind.support_resistance(data)
    if cfg.get("pivots_on"):
        levels["pivots"] = ind.pivot_points(data)
    if cfg.get("fib_on"):
        levels["fibonacci"] = ind.fibonacci(data)

    weights = (personality or {}).get("skills") or profile.skill_weights
    results = []
    for key, (_, fn) in SKILLS.items():
        if weights.get(key, 0) <= 0:
            continue
        results.append(skill_levels(data, cfg, levels) if key == "suporte_resistencia" else fn(data, cfg))
    total_w = sum(weights[r.key] for r in results) or 1
    score = sum(r.vote * weights[r.key] for r in results) / total_w * 100

    last = data.iloc[-1]
    adx_val = float(last.adx)
    regime = "tendência forte" if adx_val >= 25 else "tendência fraca" if adx_val >= 18 else "lateral"
    filters = (personality or {}).get("filters", {})
    if regime == "lateral" and not filters.get("ignore_regime"):
        score *= 0.7  # sinais de tendência são menos confiáveis em lateralização

    threshold = float((personality or {}).get("threshold", 25))
    direction = "BUY" if score >= threshold else "SELL" if score <= -threshold else "HOLD"
    notes = []

    def block(reason: str):
        nonlocal direction
        direction = "HOLD"
        notes.append(reason)

    if direction != "HOLD" and personality:
        allowed = personality.get("direction", "misto")
        if allowed == "compra" and direction == "SELL":
            block("Sinal de venda ignorado: a personalidade opera só comprado.")
        elif allowed == "venda" and direction == "BUY":
            block("Sinal de compra ignorado: a personalidade opera só vendido.")
    if direction != "HOLD":
        if filters.get("trend_ema") and ((direction == "BUY" and last.close < last.ema_trend)
                                         or (direction == "SELL" and last.close > last.ema_trend)):
            block(f"Filtro de tendência: operação contra a EMA {cfg['ema_trend']} bloqueada.")
        elif float(filters.get("adx_min", 0) or 0) and adx_val < float(filters["adx_min"]):
            block(f"Filtro ADX: {adx_val:.0f} abaixo do mínimo {filters['adx_min']}.")
        elif float(filters.get("adx_max", 0) or 0) and adx_val > float(filters["adx_max"]):
            block(f"Filtro ADX: {adx_val:.0f} acima do máximo {filters['adx_max']} (tendência forte demais).")
        elif filters.get("avoid_lateral") and regime == "lateral":
            block("Filtro: mercado lateral, a personalidade evita operar.")
        elif filters.get("volume_confirm") and not (last.vol_sma and last.volume > last.vol_sma):
            block("Filtro: volume abaixo da média, sem confirmação.")
        elif filters.get("rsi_guard") and ((direction == "BUY" and last.rsi > float(cfg["rsi_ob"]))
                                           or (direction == "SELL" and last.rsi < float(cfg["rsi_os"]))):
            block("Filtro RSI: entrada em extremo bloqueada.")
    if direction == "SELL" and not cfg.get("allow_short", True):
        block("Viés vendedor, mas operações vendidas estão desativadas: ficar de fora ou encerrar compras.")
    if direction == "SELL" and profile.market == "spot" and not cfg.get("leverage_on"):
        block("Viés vendedor no spot sem margem: não abrir compras; encerrar posições compradas se houver.")

    price = float(df["close"].iloc[-1]) if live else float(last.close)
    a = float(last.atr)
    sl_mult = float((personality or {}).get("sl_atr") or cfg["atr_sl_mult"])
    tp_mult = float((personality or {}).get("tp_atr") or cfg["atr_tp_mult"])
    sl = tp = None
    if direction != "HOLD":
        sign = 1 if direction == "BUY" else -1
        # Distância mínima do stop: evita trades em que as taxas dominam o risco
        sl_dist = max(a * sl_mult, price * float(cfg["fee_pct"]) / 100 * 8)
        tp_dist = sl_dist * tp_mult / sl_mult
        sl = price - sign * sl_dist
        tp = price + sign * tp_dist
        # Ajusta o stop para além do suporte/resistência mais próximo, se fizer sentido
        key = "supports" if direction == "BUY" else "resistances"
        if levels[key]:
            lv = levels[key][0]["price"]
            candidate = lv - sign * a * 0.3
            if sl_dist < abs(price - candidate) < sl_dist * 1.3:
                sl = candidate
    return RulePlan(direction, round(score, 1), price, sl, tp, a, regime, results, levels, " ".join(notes))


def market_snapshot(df: pd.DataFrame, n: int = 60) -> list[dict]:
    """Candles recentes resumidos para a IA (com indicadores principais)."""
    cols = ["time", "open", "high", "low", "close", "volume", "ema_fast", "ema_slow", "rsi", "macd_hist", "atr"]
    tail = df[cols].tail(n).copy()
    tail["time"] = tail["time"].dt.strftime("%Y-%m-%d %H:%M")
    return [{k: (round(v, 6) if isinstance(v, float) else v) for k, v in row.items()} for row in tail.to_dict("records")]
