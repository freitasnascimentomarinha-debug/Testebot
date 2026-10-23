"""Núcleo da plataforma de bots de trade (independente do Streamlit).

Os módulos deste pacote não importam Streamlit (exceto ``core.ui``), para que
possam ser reutilizados pelo ``worker.py`` (execução 24/7 sem navegador) e,
futuramente, por um executor ligado à API de negociação da Binance.
"""
