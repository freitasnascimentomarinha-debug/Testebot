"""Perfis dos três bots: mercado, timeframes e padrões de cada estilo."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BotProfile:
    key: str
    name: str
    icon: str
    market: str  # "futures" (USDⓈ-M perpétuo) ou "spot"
    description: str
    intervals: tuple[str, ...]
    default_interval: str
    default_leverage: int
    max_leverage: int
    leverage_on_by_default: bool
    candles: int
    refresh_sec: int
    atr_sl_mult: float
    atr_tp_mult: float
    horizon: str
    skill_weights: dict = field(default_factory=dict)

    @property
    def market_label(self) -> str:
        return "Futuros perpétuos (USDⓈ-M)" if self.market == "futures" else "Mercado à vista (Spot)"

    @property
    def is_crypto(self) -> bool:
        return True


# Páginas do menu: Futuros e Spot. O estilo (day trade, swing ou long) vem do tempo gráfico escolhido.
PAGE_BOTS = ("day", "swing")


def style_of(interval: str) -> str:
    """Estilo de operação pelo tempo gráfico: até 1h day trade; de 2h a 12h swing; de 1d em diante long."""
    if interval in ("1m", "3m", "5m", "15m", "30m", "1h"):
        return "⚡ Day Trade"
    return "🌊 Swing Trade" if interval in ("2h", "4h", "6h", "12h") else "🏔️ Long Trade"


SYMBOLS = (
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT",
    "AVAXUSDT", "LINKUSDT", "DOTUSDT", "LTCUSDT", "TRXUSDT", "SUIUSDT", "TONUSDT",
)

PROFILES: dict[str, BotProfile] = {
    "day": BotProfile(
        key="day",
        name="Futuros",
        icon="⚡",
        market="futures",
        description="Operações intradiárias em futuros perpétuos, comprado ou vendido, com alavancagem.",
        intervals=("1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"),
        default_interval="15m",
        default_leverage=5,
        max_leverage=125,
        leverage_on_by_default=True,
        candles=500,
        refresh_sec=15,
        atr_sl_mult=1.5,
        atr_tp_mult=3.5,
        horizon="minutos a poucas horas; posições devem ser encerradas no mesmo dia",
        skill_weights={"tendencia": 1.0, "momentum": 1.2, "macd": 1.0, "bollinger": 0.8,
                       "supertrend": 1.0, "vwap": 1.3, "volume": 0.8, "estrutura": 0.8, "suporte_resistencia": 1.0},
    ),
    "swing": BotProfile(
        key="swing",
        name="Spot",
        icon="🌊",
        market="spot",
        description="Operações de dias a semanas no mercado à vista, seguindo ondas de tendência.",
        intervals=("15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d", "3d", "1w", "1M"),
        default_interval="4h",
        default_leverage=1,
        max_leverage=1,
        leverage_on_by_default=False,
        candles=500,
        refresh_sec=60,
        atr_sl_mult=2.0,
        atr_tp_mult=4.0,
        horizon="dias a algumas semanas",
        skill_weights={"tendencia": 1.3, "momentum": 1.0, "macd": 1.1, "bollinger": 0.8,
                       "supertrend": 1.1, "vwap": 0.3, "volume": 0.7, "estrutura": 1.0, "suporte_resistencia": 1.2},
    ),
    "long": BotProfile(
        key="long",
        name="Long Trade",
        icon="🏔️",
        market="spot",
        description="Posições de longo prazo (semanas a meses) no mercado à vista, priorizando tendência primária.",
        intervals=("4h", "12h", "1d", "3d", "1w", "1M"),
        default_interval="1d",
        default_leverage=1,
        max_leverage=1,
        leverage_on_by_default=False,
        candles=500,
        refresh_sec=300,
        atr_sl_mult=3.0,
        atr_tp_mult=8.0,
        horizon="semanas a meses",
        skill_weights={"tendencia": 1.6, "momentum": 0.8, "macd": 1.0, "bollinger": 0.5,
                       "supertrend": 1.2, "vwap": 0.0, "volume": 0.6, "estrutura": 1.2, "suporte_resistencia": 1.1},
    ),
}
