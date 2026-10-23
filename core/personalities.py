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

import json
import math
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from core.storage import load_json, locked_update

CUSTOM_FILE = "personalities.json"
BACKTEST_FILE = "backtests.json"
PERIOD_FILE = "period_returns.json"
PERIOD_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")

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

# Estratégias encontradas na pesquisa de out/2026: busca em ~12 mil combinações nos primeiros 27 dias,
# validação nos 13 dias seguintes, nos 40 dias anteriores e em 5 moedas que não participaram da busca.
# Todas testadas em futuros perpétuos, timeframe de 1h, com taxa de 0,05% por lado.
_RESEARCH = "Pesquisa Claude · out/2026"
BUILTINS += [
    {
        "id": "pesq_pullback_st", "name": "🌀 Pullback SuperTrend + Estocástico", "author": _RESEARCH,
        "summary": "Compra recuos em tendência forte de alta e vende repiques em tendência forte de baixa.",
        "description": "Só opera quando a tendência é forte (ADX ≥ 25) e a favor da EMA 200. Usa o SuperTrend para a "
                       "direção e o Estocástico para o momento de entrada (fim do recuo). Stop curto (1 ATR) e alvo "
                       "longo (4 ATR): acerta cerca de 30% das vezes, mas cada ganho paga ~4 perdas.",
        "direction": "misto", "threshold": 35, "sl_atr": 1.0, "tp_atr": 4.0,
        "skills": {"supertrend": 1.5, "estocastico": 2.0}, "filters": {"trend_ema": True, "adx_min": 25},
        "markets": ["futures"], "timeframes": "1h (testado)", "tested_interval": "1h",
        "research": {"busca_pct": 8.04, "inéditas_pct": 5.81, "anteriores_r": 0.16, "pior_queda_pct": 15.3,
                     "acerto_pct": 29, "operacoes_40d": 261},
    },
    {
        "id": "pesq_tendencia_equilibrada", "name": "🎯 Tendência Equilibrada", "author": _RESEARCH,
        "summary": "MACD + SuperTrend + Estocástico em tendência forte, com stop e alvo mais próximos.",
        "description": "Mesma família do Pullback SuperTrend, com MACD e RSI como confirmação extra. Stop de 2 ATR e "
                       "alvo de 3 ATR: acerta cerca de metade das operações, com quedas da banca menores. Foi a mais "
                       "regular entre as moedas (positiva nas 5 moedas inéditas).",
        "direction": "misto", "threshold": 35, "sl_atr": 2.0, "tp_atr": 3.0,
        "skills": {"macd": 1.0, "supertrend": 1.5, "estocastico": 2.0, "momentum": 0.5},
        "filters": {"trend_ema": True, "adx_min": 25},
        "markets": ["futures"], "timeframes": "1h (testado)", "tested_interval": "1h",
        "research": {"busca_pct": 4.24, "inéditas_pct": 5.00, "anteriores_r": 0.02, "pior_queda_pct": 9.5,
                     "acerto_pct": 50, "operacoes_40d": 232},
    },
    {
        "id": "pesq_ichimoku_forca", "name": "☁️ Ichimoku com Força", "author": _RESEARCH,
        "summary": "Ichimoku, ADX, momentum e volume alinhados — só entra com consenso forte.",
        "description": "Exige consenso alto (limiar 50) entre Ichimoku, ADX/DMI, RSI, volume e Bollinger, a favor da "
                       "EMA 200, com ADX ≥ 25 e sem comprar sobrecomprado/vender sobrevendido. Stop curto (0,8 ATR) "
                       "e alvo de 4× o risco. Foi a melhor nos 40 dias anteriores ao período analisado.",
        "direction": "misto", "threshold": 50, "sl_atr": 0.8, "tp_atr": 3.2,
        "skills": {"volume": 1.5, "momentum": 1.5, "ichimoku": 2.0, "adx": 2.0, "bollinger": 1.0},
        "filters": {"trend_ema": True, "rsi_guard": True, "ignore_regime": True, "adx_min": 25},
        "markets": ["futures"], "timeframes": "1h (testado)", "tested_interval": "1h",
        "research": {"busca_pct": 3.83, "inéditas_pct": 3.24, "anteriores_r": 0.23, "pior_queda_pct": 9.6,
                     "acerto_pct": 26, "operacoes_40d": 278},
    },
    {
        "id": "pesq_rompimento_consolidacao", "name": "📦 Rompimento de Consolidação", "author": _RESEARCH,
        "summary": "Opera a saída de mercados parados (ADX baixo) pelo rompimento do canal de 20 candles.",
        "description": "Só procura entradas quando ainda NÃO há tendência (ADX ≤ 25): espera o preço romper a máxima "
                       "ou mínima dos últimos 20 candles, com Bollinger a favor e sem RSI extremo. Stop largo (3 ATR) "
                       "e alvo de 4,5 ATR. Poucas operações e as menores quedas da banca da pesquisa (3–4%).",
        "direction": "misto", "threshold": 50, "sl_atr": 3.0, "tp_atr": 4.5,
        "skills": {"bollinger": 0.5, "rompimento": 2.0}, "filters": {"rsi_guard": True, "adx_max": 25},
        "markets": ["futures"], "timeframes": "1h (testado)", "tested_interval": "1h",
        "research": {"busca_pct": 2.38, "inéditas_pct": 3.41, "anteriores_r": -0.07, "pior_queda_pct": 4.1,
                     "acerto_pct": 53, "operacoes_40d": 94},
    },
    {
        "id": "pesq_momentum_moderado", "name": "⚖️ Momentum Moderado", "author": _RESEARCH,
        "summary": "Entra no começo das tendências (ADX entre 25 e 30) com Estocástico, MACD e volume.",
        "description": "Procura o início de uma tendência: ADX entre 25 e 30 (força surgindo, mas ainda não esticada). "
                       "Limiar baixo (mais entradas), confirmação por Estocástico, MACD, volume e Bollinger. Stop e "
                       "alvo iguais (3 ATR): a maior taxa de acerto da pesquisa (~60%).",
        "direction": "misto", "threshold": 15, "sl_atr": 3.0, "tp_atr": 3.0,
        "skills": {"bollinger": 0.5, "estocastico": 1.0, "macd": 0.5, "volume": 1.0},
        "filters": {"ignore_regime": True, "adx_min": 25, "adx_max": 30},
        "markets": ["futures"], "timeframes": "1h (testado)", "tested_interval": "1h",
        "research": {"busca_pct": 3.37, "inéditas_pct": 3.60, "anteriores_r": -0.01, "pior_queda_pct": 6.4,
                     "acerto_pct": 60, "operacoes_40d": 206},
    },
]
# Especialidade (etiqueta curta), dica rápida e bot indicado das personalidades clássicas e da pesquisa
_CARD = {
    "tendencia": ("Tendência · EMAs + SuperTrend", "Só entra a favor de tendência forte; acerta pouco, ganha muito quando acerta.", "swing"),
    "reversao": ("Reversão · Bollinger + RSI", "Compra exageros de queda e vende exageros de alta em mercado lateral.", "day"),
    "rompimento": ("Rompimento · Donchian + volume", "Entra quando o preço rompe a máxima/mínima de 20 candles com volume.", "day"),
    "scalper_vwap": ("Scalping · VWAP", "Operações curtas de recuo até a VWAP, sem dormir posicionado.", "day"),
    "momentum": ("Momentum · MACD + RSI", "Acompanha movimentos que estão acelerando; sai quando perdem força.", "day"),
    "price_action": ("Price action · suporte/resistência", "Lê o gráfico: reação em suportes/resistências e topos/fundos.", "day"),
    "ichimoku": ("Ichimoku", "Nuvem e Tenkan/Kijun: opera só fora da nuvem, em tempos maiores.", "swing"),
    "conservador": ("Multi-confirmação", "Só entra quando quase todos os indicadores concordam.", "swing"),
    "posicional": ("Longo prazo · só compra", "Acumula compras em tendência primária de alta, com stops largos.", "long"),
    "pesq_pullback_st": ("Pullback · SuperTrend + Estocástico · 4:1", "Recuos em tendência forte; acerta ~30%, cada ganho paga 4 perdas.", "day"),
    "pesq_tendencia_equilibrada": ("Tendência · MACD + SuperTrend · 1,5:1", "A mais regular da pesquisa: acerta metade, quedas pequenas.", "day"),
    "pesq_ichimoku_forca": ("Ichimoku + ADX + volume · 4:1", "Só entra com consenso forte entre Ichimoku, força e volume.", "day"),
    "pesq_rompimento_consolidacao": ("Rompimento de consolidação · 1,5:1", "Opera a saída de mercados parados; as menores quedas da banca.", "day"),
    "pesq_momentum_moderado": ("Início de tendência · 1:1", "Entra quando a tendência começa (ADX 25–30); acerta ~60%.", "day"),
}
for _p in BUILTINS:
    if _p["id"] in _CARD:
        _p.setdefault("specialty", _CARD[_p["id"]][0])
        _p.setdefault("tip", _CARD[_p["id"]][1])
        _p.setdefault("bot", _CARD[_p["id"]][2])

