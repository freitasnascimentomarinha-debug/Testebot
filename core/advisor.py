"""Consultor técnico: cenário do gráfico, melhor bot para o momento e plano condicional.

Tudo aqui é calculado por regras, sem IA (a IA, quando ativa, usa estes números como base e escreve a análise
final, mas só pode escolher bots da lista de candidatos e só propõe gatilhos que o sistema consegue conferir).

Plano condicional ("plano armado"): "comprar/vender se um candle fechar acima/abaixo de X (com volume ≥ Y× a média),
usando a personalidade Z". O gatilho é conferido pelo sistema a cada candle fechado — nunca pela IA — e a ordem ainda
passa pelo gestor de risco."""
from __future__ import annotations

import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from core import regime as regime_mod
from core.data import INTERVAL_SECONDS
from core.storage import load_json, locked_update

PLANS_FILE = "armed_plans.json"
TYPES = {"fechar_acima": "fechar acima de", "fechar_abaixo": "fechar abaixo de"}
SIDE_TXT = {"BUY": "comprar", "SELL": "vender"}


def _f(x, nd=2):
    return None if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))) else round(float(x), nd)


def n(x, nd: int = 1) -> str:
    """Número no formato brasileiro (vírgula decimal)."""
    return f"{float(x):.{nd}f}".replace(".", ",")


def ns(x, nd: int = 2) -> str:
    return f"{float(x):+.{nd}f}".replace(".", ",")


def _p(v: float) -> str:
    v = float(v)
    t = f"{v:,.2f}" if abs(v) >= 100 else f"{v:.4g}" if abs(v) < 1 else f"{v:,.3f}"
    return t.replace(",", "X").replace(".", ",").replace("X", ".")


def _dir_txt(v) -> str | None:
    return None if v is None else {1: "alta", -1: "baixa"}.get(int(v), "lateral")


# ------------------------------------------------------------------------------------------ cenário
def scenario(df: pd.DataFrame, cfg: dict) -> dict:
    """Fatos mensuráveis do gráfico no último candle fechado (sem opinião)."""
    from core import indicators as ind

    data = df.iloc[:-1] if len(df) > 50 else df
    last = data.iloc[-1]
    price = float(df["close"].iloc[-1])
    atr = float(last.atr)
    levels = ind.support_resistance(data)
    ctx = str(regime_mod.classify(data.tail(300)).iloc[-1])
    rel = float(last.volume / last.vol_sma) if last.vol_sma else None
    rel3 = float(data["volume"].tail(3).mean() / last.vol_sma) if last.vol_sma else None
    width = (last.bb_up - last.bb_low) / last.bb_mid * 100 if last.bb_mid else None
    band_pos = (price - last.bb_low) / (last.bb_up - last.bb_low) * 100 if last.bb_up != last.bb_low else 50.0
    hi20, lo20 = float(data["high"].tail(20).max()), float(data["low"].tail(20).min())
    ef, es, et = float(last.ema_fast), float(last.ema_slow), float(last.ema_trend)
    if ef > es and price > et:
        align = "alta"
    elif ef < es and price < et:
        align = "baixa"
    else:
        align = "misto"
    sup = [{"preco": _f(x["price"], 6), "toques": x["touches"], "dist_atr": _f((price - x["price"]) / atr, 1)} for x in levels["supports"][:2]]
    res = [{"preco": _f(x["price"], 6), "toques": x["touches"], "dist_atr": _f((x["price"] - price) / atr, 1)} for x in levels["resistances"][:2]]
    htf = last.get("htf_dir") if "htf_dir" in data else None
    mtf = last.get("mtf_dir") if "mtf_dir" in data else None
    from core.htf import HTF_OF, MTF_OF

    itv = cfg.get("interval", "")
    return {
        "ativo": cfg.get("symbol"), "timeframe": itv, "preco": _f(price, 6), "atr": _f(atr, 6), "atr_pct": _f(atr / price * 100, 2),
        "contexto": ctx, "contexto_nome": regime_mod.label(ctx), "contexto_regra": regime_mod.REGIMES.get(ctx, ("", ""))[1],
        "adx": _f(last.adx, 1), "di_mais": _f(last.di_plus, 1), "di_menos": _f(last.di_minus, 1), "rsi": _f(last.rsi, 1),
        "ema_rapida": _f(ef, 6), "ema_lenta": _f(es, 6), "ema_tendencia": _f(et, 6), "alinhamento_medias": align,
        "volume_relativo": _f(rel, 2), "volume_relativo_3": _f(rel3, 2),
        "bollinger_largura_pct": _f(width, 2), "posicao_na_banda_pct": _f(band_pos, 0),
        "maxima_20": _f(hi20, 6), "minima_20": _f(lo20, 6),
        "dist_maxima_20_atr": _f((hi20 - price) / atr, 1), "dist_minima_20_atr": _f((price - lo20) / atr, 1),
        "variacao_10_candles_pct": _f((price / float(data["close"].iloc[-11]) - 1) * 100, 2) if len(data) > 11 else None,
        "suportes": sup, "resistencias": res,
        "tendencia_tempo_maior": {"tempo": HTF_OF.get(itv), "direcao": _dir_txt(htf)} if htf is not None else None,
        "tendencia_tempo_intermediario": {"tempo": MTF_OF.get(itv), "direcao": _dir_txt(mtf)} if mtf is not None else None,
    }


