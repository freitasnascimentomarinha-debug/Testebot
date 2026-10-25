"""Executor 24/7 sem navegador (piloto automático em segundo plano).

Usa exatamente as configurações salvas na interface. Analisa cada bot com
``autopilot`` ligado sempre que um novo candle fecha: varre os ativos da lista, usa o bot mais recomendado do ranking
para o contexto de cada um e opera as melhores oportunidades. Também monitora stops/alvos continuamente.

    export OPENROUTER_API_KEY=sk-or-...
    python worker.py              # todos os bots com piloto automático ligado
    python worker.py --bots day   # apenas o day trade
"""
from __future__ import annotations

import argparse
import logging
import time

from core import accounts, engine, execution, personalities, scanner, storage
from core.data import get_funding_rate, get_klines, get_ticker, last_closed_candle_time
from core.ai import get_api_key
from core.profiles import PAGE_BOTS, PROFILES
from core.settings import load_settings

log = logging.getLogger("worker")


def tick(bot: str, last_seen: dict) -> None:
    profile = PROFILES[bot]
    cfg = load_settings(bot)
    # stops e alvos de todos os ativos com posição aberta (a varredura pode abrir posições em vários ativos)
    for ev in scanner.sync_open(profile, get_klines, get_ticker, get_funding_rate):
        log.info("[%s] %s %s", bot, ev["type"], ev.get("trade", {}).get("pnl", ""))
    if not cfg["autopilot"]:
        return
    if (why := execution.orders_problem()):
        log.info("[%s] em espera: %s", bot, why)
        return
    if not personalities.allowed(profile.market, cfg["interval"]):
        log.warning("[%s] nenhum bot foi treinado/testado em %s %s: análise ignorada", bot, profile.market, cfg["interval"])
        return
    raw = get_klines(cfg["symbol"], cfg["interval"], 150, profile.market)
    marker = f"{cfg['symbol']}-{cfg['interval']}-{last_closed_candle_time(raw, cfg['interval'])}"
    if last_seen.get(bot) == marker:
        return
    last_seen[bot] = marker
    if engine.ensure_ranking(profile, cfg):
        log.info("[%s] ranking semanal dos bots atualizado (%s %s)", bot, profile.market, cfg["interval"])
    report = scanner.run(profile, cfg, get_api_key(), klines=get_klines, ticker=get_ticker, funding=get_funding_rate)
    log.info("[%s] varredura: %d ativo(s), %d oportunidade(s), ordens: %s", bot, report.scanned, len(report.opportunities),
             ", ".join(f"{e['action']} {e['symbol']} {e['status']}" for e in report.executed) or "nenhuma")
    for note in report.notes:
        log.info("[%s] %s", bot, note)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bots", nargs="*", default=list(PAGE_BOTS), choices=list(PROFILES))
    parser.add_argument("--interval", type=int, default=15, help="segundos entre verificações")
    parser.add_argument("--users", nargs="*", default=None, help="com contas ligadas: só estes usuários (padrão: todos)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not get_api_key():
        log.warning("OPENROUTER_API_KEY não definida — usando somente as habilidades de programação.")
    last_seen: dict = {}
    while True:
        # Com contas ligadas, percorre os usuários (cada um com a própria carteira e configuração).
        users = (args.users or accounts.list_users()) if accounts.enabled() else [None]
        for user in users:
            storage.set_user(user)
            for bot in args.bots:
                try:
                    tick(bot, last_seen.setdefault(user, {}))
                except Exception:  # noqa: BLE001
                    log.exception("[%s/%s] erro no ciclo", user or "-", bot)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
