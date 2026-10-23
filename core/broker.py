"""Camada de execução: hoje simulada, amanhã Binance.

A interface abaixo isola a plataforma do destino das ordens. Para operar de
verdade basta implementar ``BinanceBroker`` (assinando as requisições com a
API Key/Secret) e trocar ``get_broker`` — interface, IA e gestão de risco
continuam iguais.
"""
from __future__ import annotations

from core import paper


class PaperBroker:
    name = "Carteira simulada (paper trading)"
    live = False

    def __init__(self, bot: str):
        self.bot = bot
        self.acc = paper.account_id(bot)  # "carteira" (única) ou o próprio bot (separada)

    def account(self) -> dict:
        return paper.get_account(self.acc)

    def stats(self, prices: dict) -> dict:
        return paper.stats(self.account(), prices, bot=self.bot)

    def limit_stats(self, cfg: dict, prices: dict, manual: bool = False) -> dict:
        """Números usados pelo gestor de risco, conforme o escopo configurado.

        Banca e saldo livre são sempre da carteira. As contagens de operações e
        o resultado do dia seguem ``limits_trades_scope`` e ``limits_pnl_scope``;
        para ordens manuais, as suas operações sempre entram na conta."""
        from core.risk import PNL_SCOPES, TRADES_SCOPES

        acct = self.account()
        t_scope, p_scope = cfg.get("limits_trades_scope", "bot"), cfg.get("limits_pnl_scope", "carteira")
        if manual:
            t_scope = "pagina"
            p_scope = "pagina" if p_scope == "bot" else p_scope
        wallet = paper.stats(acct, prices)
        trades = paper.stats(acct, prices, bot=self.bot, origin="bot" if t_scope == "bot" else "all")
        pnl = wallet if p_scope == "carteira" else paper.stats(acct, prices, bot=self.bot,
                                                               origin="bot" if p_scope == "bot" else "all")
        return {**wallet, "trades_today": trades["trades_today"], "open_positions": trades["open_positions"],
                "pnl_today": pnl["pnl_today"], "scope_trades": f" · {TRADES_SCOPES[t_scope].lower()}",
                "scope_pnl": f" · {PNL_SCOPES[p_scope].lower()}"}

    def place_order(self, **kwargs) -> dict:
        return paper.place_order(self.acc, bot=self.bot, **kwargs)

    def close_position(self, position_id: str, price: float, reason: str = "Manual"):
        return paper.close_position(self.acc, position_id, price, reason)

    def cancel_order(self, order_id: str) -> None:
        paper.cancel_order(self.acc, order_id)

    def update_protection(self, position_id: str, stop_loss, take_profit) -> None:
        paper.update_protection(self.acc, position_id, stop_loss, take_profit)

    def sync(self, symbol: str, candles, last_price: float, funding_rate_pct: float | None = None) -> list[dict]:
        return paper.sync(self.acc, symbol, candles, last_price, funding_rate_pct)

    def reset(self, initial: float) -> None:
        paper.reset_account(self.acc, initial)


class BinanceBroker(PaperBroker):  # pragma: no cover - fase 2
    """Esqueleto da integração real (fase 2).

    Mapeamento previsto:
      * spot  → POST /api/v3/order (MARKET/LIMIT) + OCO para stop/alvo;
        margem → /sapi/v1/margin/order
      * futuros → POST /fapi/v1/leverage, /fapi/v1/marginType e /fapi/v1/order
        com STOP_MARKET / TAKE_PROFIT_MARKET (reduceOnly); faixas reais em
        GET /fapi/v1/leverageBracket
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
