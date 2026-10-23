"""Camada de execução: hoje simulada, amanhã Binance.

A interface abaixo isola a plataforma do destino das ordens. Para operar de
verdade basta implementar ``BinanceBroker`` (assinando as requisições com a
API Key/Secret) e trocar ``get_broker`` — interface, IA e gestão de risco
continuam iguais.
"""
from __future__ import annotations

from core import paper


class PaperBroker:
    name = "Conta simulada (paper trading)"
    live = False

    def __init__(self, bot: str):
        self.bot = bot

    def account(self) -> dict:
        return paper.get_account(self.bot)

    def place_order(self, **kwargs) -> dict:
        return paper.place_order(self.bot, **kwargs)

    def close_position(self, position_id: str, price: float, reason: str = "Manual"):
        return paper.close_position(self.bot, position_id, price, reason)

    def cancel_order(self, order_id: str) -> None:
        paper.cancel_order(self.bot, order_id)

    def update_protection(self, position_id: str, stop_loss, take_profit) -> None:
        paper.update_protection(self.bot, position_id, stop_loss, take_profit)

    def sync(self, symbol: str, candles, last_price: float) -> list[dict]:
        return paper.sync(self.bot, symbol, candles, last_price)

    def reset(self, initial: float) -> None:
        paper.reset_account(self.bot, initial)


class BinanceBroker(PaperBroker):  # pragma: no cover - fase 2
    """Esqueleto da integração real (fase 2).

    Mapeamento previsto:
      * spot  → POST /api/v3/order (MARKET/LIMIT) + OCO para stop/alvo
      * futuros → POST /fapi/v1/leverage, /fapi/v1/marginType e /fapi/v1/order
        com STOP_MARKET / TAKE_PROFIT_MARKET (reduceOnly)
    Recomenda-se validar primeiro na Binance Testnet
    (testnet.binance.vision e testnet.binancefuture.com).
    """
    name = "Binance (real)"
    live = True

    def __init__(self, bot: str, api_key: str, api_secret: str, testnet: bool = True):
        super().__init__(bot)
        raise NotImplementedError("Integração com a Binance será implementada na fase 2.")


def get_broker(bot: str) -> PaperBroker:
    return PaperBroker(bot)
