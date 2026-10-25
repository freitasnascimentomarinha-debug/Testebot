"""Varredura automática: a cada candle fechado o bot procura oportunidades em vários ativos, sozinho.

Para cada ativo da lista: baixa os candles, escolhe o bot do ranking para o contexto dele, aplica as regras e (sem gastar IA) vê se
há sinal. As melhores oportunidades — e só elas — passam pela IA (no máximo uma consulta por varredura, a não ser que a IA esteja
autorizada a confirmar/vetar a entrada) e viram ordem. Sinais contrários a posições abertas do bot as encerram. Também confere
stops e alvos das posições abertas em todos os ativos, não só no que está na tela.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from core import engine, execution
from core.broker import get_broker
from core.profiles import BotProfile

import random

from core import data as market_data

DEFAULT_SCAN = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "LTCUSDT"]
WINDOW = 120      # candles fechados analisados em cada moeda
WARMUP = 210      # candles anteriores só para os indicadores "esquentarem" (médias de 200 períodos etc.)
MIN_COUNT = 20


@dataclass
class ScanReport:
    time: str
    interval: str
    scanned: int = 0
    viewed: engine.AnalysisResult | None = None            # leitura do ativo que está na tela
    opportunities: list = field(default_factory=list)       # AnalysisResult de cada oportunidade (BUY/SELL) encontrada
    executed: list = field(default_factory=list)            # {"symbol", "action", "status"}
    notes: list = field(default_factory=list)


def symbols_for(cfg: dict, market: str, pool=None, rng: random.Random | None = None, extra=()) -> list[str]:
    """Moedas da varredura: a da tela primeiro, depois um sorteio entre as de maior volume do mercado (futuros ou spot) até completar
    ``scan_count`` (mínimo 20), mais as que têm posição aberta do bot (para o sinal contrário poder encerrá-las)."""
    first = str(cfg["symbol"]).upper()
    if not cfg.get("scan_on", True):
        return [first]
    count = max(MIN_COUNT, int(cfg.get("scan_count") or MIN_COUNT))
    try:
        ranked = (pool or market_data.volume_ranking)(market)
    except Exception:  # noqa: BLE001
        ranked = []
    top = list(dict.fromkeys(ranked[:max(count, int(cfg.get("scan_pool") or 60))])) or list(DEFAULT_SCAN)
    rng = rng or random.Random()
    others = [x for x in top if x != first]
    picked = rng.sample(others, min(count - 1, len(others)))
    return list(dict.fromkeys([first, *picked, *[str(e).upper() for e in extra]]))


def sync_open(profile: BotProfile, klines, ticker, funding=None, skip: set | None = None) -> list[dict]:
    """Confere stops, alvos e ordens limitadas dos ativos com posição aberta (exceto ``skip``, que a tela já conferiu)."""
    broker = get_broker(profile.key)
    acct = broker.account()
    symbols = ({p["symbol"] for p in acct["positions"] if p.get("market") == profile.market}
               | {o["symbol"] for o in acct["orders"] if o.get("market") == profile.market}) - (skip or set())
    events = []
    for sym in sorted(symbols):
        try:
            raw = klines(sym, "5m", 300, profile.market)
            price = ticker(sym, profile.market).last
            fr = funding(sym) if funding and profile.market == "futures" else None
            events += broker.sync(sym, raw, price, fr)
        except Exception:  # noqa: BLE001 - sem dados desse ativo agora: confere na próxima vez
            continue
    return events


def run(profile: BotProfile, cfg: dict, api_key: str | None, *, klines, ticker, funding=None, execute: bool = True,
        progress=None, pool=None, rng: random.Random | None = None) -> ScanReport:
    """Uma varredura completa. ``klines(sym, interval, n, market)`` e ``ticker(sym, market)`` vêm da interface (cache) ou do worker."""
    broker = get_broker(profile.key)
    report = ScanReport(time=datetime.now(timezone.utc).isoformat(timespec="seconds"), interval=cfg["interval"])
    acct_positions = broker.account()["positions"]
    mine = [p["symbol"] for p in acct_positions if p.get("market") == profile.market and p.get("source") != "manual"
            and p.get("bot", profile.key) == profile.key]
    symbols = symbols_for(cfg, profile.market, pool, rng, extra=mine)
    execute = execute and execution.orders_enabled()
    found: list[tuple] = []
    for k, sym in enumerate(symbols, start=1):
        cfg_s = {**cfg, "symbol": sym}
        try:
            raw = klines(sym, cfg["interval"], WINDOW + WARMUP + 1, profile.market)
            price = ticker(sym, profile.market).last
            htf_raw = mtf_raw = None
            if engine.needs_htf(cfg_s):
                htf_raw, mtf_raw = engine.htf_frames(klines, cfg_s, len(raw), profile.market)
            # indicadores calculados com o aquecimento; a análise olha os últimos 120 candles fechados (+ o candle em formação)
            df = engine.prepare(raw, cfg_s, htf_raw, mtf_raw).tail(WINDOW + 1).reset_index(drop=True)
            res = _best_signal(profile, cfg_s, df, price)   # só regras: não gasta IA
        except Exception as exc:  # noqa: BLE001 - um ativo sem dados não derruba a varredura
            report.notes.append(f"{sym}: sem dados ({str(exc)[:60]})")
            continue
        report.scanned += 1
        if sym == symbols[0]:
            report.viewed = res
        if res.decision.decision == "CLOSE":
            if execute:
                _run_close(profile, cfg_s, res, price, report)
        elif res.decision.decision in ("BUY", "SELL") and res.check and res.check.allowed:
            found.append((abs(res.plan["score"]), sym, cfg_s, df, price, res))  # res.personality = bot que deu o sinal
        if progress:
            progress(k / len(symbols), sym)

    found.sort(key=lambda f: -f[0])
    entries = 0
    for idx, (_, sym, cfg_s, df, price, res) in enumerate(found):
        if entries >= int(cfg.get("scan_max_entries", 2)):
            break
        # A IA só entra com a melhor oportunidade (ou em todas, se ela puder confirmar/vetar a entrada); as demais são
        # refeitas só com regras porque o saldo disponível mudou depois da ordem anterior.
        use_ai = bool(api_key) and (idx == 0 or cfg.get("ai_intervene"))
        res = engine.run_analysis(profile, cfg_s, df, price, api_key if use_ai else None, log=False,
                                  personality_id=(res.personality or {}).get("id"))
        if sym == symbols[0] or report.viewed is None:
            report.viewed = res
        if res.decision.decision not in ("BUY", "SELL") or not (res.check and res.check.allowed):
            engine.log_decision(profile.key, res)
            continue
        report.opportunities.append(res)
        engine.log_decision(profile.key, res)
        if execute:
            try:
                out = engine.execute(profile, cfg_s, res, price)
                report.executed.append({"symbol": sym, "action": res.decision.decision, "status": out.get("status")})
                entries += 1
            except Exception as exc:  # noqa: BLE001
                report.notes.append(f"{sym}: falha ao enviar a ordem ({str(exc)[:80]})")
    if report.viewed is not None and report.viewed.decision.decision == "HOLD":
        engine.log_decision(profile.key, report.viewed)
    return report


def _best_signal(profile: BotProfile, cfg_s: dict, df, price: float, top: int = 3) -> engine.AnalysisResult:
    """Lê o contexto da moeda (tendência, força, volume, tempo maior…) e aplica, em ordem, os melhores bots do ranking para esse
    contexto até um deles dar sinal. Sem sinal de nenhum, devolve a leitura do melhor bot (ou de espera, se nenhum tem vantagem)."""
    try:
        bots, _ = engine.pick_bots(profile, cfg_s, df, top=top)
    except Exception:  # noqa: BLE001 - a escolha automática nunca derruba a varredura
        bots = []
    first = None
    for bot in bots:
        res = engine.run_analysis(profile, cfg_s, df, price, None, log=False, personality_id=bot["id"])
        first = first or res
        if res.decision.decision in ("BUY", "SELL", "CLOSE"):
            return res
    return first or engine.run_analysis(profile, cfg_s, df, price, None, log=False)


def _run_close(profile, cfg_s, res, price, report: ScanReport) -> None:
    try:
        engine.log_decision(profile.key, res)
        out = engine.execute(profile, cfg_s, res, price)
        report.executed.append({"symbol": cfg_s["symbol"], "action": "CLOSE", "status": out.get("status")})
    except Exception as exc:  # noqa: BLE001
        report.notes.append(f"{cfg_s['symbol']}: falha ao encerrar ({str(exc)[:80]})")