def bias(sc: dict, plan_score: float = 0.0) -> str:
    """Viés do momento: 'alta', 'baixa' ou 'neutro' (médias + tempo maior + placar das regras)."""
    pts = {"alta": 1, "baixa": -1}.get(sc["alinhamento_medias"], 0)
    h = (sc.get("tendencia_tempo_maior") or {}).get("direcao")
    pts += {"alta": 1, "baixa": -1}.get(h, 0)
    pts += 1 if plan_score >= 15 else -1 if plan_score <= -15 else 0
    return "alta" if pts >= 2 else "baixa" if pts <= -2 else "neutro"


# ------------------------------------------------------------------------------------------ candidatos
def candidates(profile, cfg: dict, sc: dict, vies: str, active_id: str | None, top: int = 5) -> list[dict]:
    """Bots prontos ranqueados para o contexto atual (usa a pesquisa de cada bot: desempenho por contexto)."""
    from core import personalities as P

    ctx, itv = sc["contexto"], cfg.get("interval")
    rows = []
    for p in P.list_all():
        rs = p.get("research") or {}
        if not rs or rs.get("market") != profile.market:
            continue
        if rs.get("status") == "fraco" and p["id"] != active_id:
            continue
        cx = (rs.get("contexts") or {}).get(ctx) or {}
        ctx_r = cx.get("avg_r") if cx.get("n", 0) >= 6 else None
        shrunk = ctx_r * cx["n"] / (cx["n"] + 20) if ctx_r is not None else 0.0  # amostra pequena vale menos
        same = rs.get("interval") == itv
        score = shrunk * 0.6 + (rs.get("monthly_pct") or 0) / 10 * 0.2
        score += {"aprovado": 0.15, "ressalva": 0.0}.get(rs.get("status"), -0.3) + (0.35 if same else 0.0)
        if rs.get("prev_ret_pct") is not None and rs["prev_ret_pct"] < 0:
            score -= 0.25
        direction = p.get("direction", "misto")
        if (direction == "compra" and vies == "baixa") or (direction == "venda" and vies == "alta"):
            score -= 0.5
        if ctx_r is None:
            score -= 0.2
        why = []
        if ctx_r is not None:
            why.append(f"em {sc['contexto_nome']} teve {ns(ctx_r)}R por operação ({cx['n']} operações simuladas, acerto {cx['win_pct']:.0f}%)")
        else:
            why.append(f"sem histórico suficiente em {sc['contexto_nome']}")
        why.append(f"simulado {ns(rs['monthly_pct'], 1)}% ao mês, selo {rs.get('status')}")
        if rs.get("prev_ret_pct") is not None:
            why.append(f"40 dias anteriores: {ns(rs['prev_ret_pct'], 1)}%")
        rows.append({"id": p["id"], "nome": p["name"], "tempo_testado": rs.get("interval"), "mesmo_tempo": same, "selo": rs.get("status"),
                     "direcao": direction, "saida": P.exit_text(p), "contexto_r": ctx_r, "contexto_n": cx.get("n", 0),
                     "mensal_pct": rs.get("monthly_pct"), "ativo": p["id"] == active_id, "pontuacao": round(score, 3), "porque": "; ".join(why)})
    rows.sort(key=lambda r: -r["pontuacao"])
    out = rows[:top]
    if active_id and not any(r["id"] == active_id for r in out):
        act = next((r for r in rows if r["id"] == active_id), None)
        if act:
            out.append(act)
    return out


