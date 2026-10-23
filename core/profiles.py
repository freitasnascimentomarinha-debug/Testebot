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
        if self.market == "futures":
            return "Futuros perpétuos (USDⓈ-M)"
        if self.market == "spot":
            return "Mercado à vista (Spot)"
        from core import markets

        return markets.MARKETS[self.market].label

    @property
    def is_crypto(self) -> bool:
        return self.market in ("futures", "spot")


SYMBOLS = (
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT",
    "AVAXUSDT", "LINKUSDT", "DOTUSDT", "LTCUSDT", "TRXUSDT", "SUIUSDT", "TONUSDT",
)

PROFILES: dict[str, BotProfile] = {
    "day": BotProfile(
        key="day",
        name="Day Trade",
        icon="⚡",
        market="futures",
        description="Operações intradiárias em futuros perpétuos, comprado ou vendido, com alavancagem.",
        intervals=("1m", "3m", "5m", "15m", "30m", "1h"),
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
        name="Swing Trade",
        icon="🌊",
        market="spot",
        description="Operações de dias a semanas no mercado à vista, seguindo ondas de tendência.",
        intervals=("15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"),
        default_interval="4h",
        default_leverage=3,
        max_leverage=10,
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
        default_leverage=2,
        max_leverage=10,
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


# --------------------------------------------------------------------- outros mercados (Yahoo Finance)
from core import markets as _markets  # noqa: E402

_OTHER = {
    # chave: (nome curto, atr stop, atr alvo, horizonte, pesos, atualização em segundos)
    "forex": ("Forex", 1.5, 3.0, "minutos a dias; mercado 24 h de segunda a sexta",
              {"tendencia": 1.2, "momentum": 1.0, "macd": 1.0, "bollinger": 0.8, "supertrend": 1.0, "volume": 0.0, "estrutura": 1.0,
               "suporte_resistencia": 1.2}, 15),
    "commodities": ("Commodities", 2.0, 4.0, "horas a semanas; contratos futuros",
                    {"tendencia": 1.3, "momentum": 1.0, "macd": 1.0, "bollinger": 0.8, "supertrend": 1.1, "volume": 0.6, "estrutura": 1.0,
                     "suporte_resistencia": 1.2}, 30),
    "indices": ("Índices", 2.0, 4.0, "horas a semanas; segue o horário de cada bolsa",
                {"tendencia": 1.3, "momentum": 1.0, "macd": 1.0, "bollinger": 0.8, "supertrend": 1.1, "volume": 0.6, "estrutura": 1.0,
                 "suporte_resistencia": 1.2}, 30),
    "stocks": ("Ações Brasil", 2.0, 4.0, "horas a semanas; pregão das 10h às 17h55 (Brasília)",
               {"tendencia": 1.3, "momentum": 1.0, "macd": 1.0, "bollinger": 0.8, "supertrend": 1.1, "volume": 0.8, "estrutura": 1.0,
                "suporte_resistencia": 1.2}, 30),
}
for _key, (_name, _sl, _tp, _hz, _w, _ref) in _OTHER.items():
    _m = _markets.MARKETS[_key]
    PROFILES[_key] = BotProfile(
        key=_key, name=_m.label, icon=_m.icon, market=_key, description=_m.description, intervals=_m.intervals,
        default_interval=_m.default_interval, default_leverage=_m.default_leverage, max_leverage=_m.max_leverage,
        leverage_on_by_default=_m.max_leverage > 1, candles=500, refresh_sec=_ref, atr_sl_mult=_sl, atr_tp_mult=_tp, horizon=_hz,
        skill_weights=_w)
