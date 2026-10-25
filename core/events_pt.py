"""Tradução para o português e explicação ("?") dos eventos do Polymarket.

Texto em inglês é traduzido pela IA (em lotes, em segundo plano, uma única vez por evento; o resultado fica guardado). Enquanto a IA não
respondeu — ou sem chave —, valem regras simples (meses, sim/não, juros) e uma explicação genérica em português escrita pelo próprio
sistema, então a página nunca fica sem o "?".
"""
from __future__ import annotations

import hashlib
import re
import threading

import requests

from core import ai
from core.storage import load_json, locked_update

FILE = "events_pt.json"
BATCH = 12
KEEP = 800
MONTHS = {"January": "janeiro", "February": "fevereiro", "March": "março", "April": "abril", "May": "maio", "June": "junho", "July": "julho",
          "August": "agosto", "September": "setembro", "October": "outubro", "November": "novembro", "December": "dezembro"}
_RULES = [
    (r"\bNo change\b", "Sem mudança"), (r"(\d+(?:\+)?) bps increase", r"Alta de \1 bps"), (r"(\d+(?:\+)?) bps decrease", r"Queda de \1 bps"),
    (r"\bFed Decision in (\w+)\?", lambda m: f"Decisão do Fed em {MONTHS.get(m.group(1), m.group(1))}?"),
    (r"\bFed decisions\b", "Decisões do Fed"), (r"\bPresidential Election\b", "Eleição presidencial"), (r"\bSecond Round\b", "Segundo turno"),
    (r"\bMargin of Victory\b", "Margem de vitória"), (r"\bBrazil(ian)?\b", "Brasil"), (r"\bWinner\b", "Vencedor"),
    (r"\bor more\b", "ou mais"), (r"\bRussia\b", "Rússia"), (r"\bUkraine\b", "Ucrânia"), (r"\bIran\b", "Irã"), (r"\bUS-", "EUA-"), (r"\bU\.S\.", "EUA"),
    (r"\bStrait of Hormuz\b", "Estreito de Ormuz"), (r"\bHormuz\b", "Ormuz"), (r"\btraffic returns to normal\b", "tráfego volta ao normal"),
    (r"\bagreement\b", "acordo"), (r"\bdiplomatic meeting\b", "reunião diplomática"), (r"\bany\b", "qualquer"), (r"\bby\b", "até"), (r"\bAgreement\b", "Acordo"), (r"\bby\.\.\.\?", "até...?"),
    (r"\bSenate\b", "Senado"), (r"\bHouse\b", "Câmara"), (r"\bmidterms?\b", "eleições de meio de mandato"), (r"\bby end of\b", "até o fim de"), (r"\bceasefire\b", "cessar-fogo"), (r"\bcontinues through\b", "continua até"),
]
_state = {"cache": None, "running": False}
_lock = threading.Lock()


def rule_pt(text: str) -> str:
    """Tradução mínima por regras (meses e termos mais comuns). O resto fica como veio."""
    out = text or ""
    for pat, rep in _RULES:
        out = re.sub(pat, rep, out)
    for en, pt in MONTHS.items():
        out = re.sub(rf"\b{en}\b", pt, out)
    return out


def key_of(card: dict) -> str:
    return hashlib.sha1((card["titulo"] + "|" + "|".join(o["nome"] for o in card["opcoes"])).encode()).hexdigest()[:16]


def generic_explanation(card: dict) -> str:
    """O que é a aposta, em português simples, sem depender de tradução."""
    kind = ("As linhas são níveis de preço: a porcentagem é a chance, dada pelos apostadores, de o preço tocar esse nível até o vencimento."
            if card.get("escada") else
            "É uma aposta de sim ou não: a porcentagem é a chance, dada pelos apostadores, de acontecer até o vencimento."
            if len(card["opcoes"]) == 2 and card["opcoes"][0]["nome"] in ("Sim", "Yes") else
            "É uma aposta entre várias opções: cada porcentagem é a chance, dada pelos apostadores, de aquela opção ser a vencedora.")
    why = {"macro": "Juros, inflação e emprego nos EUA movem o dólar e, por consequência, o preço de cripto e de outros ativos de risco.",
           "geopolitica": "Guerras e tensões entre países mexem com petróleo, dólar e apetite a risco: cripto costuma cair em sustos e subir com alívio.",
           "politica": "Eleições e decisões de governo mudam regulação, impostos e confiança dos investidores, o que acaba chegando ao mercado.",
           "commodities": "Ouro, petróleo e bolsas mostram o humor geral do mercado: cripto tende a acompanhar o apetite a risco.",
           "cripto": "Mostra o que o mercado de previsões espera do preço da moeda."}.get(card["categoria"], "")
    return f"{kind} {why}".strip()