# ------------------------------------------------------------------------------------------ texto didático (regras)
def _tendencia_txt(sc: dict) -> str:
    adx = sc["adx"]
    forca = "forte" if adx >= 25 else "moderada" if adx >= 18 else "fraca (mercado sem direção)"
    al = {"alta": "alinhadas para cima (média rápida acima da lenta e preço acima da média de tendência)",
          "baixa": "alinhadas para baixo (média rápida abaixo da lenta e preço abaixo da média de tendência)",
          "misto": "misturadas, sem alinhamento claro"}[sc["alinhamento_medias"]]
    return f"As médias móveis estão {al}. O ADX está em {adx:.0f}, o que indica tendência {forca}."


def _htf_txt(sc: dict) -> str:
    parts = []
    for k, nome in (("tendencia_tempo_maior", "tempo maior"), ("tendencia_tempo_intermediario", "tempo intermediário")):
        v = sc.get(k)
        if v and v.get("direcao"):
            parts.append(f"o {nome} ({v['tempo']}) está de {v['direcao']}")
    return ("Contexto multitemporal: " + " e ".join(parts) + ".") if parts else ""


def _vol_txt(sc: dict) -> str:
    r = sc.get("volume_relativo")
    if r is None:
        return ""
    leitura = ("volume forte, que confirma o movimento" if r >= 1.5 else "volume acima da média" if r >= 1.1
               else "volume dentro do normal" if r >= 0.8 else "volume fraco: movimentos sem convicção")
    return f"O último candle teve {n(r, 1)}× o volume médio ({leitura})."


