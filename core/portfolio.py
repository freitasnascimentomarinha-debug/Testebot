"""Carteira comprovada: os bots que lucraram em períodos que a escolha deles não usou — operam juntos, cada um no seu tempo gráfico.

Como foram escolhidos (out/2026, ``tools/pesquisa/validar_carteira.py``):

* família de rompimento no formato de bot do app (habilidades + filtros + stop/alvo em ATR), simulada com ``core/fastsim.py``;
* escolha em dez/2025–mai/2026, em 6 moedas; aprovação só com lucro em jun–dez/2025 e mai–out/2026 (10 moedas) e nas 4 moedas
  que a escolha não viu;
* a carteira (os dois juntos, 1% da banca por operação) também lucrou nos três períodos.

O mesmo teste reprovou quase todos os bots antigos da biblioteca (selo dado olhando só 40 dias) e a troca automática de bot por
contexto do gráfico, que piorou o resultado na simulação. Por isso, onde há carteira, o robô usa estes bots — cada um decide sozinho
quando entrar (as próprias regras e filtros) — em vez de trocar de bot conforme o contexto.

No spot nenhum candidato passou na prova: lá o robô segue como antes.
"""
from __future__ import annotations

import json
from pathlib import Path

FILE = Path(__file__).resolve().with_name("portfolio_bots.json")

# Definição dos bots (as regras); os números de validação vêm de ``portfolio_bots.json`` (gerado pela ferramenta).
DEFINITIONS = [
    {
        "id": "cart_1h_rompimento_consolidacao", "interval": "1h", "market": "futures",
        "name": "📦 Rompimento de Consolidação · 1h",
        "specialty": "Carteira comprovada · rompimento de mercado parado · 2:1",
        "tip": "Espera o mercado parado (ADX ≤ 25) romper o canal de 20 candles; alvo de 2× o risco.",
        "description": "Só procura entradas quando ainda NÃO há tendência (ADX ≤ 25): entra quando o preço rompe a máxima ou a mínima "
                       "dos últimos 20 candles, com Bollinger a favor e sem RSI extremo. Stop de 3 ATR e alvo de 6 ATR (2× o risco). "
                       "Acerta ~40% das operações; o lucro vem do alvo maior que o stop.",
        "direction": "misto", "threshold": 50, "sl_atr": 3.0, "tp_atr": 6.0,
        "skills": {"bollinger": 0.5, "rompimento": 2.0}, "filters": {"rsi_guard": True, "adx_max": 25},
    },
    {
        "id": "cart_4h_rompimento_tendencia", "interval": "4h", "market": "futures",
        "name": "🚀 Rompimento a favor da tendência · 4h",
        "specialty": "Carteira comprovada · rompimento no 4h a favor da média de 200 · 2:1",
        "tip": "Rompimento do canal de 20 candles no 4h, só a favor da média de 200; alvo de 2× o risco.",
        "description": "No gráfico de 4h, entra quando o preço rompe a máxima ou a mínima dos últimos 20 candles com Bollinger a "
                       "favor, só no sentido da média de 200 (compra acima dela, venda abaixo). Stop de 4 ATR e alvo de 8 ATR "
                       "(2× o risco). Poucas operações, que duram dias.",
        "direction": "misto", "threshold": 50, "sl_atr": 4.0, "tp_atr": 8.0,
        "skills": {"rompimento": 2.0, "bollinger": 0.5}, "filters": {"trend_ema": True},
    },
]
RISK_PCT = 1.0          # risco sugerido por operação (% da banca)


def _load() -> dict:
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def personalities() -> list[dict]:
    """Os bots da carteira no formato de personalidade do app (com a pesquisa por cima, quando já validados)."""
    data = _load()
    out = []
    for d in DEFINITIONS:
        res = (data.get("research") or {}).get(d["id"])
        p = {k: v for k, v in d.items() if k not in ("interval", "market")}
        p.update({"author": "Carteira comprovada · out/2026", "summary": d["tip"], "bot": "day", "markets": [d["market"]],
                  "tested_interval": d["interval"], "timeframes": f"{d['interval']} (testado)", "portfolio": True})
        if res:
            p["research"] = res
        out.append(p)
    return out


def for_market(market: str) -> list[dict]:
    """Bots da carteira deste mercado (já com o ranking semanal por cima, como os demais)."""
    from core import personalities as P

    ids = [d["id"] for d in DEFINITIONS if d["market"] == market]
    return [p for p in (P.get(i) for i in ids) if p]


def interval_of(pid: str) -> str | None:
    return next((d["interval"] for d in DEFINITIONS if d["id"] == pid), None)


def by_interval(market: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for p in for_market(market):
        out.setdefault(interval_of(p["id"]), []).append(p)
    return out


def active(cfg: dict, market: str) -> bool:
    """A carteira está ligada (padrão) e existe para este mercado?"""
    return bool(cfg.get("portfolio_mode", True)) and any(d["market"] == market for d in DEFINITIONS)


def summary(market: str) -> dict | None:
    """Resultado da carteira (os bots juntos) na validação, para mostrar na página."""
    s = (_load().get("portfolio") or {}).get(market)
    return s or None