def _cache() -> dict:
    if _state["cache"] is None:
        _state["cache"] = load_json(FILE, {}) or {}
    return _state["cache"]


def localize(cards: list[dict]) -> list[dict]:
    """Cartões em português: tradução da IA quando houver; senão regras mínimas. Sempre com a explicação do "?"."""
    cache, out = _cache(), []
    for c in cards:
        t = cache.get(key_of(c))
        opts = c["opcoes"]
        if t and len(t.get("o") or []) == len(opts):
            titulo, nomes, expl, ia = t["t"], t["o"], t.get("e") or generic_explanation(c), True
        else:
            titulo, nomes, expl, ia = rule_pt(c["titulo"]), [rule_pt(o["nome"]) for o in opts], generic_explanation(c), False
        out.append({**{k: v for k, v in c.items() if k != "desc"}, "titulo": titulo, "traduzido": ia, "explicacao": expl,
                    "opcoes": [{"nome": n, "pct": o["pct"]} for n, o in zip(nomes, opts)]})
    return out


SYSTEM = """Você traduz mercados do Polymarket para o português do Brasil e explica cada um para quem nunca viu o mercado.
Responda SOMENTE um JSON: {"itens":[{"id":"...","titulo":"...","opcoes":["...", ...],"explicacao":"..."}]}.
Regras: mantenha a ordem das opções e a MESMA quantidade; traduza títulos e opções de forma natural (ex.: "No change" → "Sem mudança",
"25 bps increase" → "Alta de 25 bps"); mantenha nomes próprios, siglas e números (Fed, bps, WTI, BTC, US$). "explicacao": 2 a 3 frases
simples dizendo o que está sendo apostado, até quando e como resolve (use a descrição), e por que importa para cripto/dólar quando for óbvio.
Não invente fatos além da descrição."""


def translate(cards: list[dict], api_key: str, model: str) -> dict:
    """Pede à IA a tradução de ``cards`` (já sem tradução guardada). Devolve {chave: {t, o, e}}; falhas devolvem vazio."""
    payload = [{"id": key_of(c), "titulo": c["titulo"], "opcoes": [o["nome"] for o in c["opcoes"]], "descricao": c.get("desc", "")[:450]} for c in cards]
    try:
        r = requests.post(ai.OPENROUTER_URL, timeout=ai.TIMEOUT, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
                                                                         "X-Title": "TradeBot Platform"},
                          json={"model": model, "temperature": 0.1, "max_tokens": 6000, "response_format": {"type": "json_object"},
                                "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": __import__("json").dumps(payload, ensure_ascii=False)}]})
        r.raise_for_status()
        msg = r.json()["choices"][0]["message"]
        data = ai._extract_json(msg.get("content") or msg.get("reasoning") or "")
    except Exception:  # noqa: BLE001 - sem tradução da IA, valem as regras
        return {}
    return parse(data, cards)


def parse(data: dict, cards: list[dict]) -> dict:
    by_id = {key_of(c): c for c in cards}
    out = {}
    for it in (data.get("itens") if isinstance(data, dict) else None) or []:
        c = by_id.get(str(it.get("id")))
        opts = it.get("opcoes")
        if not c or not isinstance(opts, list) or len(opts) != len(c["opcoes"]) or not str(it.get("titulo", "")).strip():
            continue   # resposta fora do combinado: esse evento fica com as regras
        out[str(it["id"])] = {"t": str(it["titulo"]).strip()[:200], "o": [str(o).strip()[:80] for o in opts], "e": str(it.get("explicacao", "")).strip()[:600]}
    return out


def save(new: dict) -> None:
    cache = _cache()
    cache.update(new)
    if len(cache) > KEEP:
        for k in list(cache)[: len(cache) - KEEP]:
            cache.pop(k, None)

    def _apply(data):
        data.update(new)
        for k in list(data)[: max(0, len(data) - KEEP)]:
            data.pop(k, None)

    locked_update(FILE, {}, _apply)


def pending(cards: list[dict]) -> list[dict]:
    cache = _cache()
    return [c for c in cards if key_of(c) not in cache]


def translate_async(cards: list[dict], api_key: str | None, model: str) -> None:
    """Traduz em segundo plano os eventos que ainda não têm tradução guardada (a página mostra as regras até lá)."""
    if not api_key or _state["running"]:
        return
    todo = pending(cards)
    if not todo:
        return
    _state["running"] = True

    def _run():
        try:
            for i in range(0, len(todo), BATCH):
                got = translate(todo[i:i + BATCH], api_key, model)
                if got:
                    save(got)
        finally:
            _state["running"] = False

    threading.Thread(target=_run, daemon=True).start()