def rules_advice(sc: dict, cands: list[dict], plan_d: dict, cfg: dict, price: float, vies: str, atr: float) -> dict:
    """Análise didática e recomendação usando só regras (usada sem IA e como base/validação da IA)."""
    ctx = sc["contexto"]
    itv, sym = sc["timeframe"], sc["ativo"]
    rsi = sc["rsi"]
    rsi_txt = (f"O RSI marca {rsi:.0f}: " + ("sobrecomprado, risco de recuo curto." if rsi >= 70 else "sobrevendido, possível repique." if rsi <= 30
                                              else "região neutra, sem esticamento."))
    sr = []
    if sc["suportes"]:
        s0 = sc["suportes"][0]
        sr.append(f"suporte em {_p(s0['preco'])} (a {n(s0['dist_atr'], 1)} ATR abaixo, {s0['toques']} toques)")
    if sc["resistencias"]:
        r0 = sc["resistencias"][0]
        sr.append(f"resistência em {_p(r0['preco'])} (a {n(r0['dist_atr'], 1)} ATR acima, {r0['toques']} toques)")
    cenario = (f"No {itv}, {sym} está em **{sc['contexto_nome']}** — {sc['contexto_regra']} {_tendencia_txt(sc)} {_htf_txt(sc)} "
               f"{_vol_txt(sc)} {rsi_txt}" + (f" Estrutura: {'; '.join(sr)}." if sr else "")).replace("  ", " ")
    leitura = [f"Contexto: {sc['contexto_nome']} · viés {vies}", f"ADX {sc['adx']:.0f} (+DI {sc['di_mais']:.0f} / −DI {sc['di_menos']:.0f}) · RSI {rsi:.0f}",
               f"Volume relativo {n(sc['volume_relativo'], 2)}× · ATR {n(sc['atr_pct'], 2)}% do preço",
               f"Faixa dos últimos 20 candles: {_p(sc['minima_20'])} – {_p(sc['maxima_20'])}"]
    plano = _rule_plan(sc, cands, vies, price)
    opp = {
        "rompimento_alta": "O preço acabou de romper para cima. A melhor oportunidade costuma ser a entrada de continuação num recuo curto ao nível rompido, "
                           "com stop abaixo dele. Cuidado com rompimento falso: sem volume, o movimento tende a desfazer.",
        "rompimento_baixa": "O preço acabou de romper para baixo. A oportunidade é a venda na continuação, num repique até o nível rompido; "
                            "se o preço voltar para dentro da faixa, a ideia está invalidada.",
        "reversao_alta": "O preço esticou para baixo (RSI baixo e fora da banda inferior). A oportunidade é um repique de curto prazo, com stop curto "
                         "e alvo na média; só vale em mercado sem tendência de baixa forte.",
        "reversao_baixa": "O preço esticou para cima (RSI alto e fora da banda superior). A oportunidade é uma correção de curto prazo, com stop curto e alvo na média.",
        "pullback_alta": "Recuo dentro de uma tendência de alta: é a zona clássica de compra. Espere o candle voltar a fechar acima da média rápida para confirmar a retomada.",
        "pullback_baixa": "Repique dentro de uma tendência de baixa: é a zona clássica de venda. Espere um candle fechar abaixo da média rápida para confirmar a retomada.",
        "tendencia_alta": "Tendência de alta saudável. Evite comprar esticado: prefira entradas em recuos às médias ou no rompimento da máxima recente com volume.",
        "tendencia_baixa": "Tendência de baixa saudável. Evite vender no fundo: prefira repiques às médias ou o rompimento da mínima recente com volume.",
        "lateral": "Mercado lateral, sem direção. O melhor quase sempre é esperar: ou operar os extremos da faixa com bots de reversão, ou aguardar o rompimento da faixa com volume.",
        "indefinido": "Nenhum padrão claro no momento. Preservar capital e esperar um contexto definido é uma posição válida.",
    }[ctx]
    if sc["adx"] < 15 or (sc.get("volume_relativo") or 1) < 0.6:
        opp = ("Ressalva: ADX baixo e/ou volume fraco reduzem a confiança neste contexto; o movimento pode não ter força para seguir. " + opp)
    dica = {
        "lateral": "Em mercado lateral os indicadores de tendência dão muitos falsos sinais. Reduza o tamanho da mão ou espere o rompimento.",
        "rompimento_alta": "Volume é o teste do rompimento. Se o próximo candle fechar de volta dentro da faixa, saia.",
        "rompimento_baixa": "Volume é o teste do rompimento. Se o próximo candle fechar de volta dentro da faixa, saia.",
    }.get(ctx, "Opere a favor do tempo gráfico maior e arrisque sempre o mesmo valor por operação; o stop vem antes do alvo.")
    bot = None
    positive = [c for c in cands if c["contexto_r"] and c["contexto_r"] > 0]
    positive.sort(key=lambda c: (not c["mesmo_tempo"], -c["pontuacao"]))
    if not positive:
        bot = {"id": None, "nome": None, "motivo": f"Nenhum bot testado mostra vantagem comprovada em {sc['contexto_nome']} no {itv}. "
               "O melhor movimento agora é aguardar um contexto melhor ou o gatilho do plano abaixo.", "mesmo_tempo": False, "ativo": False,
               "alternativas": [{"id": c["id"], "nome": c["nome"]} for c in cands[:3]], "sem_vantagem": True}
    else:
        best = positive[0]
        bot = {"id": best["id"], "nome": best["nome"], "motivo": best["porque"] + ("" if best["mesmo_tempo"] else f". Atenção: foi testado no {best['tempo_testado']}, "
               f"e você está no {itv}"), "mesmo_tempo": best["mesmo_tempo"], "ativo": best["ativo"],
               "alternativas": [{"id": c["id"], "nome": c["nome"]} for c in positive if c["id"] != best["id"]][:3]}
    return {"cenario": cenario, "leitura_tecnica": leitura, "oportunidade": opp, "dica": dica, "bot": bot, "plano": plano, "fonte": "regras",
            "vies": vies}


