"""Personalidades (estratégias) dos bots.

Uma personalidade define *como* o bot pensa: quais habilidades usa e com que
peso, quão forte precisa ser o sinal para entrar, a direção permitida (só
compra, só venda ou misto), filtros, stop/alvo por ATR e um texto descritivo
que vai para a IA como a "persona" da estratégia.

* **Prontas** — estratégias clássicas, somente leitura (podem ser duplicadas).
* **Da comunidade** — criadas por qualquer usuário na página Personalidades,
  com nome e autor, visíveis e utilizáveis por todos.

O **ranking** combina o desempenho real (operações dos bots na carteira
simulada, medido em R = resultado ÷ risco planejado, o que permite comparar
bancas de tamanhos diferentes) com os backtests salvos.
"""
from __future__ import annotations

import math
import re
import uuid
from datetime import datetime, timezone

from core.storage import load_json, locked_update

CUSTOM_FILE = "personalities.json"
BACKTEST_FILE = "backtests.json"

DIRECTIONS = {"misto": "Misto (compra e venda)", "compra": "Só compra", "venda": "Só venda"}
FILTERS = {
    "trend_ema": "Só a favor da EMA de tendência",
    "avoid_lateral": "Evitar mercado lateral (ADX baixo)",
    "volume_confirm": "Exigir volume acima da média",
    "rsi_guard": "Não comprar sobrecomprado / vender sobrevendido",
    "ignore_regime": "Não reduzir o sinal em mercado lateral",
}

