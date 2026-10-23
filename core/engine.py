"""Pipeline do bot: dados → habilidades → IA → gestor de risco → ordem.

Usado tanto pelo botão "Analisar com IA" da interface quanto pelo piloto
automático e pelo ``worker.py``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pandas as pd

from core import advisor, ai, htf, indicators as ind, markets, personalities, quota, risk
from core import paper
from core.broker import get_broker
from core.data import get_funding_rate
from core.storage import current_user, get_secret
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


def market_closed(profile: BotProfile, cfg: dict) -> bool:
    """Forex, commodities, índices e ações: sem negócios recentes = mercado fechado (a cripto opera 24 h)."""
    if profile.is_crypto:
        return False
    try:
        from core.data import get_ticker

        return not markets.is_open(get_ticker(cfg["symbol"], profile.market).market_time)
    except Exception:  # noqa: BLE001 - sem cotação, não abre ordem
        return True


def run_analysis(profile: BotProfile, cfg: dict, df: pd.DataFrame, price: float,
                 api_key: str | None) -> AnalysisResult:
    symbol, interval = cfg["symbol"], cfg["interval"]
    broker = get_broker(profile.key)
    acct = broker.account()
    st_ = broker.limit_stats(cfg, {symbol: price})
    personality = personalities.get(cfg.get("personality")) or personalities.get(personalities.DEFAULT_BY_BOT.get(profile.key))
    if cfg.get("context_mode") == "favoraveis" and personality:
        best = (personality.get("research") or {}).get("best_contexts")
        if best:
            cfg = {**cfg, "context_filter": best}
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
                 | {"pnl_nao_realizado": round(paper.pnl_of(p, price), 2)}
                 for p in acct["positions"] if p["symbol"] == symbol]
    account_view = {k: round(v, 2) for k, v in st_.items() if isinstance(v, (int, float)) and not math.isinf(v)}
    funding = get_funding_rate(symbol) if profile.market == "futures" else None

    # Consultor técnico: cenário medido, melhores bots para o momento e plano condicional por regras
    sc = cands = rules_adv = extras = None
    try:
        sc = advisor.scenario(df, cfg)
        vies = advisor.bias(sc, plan_d["score"])
        cands = advisor.candidates(profile, cfg, sc, vies, personality["id"] if personality else None)
        rules_adv = advisor.rules_advice(sc, cands, plan_d, cfg, price, vies, sc["atr"])
        extras = {"scenario": sc, "candidates": cands, "rules": rules_adv, "price": price, "atr": sc["atr"]}
    except Exception:  # noqa: BLE001 - o consultor nunca derruba a análise principal
        pass
    rec = advisor.armed(profile.key)
    armed_view = ({k: rec[k] for k in ("plano", "ativo", "tempo", "descricao")} if rec and rec.get("ativo") == symbol else None)
    context = ai.build_context(profile=profile, cfg=cfg, symbol=symbol, interval=interval, plan=plan_d,
                               snapshot=market_snapshot(df.iloc[:-1], int(cfg["ai_candles_context"])),
                               indicators_now=indicators_now, account=account_view, positions=positions,
                               risk_rules=risk_rules, funding_rate=funding, personality=personality, scenario=sc,
                               candidates=cands, armed_plan=armed_view)
    error = ""
    # A chave da OpenRouter é do dono da plataforma: cada usuário tem um limite diário de análises (quem usa a própria chave não tem).
    platform_key = bool(api_key) and api_key == get_secret("OPENROUTER_API_KEY") and bool(current_user())
    if platform_key and not quota.allow():
        api_key, quota_msg = None, f"limite diário de {quota.limit()} análises da IA atingido (volta amanhã, 00:00 UTC)"
    else:
        quota_msg = "chave da OpenRouter não configurada"
        if platform_key:
            quota.consume()
    if api_key:
        try:
            decision = ai.ask_ai(context, api_key=api_key, model=cfg["ai_model"], temperature=float(cfg["ai_temperature"]),
                                 extras=extras)
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
            decision = ai.rules_fallback(plan_d, f"falha na IA ({exc})")
    else:
        decision = ai.rules_fallback(plan_d, quota_msg)

    if not decision.advice and rules_adv:
        decision.advice = rules_adv
    # Modo filtro (padrão): a IA só confirma ou veta o sinal das regras testadas no backtest e usa o
    # stop/alvo validados; não abre operação sem sinal das regras nem inverte a direção.
    if decision.source == "ia" and cfg.get("ai_mode", "filtro") == "filtro" and decision.decision in ("BUY", "SELL"):
        if plan_d["direction"] == "HOLD":
            decision.reasoning = ("[Modo filtro] Sem sinal das regras da personalidade: a IA não abre operação sozinha. "
                                  "Leitura da IA: " + decision.reasoning)
            decision.decision = "HOLD"
        elif plan_d["direction"] != decision.decision:
            decision.reasoning = ("[Modo filtro] A IA discordou da direção das regras: operação vetada. "
                                  "Leitura da IA: " + decision.reasoning)
            decision.decision = "HOLD"
        else:
            decision.order_type, decision.entry = "MARKET", plan_d["entry"]
            decision.stop_loss, decision.take_profit = plan_d["stop_loss"], plan_d["take_profit"]
            decision.reasoning = "[Modo filtro] A IA confirmou o sinal das regras. " + decision.reasoning

    if decision.decision in ("BUY", "SELL") and market_closed(profile, cfg):
        decision.reasoning = "[Mercado fechado] Sem negócios agora: nenhuma ordem a mercado é aberta. " + decision.reasoning
        decision.decision = "HOLD"

    check = None
    if decision.decision in ("BUY", "SELL"):
        entry = decision.entry if decision.order_type == "LIMIT" and decision.entry else price
        trailing = bool(plan_d.get("trail_dist"))
        if trailing:  # modo surfar: sem alvo, o stop acompanha o preço
            decision.take_profit = None
        check = risk.check_trade(cfg, st_, decision.decision, entry, decision.stop_loss, decision.take_profit, profile.market,
                                 trailing=trailing)
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
            personality=result.personality, trail_dist=result.plan.get("trail_dist"), be_r=result.plan.get("be_r") or 0.0,
            fx=calc.fx,
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


def prepare(df: pd.DataFrame, cfg: dict, htf_raw: pd.DataFrame | None = None,
            mtf_raw: pd.DataFrame | None = None) -> pd.DataFrame:
    out = ind.compute(df, cfg)
    if htf_raw is not None or mtf_raw is not None:
        out = htf.attach(out, htf_raw, cfg["interval"], mtf_raw)
    return out


def needs_htf(cfg: dict) -> bool:
    """A personalidade escolhida usa filtro de tendência de tempo maior/intermediário?"""
    p = personalities.get(cfg.get("personality"))
    return bool(p and any(htf.needs(p.get("filters"))))


def htf_frames(getter, cfg: dict, n: int, market: str):
    """Candles dos tempos maiores exigidos pela personalidade escolhida: (htf_raw, mtf_raw)."""
    p = personalities.get(cfg.get("personality"))
    return htf.frames(getter, cfg["symbol"], cfg["interval"], n, market, (p or {}).get("filters"))


# ----------------------------------------------------------------------- plano condicional armado
def arm_plan(profile: BotProfile, cfg: dict, plan: dict, df: pd.DataFrame, source: str = "manual") -> dict:
    """Arma o plano: o gatilho passa a ser conferido a cada candle fechado, a partir do candle em formação."""
    return advisor.arm(profile.key, cfg["symbol"], cfg["interval"], plan, df["time"].iloc[-1], source)


def check_armed_plan(profile: BotProfile, cfg: dict, df: pd.DataFrame, price: float):
    """Confere o plano armado do bot. Devolve ``(estado, resultado)``:
    ``("disparou", AnalysisResult)`` quando o gatilho confirmou (o plano é desarmado), ``("cancelado:<motivo>", None)``
    quando caiu (invalidado, expirado ou perdido) e ``(None, None)`` quando continua pendente ou não se aplica."""
    from core.strategy import stops_for

    bot = profile.key
    rec = advisor.armed(bot)
    if not rec or rec.get("ativo") != cfg["symbol"] or rec.get("tempo") != cfg["interval"]:
        return None, None
    state, info = advisor.evaluate(rec, df, cfg["interval"])
    if state == "pendente":
        return None, None
    advisor.disarm(bot, state)
    if state != "disparou":
        return f"cancelado:{state}", None
    plan = rec["plano"]
    side = plan["direcao"]
    pers = personalities.get(plan.get("personalidade")) or personalities.get(cfg.get("personality")) \
        or personalities.get(personalities.DEFAULT_BY_BOT.get(bot))
    st_ = stops_for(df, cfg, side, pers)
    why = (f"Plano condicional confirmado: {rec['descricao']} Gatilho: candle {info['candle'][:16]} fechou em {info['close']:.6g}"
           + (f" com volume {info['volume_x']:g}× a média." if info.get("volume_x") else "."))
    decision = ai.AIDecision(decision=side, order_type="MARKET", entry=st_["price"], stop_loss=st_["stop_loss"],
                             take_profit=st_["take_profit"], confidence=75, reasoning=why, risks="Plano condicional: confira o gestor de risco.",
                             model="plano", source="ia" if rec.get("origem") == "ia" else "regras")
    broker = get_broker(bot)
    stats = broker.limit_stats(cfg, {cfg["symbol"]: price})
    trailing = bool(st_["trail_dist"])
    check = risk.check_trade(cfg, stats, side, price, decision.stop_loss, decision.take_profit, profile.market, trailing=trailing)
    plan_d = {"direction": side, "score": 0.0, "regime": "plano condicional", "entry": price, "stop_loss": decision.stop_loss,
              "take_profit": decision.take_profit, "trail_dist": st_["trail_dist"], "be_r": st_["be_r"]}
    result = AnalysisResult(plan=plan_d, decision=decision, check=check, price=price, symbol=cfg["symbol"], interval=cfg["interval"],
                            time=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                            personality={"id": pers["id"], "name": pers["name"]} if pers else None)
    log_decision(bot, result)
    return "disparou", result


def auto_arm(profile: BotProfile, cfg: dict, result: AnalysisResult, df: pd.DataFrame) -> bool:
    """Piloto automático: arma o plano condicional proposto pela IA (só planos da IA; nunca os de regras)."""
    adv = result.decision.advice or {}
    plan = adv.get("plano")
    if not cfg.get("ai_auto_arm", True) or not plan or adv.get("fonte") != "ia" or advisor.armed(profile.key):
        return False
    arm_plan(profile, cfg, plan, df, "ia")
    return True
