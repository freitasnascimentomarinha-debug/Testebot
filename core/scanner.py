"""Varredura automática: de tempos em tempos (padrão 15 min, configurável) o bot procura oportunidades em vários ativos, sozinho.

Para cada ativo da lista: baixa os candles, escolhe o bot do ranking para o contexto dele, aplica as regras e (sem gastar IA) vê se
há sinal. As melhores oportunidades — e só elas — passam pela IA (a IA confirma ou veta as melhores, até AI_MAX_PER_SCAN por varredura) e viram ordem. Sinais contrários a posições abertas do bot as encerram. Também confere
stops e alvos das posições abertas em todos os ativos, não só no que está na tela.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from core import ai_exit, advisor, engine, events, execution, portfolio, sentiment
from core.storage import get_secret, current_user
from core.broker import get_broker
from core.profiles import BotProfile
from core.storage import locked_update, load_json

import random
import time

from core import data as market_data

DEFAULT_SCAN = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "LTCUSDT"]
WINDOW = 120      # candles fechados analisados em cada moeda
WARMUP = 210      # candles anteriores só para os indicadores "esquentarem" (médias de 200 períodos etc.)
DEFAULT_COUNT = 15
AI_MAX_PER_SCAN = 5   # a IA confirma ou veta só as melhores oportunidades de cada varredura (limita as consultas)


SCAN_STATE = "scan_state.json"
DEFAULT_MINUTES = 15


def last_scan(bot: str) -> float | None:
    return (load_json(SCAN_STATE, {}) or {}).get(bot)


def claim(bot: str, minutes: float, now: float | None = None) -> bool:
    """Reserva a próxima varredura: True se já passaram ``minutes`` desde a anterior (e marca a hora agora). Guardado em disco/nuvem para
    que a página e o worker nunca varram ao mesmo tempo, e para abrir a página ou trocar de ativo/tempo gráfico não disparar nada."""
    now = time.time() if now is None else now
    got = []

    def _apply(data):
        if now - float(data.get(bot, 0) or 0) >= max(1.0, float(minutes)) * 60:
            data[bot] = now
            got.append(True)

    locked_update(SCAN_STATE, {}, _apply)
    return bool(got)


def reset(bot: str) -> None:
    """A próxima verificação varre na hora (usado ao ligar o bot)."""
    def _apply(data):
        data.pop(bot, None)

    locked_update(SCAN_STATE, {}, _apply)


def next_scan(bot: str, minutes: float) -> float | None:
    last = last_scan(bot)
    return None if last is None else last + max(1.0, float(minutes)) * 60


@dataclass
class ScanReport:
    time: str
    interval: str
    scan_time: str = ""                                    # hora da última varredura de verdade (todas as moedas)
    scanned: int = 0
    viewed: engine.AnalysisResult | None = None            # leitura do ativo que está na tela
    opportunities: list = field(default_factory=list)       # AnalysisResult de cada oportunidade (BUY/SELL) encontrada
    executed: list = field(default_factory=list)            # {"symbol", "action", "status"}
    notes: list = field(default_factory=list)
    exit_views: list = field(default_factory=list)          # respostas da IA sobre posições abertas ({"symbol","acao","confianca","motivo"})


def symbols_for(cfg: dict, market: str, pool=None, rng: random.Random | None = None, extra=()) -> list[str]:
    """Moedas da varredura: a da tela primeiro, depois um sorteio entre as de maior volume do mercado (futuros ou spot) até completar
    ``scan_count`` (padrão 15), mais as que têm posição aberta do bot (para o sinal contrário poder encerrá-las)."""
    first = str(cfg["symbol"]).upper()
    if not cfg.get("scan_on", True):
        return [first]
    count = max(1, int(cfg.get("scan_count") or DEFAULT_COUNT))
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
    if api_key:
        events.ensure()   # a IA lê os eventos do Polymarket guardados (a primeira vez carrega na hora; depois renova em segundo plano)
    broker = get_broker(profile.key)
    report = ScanReport(time=datetime.now(timezone.utc).isoformat(timespec="seconds"), interval=cfg["interval"])
    report.scan_time = report.time
    acct_positions = broker.account()["positions"]
    mine = [p["symbol"] for p in acct_positions if p.get("market") == profile.market and p.get("source") != "manual"
            and p.get("bot", profile.key) == profile.key]
    symbols = symbols_for(cfg, profile.market, pool, rng, extra=mine)
    execute = execute and execution.orders_enabled()
    found: list[tuple] = []
    # Carteira comprovada: cada bot dela no próprio tempo gráfico (ex.: 1h e 4h); sem carteira, o tempo gráfico do robô
    intervals = sorted(portfolio.by_interval(profile.market)) if portfolio.active(cfg, profile.market) else [cfg["interval"]]
    tasks = [(sym, itv) for itv in intervals for sym in symbols]
    exit_checked: set = set()
    for k, (sym, itv) in enumerate(tasks, start=1):
        cfg_s = {**cfg, "symbol": sym, "interval": itv}
        try:
            raw = klines(sym, itv, WINDOW + WARMUP + 1, profile.market)
            price = ticker(sym, profile.market).last
            htf_raw = mtf_raw = None
            if engine.needs_htf(cfg_s):
                htf_raw, mtf_raw = engine.htf_frames(klines, cfg_s, len(raw), profile.market)
            # indicadores calculados com o aquecimento; a análise olha os últimos 120 candles fechados (+ o candle em formação)
            df = engine.prepare(raw, cfg_s, htf_raw, mtf_raw).tail(WINDOW + 1).reset_index(drop=True)
            res = _best_signal(profile, cfg_s, df, price, int(cfg.get("scan_bots") or 3))   # só regras: não gasta IA
        except Exception as exc:  # noqa: BLE001 - um ativo sem dados não derruba a varredura
            report.notes.append(f"{sym}: sem dados ({str(exc)[:60]})")
            continue
        report.scanned += 1
        if sym == symbols[0] and report.viewed is None:
            report.viewed = res
        if cfg.get("ai_exit") and api_key and sym in mine and sym not in exit_checked and res.decision.decision != "CLOSE":
            exit_checked.add(sym)   # uma consulta de saída por ativo, mesmo com vários tempos gráficos
            _ai_exit(profile, cfg_s, df, price, api_key, report, execute, res)
        elif res.decision.decision == "CLOSE":
            if execute:
                _run_close(profile, cfg_s, res, price, report)
        elif res.decision.decision in ("BUY", "SELL") and res.check and res.check.allowed:
            found.append((abs(res.plan["score"]), sym, cfg_s, df, price, res))  # res.personality = bot que deu o sinal
        if progress:
            progress(k / len(tasks), sym if len(intervals) == 1 else f"{sym} {itv}")

    found.sort(key=lambda f: -f[0])
    entries = 0
    for idx, (_, sym, cfg_s, df, price, res) in enumerate(found):
        if entries >= int(cfg.get("scan_max_entries", 2)):
            break
        # A IA só entra com a melhor oportunidade (ou em todas, se ela puder confirmar/vetar a entrada); as demais são
        # refeitas só com regras porque o saldo disponível mudou depois da ordem anterior.
        if idx >= AI_MAX_PER_SCAN and api_key and cfg.get("ai_intervene"):
            break
        use_ai = bool(api_key) and (idx == 0 or bool(cfg.get("ai_intervene")))
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


def _ai_exit(profile: BotProfile, cfg_s: dict, df, price: float, api_key: str, report: ScanReport, execute: bool, res) -> None:
    """Consulta a IA sobre cada posição do bot neste ativo; só ela decide se a saída é antecipada (stop e alvo seguem valendo)."""
    from core import quota
    from core.strategy import market_snapshot

    platform_key = api_key == get_secret("OPENROUTER_API_KEY") and bool(current_user())
    broker = get_broker(profile.key)
    sym = cfg_s["symbol"]
    positions = [p for p in broker.account()["positions"] if p["symbol"] == sym and p.get("market", profile.market) == profile.market
                 and p.get("source") != "manual" and p.get("bot", profile.key) == profile.key]
    if not positions:
        return
    sc = advisor.scenario(df, cfg_s)
    snap = market_snapshot(df.iloc[:-1], min(int(cfg_s.get("ai_candles_context") or 60), 40))
    for pos in positions:
        if platform_key and not quota.allow():
            report.notes.append(f"{sym}: limite diário de consultas da IA atingido; posição mantida.")
            return
        if platform_key:
            quota.consume()
        ans = ai_exit.consult(ai_exit.build_context(pos, price, sc, snap, res.personality, cfg_s, sentiment.for_symbol(sym, price), events.ai_context()), api_key=api_key, model=cfg_s["ai_model"])
        report.exit_views.append({"symbol": sym, "id": pos["id"], **ans})
        if ans["acao"] == "CLOSE" and ans["confianca"] >= 50 and execute:
            broker.close_position(pos["id"], price, "IA: " + ans["motivo"][:120])
            report.executed.append({"symbol": sym, "action": "CLOSE", "status": "ENCERRADA pela IA"})


def _run_close(profile, cfg_s, res, price, report: ScanReport) -> None:
    try:
        engine.log_decision(profile.key, res)
        out = engine.execute(profile, cfg_s, res, price)
        report.executed.append({"symbol": cfg_s["symbol"], "action": "CLOSE", "status": out.get("status")})
    except Exception as exc:  # noqa: BLE001
        report.notes.append(f"{cfg_s['symbol']}: falha ao encerrar ({str(exc)[:80]})")