BUILTINS: list[dict] = [
    {
        "id": "tendencia", "name": "🧭 Seguidor de Tendência", "author": "TradeBot",
        "summary": "Surfa tendências estabelecidas (escola Dow / Tartarugas).",
        "description": "Opera somente a favor da tendência principal. Entra quando as médias estão alinhadas, o "
                       "SuperTrend confirma e o ADX mostra força. Prefere pullbacks curtos às médias rápidas. Aceita "
                       "taxa de acerto menor em troca de ganhos grandes; nunca opera contra a EMA de tendência.",
        "direction": "misto", "threshold": 30, "sl_atr": 2.0, "tp_atr": 5.0,
        "skills": {"tendencia": 1.6, "supertrend": 1.3, "macd": 1.0, "adx": 1.0, "estrutura": 1.0, "volume": 0.5},
        "filters": {"trend_ema": True, "adx_min": 20}, "markets": ["futures", "spot"], "timeframes": "1h a 1d",
    },
    {
        "id": "reversao", "name": "🎯 Reversão à Média", "author": "TradeBot",
        "summary": "Compra exageros de queda e vende exageros de alta em mercados laterais.",
        "description": "Busca extremos estatísticos: preço fora das Bandas de Bollinger com RSI/Estocástico em "
                       "sobrevenda/sobrecompra e próximo de suporte/resistência. Alvo na média (banda central), stop "
                       "curto. Evita operar quando há tendência forte (ADX alto).",
        "direction": "misto", "threshold": 28, "sl_atr": 1.2, "tp_atr": 2.0,
        "skills": {"reversao": 1.8, "estocastico": 1.0, "suporte_resistencia": 1.2, "bollinger": 0.8},
        "filters": {"adx_max": 28, "ignore_regime": True}, "markets": ["futures", "spot"], "timeframes": "5m a 4h",
    },
    {
        "id": "rompimento", "name": "🚀 Rompimento (Breakout)", "author": "TradeBot",
        "summary": "Entra quando o preço rompe máximas/mínimas recentes com volume.",
        "description": "Opera rompimentos do canal de 20 candles e saídas de compressão das Bandas de Bollinger, "
                       "exigindo volume acima da média. Evita rompimentos sem volume (falsos). Stop logo abaixo da "
                       "região rompida e alvo longo.",
        "direction": "misto", "threshold": 30, "sl_atr": 1.5, "tp_atr": 4.5,
        "skills": {"rompimento": 2.0, "volume": 1.2, "adx": 0.8, "bollinger": 0.6, "tendencia": 0.6},
        "filters": {"volume_confirm": True}, "markets": ["futures", "spot"], "timeframes": "15m a 1d",
    },
    {
        "id": "scalper_vwap", "name": "⚡ Scalper VWAP", "author": "TradeBot",
        "summary": "Day trade rápido usando a VWAP como referência de valor.",
        "description": "Opera intradiário em futuros: compra pullbacks à VWAP em dia comprador e vende repiques à "
                       "VWAP em dia vendedor, com momentum (RSI) e volume a favor. Operações curtas, alvo de ~2× o "
                       "risco, sem segurar posição para o dia seguinte.",
        "direction": "misto", "threshold": 25, "sl_atr": 1.0, "tp_atr": 2.2,
        "skills": {"vwap": 1.8, "momentum": 1.0, "volume": 1.0, "tendencia": 0.8, "estocastico": 0.6},
        "filters": {"rsi_guard": True}, "markets": ["futures"], "timeframes": "1m a 15m",
    },
    {
        "id": "momentum", "name": "📈 Momentum", "author": "TradeBot",
        "summary": "Acompanha movimentos que estão acelerando.",
        "description": "Entra quando MACD e RSI mostram aceleração na mesma direção da tendência curta, com volume "
                       "crescente. Sai rápido se o momentum perder força. Não compra RSI acima de sobrecompra nem "
                       "vende abaixo de sobrevenda.",
        "direction": "misto", "threshold": 30, "sl_atr": 1.5, "tp_atr": 3.5,
        "skills": {"macd": 1.5, "momentum": 1.3, "volume": 1.0, "tendencia": 0.8, "adx": 0.6},
        "filters": {"rsi_guard": True}, "markets": ["futures", "spot"], "timeframes": "15m a 4h",
    },
    {
        "id": "price_action", "name": "🧱 Price Action (Suporte/Resistência)", "author": "TradeBot",
        "summary": "Opera reações em zonas de suporte e resistência e a estrutura de topos/fundos.",
        "description": "Lê o gráfico: compra reação em suporte com fundos ascendentes e vende rejeição em "
                       "resistência com topos descendentes. Considera os níveis desenhados pelo usuário como zonas "
                       "importantes. Stop além da zona, alvo na próxima zona.",
        "direction": "misto", "threshold": 25, "sl_atr": 1.5, "tp_atr": 3.0,
        "skills": {"suporte_resistencia": 2.0, "estrutura": 1.5, "estocastico": 0.7, "volume": 0.7},
        "filters": {"ignore_regime": True}, "markets": ["futures", "spot"], "timeframes": "15m a 1d",
    },
    {
        "id": "ichimoku", "name": "☁️ Ichimoku", "author": "TradeBot",
        "summary": "Sistema japonês completo: nuvem, Tenkan/Kijun e tendência.",
        "description": "Compra com preço acima da nuvem e Tenkan acima da Kijun; vende o oposto. Evita operar com "
                       "o preço dentro da nuvem (indefinição). Prefere tempos gráficos maiores.",
        "direction": "misto", "threshold": 30, "sl_atr": 2.0, "tp_atr": 5.0,
        "skills": {"ichimoku": 2.0, "tendencia": 0.8, "adx": 0.8},
        "filters": {"avoid_lateral": True}, "markets": ["futures", "spot"], "timeframes": "4h a 1w",
    },
    {
        "id": "conservador", "name": "🛡️ Conservador (multi-confirmação)", "author": "TradeBot",
        "summary": "Só entra quando quase tudo concorda. Poucas operações, mais seletivas.",
        "description": "Exige consenso amplo entre tendência, momentum, MACD, SuperTrend, estrutura e volume, a "
                       "favor da EMA de tendência, fora de lateralização e sem extremos de RSI. Prefere ficar de fora "
                       "a arriscar.",
        "direction": "misto", "threshold": 45, "sl_atr": 2.0, "tp_atr": 4.0,
        "skills": {k: 1.0 for k in ("tendencia", "momentum", "macd", "supertrend", "estrutura", "volume",
                                    "suporte_resistencia", "adx")},
        "filters": {"trend_ema": True, "avoid_lateral": True, "rsi_guard": True}, "markets": ["futures", "spot"],
        "timeframes": "1h a 1d",
    },
    {
        "id": "posicional", "name": "🐂 Posicional Comprador", "author": "TradeBot",
        "summary": "Acumula posições compradas em tendência de alta de longo prazo.",
        "description": "Estratégia de longo prazo só comprada: compra correções dentro de tendência primária de "
                       "alta (acima da EMA de tendência, estrutura de fundos ascendentes). Stops largos e alvos "
                       "longos; ignora ruído de curto prazo.",
        "direction": "compra", "threshold": 25, "sl_atr": 3.0, "tp_atr": 9.0,
        "skills": {"tendencia": 1.6, "estrutura": 1.4, "supertrend": 1.0, "ichimoku": 0.6, "macd": 0.6},
        "filters": {"trend_ema": True}, "markets": ["spot", "futures"], "timeframes": "1d a 1w",
    },
]
for _p in BUILTINS:
    _p["builtin"] = True