# Bots especialistas gerados pela pesquisa (core/specialists.json) e resultados simulados
# padronizados de todas as personalidades prontas (core/research_results.json).
_HERE = Path(__file__).resolve().parent
try:
    BUILTINS += json.loads((_HERE / "specialists.json").read_text(encoding="utf-8"))
except FileNotFoundError:  # pragma: no cover
    pass
try:
    _RESULTS = json.loads((_HERE / "research_results.json").read_text(encoding="utf-8"))
except FileNotFoundError:  # pragma: no cover
    _RESULTS = {}
for _p in BUILTINS:
    if _p["id"] in _RESULTS:
        _p["research"] = _RESULTS[_p["id"]]

for _p in BUILTINS:
    _p["builtin"] = True

# Padrões: especialistas aprovados na prova final (moedas inéditas) da pesquisa de out/2026
DEFAULT_BY_BOT = {"day": "esp_15m_ema_3x1", "swing": "esp_swing_4h_breakout_3x1", "long": "esp_long_1d_ichimoku_4x1"}


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


# ------------------------------------------------ retorno no período recente
def period_key(market: str, interval: str, days: int, risk_pct: float) -> str:
    return f"{market}|{interval}|{days}|{risk_pct:g}"


def period_results(key: str) -> dict:
    """{"date": "AAAA-MM-DD", "results": {pid: resumo}} do cálculo salvo."""
    return (load_json(PERIOD_FILE, {}) or {}).get(key, {"date": "", "results": {}})


