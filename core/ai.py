"""Integração com a IA (DeepSeek via OpenRouter).

A IA recebe o contexto completo (candles, indicadores, votos das habilidades,
plano por regras, níveis do usuário, regras de risco e estado da conta) e
devolve um JSON estrito com a ordem a ser programada. A IA explica o
mercado e dá uma dica útil; só interfere na decisão de ativar o bot (confirmando ou vetando o sinal das regras) quando o
usuário permite.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field

import requests

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
TIMEOUT = 90


@dataclass
class AIDecision:
    decision: str                 # BUY, SELL, HOLD ou CLOSE
    order_type: str = "MARKET"
    entry: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    confidence: int = 0
    reasoning: str = ""
    risks: str = ""
    invalidation: str = ""
    management: str = ""
    model: str = ""
    source: str = "ia"            # "ia" ou "regras" (quando a IA não está disponível)
    raw: str = ""
    usage: dict = field(default_factory=dict)
    advice: dict = field(default_factory=dict)   # análise didática, bot recomendado e plano condicional (core/advisor.py)

    def to_dict(self) -> dict:
        return asdict(self)


# Tom da IA nas explicações (escolhido pelo usuário em Configurações → IA)
AI_PERSONAS = {
    "professor": ("🎓 Professor didático", "Explica como um professor paciente: usa linguagem simples e, quando útil, ensina o conceito em uma frase."),
    "direto": ("⚡ Direto ao ponto", "Fala como um trader experiente com pressa: frases curtas, sem rodeios, só o que muda a decisão."),
    "cauteloso": ("🛡️ Gestor cauteloso", "Fala como um gestor de risco: destaca primeiro o que pode dar errado e só depois a oportunidade."),
    "mentor": ("🧭 Mentor motivador", "Fala como um mentor calmo e encorajador: reforça disciplina e processo, sem prometer resultado."),
    "quant": ("📊 Analista quantitativo", "Fala como um analista quantitativo: números e probabilidades primeiro, opinião por último."),
}
DEFAULT_PERSONA = "professor"


def persona_text(key: str | None) -> str:
    label, text = AI_PERSONAS.get(key or "", AI_PERSONAS[DEFAULT_PERSONA])
    return f"Seu estilo de comunicação ({label}): {text}"


SYSTEM_PROMPT = """Você é um trader experiente de criptomoedas que explica o mercado para quem não é técnico. Seu papel é RESUMIR em
linguagem simples o que está acontecendo no gráfico, citando fatos dos dados (contexto, força da tendência, volume, níveis). Sem
dicas genéricas nem conselhos que valeriam para qualquer gráfico. Sem promessas de lucro.
O campo "papel_da_ia" diz se o usuário deixou você INTERFERIR ("interferir": o sistema só abre a operação se o seu "decision"
confirmar o sinal das regras) ou apenas explicar ("explicar": o "decision" é só a sua leitura e não abre nada).
Você recebe dados REAIS já calculados. Regras:
1. Responda SOMENTE com um objeto JSON válido, sem texto fora dele.
2. Evite jargão: diga "o preço está subindo com força" em vez de "ADX 32 com +DI > -DI"; use no máximo 2 números por frase.
3. Prefira HOLD quando os sinais forem conflitantes ou o mercado estiver lateral. Preservar capital é prioridade.
4. BUY/SELL exigem stop_loss coerente com o lado (compra: stop < entrada; venda: stop > entrada) e, salvo no modo surfar
   (sem alvo), take_profit coerente. Use CLOSE só se houver posição do bot (source diferente de "manual") e o cenário tiver virado.
5. Siga a "personalidade" recebida (estratégia, direção e filtros). Se o cenário não combina com ela, responda HOLD.
6. Spot não permite venda a descoberto. Nunca invente números: use só os dados recebidos.
7. "sentimento_polymarket" (quando vier) é a probabilidade que apostadores com dinheiro real dão aos preços da moeda (mercado de previsões):
   use como contexto de apoio (confirma ou enfraquece o cenário técnico), nunca como gatilho sozinho; se estiver ausente, ignore.
