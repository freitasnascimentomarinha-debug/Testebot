"""Pipeline do bot: dados → habilidades → IA → gestor de risco → ordem.

Usado tanto pelo botão "Analisar com IA" da interface quanto pelo piloto
automático e pelo ``worker.py``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pandas as pd

from core import ai, indicators as ind, personalities, risk
from core.broker import get_broker
from core.data import get_funding_rate
from core.profiles import BotProfile
from core.storage import locked_update
from core.strategy import analyze, market_snapshot

LOG_FILE = "decisions.json"


@dataclass
class AnalysisResult:
    plan: dict
    decision: ai.AIDecision
    check: risk.RiskCheck | None
    price: float
    symbol: str
    interval: str
    time: str
    error: str = ""
    personality: dict | None = None
    executed: dict | None = None
    events: list = field(default_factory=list)


def _clean(v):
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return round(v, 6) if isinstance(v, float) else v


def run_analysis(profile: BotProfile, cfg: dict, df: pd.DataFrame, price: float,
                 api_key: str | None) -> AnalysisResult:
    symbol, interval = cfg["symbol"], cfg["interval"]
    broker = get_broker(profile.key)
    acct = broker.account()
    st_ = broker.limit_stats(cfg, {symbol: price})
    personality = personalities.get(cfg.get("personality")) or personalities.get(personalities.DEFAULT_BY_BOT[profile.key])
    plan = analyze(df, cfg, profile, personality)
    plan_d = plan.to_dict()

    last = df.iloc[-2]
    indicators_now = {k: _clean(float(last[k])) for k in
                      ("close", "ema_fast", "ema_slow", "ema_trend", "rsi", "macd", "macd_signal", "macd_hist",
                       "bb_up", "bb_mid", "bb_low", "atr", "adx", "di_plus", "di_minus", "stoch_k", "vwap", "st_line", "st_dir")}
    budget = risk.risk_budget(cfg, st_["equity"])
    risk_rules = {
        "perda_maxima_por_trade_usdt": round(budget, 2), "rr_minimo": cfg["min_rr"],
        "alavancagem": risk.effective_leverage(cfg), "modo_margem": cfg["margin_mode"],
        "meta_operacoes_dia": cfg["max_trades_day"], "operacoes_hoje": st_["trades_today"],
        "meta_lucro_dia_usdt": cfg["daily_profit_target"], "limite_perda_dia_usdt": cfg["daily_max_loss"],
        "resultado_hoje_usdt": round(st_["pnl_today"], 2),
        "operacoes_contadas": st_["scope_trades"].strip(" ·"), "resultado_contado": st_["scope_pnl"].strip(" ·"), "max_posicoes_abertas": cfg["max_open_positions"],
        "taxa_pct": cfg["fee_pct"],
    }
    positions = [{k: p.get(k) for k in ("side", "qty", "entry", "stop_loss", "take_profit", "leverage", "liquidation",
                                         "opened", "source")}
                 | {"pnl_nao_realizado": round((price - p["entry"]) * p["qty"] * (1 if p["side"] == "BUY" else -1), 2)}
                 for p in acct["positions"] if p["symbol"] == symbol]
    account_view = {k: round(v, 2) for k, v in st_.items() if isinstance(v, (int, float)) and not math.isinf(v)}
    funding = get_funding_rate(symbol) if profile.market == "futures" else None

    context = ai.build_context(profile=profile, cfg=cfg, symbol=symbol, interval=interval, plan=plan_d,
                               snapshot=market_snapshot(df.iloc[:-1], int(cfg["ai_candles_context"])),
                               indicators_now=indicators_now, account=account_view, positions=positions,
                               risk_rules=risk_rules, funding_rate=funding, personality=personality)
    error = ""
    if api_key:
        try:
            decision = ai.ask_ai(context, api_key=api_key, model=cfg["ai_model"], temperature=float(cfg["ai_temperature"]))
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
            decision = ai.rules_fallback(plan_d, f"falha na IA ({exc})")
    else:
        decision = ai.rules_fallback(plan_d, "chave da OpenRouter não configurada")

    check = None
    if decision.decision in ("BUY", "SELL"):
        entry = decision.entry if decision.order_type == "LIMIT" and decision.entry else price
        check = risk.check_trade(cfg, st_, decision.decision, entry, decision.stop_loss, decision.take_profit, profile.market)
        if decision.confidence < int(cfg["ai_min_confidence"]):
            check.add("confianca", f"Confiança {decision.confidence}% abaixo do mínimo configurado ({cfg['ai_min_confidence']}%).")

    result = AnalysisResult(plan=plan_d, decision=decision, check=check, price=price, symbol=symbol,
                            interval=interval, time=datetime.now(timezone.utc).isoformat(timespec="seconds"), error=error,
                            personality={"id": personality["id"], "name": personality["name"]} if personality else None)
    log_decision(profile.key, result)
    return result


def execute(profile: BotProfile, cfg: dict, result: AnalysisResult, price: float) -> dict:
    """Programa a ordem decidida (após aprovação do gestor de risco)."""
    d = result.decision
    broker = get_broker(profile.key)
    if d.decision == "CLOSE":
        # O bot só encerra as posições que ele mesmo abriu; as manuais ficam com o usuário.
        closed = [broker.close_position(p["id"], price, "IA: cenário invertido")
                  for p in broker.account()["positions"]
                  if p["symbol"] == result.symbol and p.get("source") != "manual" and p.get("bot", profile.key) == profile.key]
        out = {"status": "ENCERRADAS", "closed": closed}
    elif d.decision in ("BUY", "SELL") and result.check and result.check.allowed and result.check.calc:
        calc = result.check.calc
        out = broker.place_order(
            symbol=result.symbol, market=profile.market, side=d.decision, qty=calc.qty,
            order_type=d.order_type, price=price, limit_price=d.entry if d.order_type == "LIMIT" else None,
            stop_loss=d.stop_loss, take_profit=d.take_profit, leverage=calc.leverage,
            fee_pct=float(cfg["fee_pct"]), slippage_pct=float(cfg["slippage_pct"]),
            source=d.source, note=d.reasoning[:300], max_loss_planned=calc.risk_usdt, margin_mode=cfg["margin_mode"],
            personality=result.personality,
        )
    else:
        raise ValueError("Não há ordem aprovada para executar.")
    result.executed = out
    log_decision(profile.key, result, executed=True)
    return out


def log_decision(bot: str, result: AnalysisResult, executed: bool = False) -> None:
    entry = {"time": result.time, "symbol": result.symbol, "interval": result.interval, "price": result.price,
             "decision": result.decision.decision, "source": result.decision.source, "confidence": result.decision.confidence,
             "entry": result.decision.entry, "stop_loss": result.decision.stop_loss, "take_profit": result.decision.take_profit,
             "score": result.plan["score"], "approved": bool(result.check and result.check.allowed),
             "reasons": result.check.reasons if result.check else [], "reasoning": result.decision.reasoning,
             "executed": executed, "error": result.error,
             "personality": (result.personality or {}).get("name", "")}

    def _apply(data):
        logs = data.setdefault(bot, [])
        if executed and logs and logs[-1]["time"] == result.time:
            logs[-1] = entry
        else:
            logs.append(entry)
        del logs[:-300]

    locked_update(LOG_FILE, {}, _apply)


def prepare(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    return ind.compute(df, cfg)
