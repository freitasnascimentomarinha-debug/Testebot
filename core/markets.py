"""Mercados da plataforma: só cripto — futuros perpétuos (``futures``) e à vista (``spot``)."""
from __future__ import annotations

CRYPTO_MARKETS = ("futures", "spot")


def is_crypto(market: str) -> bool:
    return market in CRYPTO_MARKETS