8. "eventos_externos" (quando vier) são eventos macro e políticos com probabilidades do Polymarket (decisão do Fed, eleições, commodities).
   Cite só os que mudam o risco do trade agora (vence em poucos dias, afeta cripto/dólar): em véspera de evento grande, prefira HOLD ou
   alvos mais curtos. Se nada for relevante, ignore.
9. "modelo_ml" (quando vier) é a previsão de um modelo de machine learning treinado com o histórico recente: chance de alta nas próximas
   velas e se o mercado está fora do que ele conhece. É mais um indício, fraco (AUC perto de 0,5 = quase moeda ao ar), nunca um gatilho.
Formato:
{"decision":"BUY|SELL|HOLD|CLOSE","order_type":"MARKET|LIMIT","entry":number|null,"stop_loss":number|null,"take_profit":number|null,
 "confidence":0-100,"reasoning":"1 a 2 frases simples sobre a decisão",
 "analise":{"cenario":"2 a 3 frases simples: o que o preço está fazendo e por quê, com fatos dos dados"}}"""


def get_api_key(explicit: str | None = None) -> str | None:
    from core.storage import get_secret

    return explicit or get_secret("OPENROUTER_API_KEY")


def build_context(*, profile, cfg: dict, symbol: str, interval: str, plan: dict, snapshot: dict,
                  indicators_now: dict, account: dict, positions: list[dict], risk_rules: dict,
                  funding_rate: float | None = None, personality: dict | None = None, scenario: dict | None = None,
                  candidates: list | None = None, armed_plan: dict | None = None, sentiment: dict | None = None, events: list | None = None,
                  ml: dict | None = None) -> dict:
    persona = None
    if personality:
        from core.personalities import DIRECTIONS, FILTERS

        filters = personality.get("filters", {})
        persona = {"nome": personality["name"], "estrategia": personality.get("description", ""),
                   "direcao_permitida": DIRECTIONS.get(personality.get("direction", "misto")),
                   "filtros": [FILTERS[k] for k, v in filters.items() if v and k in FILTERS]
                   + ([f"ADX mínimo {filters['adx_min']}"] if filters.get("adx_min") else [])
                   + ([f"ADX máximo {filters['adx_max']}"] if filters.get("adx_max") else [])
                   + ([f"Volume ≥ {filters['vol_mult']}× a média"] if filters.get("vol_mult") else [])
                   + ([f"Contextos: {', '.join(filters['contexts'])}"] if filters.get("contexts") else []),
                   "stop_atr": personality.get("sl_atr"),
                   "alvo_atr": personality.get("tp_atr") if not personality.get("trail_atr") else
                   "SEM ALVO: o stop acompanha o preço (modo surfar); não defina take_profit",
                   "tempos_graficos_indicados": personality.get("timeframes", "")}
    return {
        "personalidade": persona,
        "bot": {"estilo": profile.name, "mercado": profile.market_label, "horizonte": profile.horizon,
                "ativo": symbol, "timeframe": interval,
                "venda_permitida": bool(cfg.get("allow_short")) and (profile.market == "futures" or cfg.get("leverage_on"))},
        "papel_da_ia": "interferir" if cfg.get("ai_intervene") else "explicar",
        "regras_de_risco": risk_rules,
        "conta_simulada": account,
        "posicoes_abertas_no_ativo": positions,
        "plano_por_regras": plan,
        "indicadores_atuais": indicators_now,
        "niveis_desenhados_pelo_usuario": cfg.get("user_levels", []),
        "taxa_de_financiamento_pct": funding_rate,
        "candles_recentes": snapshot,
        "instrucoes_do_usuario": cfg.get("ai_instructions") or "",
        "cenario_calculado": scenario,
        "sentimento_polymarket": sentiment,
        "eventos_externos": events,
        "modelo_ml": ({"prob_alta_pct": round(ml["p_up"] * 100, 1), "mercado_fora_do_conhecido": ml["outlier"], "auc_validacao": ml.get("auc")}
                      if ml else None),
    }


def _extract_json(text: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
    if not text:
        raise ValueError("resposta vazia")
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("a resposta não contém um objeto JSON: " + text[:120].replace("\n", " "))
        text = text[start: end + 1]
    return json.loads(text)


def _num(v):
    try:
        return float(v) if v not in (None, "", "null") else None
    except (TypeError, ValueError):
        return None


def _strs(v, limit: int = 8) -> list[str]:
    return [str(x).strip() for x in v if str(x).strip()][:limit] if isinstance(v, list) else []


def build_advice(data: dict, rules: dict, extras: dict) -> dict:
    """Junta a análise da IA com a base calculada por regras, validando tudo o que a IA pode afetar:
    o bot precisa ser um dos candidatos e o gatilho do plano precisa ser conferível pelo sistema."""
    from core import advisor, personalities

    advice = dict(rules)
    an = data.get("analise") if isinstance(data.get("analise"), dict) else {}
    for k_src, k_dst in (("cenario", "cenario"), ("melhor_oportunidade", "oportunidade"), ("dica", "dica")):
        if str(an.get(k_src, "")).strip():
            advice[k_dst] = str(an[k_src]).strip()
    if str(an.get("cenario", "")).strip():
        advice["resumo"] = str(an["cenario"]).strip()
    if _strs(an.get("leitura_tecnica")):
        advice["leitura_tecnica"] = _strs(an["leitura_tecnica"])
    cands = {c["id"]: c for c in extras.get("candidates", [])}
    br = data.get("bot_recomendado") if isinstance(data.get("bot_recomendado"), dict) else None
    if br is not None:
        bid = br.get("id")
        if bid in cands:
            c = cands[bid]
            advice["bot"] = {"id": bid, "nome": c["nome"], "motivo": str(br.get("motivo") or c["porque"]).strip(), "mesmo_tempo": c["mesmo_tempo"],
                             "ativo": c["ativo"], "alternativas": [{"id": x["id"], "nome": x["nome"]} for x in extras["candidates"] if x["id"] != bid][:3]}
        elif bid in (None, "", "null"):
            advice["bot"] = {"id": None, "nome": None, "motivo": str(br.get("motivo") or "").strip() or (rules.get("bot") or {}).get("motivo", ""),
                             "mesmo_tempo": False, "ativo": False, "sem_vantagem": True,
                             "alternativas": [{"id": x["id"], "nome": x["nome"]} for x in extras["candidates"][:3]]}
    if "plano_condicional" in data:
        pc = data["plano_condicional"]
        plan = None
        if isinstance(pc, dict):
            pid = pc.get("personalidade")
            if pid not in cands and not personalities.get(pid):
                pid = (advice.get("bot") or {}).get("id")
            plan = advisor.make_plan(pc.get("direcao"), pc.get("tipo"), pc.get("nivel"), pc.get("volume_min_x"), pid, pc.get("validade_candles") or 12,
                                     invalida=pc.get("invalida_em"), price=extras["price"], atr=extras["atr"], why=str(pc.get("explicacao") or ""))
            if plan is None:
                plan = rules.get("plano")  # gatilho inválido: mantém o plano padrão por regras
        advice["plano"] = plan
    advice["fonte"] = "ia"
    return advice


def ask_ai(context: dict, *, api_key: str, model: str, temperature: float = 0.2, extras: dict | None = None,
           persona: str | None = None) -> AIDecision:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/freitasnascimentomarinha-debug/Testebot",
        "X-Title": "TradeBot Platform",
    }
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT + "\n" + persona_text(persona)},
        {"role": "user", "content": "Contexto do mercado e da conta (JSON):\n" + json.dumps(context, ensure_ascii=False, default=str)},
    ]
    # Modelos que "raciocinam" gastam tokens antes de responder e podem devolver conteúdo vazio ou cortado. Por isso há uma
    # segunda tentativa, sem o modo JSON forçado (que alguns provedores não suportam), com mais espaço e um lembrete do formato.
    attempts = [
        {"response_format": {"type": "json_object"}, "max_tokens": 4000, "messages": messages},
        {"max_tokens": 8000, "messages": messages + [{"role": "user", "content":
            "Responda AGORA somente com o objeto JSON do formato pedido (sem texto antes ou depois, sem markdown)."}]},
    ]
    payload, content, data, problems = {}, "", None, []
    for extra in attempts:
        body = {"model": model, "temperature": temperature, **extra}
        resp = requests.post(OPENROUTER_URL, headers=headers, json=body, timeout=TIMEOUT)
        if resp.status_code >= 400:
            try:
                msg = resp.json().get("error", {}).get("message", resp.text)
            except ValueError:
                msg = resp.text
            if "response_format" in extra and resp.status_code in (400, 422):
                problems.append(f"HTTP {resp.status_code}: {msg[:150]}")  # modelo/provedor sem modo JSON: tenta sem ele
                continue
            raise RuntimeError(f"OpenRouter HTTP {resp.status_code}: {msg}")
        payload = resp.json()
        if payload.get("error"):
            problems.append(str(payload["error"].get("message", payload["error"]))[:150])
            continue
        choice = (payload.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        content = msg.get("content") or ""
        if isinstance(content, list):  # alguns provedores devolvem blocos de texto
            content = "".join(b.get("text", "") for b in content if isinstance(b, dict))
        try:
            data = _extract_json(content or msg.get("reasoning") or msg.get("reasoning_content") or "")
            break
        except (ValueError, json.JSONDecodeError) as exc:
            problems.append(f"{exc} (fim: {choice.get('finish_reason') or '?'}, {len(content)} caracteres)")
    if data is None:
        raise RuntimeError("A IA não devolveu um JSON válido após 2 tentativas — " + " | ".join(problems)
                           + ". Tente outro modelo na aba IA (ex.: um sem raciocínio longo).")
    decision = str(data.get("decision", "HOLD")).upper()
    if decision not in {"BUY", "SELL", "HOLD", "CLOSE"}:
        decision = "HOLD"
    advice = build_advice(data, extras["rules"], extras) if extras else {}
    return AIDecision(
        decision=decision, advice=advice,
        order_type="LIMIT" if str(data.get("order_type", "MARKET")).upper() == "LIMIT" else "MARKET",
        entry=_num(data.get("entry")), stop_loss=_num(data.get("stop_loss")), take_profit=_num(data.get("take_profit")),
        confidence=int(_num(data.get("confidence")) or 0), reasoning=str(data.get("reasoning", "")),
        risks=str(data.get("risks", "")), invalidation=str(data.get("invalidation", "")),
        management=str(data.get("management", "")), model=payload.get("model", model), source="ia",
        raw=content, usage=payload.get("usage", {}),
    )


def rules_fallback(plan: dict, reason: str) -> AIDecision:
    """Decisão somente por regras, usada quando não há chave ou a IA falha."""
    conf = int(min(100, abs(plan["score"]) * 1.2)) if plan["direction"] != "HOLD" else 0
    return AIDecision(
        decision=plan["direction"], order_type="MARKET", entry=plan["entry"], stop_loss=plan["stop_loss"],
        take_profit=plan["take_profit"], confidence=conf,
        reasoning=f"Decisão gerada apenas pelas habilidades de programação (placar {plan['score']:+.1f}, regime {plan['regime']}). {plan.get('note', '')}",
        risks="Sem interpretação da IA: " + reason, model="regras", source="regras",
    )


# ------------------------------------------------- estratégia a partir de texto
STRATEGY_PROMPT = """Você converte a descrição de uma estratégia de trading em parâmetros de um bot.
Responda SOMENTE um JSON com:
{"summary": "resumo em 1 frase", "direction": "misto|compra|venda",
 "skills": {"<chave>": peso 0.5-2.0, ...}, "threshold": 15-55,
 "filters": {"trend_ema": bool, "avoid_lateral": bool, "volume_confirm": bool, "rsi_guard": bool,
             "ignore_regime": bool, "adx_min": número ou 0, "adx_max": número ou 0},
 "sl_atr": 0.5-5, "tp_atr": 1-15, "timeframes": "ex.: 15m a 4h"}
