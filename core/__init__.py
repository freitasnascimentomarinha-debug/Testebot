"""Núcleo da plataforma de bots de trade (independente do Streamlit).

Os módulos deste pacote não importam Streamlit (exceto ``core.ui``), para que
possam ser reutilizados pelo ``worker.py`` (execução 24/7 sem navegador) e,
futuramente, por um executor ligado à API de negociação da Binance.
"""

import subprocess as _sp
from pathlib import Path as _Path


def _version() -> str:
    """Data e commit do código em execução (para conferir se o deploy atualizou)."""
    try:
        out = _sp.run(["git", "log", "-1", "--format=%cd · %h", "--date=format:%d/%m/%Y %H:%M"],
                      cwd=_Path(__file__).resolve().parent.parent, capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or "desconhecida"
    except Exception:  # noqa: BLE001
        return "desconhecida"


APP_VERSION = _version()
