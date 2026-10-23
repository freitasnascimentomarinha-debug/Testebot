"""Integração com a IA (DeepSeek via OpenRouter).

A IA recebe o contexto completo (candles, indicadores, votos das habilidades,
plano por regras, níveis do usuário, regras de risco e estado da conta) e
devolve um JSON estrito com a ordem a ser programada. A resposta sempre passa
pelo gestor de risco antes de virar ordem — a IA nunca ignora os limites do
usuário.
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

    def to_dict(self) -> dict:
        return asdict(self)


SYSTEM_PROMPT = """Você é o motor de decisão de um bot de trading quantitativo de criptomoedas.
Recebe dados de mercado REAIS já calculados por habilidades de programação e deve
interpretar o contexto para decidir a próxima ordem. Regras obrigatórias:
1. Responda SOMENTE com um objeto JSON válido, sem texto fora dele.
2. Respeite o estilo do bot (horizonte), o mercado (spot não permite venda a descoberto
   sem margem) e as regras de risco recebidas. Nunca sugira stop mais distante do que o
   permitido pela perda máxima por trade — o tamanho da posição será calculado pelo sistema.
3. Toda entrada (BUY/SELL) exige stop_loss e take_profit numéricos coerentes com o lado
   (compra: stop < entrada < alvo; venda: alvo < entrada < stop) e relação risco:retorno
   maior ou igual ao mínimo informado.
4. Prefira HOLD quando os sinais forem conflitantes, o regime for lateral sem ponto claro
   ou as metas diárias estiverem próximas. Preservar capital é prioridade.
5. Use CLOSE apenas quando houver posição aberta pelo bot (source diferente de "manual") no ativo e o
   cenário tiver se invertido. Posições "manual" são do usuário: considere-as como exposição já existente,
   mas nunca as encerre.
6. Siga a "personalidade" recebida (estratégia, direção permitida e filtros): ela define o estilo do bot.
   Se o cenário não se encaixar na estratégia dela, responda HOLD. As "instrucoes_do_usuario" complementam.
7. "order_type": "LIMIT" só quando houver nível técnico claro para entrada melhor
   (informe "entry"); caso contrário use "MARKET".
Formato:
{"decision":"BUY|SELL|HOLD|CLOSE","order_type":"MARKET|LIMIT","entry":number|null,
 "stop_loss":number|null,"take_profit":number|null,"confidence":0-100,
 "reasoning":"análise objetiva em português (3-6 frases)","risks":"principais riscos",
 "invalidation":"o que invalida a ideia","management":"como conduzir a posição (parciais, trailing, prazo)"}"""


def get_api_key(explicit: str | None = None) -> str | None:
    from core.storage import get_secret

    return explicit or get_secret("OPENROUTER_API_KEY")


def build_context(*, profile, cfg: dict, symbol: str, interval: str, plan: dict, snapshot: list[dict],
                  indicators_now: dict, account: dict, positions: list[dict], risk_rules: dict,
                  funding_rate: float | None = None, personality: dict | None = None) -> dict:
    persona = None
    if personality:
        from core.personalities import DIRECTIONS, FILTERS

        filters = personality.get("filters", {})
        persona = {"nome": personality["name"], "estrategia": personality.get("description", ""),
                   "direcao_permitida": DIRECTIONS.get(personality.get("direction", "misto")),
                   "filtros": [FILTERS[k] for k, v in filters.items() if v and k in FILTERS]
                   + ([f"ADX mínimo {filters['adx_min']}"] if filters.get("adx_min") else [])
                   + ([f"ADX máximo {filters['adx_max']}"] if filters.get("adx_max") else []),
                   "stop_atr": personality.get("sl_atr"), "alvo_atr": personality.get("tp_atr"),
                   "tempos_graficos_indicados": personality.get("timeframes", "")}
    return {
        "personalidade": persona,
        "bot": {"estilo": profile.name, "mercado": profile.market_label, "horizonte": profile.horizon,
                "ativo": symbol, "timeframe": interval,
                "venda_permitida": bool(cfg.get("allow_short")) and (profile.market == "futures" or cfg.get("leverage_on"))},
        "regras_de_risco": risk_rules,
        "conta_simulada": account,
        "posicoes_abertas_no_ativo": positions,
        "plano_por_regras": plan,
        "indicadores_atuais": indicators_now,
        "niveis_desenhados_pelo_usuario": cfg.get("user_levels", []),
        "taxa_de_financiamento_pct": funding_rate,
        "candles_recentes": snapshot,
        "instrucoes_do_usuario": cfg.get("ai_instructions") or "",
    }


def _extract_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            text = text[start: end + 1]
    return json.loads(text)


def _num(v):
    try:
        return float(v) if v not in (None, "", "null") else None
    except (TypeError, ValueError):
        return None


def ask_ai(context: dict, *, api_key: str, model: str, temperature: float = 0.2) -> AIDecision:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/freitasnascimentomarinha-debug/Testebot",
        "X-Title": "TradeBot Platform",
    }
    body = {
        "model": model,
        "temperature": temperature,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "Contexto do mercado e da conta (JSON):\n" + json.dumps(context, ensure_ascii=False, default=str)},
        ],
    }
    resp = requests.post(OPENROUTER_URL, headers=headers, json=body, timeout=TIMEOUT)
    if resp.status_code >= 400:
        try:
            msg = resp.json().get("error", {}).get("message", resp.text)
        except ValueError:
            msg = resp.text
        raise RuntimeError(f"OpenRouter HTTP {resp.status_code}: {msg}")
    payload = resp.json()
    content = payload["choices"][0]["message"].get("content") or ""
    data = _extract_json(content)
    decision = str(data.get("decision", "HOLD")).upper()
    if decision not in {"BUY", "SELL", "HOLD", "CLOSE"}:
        decision = "HOLD"
    return AIDecision(
        decision=decision,
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
