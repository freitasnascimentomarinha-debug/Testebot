"""A IA decide se uma posição aberta do bot deve ser encerrada, a partir do contexto de mercado atual.

Roda só quando o usuário liga "IA decide saídas" (Configurações → IA) e só para posições abertas pelo próprio bot. O stop e o alvo
continuam valendo: a IA só pode antecipar a saída (CLOSE) ou manter (HOLD); qualquer resposta inválida ou falha vira HOLD.
"""
from __future__ import annotations

import json

import requests

from core import ai, positions_view

SYSTEM_PROMPT = """Você é um gestor de risco de criptomoedas. Há uma posição ABERTA do bot e o stop e o alvo já a protegem.
Decida apenas: manter (HOLD) ou encerrar agora a mercado (CLOSE). Regras:
1. Responda SOMENTE um JSON: {"acao":"HOLD|CLOSE","confianca":0-100,"motivo":"1 a 2 frases objetivas"}.
2. O padrão é HOLD. Só use CLOSE se a tese da entrada foi invalidada ou o cenário virou contra a posição com evidência nos dados
   (contexto do gráfico mudou, tendência do tempo maior virou, rompimento falhou, perda de suporte/resistência, volume contra),
   ou se o lucro já está esticado e os dados mostram exaustão. Um recuo pequeno dentro do normal NÃO é motivo para sair.
3. O "motivo" cita os fatos dos dados (contexto, ADX, RSI, volume, distância ao stop/alvo em ATR). Não repita lugares-comuns
   nem conselhos genéricos. Nunca invente números."""


def build_context(pos: dict, price: float, sc: dict, snapshot: dict, personality: dict | None, cfg: dict) -> dict:
    atr = sc.get("atr") or 0
    long = pos["side"] == "BUY"
    sign = 1 if long else -1
    d_atr = lambda lvl: None if not lvl or not atr else round(sign * (price - lvl) / atr, 2)  # noqa: E731 - distância do preço ao nível, em ATR
    return {
        "posicao": {"ativo": pos["symbol"], "lado": "compra" if long else "venda", "entrada": pos["entry"], "preco_agora": price,
                    "resultado_liquido_usdt": round(positions_view.summarize(pos, price)["net"], 2),
                    "stop": pos.get("stop_loss"), "alvo": pos.get("take_profit"), "aberta_em": pos.get("opened"),
                    "distancia_do_stop_em_atr": d_atr(pos.get("stop_loss")), "distancia_do_alvo_em_atr": (None if not pos.get("take_profit") else
                                                                                                          round(-d_atr(pos["take_profit"]), 2)),
                    "motivo_da_entrada": (pos.get("note") or "")[:200], "bot": (personality or {}).get("name") or (pos.get("personality") or {}).get("name")},
        "cenario_agora": sc, "candles_recentes": snapshot, "tempo_grafico": cfg["interval"],
    }


def consult(ctx: dict, *, api_key: str, model: str) -> dict:
    """Devolve ``{"acao": "HOLD"|"CLOSE", "confianca": int, "motivo": str}``; qualquer falha vira HOLD."""
    try:
        body = {"model": model, "temperature": 0.1, "max_tokens": 3000, "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                             {"role": "user", "content": "Dados reais (JSON):\n" + json.dumps(ctx, ensure_ascii=False, default=str)}]}
        resp = requests.post(ai.OPENROUTER_URL, json=body, timeout=ai.TIMEOUT,
                             headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "X-Title": "TradeBot Platform"})
        resp.raise_for_status()
        msg = resp.json()["choices"][0]["message"]
        data = ai._extract_json(msg.get("content") or msg.get("reasoning") or "")
    except Exception as exc:  # noqa: BLE001 - IA fora do ar: a posição segue com stop e alvo
        return {"acao": "HOLD", "confianca": 0, "motivo": f"IA indisponível ({str(exc)[:60]}): mantida.", "erro": True}
    return parse(data)


def parse(data: dict) -> dict:
    acao = str(data.get("acao", "HOLD")).upper()
    try:
        conf = max(0, min(100, int(float(data.get("confianca", 0)))))
    except (TypeError, ValueError):
        conf = 0
    return {"acao": "CLOSE" if acao == "CLOSE" else "HOLD", "confianca": conf, "motivo": str(data.get("motivo", "")).strip()[:400]}