Chaves de habilidades disponíveis: tendencia (médias móveis), momentum (RSI), macd, bollinger, supertrend,
vwap, volume, estrutura (topos/fundos), suporte_resistencia, rompimento (Donchian), reversao (reversão à média),
ichimoku, estocastico, adx, fibonacci (retração). Use só as citadas ou claramente implícitas na descrição. threshold menor = mais
agressivo (mais entradas), maior = mais seletivo."""

_KEYWORDS = {
    "tendencia": ("média", "media", "ema", "sma", "tendência", "tendencia", "cruzamento"),
    "momentum": ("rsi", "ifr", "momentum", "força relativa"),
    "macd": ("macd",),
    "bollinger": ("bollinger", "bandas"),
    "supertrend": ("supertrend", "super trend"),
    "vwap": ("vwap",),
    "volume": ("volume", "obv"),
    "estrutura": ("topo", "fundo", "estrutura", "price action", "pivô"),
    "suporte_resistencia": ("suporte", "resistência", "resistencia", "zona"),
    "rompimento": ("rompimento", "breakout", "romper", "donchian"),
    "reversao": ("reversão", "reversao", "sobrevend", "sobrecompr", "exagero"),
    "ichimoku": ("ichimoku", "nuvem", "kumo"),
    "estocastico": ("estocástico", "estocastico", "stoch"),
    "adx": ("adx", "dmi", "força da tendência"),
    "fibonacci": ("fibonacci", "fibo", "retração", "retracao", "61,8", "61.8", "golden"),
}


def strategy_from_text_rules(text: str) -> dict:
    """Interpretação simples por palavras-chave (usada sem chave da IA)."""
    t = text.lower()
    skills = {k: 1.0 for k, words in _KEYWORDS.items() if any(w in t for w in words)} or {"tendencia": 1.0, "momentum": 1.0}
    direction = "compra" if re.search(r"(s[oó]|apenas|somente) compra", t) else \
        "venda" if re.search(r"(s[oó]|apenas|somente) vend", t) else "misto"
    filters = {"trend_ema": "a favor da tendência" in t or "200" in t, "volume_confirm": "volume" in t,
               "avoid_lateral": "lateral" in t, "rsi_guard": "sobrecompr" in t and "reversao" not in skills}
    aggressive = any(w in t for w in ("agressiv", "scalp", "muitas entradas"))
    selective = any(w in t for w in ("conservador", "seletiv", "poucas entradas", "confirmação", "confirmacao"))
    return {"summary": text.strip().split(".")[0][:140], "direction": direction, "skills": skills,
            "threshold": 20 if aggressive else 40 if selective else 30, "filters": filters,
            "sl_atr": 1.5, "tp_atr": 3.0, "timeframes": ""}


def strategy_from_text(text: str, *, api_key: str | None, model: str) -> tuple[dict, str]:
    """Converte a descrição em parâmetros. Devolve (parâmetros, fonte)."""
    if api_key:
        try:
            resp = requests.post(OPENROUTER_URL, timeout=TIMEOUT, json={
                "model": model, "temperature": 0.1, "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": STRATEGY_PROMPT}, {"role": "user", "content": text}]},
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
                         "X-Title": "TradeBot Platform"})
            resp.raise_for_status()
            data = _extract_json(resp.json()["choices"][0]["message"]["content"])
            return data, "IA"
        except Exception as exc:  # noqa: BLE001
            return strategy_from_text_rules(text), f"palavras-chave (IA indisponível: {str(exc)[:80]})"
    return strategy_from_text_rules(text), "palavras-chave"
