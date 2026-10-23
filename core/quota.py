"""Limite diário de análises da IA por usuário (a chave da OpenRouter é do dono da plataforma e é paga por ele).

``AI_DAILY_LIMIT`` (Secrets): análises por usuário por dia (UTC); padrão 300; ``0`` = sem limite. Só vale para a chave
da plataforma — quem informa a própria chave não é limitado."""
from __future__ import annotations

from datetime import datetime, timezone

from core.storage import get_secret, load_json, locked_update

FILE = "ai_usage.json"
DEFAULT_LIMIT = 300


def limit() -> int:
    try:
        return int(get_secret("AI_DAILY_LIMIT") or DEFAULT_LIMIT)
    except ValueError:
        return DEFAULT_LIMIT


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def used() -> int:
    return int((load_json(FILE, {}) or {}).get(_today(), 0))


def allow() -> bool:
    lim = limit()
    return lim <= 0 or used() < lim


def consume() -> None:
    def _apply(data):
        today = _today()
        for k in [k for k in data if k != today]:
            del data[k]  # guarda só o dia atual
        data[today] = int(data.get(today, 0)) + 1

    locked_update(FILE, {}, _apply)
