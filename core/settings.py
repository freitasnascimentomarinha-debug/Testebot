"""Configurações de cada bot (risco, metas, alavancagem, indicadores e IA).

As configurações ficam em ``data/settings.json`` para que a interface e o
``worker.py`` usem exatamente os mesmos parâmetros.
"""
from __future__ import annotations

from core.profiles import PROFILES, BotProfile
from core.storage import load_json, locked_update

SETTINGS_FILE = "settings.json"
DEFAULT_MODEL = "deepseek/deepseek-v4.1-flash"


def default_settings(profile: BotProfile) -> dict:
    futures = profile.market == "futures"
    return {
        # Mercado
        "symbol": "BTCUSDT",
        "interval": profile.default_interval,
        "candles": profile.candles,
        # Risco por operação
        "risk_mode": "USDT",            # "USDT" ou "% do saldo"
        "max_loss_usdt": 20.0,          # perda máxima aceitável por trade
        "max_loss_pct": 1.0,
        "min_rr": 1.5,                  # relação risco:retorno mínima
        "atr_sl_mult": profile.atr_sl_mult,
        "atr_tp_mult": profile.atr_tp_mult,
        # Metas diárias
        "max_trades_day": 6 if futures else 3,
        "daily_profit_target": 60.0,    # ao atingir, o bot para no dia
        "daily_max_loss": 60.0,         # ao atingir, o bot para no dia
        "max_open_positions": 2 if futures else 3,
        # Escopo dos limites (você × bot)
        "limits_trades_scope": "bot",       # meta de operações e posições simultâneas
        "limits_pnl_scope": "carteira",     # meta de lucro e limite de perda do dia
        "manual_limits": "livre",           # suas ordens manuais: livre | pnl | todos
        # Alavancagem
        "leverage_on": profile.leverage_on_by_default,
        "leverage": profile.default_leverage,
        "margin_mode": "Isolada",
        "allow_short": futures,
        # Custos simulados
        "fee_pct": 0.05 if futures else 0.10,
        "slippage_pct": 0.02,
        # Indicadores
        "ema_on": True, "ema_fast": 9, "ema_slow": 21, "ema_trend": 200,
        "bb_on": True, "bb_period": 20, "bb_std": 2.0,
        "vwap_on": futures,
        "supertrend_on": True, "st_period": 10, "st_mult": 3.0,
        "ichimoku_on": False,
        "rsi_on": True, "rsi_period": 14, "rsi_ob": 70, "rsi_os": 30,
        "macd_on": True, "macd_fast": 12, "macd_slow": 26, "macd_signal": 9,
        "stoch_on": False, "stoch_k": 14, "stoch_d": 3,
        "adx_on": True, "adx_period": 14,
        "atr_period": 14,
        "obv_on": False,
        "volume_on": True,
        "sr_on": True,
        "fib_on": False,
        "pivots_on": futures,
        # IA
        "ai_model": DEFAULT_MODEL,
        "ai_temperature": 0.2,
        "ai_auto_execute": False,
        "ai_min_confidence": 60,
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
    return {**defaults, **{k: v for k, v in stored.items() if k in defaults}}


def save_settings(bot: str, cfg: dict) -> None:
    def _apply(data: dict):
        data[bot] = cfg

    locked_update(SETTINGS_FILE, {}, _apply)
