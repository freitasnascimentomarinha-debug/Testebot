"""Configurações de cada bot (risco, metas, alavancagem, indicadores e IA).

As configurações ficam em ``data/settings.json`` para que a interface e o
``worker.py`` usem exatamente os mesmos parâmetros.
"""
from __future__ import annotations

from core.personalities import DEFAULT_BY_BOT
from core.profiles import PROFILES, BotProfile
from core.storage import load_json, locked_update

SETTINGS_FILE = "settings.json"
DEFAULT_MODEL = "deepseek/deepseek-v4.1-flash"

# Par de médias móveis exibido por padrão em cada estilo (rápida, lenta)
EMA_PAIRS = {"day": (9, 21), "swing": (21, 50), "long": (50, 200)}

# Chaves de exibição de indicadores; versões antigas das configurações são migradas
# uma vez para o novo padrão enxuto (2 médias + volume).
INDICATOR_KEYS = ("ema_on", "ema_fast", "ema_slow", "bb_on", "vwap_on", "supertrend_on", "ichimoku_on", "rsi_on",
                  "macd_on", "stoch_on", "adx_on", "obv_on", "volume_on", "sr_on", "fib_on", "pivots_on")


def default_settings(profile: BotProfile) -> dict:
    futures = profile.market == "futures"
    return {
        # Mercado
        "symbol": "BTCUSDT",
        "interval": profile.default_interval,
        "candles": profile.candles,
        # Risco por operação
        "risk_mode": "% do saldo",      # "USDT" ou "% do saldo" (banca-padrão pequena: 100 USDT)
        "max_loss_usdt": 2.0,           # perda máxima aceitável por trade
        "max_loss_pct": 2.0,
        "atr_sl_mult": profile.atr_sl_mult,
        "atr_tp_mult": profile.atr_tp_mult,
        # Alavancagem
        "leverage_on": profile.leverage_on_by_default,
        "leverage": profile.default_leverage,
        "margin_mode": "Isolada",
        "allow_short": futures,
        # Custos simulados
        "fee_pct": 0.05 if futures else 0.10,
        "slippage_pct": 0.02,
        # Indicadores
        # Indicadores: por padrão só duas médias móveis + volume (os demais são adicionados pelo usuário)
        "ema_on": True, "ema_fast": EMA_PAIRS[profile.key][0], "ema_slow": EMA_PAIRS[profile.key][1],
        "ema_trend_on": False, "ema_trend": 200,
        "bb_on": False, "bb_period": 20, "bb_std": 2.0,
        "vwap_on": False,
        "supertrend_on": False, "st_period": 10, "st_mult": 3.0,
        "ichimoku_on": False,
        "rsi_on": False, "rsi_period": 14, "rsi_ob": 70, "rsi_os": 30,
        "macd_on": False, "macd_fast": 12, "macd_slow": 26, "macd_signal": 9,
        "stoch_on": False, "stoch_k": 14, "stoch_d": 3,
        "adx_on": False, "adx_period": 14,
        "atr_period": 14,
        "obv_on": False,
        "volume_on": True,
        "sr_on": False,
        "fib_on": False,
        "pivots_on": False,
        # Personalidade (estratégia) do bot — ver página Personalidades
        "personality": DEFAULT_BY_BOT.get(profile.key),
        "context_mode": "sempre",   # "sempre" ou "favoraveis" (só nos contextos favoráveis da personalidade)
        # IA
        "ai_model": DEFAULT_MODEL,
        "ai_intervene": False,       # False: a IA só explica e dá dicas · True: ela confirma ou veta a ativação do bot
        "ai_persona": "professor",   # tom das explicações (core/ai.py: AI_PERSONAS)
        "auto_bot": True,            # no fechamento do candle usa o bot mais recomendado para o contexto (ranking semanal)
        "ai_temperature": 0.2,
        "ai_auto_execute": False,
        "ai_auto_arm": True,         # piloto automático arma os planos condicionais propostos pela IA
        "ai_candles_context": 60,
        "ai_instructions": "",
        # Automação
        "refresh_sec": profile.refresh_sec,
        "autopilot": False,
        # Níveis desenhados pelo usuário (horizontais / linhas de tendência)
        "user_levels": [],
    }


def load_settings(bot: str) -> dict:
    defaults = default_settings(PROFILES[bot])
    stored = (load_json(SETTINGS_FILE, {}) or {}).get(bot, {})
    if stored and "ema_trend_on" not in stored:  # configuração anterior ao padrão enxuto
        stored = {k: v for k, v in stored.items() if k not in INDICATOR_KEYS}
    cfg = {**defaults, **{k: v for k, v in stored.items() if k in defaults}}
    if PROFILES[bot].market == "spot":  # spot não tem alavancagem, margem nem venda a descoberto
        cfg.update(leverage_on=False, leverage=1, margin_mode="Isolada", allow_short=False)
    return cfg


def save_settings(bot: str, cfg: dict) -> None:
    def _apply(data: dict):
        data[bot] = cfg

    locked_update(SETTINGS_FILE, {}, _apply)
