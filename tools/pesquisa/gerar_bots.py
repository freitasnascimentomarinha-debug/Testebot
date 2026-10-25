"""Gera os bots por contexto (backtest em candles reais da Binance) e salva em core/context_bots.json + relatório em docs/.

    python tools/pesquisa/gerar_bots.py                      # tudo: futuros e spot, 5m/15m/1h/4h, 6 contextos
    python tools/pesquisa/gerar_bots.py --fast               # grade menor (teste rápido)
    python tools/pesquisa/gerar_bots.py --markets futures --intervals 15m 1h --contexts tendencia rompimento

Precisa de acesso à Binance (api.binance.com / fapi.binance.com ou data-api.binance.vision). Veja core/context_research.py.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core import context_research as cr  # noqa: E402
from core import data  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--markets", nargs="*", default=list(cr.MARKET_SIDES), choices=list(cr.MARKET_SIDES))
    ap.add_argument("--intervals", nargs="*", default=list(cr.INTERVALS), choices=list(cr.INTERVALS))
    ap.add_argument("--contexts", nargs="*", default=list(cr.CONTEXTS), choices=list(cr.CONTEXTS))
    ap.add_argument("--fast", action="store_true", help="grade menor de candidatos")
    ap.add_argument("--merge", action="store_true", help="mantém os bots já salvos das células não pesquisadas agora")
    args = ap.parse_args()

    result = cr.run(args.markets, args.intervals, args.contexts, universe=data.volume_ranking, getter=data.get_klines, fast=args.fast)
    if args.merge and cr.OUT_FILE.exists():
        import json

        old = json.loads(cr.OUT_FILE.read_text(encoding="utf-8"))
        done = {(r["market"], r["interval"], r["context"], r["side"]) for r in result["report"]}
        keep = [b for b in old.get("bots", []) if (b["markets"][0], b["tested_interval"], b["context_group"], b["side"]) not in done]
        result["bots"] = keep + result["bots"]
        result["research"] = {**{b["id"]: old["research"][b["id"]] for b in keep}, **result["research"]}
        result["report"] = [r for r in old.get("report", []) if (r["market"], r["interval"], r["context"], r["side"]) not in done] + result["report"]
    cr.save(result)
    doc = ROOT / "docs" / f"bots_por_contexto_{date.today():%Y-%m}.md"
    doc.write_text(cr.report_markdown(result), encoding="utf-8")
    ok = len(result["bots"])
    print(f"\n{ok} bot(s) aprovado(s) de {len(result['report'])} células. Salvo em {cr.OUT_FILE} e {doc}.")


if __name__ == "__main__":
    main()
