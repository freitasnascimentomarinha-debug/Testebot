"""Executor 24/7 sem navegador (piloto automático em segundo plano).

Usa exatamente as configurações salvas na interface. Analisa cada bot com
``autopilot`` ligado sempre que um novo candle fecha e executa as ordens
aprovadas pelo gestor de risco. Também monitora stops/alvos continuamente.

    export OPENROUTER_API_KEY=sk-or-...
    python worker.py              # todos os bots com piloto automático ligado
    python worker.py --bots day   # apenas o day trade
"""
from __future__ import annotations

import argparse
import logging
import time

from core import accounts, engine, personalities, storage
from core.broker import get_broker
from core.data import get_funding_rate, get_klines, get_ticker, last_closed_candle_time
from core.ai import get_api_key
from core.profiles import PROFILES
from core.settings import load_settings

log = logging.getLogger("worker")


def tick(bot: str, last_seen: dict) -> None:
    profile = PROFILES[bot]
    cfg = load_settings(bot)
    raw = get_klines(cfg["symbol"], cfg["interval"], int(cfg["candles"]), profile.market)
    price = get_ticker(cfg["symbol"], profile.market).last
    broker = get_broker(bot)
    funding = get_funding_rate(cfg["symbol"]) if profile.market == "futures" else None
    for ev in broker.sync(cfg["symbol"], raw, price, funding):
        log.info("[%s] %s %s", bot, ev["type"], ev.get("trade", {}).get("pnl", ""))
    if not cfg["autopilot"]:
        return
    if not personalities.is_allowed(cfg.get("personality"), profile.market, cfg["interval"]):
        log.warning("[%s] personalidade %s não foi treinada/testada em %s %s: análise ignorada", bot, cfg.get("personality"),
                    profile.market, cfg["interval"])
        return
    marker = f"{cfg['symbol']}-{cfg['interval']}-{last_closed_candle_time(raw, cfg['interval'])}"
    if last_seen.get(bot) == marker:
        return
    last_seen[bot] = marker
    htf_raw = mtf_raw = None
    if engine.needs_htf(cfg):
        htf_raw, mtf_raw = engine.htf_frames(get_klines, cfg, len(raw), profile.market)
    df = engine.prepare(raw, cfg, htf_raw, mtf_raw)
    state, planned = engine.check_armed_plan(profile, cfg, df, price)
    if state:
        log.info("[%s] plano condicional: %s", bot, state)
    if planned is not None:
        if planned.check and planned.check.allowed:
            out = engine.execute(profile, cfg, planned, price)
            log.info("[%s] plano condicional confirmado: ordem %s", bot, out.get("status"))
        else:
            log.info("[%s] plano confirmado, bloqueado: %s", bot, " | ".join(planned.check.reasons if planned.check else []))
        return
    result = engine.run_analysis(profile, cfg, df, price, get_api_key())
    d = result.decision
    log.info("[%s] %s %s conf=%s%% fonte=%s aprovado=%s", bot, cfg["symbol"], d.decision, d.confidence, d.source,
             bool(result.check and result.check.allowed))
    if (result.check and result.check.allowed) or d.decision == "CLOSE":
        out = engine.execute(profile, cfg, result, price)
        log.info("[%s] ordem: %s", bot, out.get("status"))
    elif result.check:
        log.info("[%s] bloqueada: %s", bot, " | ".join(result.check.reasons))
    elif engine.auto_arm(profile, cfg, result, df):
        log.info("[%s] plano condicional da IA armado", bot)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bots", nargs="*", default=list(PROFILES), choices=list(PROFILES))
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
