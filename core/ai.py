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
5. Use CLOSE apenas quando houver posição aberta no ativo e o cenário tiver se invertido.
6. "order_type": "LIMIT" só quando houver nível técnico claro para entrada melhor
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
                  funding_rate: float | None = None) -> dict:
    return {
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