DEFAULT_BY_BOT = {"day": "scalper_vwap", "swing": "tendencia", "long": "posicional"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def list_all() -> list[dict]:
    custom = load_json(CUSTOM_FILE, {}) or {}
    return BUILTINS + sorted(custom.values(), key=lambda p: p.get("created", ""))


def get(pid: str | None) -> dict | None:
    if not pid:
        return None
    return next((p for p in list_all() if p["id"] == pid), None)


def slug(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:30] or "estrategia"
    return f"{base}_{uuid.uuid4().hex[:5]}"


def save_custom(p: dict) -> dict:
    """Cria ou atualiza uma personalidade da comunidade."""
    p = {**p, "builtin": False, "updated": _now()}
    p.setdefault("id", slug(p["name"]))
    p.setdefault("created", _now())
    if any(b["id"] == p["id"] for b in BUILTINS):
        raise ValueError("Personalidades prontas não podem ser alteradas — duplique-a para personalizar.")

    def _apply(data):
        data[p["id"]] = p

    locked_update(CUSTOM_FILE, {}, _apply)
    return p


def delete_custom(pid: str) -> None:
    def _apply(data):
        data.pop(pid, None)

    locked_update(CUSTOM_FILE, {}, _apply)


# ------------------------------------------------------------------ ranking
def save_backtest(pid: str, result: dict) -> None:
    def _apply(data):
        # Um resultado por ativo/timeframe/mercado: repetir o teste substitui o anterior
        same = (result.get("symbol"), result.get("interval"), result.get("market"))
        runs = [r for r in data.get(pid, []) if (r.get("symbol"), r.get("interval"), r.get("market")) != same]
        runs.append(result)
        data[pid] = runs[-30:]

    locked_update(BACKTEST_FILE, {}, _apply)


def backtests() -> dict:
    return load_json(BACKTEST_FILE, {}) or {}


def live_trades() -> list[dict]:
    """Todas as operações encerradas pelos bots (de todas as carteiras)."""
    from core.paper import ACCOUNT_FILE

    accounts = load_json(ACCOUNT_FILE, {}) or {}
    return [t for acct in accounts.values() if isinstance(acct, dict)
            for t in acct.get("history", []) if t.get("personality") and t.get("source") != "manual"]


def _r(trade: dict) -> float | None:
    risk = trade.get("max_loss_planned")
    return trade["pnl"] / risk if risk and risk > 0 else None


def ranking(min_trades: int = 10) -> list[dict]:
    """Linhas do ranking, da melhor para a pior pontuação.

    Pontuação = R médio por operação × confiança estatística (n ÷ (n + 10)),
    combinando as operações reais (peso 2) com os backtests (peso 1)."""
    trades = live_trades()
    bts = backtests()
    rows = []
    for p in list_all():
        mine = [t for t in trades if t.get("personality") == p["id"]]
        rs = [r for r in (_r(t) for t in mine) if r is not None]
        wins = [t["pnl"] for t in mine if t["pnl"] > 0]
        losses = [t["pnl"] for t in mine if t["pnl"] <= 0]
        runs = bts.get(p["id"], [])
        bt_trades = sum(r["trades"] for r in runs)
        bt_avg_r = (sum(r["avg_r"] * r["trades"] for r in runs) / bt_trades) if bt_trades else None
        live_avg_r = sum(rs) / len(rs) if rs else None
        n_live, n_bt = len(rs), bt_trades
        weight_live, weight_bt = 2 * n_live, n_bt
        combined = ((live_avg_r or 0) * weight_live + (bt_avg_r or 0) * weight_bt) / (weight_live + weight_bt) \
            if weight_live + weight_bt else None
        n_eff = n_live + n_bt / 2
        score = combined * (n_eff / (n_eff + 10)) if combined is not None else None
        rows.append({
            "id": p["id"], "name": p["name"], "author": p.get("author", ""), "builtin": p.get("builtin", False),
            "direction": p.get("direction", "misto"), "live_trades": len(mine),
            "live_win_rate": len(wins) / len(mine) * 100 if mine else None, "live_avg_r": live_avg_r,
            "live_pnl": sum(t["pnl"] for t in mine) if mine else 0.0,
            "live_pf": (sum(wins) / abs(sum(losses))) if losses and sum(losses) else None,
            "bt_runs": len(runs), "bt_trades": bt_trades, "bt_avg_r": bt_avg_r,
            "bt_win_rate": (sum(r["win_rate"] * r["trades"] for r in runs) / bt_trades) if bt_trades else None,
            "score": score, "enough_data": n_eff >= min_trades,
            "users": len({t.get("bot") for t in mine}),
        })
    # positivas primeiro, depois as ainda sem dados, por fim as negativas
    rows.sort(key=lambda r: (-(r["score"] if r["score"] is not None and not math.isnan(r["score"]) else 0.0),
                             -(r["live_trades"] + r["bt_trades"])))
    return rows