def _rule_plan(sc: dict, cands: list[dict], vies: str, price: float) -> dict | None:
    """Gatilho padrão: rompimento do nível mais próximo na direção do viés, confirmado por fechamento e volume."""
    atr = sc["atr"]
    pos = [c for c in cands if c["contexto_r"] and c["contexto_r"] > 0]
    pos.sort(key=lambda c: (not c["mesmo_tempo"], -c["pontuacao"]))
    best = pos[0]["id"] if pos else None
    if vies == "baixa" and sc["suportes"]:
        lv = sc["suportes"][0]["preco"]
        return make_plan("SELL", "fechar_abaixo", lv, 1.2, best, 12, invalida=lv + 2.5 * atr, price=price, atr=atr,
                         why="Viés de baixa: a venda só se confirma se o preço perder o suporte com volume; sem isso, é só ruído.")
    if vies == "alta" and sc["resistencias"]:
        lv = sc["resistencias"][0]["preco"]
        return make_plan("BUY", "fechar_acima", lv, 1.2, best, 12, invalida=lv - 2.5 * atr, price=price, atr=atr,
                         why="Viés de alta: a compra só se confirma se o preço superar a resistência com volume; sem isso, é só ruído.")
    if vies == "neutro" and sc["resistencias"] and sc["suportes"]:
        r0, s0 = sc["resistencias"][0], sc["suportes"][0]
        if r0["dist_atr"] <= s0["dist_atr"]:
            return make_plan("BUY", "fechar_acima", r0["preco"], 1.5, best, 12, invalida=r0["preco"] - 2.5 * atr, price=price, atr=atr,
                             why="Sem viés claro: espere o preço sair da faixa. Aqui, o rompimento da resistência mais próxima, com volume forte.")
        return make_plan("SELL", "fechar_abaixo", s0["preco"], 1.5, best, 12, invalida=s0["preco"] + 2.5 * atr, price=price, atr=atr,
                         why="Sem viés claro: espere o preço sair da faixa. Aqui, a perda do suporte mais próximo, com volume forte.")
    return None


# ------------------------------------------------------------------------------------------ plano condicional
def make_plan(side: str, kind: str, level: float, vol_min: float | None, personality: str | None, valid: int, *, invalida: float | None,
              price: float, atr: float, why: str = "") -> dict | None:
    """Valida e normaliza um plano condicional (devolve None se for incoerente ou impossível de conferir)."""
    from core import personalities as P

    side, kind = str(side).upper(), str(kind)
    if side not in SIDE_TXT or kind not in TYPES:
        return None
    try:
        level = float(level)
    except (TypeError, ValueError):
        return None
    if not (price - 8 * atr <= level <= price + 8 * atr):
        return None
    if (kind == "fechar_acima" and level <= price) or (kind == "fechar_abaixo" and level >= price):
        return None  # o gatilho precisa estar do lado ainda não atingido
    vol = None
    try:
        vol = float(vol_min) if vol_min not in (None, "", 0) else None
    except (TypeError, ValueError):
        pass
    if vol is not None:
        vol = min(max(vol, 1.0), 4.0)
    try:
        inv = float(invalida) if invalida not in (None, "") else None
    except (TypeError, ValueError):
        inv = None
    if inv is not None and ((side == "BUY" and inv >= level) or (side == "SELL" and inv <= level)):
        inv = None
    pers = P.get(personality) if personality else None
    plan = {"direcao": side, "tipo": kind, "nivel": round(level, 8), "volume_min_x": vol, "personalidade": pers["id"] if pers else None,
            "personalidade_nome": pers["name"] if pers else None, "validade_candles": int(min(max(int(valid or 12), 3), 48)),
            "invalida_em": round(inv, 8) if inv is not None else None, "explicacao": why}
    return plan


