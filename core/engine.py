"""Pipeline do bot: dados → habilidades → IA → gestor de risco → ordem.

Usado tanto pelo botão "Analisar com IA" da interface quanto pelo piloto
automático e pelo ``worker.py``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pandas as pd

from core import advisor, ai, htf, indicators as ind, personalities, quota, ranking, risk
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


def ensure_ranking(profile: BotProfile, cfg: dict, progress=None) -> bool:
    """Atualiza o ranking dos bots se passou uma semana (ver ``core/ranking.py``). Devolve True se recalculou."""
    return ranking.refresh_if_stale(profile.market, cfg["interval"], progress=progress)


def pick_bots(profile: BotProfile, cfg: dict, df: pd.DataFrame, top: int = 3) -> tuple[list[dict], dict]:
    """Os bots mais recomendados para o contexto do gráfico agora (tendência, força, volume, tempo maior…), do melhor para o pior,
    segundo o ranking semanal.

    Só entram bots treinados neste mercado e tempo gráfico, sem selo fraco e com vantagem comprovada (R médio positivo) no
    contexto atual. A lista vem vazia quando nenhum tem vantagem — então o melhor é aguardar."""
    sc = advisor.scenario(df, cfg)
    vies = advisor.bias(sc)
    ok_ids = {p["id"] for p in personalities.allowed(profile.market, cfg["interval"])}
    cands = advisor.candidates(profile, cfg, sc, vies, cfg.get("personality"), top=10)
    good = [c for c in cands if c["mesmo_tempo"] and c["id"] in ok_ids and (c["contexto_r"] or 0) > 0]
    good.sort(key=lambda c: -c["pontuacao"])
    info = {"contexto": sc["contexto"], "contexto_nome": sc["contexto_nome"], "candidatos": [c["id"] for c in good]}
    return [personalities.get(c["id"]) for c in good[:top]], info


def pick_bot(profile: BotProfile, cfg: dict, df: pd.DataFrame) -> tuple[dict | None, dict]:
    """O melhor bot para o contexto do gráfico agora (``None`` quando nenhum tem vantagem comprovada)."""
    bots, info = pick_bots(profile, cfg, df, top=1)
    return (bots[0] if bots else None), info


def run_analysis(profile: BotProfile, cfg: dict, df: pd.DataFrame, price: float,
                 api_key: str | None, log: bool = True, personality_id: str | None = None) -> AnalysisResult:
    symbol, interval = cfg["symbol"], cfg["interval"]
    broker = get_broker(profile.key)
    acct = broker.account()
    st_ = broker.stats({symbol: price})
    personality = personalities.get(cfg.get("personality")) or personalities.get(personalities.DEFAULT_BY_BOT.get(profile.key))
    waiting = ""
    if personality_id and personalities.get(personality_id):  # bot já escolhido pela varredura para este contexto
        personality = personalities.get(personality_id)
    elif cfg.get("auto_bot", True):  # fechamento do candle: o bot mais recomendado para o contexto assume
        try:
            best, pinfo = pick_bot(profile, cfg, df)
        except Exception:  # noqa: BLE001 - a escolha automática nunca derruba a análise
            best, pinfo = personality, {}
        if best is not None:
            personality = best
        elif pinfo:
            waiting = (f"Nenhum bot tem vantagem comprovada em {pinfo['contexto_nome']} no {interval} segundo o ranking "
                       "semanal: o melhor agora é aguardar.")
    if cfg.get("context_mode") == "favoraveis" and personality:
        best = (personality.get("research") or {}).get("best_contexts")
        if best:
            cfg = {**cfg, "context_filter": best}
    plan = analyze(df, cfg, profile, personality)
    plan_d = plan.to_dict()

    last = df.iloc[-2]
    indicators_now = {k: _clean(float(last[k])) for k in
                      ("close", "ema_fast", "ema_slow", "ema_trend", "rsi", "macd", "macd_signal", "macd_hist",
                       "bb_up", "bb_mid", "bb_low", "atr", "adx", "di_plus", "di_minus", "stoch_k", "stoch_d", "vwap", "st_line", "st_dir",
                       "obv", "vol_sma", "ichi_tenkan", "ichi_kijun", "ichi_span_a", "ichi_span_b")}
    budget = risk.risk_budget(cfg, st_["equity"])
    risk_rules = {
        "perda_maxima_por_trade_usdt": round(budget, 2), "alavancagem": risk.effective_leverage(cfg),
        "modo_margem": cfg["margin_mode"], "resultado_hoje_usdt": round(st_["pnl_today"], 2), "taxa_pct": cfg["fee_pct"],
    }
    positions = [{k: p.get(k) for k in ("side", "qty", "entry", "stop_loss", "take_profit", "leverage", "liquidation",
                                         "opened", "source")}
                 | {"pnl_nao_realizado": round(paper.pnl_of(p, price), 2)}
                 for p in acct["positions"] if p["symbol"] == symbol and p.get("market", profile.market) == profile.market]
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
                                 extras=extras, persona=cfg.get("ai_persona"))
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
            decision = ai.rules_fallback(plan_d, f"falha na IA ({exc})")
    else:
        decision = ai.rules_fallback(plan_d, quota_msg)

    if not decision.advice and rules_adv:
        decision.advice = rules_adv
    if decision.source == "ia" and not cfg.get("ai_intervene"):
        # A IA só explica: a decisão é a das regras da personalidade; o texto e as dicas da IA acompanham.
        ruled = ai.rules_fallback(plan_d, "")
        ruled.advice, ruled.model, ruled.risks = decision.advice, decision.model, decision.risks
        ruled.invalidation, ruled.management, ruled.usage = decision.invalidation, decision.management, decision.usage
        ruled.reasoning = f"[Sinal das regras: {plan_d['direction']}] " + decision.reasoning
        decision = ruled
    elif decision.source == "ia" and decision.decision in ("BUY", "SELL"):
        # A IA interfere: confirma ou veta a ativação do bot; sem sinal das regras ela não abre operação sozinha e usa o
        # stop/alvo validados.
        if plan_d["direction"] == "HOLD":
            decision.reasoning = ("[IA vetou] Sem sinal das regras do bot neste candle. Leitura da IA: " + decision.reasoning)
            decision.decision = "HOLD"
        elif plan_d["direction"] != decision.decision:
            decision.reasoning = ("[IA vetou] A IA discordou da direção do sinal das regras. Leitura da IA: " + decision.reasoning)
            decision.decision = "HOLD"
        else:
            decision.order_type, decision.entry = "MARKET", plan_d["entry"]
            decision.stop_loss, decision.take_profit = plan_d["stop_loss"], plan_d["take_profit"]
            decision.reasoning = "[IA confirmou o sinal das regras] " + decision.reasoning
    if waiting and decision.decision in ("BUY", "SELL"):
        decision.reasoning = f"[Bot automático em espera] {waiting} " + decision.reasoning
        decision.decision = "HOLD"
    # Uma posição por ativo: o bot não abre outra na mesma direção nem entra contra a que já tem (sinal contrário encerra a posição)
    mine = [p for p in acct["positions"] if p["symbol"] == symbol and p.get("market", profile.market) == profile.market and p.get("source") != "manual" and p.get("bot", profile.key) == profile.key]
    if mine and decision.decision in ("BUY", "SELL"):
        if any(p["side"] == decision.decision for p in mine):
            decision.reasoning = f"[Já posicionado em {symbol}] Aguardando o stop ou o alvo. " + decision.reasoning
            decision.decision = "HOLD"
        else:
            decision.reasoning = "[Sinal contrário ao da posição aberta] O cenário virou: a posição do bot é encerrada. " + decision.reasoning
            decision.decision = "CLOSE"

    check = None
    if decision.decision in ("BUY", "SELL"):
        entry = decision.entry if decision.order_type == "LIMIT" and decision.entry else price
        trailing = bool(plan_d.get("trail_dist"))
        if trailing:  # modo surfar: sem alvo, o stop acompanha o preço
            decision.take_profit = None
        check = risk.check_trade(cfg, st_, decision.decision, entry, decision.stop_loss, decision.take_profit, profile.market,
                                 trailing=trailing)

    result = AnalysisResult(plan=plan_d, decision=decision, check=check, price=price, symbol=symbol,
                            interval=interval, time=datetime.now(timezone.utc).isoformat(timespec="seconds"), error=error,
                            personality={"id": personality["id"], "name": personality["name"]} if personality else None)
    if log:
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
                  if p["symbol"] == result.symbol and p.get("market", profile.market) == profile.market and p.get("source") != "manual" and p.get("bot", profile.key) == profile.key]
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
    if cfg.get("auto_bot", True):  # qualquer bot do ranking pode ser o escolhido no fechamento do candle
        return True
    p = personalities.get(cfg.get("personality"))
    return bool(p and any(htf.needs(p.get("filters"))))


def htf_frames(getter, cfg: dict, n: int, market: str):
    """Candles dos tempos maiores exigidos pela personalidade escolhida: (htf_raw, mtf_raw)."""
    if cfg.get("auto_bot", True):
        return htf.frames(getter, cfg["symbol"], cfg["interval"], n, market, {"htf_trend": True, "mtf_trend": True})
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
    stats = broker.stats({cfg["symbol"]: price})
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