def save_period_result(key: str, pid: str, summary: dict) -> None:
    today = datetime.now(timezone.utc).date().isoformat()

    def _apply(data):
        entry = data.get(key)
        if not entry or entry.get("date") != today:
            entry = {"date": today, "results": {}}
        entry["results"][pid] = summary
        data[key] = entry

    locked_update(PERIOD_FILE, {}, _apply)


def summarize_period(per_symbol: list[dict]) -> dict:
    """Média entre as moedas (cada moeda simulada como uma banca separada)."""
    n = len(per_symbol) or 1
    return {"return_pct": float(sum(r["return_pct"] for r in per_symbol) / n),
            "max_dd_pct": float(max((r["max_dd_pct"] for r in per_symbol), default=0.0)),
            "trades": sum(r["trades"] for r in per_symbol),
            "positive": sum(1 for r in per_symbol if r["return_pct"] > 0), "symbols": len(per_symbol),
            "best": max(per_symbol, key=lambda r: r["return_pct"])["symbol"] if per_symbol else "",
            "worst": min(per_symbol, key=lambda r: r["return_pct"])["symbol"] if per_symbol else "",
            "per_symbol": {r["symbol"]: round(float(r["return_pct"]), 2) for r in per_symbol},
            "period": per_symbol[0]["period"] if per_symbol else ""}