def describe_plan(plan: dict, symbol: str, interval: str) -> str:
    vol = f" com volume ≥ {plan['volume_min_x']:g}× a média" if plan.get("volume_min_x") else ""
    inv = ""
    if plan.get("invalida_em") is not None:
        inv = f" O plano cai se o preço chegar a {_p(plan['invalida_em'])} antes do gatilho."
    pers = f" usando a personalidade **{plan['personalidade_nome']}** (stop/alvo dela)" if plan.get("personalidade_nome") else " usando o stop/alvo do bot ativo"
    return (f"{SIDE_TXT[plan['direcao']].capitalize()} {symbol} se um candle de {interval} {TYPES[plan['tipo']]} {_p(plan['nivel'])}{vol},"
            f"{pers}. Vale por {plan['validade_candles']} candles.{inv}")


def evaluate(record: dict, df: pd.DataFrame, interval: str) -> tuple[str, dict]:
    """Confere o gatilho nos candles fechados depois do armamento.

    Devolve (estado, info): "pendente", "disparou" (o candle de gatilho é o último fechado), "invalidado", "expirado" ou
    "perdido" (disparou num candle antigo e a entrada já não faz sentido)."""
    plan = record["plano"]
    data = df.iloc[:-1] if len(df) > 50 else df
    sec = INTERVAL_SECONDS[interval]
    now = pd.Timestamp.now(tz="UTC")
    if data["time"].iloc[-1] + pd.Timedelta(seconds=sec) > now + pd.Timedelta(seconds=1):
        data = data.iloc[:-1]  # candle ainda aberto
    armed = pd.Timestamp(record["armado_em"])
    after = data[data["time"] >= armed]
    n = 0
    for i, (_, c) in enumerate(after.iterrows()):
        n += 1
        close = float(c.close)
        if plan.get("invalida_em") is not None and ((plan["direcao"] == "BUY" and close <= plan["invalida_em"])
                                                    or (plan["direcao"] == "SELL" and close >= plan["invalida_em"])):
            return "invalidado", {"candle": str(c.time), "close": close}
        vol_ok = not plan.get("volume_min_x") or (c.vol_sma and c.volume >= c.vol_sma * plan["volume_min_x"])
        hit = close > plan["nivel"] if plan["tipo"] == "fechar_acima" else close < plan["nivel"]
        if hit and vol_ok:
            last = i == len(after) - 1
            return ("disparou" if last else "perdido"), {"candle": str(c.time), "close": close,
                                                           "volume_x": round(float(c.volume / c.vol_sma), 2) if c.vol_sma else None}
        if n >= plan["validade_candles"]:
            return "expirado", {"candles": n}
    return "pendente", {"candles": n}


# ------------------------------------------------------------------------------------------ armazenamento
def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def armed(bot: str) -> dict | None:
    return (load_json(PLANS_FILE, {}) or {}).get(bot)


def arm(bot: str, symbol: str, interval: str, plan: dict, armed_from: pd.Timestamp, source: str = "manual") -> dict:
    """Arma o plano: a partir do próximo candle fechado depois de ``armed_from``."""
    rec = {"plano": plan, "ativo": symbol, "tempo": interval, "armado_em": pd.Timestamp(armed_from).isoformat(), "criado": _now(),
           "origem": source, "descricao": describe_plan(plan, symbol, interval)}

    def _apply(data):
        data[bot] = rec

    locked_update(PLANS_FILE, {}, _apply)
    return rec


def disarm(bot: str, reason: str = "") -> None:
    def _apply(data):
        rec = data.pop(bot, None)
        if rec and reason:
            hist = data.setdefault("_historico", [])
            hist.append({**rec, "encerrado": _now(), "motivo": reason, "bot": bot})
            del hist[:-30]

    locked_update(PLANS_FILE, {}, _apply)
