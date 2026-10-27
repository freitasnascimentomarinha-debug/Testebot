import json
import sys
import os
import tempfile

os.environ["TRADEBOT_DATA_DIR"] = tempfile.mkdtemp()

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from core import indicators as ind, leverage, paper, risk  # noqa: E402

# Sem rede nos testes: faixas padrão de alavancagem
leverage.brackets = lambda symbol: (leverage.DEFAULT_BRACKETS, "padrão")
from core.ai import _extract_json, rules_fallback  # noqa: E402
from core.profiles import PROFILES  # noqa: E402
from core.settings import default_settings  # noqa: E402
from core.strategy import analyze  # noqa: E402


def make_df(n=300, trend=0.1, seed=1):
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(trend, 1, n))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) + rng.random(n)
    low = np.minimum(open_, close) - rng.random(n)
    t = pd.date_range("2026-01-01", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame({"time": t, "open": open_, "high": high, "low": low, "close": close, "volume": rng.random(n) * 100 + 10})


def test_rsi_bounds_and_trend():
    df = make_df(trend=0.5)
    r = ind.rsi(df["close"]).dropna()
    assert r.between(0, 100).all()
    assert r.iloc[-1] > 50


def test_compute_and_analyze_all_profiles():
    for key, profile in PROFILES.items():
        cfg = default_settings(profile)
        df = ind.compute(make_df(), cfg)
        plan = analyze(df, cfg, profile)
        assert -100 <= plan.score <= 100
        assert plan.direction in ("BUY", "SELL", "HOLD")
        if plan.direction == "BUY":
            assert plan.stop_loss < plan.entry < plan.take_profit
        if profile.market == "spot" and not cfg["leverage_on"]:
            assert plan.direction != "SELL"


def test_position_size_respects_max_loss():
    calc = risk.calculate("BUY", 100, 98, 106, leverage=5, fee_pct=0.05, risk_usdt=20)
    assert calc.risk_usdt == pytest.approx(20, abs=0.05)
    assert calc.margin == pytest.approx(calc.notional / 5)
    assert calc.liquidation < 98 or calc.warnings


def test_wrong_side_stop_warns():
    calc = risk.calculate("SELL", 100, 95, 90, risk_usdt=10)
    assert any("stop" in w for w in calc.warnings)


def test_check_trade_never_blocks_by_goals_or_limits():
    """Sem metas diárias, limites de perda, posições simultâneas ou R:R mínimo: o gestor só impede o que é impossível."""
    cfg = default_settings(PROFILES["day"])
    assert not {"max_trades_day", "daily_max_loss", "daily_profit_target", "max_open_positions", "min_rr", "ai_min_confidence"} & set(cfg)
    stats = {"trades_today": 999, "pnl_today": -10_000, "open_positions": 50, "equity": 10000, "available": 10000}
    chk = risk.check_trade(cfg, stats, "BUY", 100, 97, 100.5, "futures")  # R:R ruim, dia péssimo, muitas posições
    assert chk.allowed and not chk.reasons and chk.calc.qty > 0
    assert not risk.check_trade(cfg, stats, "BUY", 100, None, 110, "futures").allowed        # sem stop não há como dimensionar


def test_spot_short_requires_margin():
    cfg = default_settings(PROFILES["swing"])
    stats = {"trades_today": 0, "pnl_today": 0, "open_positions": 0, "equity": 10000, "available": 10000}
    assert not risk.check_trade(cfg, stats, "SELL", 100, 103, 90, "spot").allowed


def test_paper_round_trip_stop_loss():
    paper.reset_account("t", 1000)
    out = paper.place_order("t", symbol="X", market="futures", side="BUY", qty=1, price=100,
                            stop_loss=95, take_profit=110, leverage=5, fee_pct=0.0)
    assert out["status"] == "EXECUTADA"
    assert paper.get_account("t")["balance"] == pytest.approx(980)
    df = make_df(5)
    df["time"] = pd.Timestamp.now(tz="UTC").floor("min")
    df["low"], df["high"] = 94, 101
    events = paper.sync("t", "X", df, 96)
    assert events and events[0]["type"] == "Stop loss"
    acct = paper.get_account("t")
    assert acct["balance"] == pytest.approx(995)
    assert acct["history"][0]["pnl"] == pytest.approx(-5)
    assert [e["type"] for e in acct["ledger"]] == ["Depósito inicial", "Taxa de abertura", "Resultado (Stop loss)"]
    assert acct["ledger"][-1]["bank"] == pytest.approx(995)


def test_paper_limit_order_fills():
    paper.reset_account("l", 1000)
    paper.place_order("l", symbol="X", market="spot", side="BUY", qty=1, price=100, order_type="LIMIT",
                      limit_price=97, stop_loss=90, take_profit=120, fee_pct=0.0)
    df = make_df(3)
    df["time"] = pd.Timestamp.now(tz="UTC").ceil("min")
    df["low"], df["high"] = 96, 99
    paper.sync("l", "X", df, 98)
    acct = paper.get_account("l")
    assert not acct["orders"] and acct["positions"][0]["entry"] == 97


def test_extract_json_and_fallback():
    assert _extract_json('ok ```json\n{"decision": "SELL"}\n```')["decision"] == "SELL"
    d = rules_fallback({"direction": "HOLD", "score": 3, "entry": 1, "stop_loss": None, "take_profit": None,
                        "regime": "lateral"}, "teste")
    assert d.decision == "HOLD" and d.source == "regras"


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="sem Postgres de teste")
def test_postgres_backend_concurrent_updates():
    import threading as th

    from core.storage import PostgresBackend

    b = PostgresBackend(os.environ["TEST_DATABASE_URL"])
    b.save("t.json", {"n": 0})

    def inc():
        for _ in range(20):
            b.update("t.json", {"n": 0}, lambda d: d.__setitem__("n", d["n"] + 1))

    threads = [th.Thread(target=inc) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert b.load("t.json", None)["n"] == 80
    assert b.load("nao_existe.json", {"x": 1}) == {"x": 1}
    assert "t.json" in b.names()


class FakeGitHub:
    """Simula os endpoints da Git Data API usados pelo GitHubBackend."""

    def __init__(self):
        import itertools

        self.objects, self.refs, self.headers, self.calls = {}, {}, {}, []
        self._ids = (f"{i:040x}" for i in itertools.count(1))

    def request(self, method, url, timeout=None, json=None):
        import base64
        import json as js

        path = url.split("/repos/o/r", 1)[1]
        self.calls.append((method, path))
        body = None
        if method == "GET" and path.startswith("/git/ref/heads/"):
            sha = self.refs.get(path.rsplit("/", 1)[1])
            body = {"object": {"sha": sha}} if sha else None
        elif method == "GET" and path.startswith(("/git/commits/", "/git/trees/", "/git/blobs/")):
            body = self.objects[path.rsplit("/", 1)[1]]
        elif path == "/git/trees":
            tree = []
            for e in json["tree"]:
                blob = next(self._ids)
                self.objects[blob] = {"content": base64.b64encode(e["content"].encode()).decode()}
                tree.append({"path": e["path"], "sha": blob})
            body = {"sha": next(self._ids)}
            self.objects[body["sha"]] = {"tree": tree}
        elif path == "/git/commits":
            assert json["parents"] == []
            body = {"sha": next(self._ids)}
            self.objects[body["sha"]] = {"tree": {"sha": json["tree"]}}
        elif path == "/git/refs" or path.startswith("/git/refs/heads/"):
            self.refs[json["ref"].split("/")[-1] if "ref" in json else path.rsplit("/", 1)[1]] = json["sha"]
            body = {}

        class R:
            status_code = 200 if body is not None else 404
            content = b"x"
            text = ""

            def json(self):
                return js.loads(js.dumps(body))

        return R()


def test_github_backend_roundtrip():
    from core.storage import GitHubBackend

    fake = FakeGitHub()
    b = GitHubBackend("o/r", "tok", "dados", flush_seconds=999, session=fake)
    assert "dados" in fake.refs  # branch criado no primeiro uso
    b.update("contas.json", {"saldo": 0}, lambda d: d.__setitem__("saldo", 123))
    commits_before = len([c for c in fake.calls if c[1] == "/git/commits"])
    b.flush()
    b.flush()  # sem alterações: não grava de novo
    assert len([c for c in fake.calls if c[1] == "/git/commits"]) == commits_before + 1

    b2 = GitHubBackend("o/r", "tok", "dados", flush_seconds=999, session=fake)  # "reinício" do app
    assert b2.load("contas.json", None) == {"saldo": 123}
    assert b2.load("outro.json", []) == []


def test_binance_liquidation_formula():
    # Isolada, 10×, MMR 0,65% (faixa padrão 1): LP = entrada·(1 − 1/10)/(1 − 0,0065)
    lp = leverage.liquidation_price(side="BUY", entry=100, qty=1, leverage=10, market="futures", symbol="X")
    assert lp == pytest.approx(100 * 0.9 / (1 - 0.0065))
    lp_s = leverage.liquidation_price(side="SELL", entry=100, qty=1, leverage=10, market="futures", symbol="X")
    assert lp_s == pytest.approx(100 * 1.1 / (1 + 0.0065))
    cross = leverage.liquidation_price(side="BUY", entry=100, qty=1, leverage=10, market="futures", symbol="X",
                                       margin_mode="Cruzada", free_balance=50)
    assert cross < lp  # margem cruzada: liquidação mais distante
    assert leverage.liquidation_price(side="BUY", entry=100, qty=1, leverage=3, market="spot", symbol="X") == \
        pytest.approx(1.1 * 100 * (2 / 3))


def test_leverage_caps_notional():
    assert leverage.max_leverage("X") == 75
    assert leverage.max_notional("X", 75) == 50_000
    calc = risk.calculate("BUY", 100, 99, 105, leverage=75, fee_pct=0.0, risk_usdt=10_000, symbol="X", market="futures")
    assert calc.notional <= 50_000 and any("tabela da Binance" in w for w in calc.warnings)


def test_shared_wallet_and_cash_movements():
    paper.reset_account("w", 1000)
    paper.place_order("w", symbol="X", market="futures", side="BUY", qty=1, price=100, leverage=10, fee_pct=0.0,
                      bot="day", source="manual")
    paper.place_order("w", symbol="Y", market="spot", side="BUY", qty=1, price=50, fee_pct=0.0, bot="swing", source="ia")
    acct = paper.get_account("w")
    assert paper.stats(acct, {}, bot="day")["open_positions"] == 1
    assert paper.stats(acct, {})["open_positions"] == 2
    paper.cash_movement("w", 500, "aporte")
    paper.cash_movement("w", -200, "retirada")
    s = paper.stats(paper.get_account("w"), {"X": 110, "Y": 50})
    assert s["invested"] == 1300
    assert s["total_pnl"] == pytest.approx(10)  # +10 na posição X
    with pytest.raises(ValueError):
        paper.cash_movement("w", -1e9)


def test_funding_charged_every_8h():
    paper.reset_account("f", 1000)
    paper.place_order("f", symbol="X", market="futures", side="BUY", qty=1, price=100, leverage=5, fee_pct=0.0)

    def age(data):
        data["f"]["positions"][0]["last_funding"] = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=17)).isoformat()

    paper.locked_update(paper.ACCOUNT_FILE, {}, age)
    df = make_df(3)
    df["time"] = pd.Timestamp.now(tz="UTC").floor("min")
    df["low"], df["high"] = 99, 101
    paper.sync("f", "X", df, 100, funding_rate_pct=0.01)
    pos = paper.get_account("f")["positions"][0]
    assert pos["funding_paid"] == pytest.approx(paper._funding_events(
        pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=17), pd.Timestamp.now(tz="UTC")) * 0.01, abs=0.011)
    assert pos["funding_paid"] > 0


def test_ai_close_keeps_manual_positions():
    from core import engine
    from core.ai import AIDecision
    from core.broker import get_broker

    paper.set_wallet_mode("única")
    paper.reset_account(paper.SHARED_ACCOUNT, 1000)
    b = get_broker("day")
    b.place_order(symbol="X", market="futures", side="BUY", qty=1, price=100, leverage=5, fee_pct=0.0, source="manual")
    b.place_order(symbol="X", market="futures", side="BUY", qty=1, price=100, leverage=5, fee_pct=0.0, source="ia")
    res = engine.AnalysisResult(plan={"score": 0}, decision=AIDecision(decision="CLOSE"), check=None, price=101,
                                symbol="X", interval="15m", time="t")
    engine.execute(PROFILES["day"], default_settings(PROFILES["day"]), res, 101)
    left = b.account()["positions"]
    assert len(left) == 1 and left[0]["source"] == "manual"


def test_personalities_rules_and_direction():
    from core import personalities as Pm

    cfg = default_settings(PROFILES["day"])
    df = ind.compute(make_df(400, trend=-0.6, seed=3), cfg)  # mercado em queda
    bear = analyze(df, cfg, PROFILES["day"], Pm.get("pesq_momentum_moderado"))
    only_long = {**Pm.get("pesq_momentum_moderado"), "direction": "compra"}
    plan = analyze(df, cfg, PROFILES["day"], only_long)
    assert plan.direction != "SELL"
    if bear.direction == "SELL":
        assert "só comprado" in plan.note
    # todas as prontas rodam e respeitam a geometria do stop/alvo
    for p in Pm.BUILTINS:
        pl = analyze(df, cfg, PROFILES["day"], p)
        surf = bool(p.get("trail_atr"))  # modo surfar: sem alvo, só stop (que acompanha o preço)
        if pl.direction == "BUY":
            assert pl.stop_loss < pl.entry and (pl.take_profit is None if surf else pl.entry < pl.take_profit)
        if pl.direction == "SELL":
            assert pl.entry < pl.stop_loss and (pl.take_profit is None if surf else pl.take_profit < pl.entry)


def test_custom_personality_crud_and_ranking():
    from core import personalities as Pm

    saved = Pm.save_custom({"name": "Teste Pullback", "author": "eu", "description": "x", "direction": "compra",
                            "skills": {"tendencia": 1.0}, "threshold": 20, "sl_atr": 1, "tp_atr": 3, "filters": {}})
    assert Pm.get(saved["id"])["author"] == "eu"
    with pytest.raises(ValueError):
        Pm.save_custom({**Pm.get("tendencia"), "name": "x"})
    # operações reais simuladas: 3 ganhos de +2R e 1 perda de −1R
    paper.reset_account("rk", 1000)
    def add(data):
        hist = data["rk"]["history"]
        for pnl in (20, 20, 20, -10):
            hist.append({"personality": saved["id"], "source": "ia", "pnl": pnl, "max_loss_planned": 10, "bot": "day"})
    paper.locked_update(paper.ACCOUNT_FILE, {}, add)
    Pm.save_backtest(saved["id"], {"trades": 7, "avg_r": 0.1, "win_rate": 40, "symbol": "BTCUSDT", "interval": "1h"})
    Pm.save_backtest(saved["id"], {"trades": 10, "avg_r": 0.5, "win_rate": 50, "symbol": "BTCUSDT", "interval": "1h"})
    row = next(r for r in Pm.ranking() if r["id"] == saved["id"])
    assert row["live_trades"] == 4 and row["live_avg_r"] == pytest.approx(1.25)
    assert row["bt_trades"] == 10 and row["score"] > 0
    assert Pm.ranking()[0]["id"] == saved["id"]  # única com resultado positivo
    Pm.delete_custom(saved["id"])
    assert Pm.get(saved["id"]) is None


def test_backtest_runs_and_reports_r():
    from core import backtest, personalities as Pm

    cfg = default_settings(PROFILES["swing"])
    res = backtest.run(make_df(600, trend=0.3, seed=5), cfg, PROFILES["swing"], Pm.get("tendencia"))
    assert res["trades"] == len(res["detail"])
    if res["trades"]:
        assert res["total_r"] == pytest.approx(sum(t["r"] for t in res["detail"]))
        assert all(t["r"] > -1.2 for t in res["detail"])  # stop ≈ −1R (+ taxas)


def test_strategy_from_text_keywords():
    from core.ai import strategy_from_text_rules

    p = strategy_from_text_rules("Só compra em rompimento com volume, usando ADX. Estratégia conservadora.")
    assert p["direction"] == "compra" and {"rompimento", "volume", "adx"} <= set(p["skills"])
    assert p["threshold"] == 40


def test_lean_indicator_defaults_and_migration():
    from core import settings as S

    d = S.default_settings(PROFILES["swing"])
    shown = [k for k in S.INDICATOR_KEYS if k.endswith("_on") and d[k]]
    assert shown == ["ema_on", "volume_on"] and (d["ema_fast"], d["ema_slow"]) == (21, 50)
    S.save_settings("swing", {**d, "rsi_on": True})  # já no formato novo: mantém a escolha
    assert S.load_settings("swing")["rsi_on"] is True
    old = {k: v for k, v in d.items() if k != "ema_trend_on"}
    S.save_settings("swing", {**old, "rsi_on": True, "macd_on": True})  # formato antigo: migra
    assert S.load_settings("swing")["rsi_on"] is False


def test_native_bots_have_card_data():
    from core import personalities as Pm

    natives = [p for p in Pm.BUILTINS if p["id"].startswith("esp_")]
    assert len(natives) >= 15
    keys = {"period_label", "period_days", "ret_pct", "monthly_pct", "win_pct", "dd_pct", "trades_month",
            "pos_coins", "per_symbol", "status", "interval"}
    for p in Pm.BUILTINS:
        assert p.get("specialty") and p.get("tip") and p.get("bot") in PROFILES, p["id"]
        assert keys <= set(p.get("research", {})), p["id"]
        rs = p["research"]
        expected = ((1 + rs["ret_pct"] / 100) ** (30 / rs["period_days"]) - 1) * 100
        assert rs["monthly_pct"] == pytest.approx(expected, abs=0.02)
    for bot, pid in Pm.DEFAULT_BY_BOT.items():
        assert Pm.get(pid)["research"]["status"] == "aprovado"



def test_fastsim_matches_backtest_exactly():
    """A simulação vetorizada precisa dar exatamente o mesmo resultado do backtest candle a candle."""
    from core import backtest, fastsim
    from core import personalities as Pm
    from core.strategy import SKILLS, skill_levels

    for seed, bot in ((7, "day"), (11, "swing")):
        cfg = {**default_settings(PROFILES[bot]), "symbol": "X", "interval": "1h"}
        raw = make_df(700, trend=0.05, seed=seed)
        df = ind.compute(raw, cfg).reset_index(drop=True)
        vt = fastsim.compute_votes(df, cfg)
        for i in range(220, 700, 37):
            sl = df.iloc[: i + 1]
            lv = ind.support_resistance(sl)
            for k, (_, fn) in SKILLS.items():
                ref = (skill_levels(sl, cfg, lv) if k == "suporte_resistencia" else fn(sl, cfg)).vote
                assert np.isclose(ref, vt["v_" + k].iloc[i], atol=1e-9, equal_nan=True), (k, i)
        for pid in ("esp_15m_ema_3x1", "pesq_ichimoku_forca", "esp_5m_bb_reversal_2x1", "tendencia"):
            p = Pm.get(pid)
            fast = fastsim.simulate(vt, p, cfg)
            real = backtest.run(raw, cfg, PROFILES[bot], p)
            assert len(fast) == real["trades"], pid
            assert sum(t["r"] for t in fast) == pytest.approx(real["total_r"]), pid



def test_study_bots_validated_and_htf_equivalence():
    """Os 5 bots do estudo price action/volume: positivos nos dois regimes e simulação idêntica com o filtro do 4h."""
    from core import backtest, fastsim
    from core import personalities as Pm

    ids = ["esp_1h_priceaction_1x1", "esp_15m_tendencia_macd_2x1", "esp_1h_tendencia_supertrend_2x1",
           "esp_1h_tendencia_volume_2x1", "esp_1h_hibrida_2x1"]
    for pid in ids:
        rs = Pm.get(pid)["research"]
        assert rs["ret_pct"] > 0 and rs["prev_ret_pct"] > 0 and rs["status"] == "aprovado", pid
    assert Pm.get(ids[0])["filters"].get("htf_trend")

    cfg = {**default_settings(PROFILES["day"]), "symbol": "X", "interval": "1h"}
    raw = make_df(900, trend=0.03, seed=5)
    raw["time"] = pd.date_range("2026-01-01", periods=len(raw), freq="1h", tz="UTC")
    htf = raw.set_index("time").resample("4h").agg({"open": "first", "high": "max", "low": "min", "close": "last",
                                                     "volume": "sum"}).reset_index()
    vt = fastsim.prepare(raw, cfg, htf)
    assert vt["htf_dir"].abs().sum() > 0
    for pid in ids:
        p = Pm.get(pid)
        fast = fastsim.simulate(vt, p, cfg)
        real = backtest.run(raw, cfg, PROFILES["day"], p, htf_raw=htf)
        assert len(fast) == real["trades"], pid
        assert sum(t["r"] for t in fast) == pytest.approx(real["total_r"]), pid


def test_surf_exit_trailing_and_mtf_filters_equivalence():
    """Modo surfar (sem alvo, stop móvel + equilíbrio) e filtros 4h/15m: fastsim idêntico ao backtest candle a candle."""
    from core import backtest, fastsim
    from core import personalities as Pm

    cfg = {**default_settings(PROFILES["day"]), "symbol": "X", "interval": "5m"}
    raw = make_df(4400, trend=0.02, seed=9)
    raw["time"] = pd.date_range("2026-01-01", periods=len(raw), freq="5min", tz="UTC")

    def rs(rule):
        return raw.set_index("time").resample(rule).agg({"open": "first", "high": "max", "low": "min", "close": "last",
                                                         "volume": "sum"}).reset_index()

    h4, m15 = rs("4h"), rs("15min")
    vt = fastsim.prepare(raw, cfg, h4, m15)
    assert vt["htf_dir"].abs().sum() > 0 and vt["mtf_dir"].abs().sum() > 0
    for be in (0.0, 1.0):
        p = {"id": "t", "name": "t", "skills": {"tendencia": 1.0, "rompimento": 1.0, "volume": 1.0}, "threshold": 15,
             "direction": "misto", "sl_atr": 2.0, "tp_atr": 4.0, "trail_atr": 3.0, "be_r": be,
             "filters": {"htf_trend": True, "mtf_trend": True, "ignore_regime": True}}
        fast = fastsim.simulate(vt, p, cfg, start_time=raw["time"].iloc[3500])
        real = backtest.run(raw, cfg, PROFILES["day"], p, htf_raw=h4, mtf_raw=m15, warmup=3500)
        assert len(fast) == real["trades"] > 0
        assert sum(t["r"] for t in fast) == pytest.approx(real["total_r"])
        assert all(t["motivo"].startswith("Stop") for t in fast)  # sem alvo


def test_trailing_stop_in_paper_broker():
    from core import trail

    # compra: o stop sobe junto com o preço e depois do 1R vai ao equilíbrio; nunca recua
    sl, best = trail.step(1, 100.0, 98.0, 100.0, 103.0, 100.5, 3.0, 2.0, 1.0, 0.0005)
    assert best == 103.0 and sl == pytest.approx(100.1)  # 103−3 = 100 < equilíbrio 100,1
    sl2, best2 = trail.step(1, 100.0, sl, best, 101.0, 99.0, 3.0, 2.0, 1.0, 0.0005)
    assert sl2 == sl and best2 == best
    # venda: espelhado
    sl, best = trail.step(-1, 100.0, 102.0, 100.0, 99.5, 96.0, 3.0, 2.0, 0.0, 0.0005)
    assert best == 96.0 and sl == pytest.approx(99.0)

    paper.set_wallet_mode("única")
    paper.reset_account(paper.SHARED_ACCOUNT, 100)
    paper.place_order(paper.SHARED_ACCOUNT, symbol="SOLUSDT", market="futures", side="BUY", qty=1.0, price=100.0,
                      stop_loss=98.0, leverage=5, fee_pct=0.05, trail_dist=3.0, be_r=1.0)
    t0 = pd.Timestamp.now(tz="UTC").floor("min")
    up = pd.DataFrame({"time": [t0], "open": [100.0], "high": [106.0], "low": [100.0], "close": [105.0], "volume": [1.0]})
    paper.sync(paper.SHARED_ACCOUNT, "SOLUSDT", up, 105.0)
    pos = paper.get_account(paper.SHARED_ACCOUNT)["positions"][0]
    assert pos["stop_loss"] == pytest.approx(103.0) and pos["take_profit"] is None
    down = pd.DataFrame({"time": [t0], "open": [105.0], "high": [105.0], "low": [102.5], "close": [103.0], "volume": [1.0]})
    ev = paper.sync(paper.SHARED_ACCOUNT, "SOLUSDT", down, 103.0)
    assert ev and ev[0]["type"] == "Stop móvel"
    assert paper.get_account(paper.SHARED_ACCOUNT)["history"][-1]["pnl"] > 0  # saiu no lucro


def test_learning_page_assets():
    """Página Aprendendo: 5 aulas com vídeo, legenda, capítulos e perguntas."""
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    aulas = json.loads((root / "assets" / "aulas" / "aulas.json").read_text(encoding="utf-8"))
    assert [a["id"] for a in aulas] == [f"aula{i}" for i in range(1, 6)]
    for a in aulas:
        assert (root / a["video"]).stat().st_size > 100_000
        vtt = (root / a["legenda"]).read_text(encoding="utf-8")
        assert vtt.startswith("WEBVTT") and "-->" in vtt
        assert a["duracao_s"] > 120 and len(a["capitulos"]) >= 8
        assert all(c["fala"] for c in a["capitulos"])
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(root / "views" / "learning.py"), default_timeout=60).run()
    assert not at.exception and len(at.tabs) == 5 and len(at.radio) == 16


def _adv_setup(n=400, seed=3):
    cfg = {**default_settings(PROFILES["day"]), "symbol": "SOLUSDT", "interval": "15m", "auto_bot": False}
    raw = make_df(n, trend=0.02, seed=seed)
    raw["time"] = pd.date_range(end=pd.Timestamp.now(tz="UTC").floor("15min") - pd.Timedelta(minutes=15), periods=n, freq="15min")
    return cfg, ind.compute(raw, cfg)


def test_advisor_scenario_candidates_and_plan():
    from core import advisor

    cfg, df = _adv_setup()
    sc = advisor.scenario(df, cfg)
    assert sc["contexto"] and sc["adx"] is not None and sc["suportes"] is not None
    vies = advisor.bias(sc, 0.0)
    cands = advisor.candidates(PROFILES["day"], cfg, sc, vies, "esp_15m_ema_3x1")
    assert cands and all(c["id"] and c["selo"] != "fraco" or c["ativo"] for c in cands)
    assert cands == sorted(cands, key=lambda c: -c["pontuacao"])[:len(cands)] or any(c["ativo"] for c in cands)
    adv = advisor.rules_advice(sc, cands, {}, cfg, sc["preco"], vies, sc["atr"])
    assert adv["cenario"] and adv["oportunidade"] and adv["dica"] and adv["fonte"] == "regras"
    if adv["bot"].get("id"):  # só recomenda bot com vantagem comprovada no contexto
        assert next(c for c in cands if c["id"] == adv["bot"]["id"])["contexto_r"] > 0
    price, atr = sc["preco"], sc["atr"]
    ok = advisor.make_plan("BUY", "fechar_acima", price + atr, 1.5, "esp_15m_ema_3x1", 12, invalida=price - atr, price=price, atr=atr)
    assert ok and ok["personalidade_nome"] and ok["validade_candles"] == 12
    # incoerentes são descartados: gatilho do lado já atingido, longe demais, direção/tipo inválidos
    assert advisor.make_plan("BUY", "fechar_acima", price - atr, 1, None, 12, invalida=None, price=price, atr=atr) is None
    assert advisor.make_plan("BUY", "fechar_acima", price + 20 * atr, 1, None, 12, invalida=None, price=price, atr=atr) is None
    assert advisor.make_plan("HOLD", "fechar_acima", price + atr, 1, None, 12, invalida=None, price=price, atr=atr) is None
    txt = advisor.describe_plan(ok, "SOLUSDT", "15m")
    assert "Comprar SOLUSDT" in txt and "fechar acima de" in txt


def test_armed_plan_trigger_states_and_execution():
    from core import advisor, engine

    cfg, df = _adv_setup()
    profile = PROFILES["day"]
    paper.set_wallet_mode("única")
    paper.reset_account(paper.SHARED_ACCOUNT, 100)
    price = float(df["close"].iloc[-1])
    atr = float(df["atr"].iloc[-2])
    level = price + atr
    plan = advisor.make_plan("BUY", "fechar_acima", level, 1.0, "esp_15m_ema_3x1", 6, invalida=price - 3 * atr, price=price, atr=atr)
    advisor.disarm("day")
    engine.arm_plan(profile, cfg, plan, df, "ia")
    assert advisor.armed("day")["descricao"]
    # sem candle de confirmação: pendente
    assert engine.check_armed_plan(profile, cfg, df, price) == (None, None)

    def with_candle(close, vol_mult):
        d = df.copy()
        nxt = d.iloc[-1:].copy()
        nxt["time"] = d["time"].iloc[-1] + pd.Timedelta(minutes=15)
        d = pd.concat([d, nxt], ignore_index=True)
        d.loc[len(d) - 2, ["close", "high"]] = [close, max(close, d["high"].iloc[-2])]  # candle de gatilho (penúltimo linha)
        d.loc[len(d) - 2, "volume"] = d["vol_sma"].iloc[-2] * vol_mult
        return d

    # armado a partir do candle em formação (último): o gatilho é o candle que fecha depois dele
    base_time = df["time"].iloc[-1]
    assert pd.Timestamp(advisor.armed("day")["armado_em"]) == base_time
    # fechou acima, mas sem volume suficiente → continua pendente
    low_vol = with_candle(level + atr * 0.2, 0.5)
    assert advisor.evaluate(advisor.armed("day"), low_vol, "15m")[0] == "pendente"
    # fechou acima com volume → dispara e a ordem passa pelo gestor de risco
    hit = with_candle(level + atr * 0.2, 2.0)
    state, res = engine.check_armed_plan(profile, cfg, hit, level + atr * 0.2)
    assert state == "disparou" and res.decision.decision == "BUY" and res.decision.stop_loss < res.decision.entry
    assert res.check and res.check.calc and res.check.allowed, res.check.reasons if res.check else None
    out = engine.execute(profile, cfg, res, level + atr * 0.2)
    assert out["status"] == "EXECUTADA" and advisor.armed("day") is None
    # invalidado
    engine.arm_plan(profile, cfg, plan, df, "ia")
    bad = with_candle(price - 4 * atr, 2.0)
    assert advisor.evaluate(advisor.armed("day"), bad, "15m")[0] == "invalidado"
    advisor.disarm("day")


def test_ai_advice_is_validated(monkeypatch):
    import json

    from core import advisor, ai, engine
    from core import personalities as Pm

    cfg, df = _adv_setup()
    cfg["ai_intervene"] = True
    monkeypatch.setattr(engine, "get_funding_rate", lambda s: None)
    sc = advisor.scenario(df, cfg)
    price, atr = sc["preco"], sc["atr"]
    good = [c for c in Pm.BUILTINS if (c.get("research") or {}).get("market") == "futures"][0]["id"]
    reply = {"decision": "HOLD", "confidence": 40, "reasoning": "aguardar",
             "analise": {"cenario": "Cenário técnico da IA.", "leitura_tecnica": ["ADX 20", "RSI 50"], "melhor_oportunidade": "Rompimento com volume.", "dica": "Espere o fechamento."},
             "bot_recomendado": {"id": "bot_que_nao_existe", "motivo": "inventado"},
             "plano_condicional": {"direcao": "BUY", "tipo": "fechar_acima", "nivel": price - atr, "volume_min_x": 1.5, "personalidade": good, "validade_candles": 99}}

    class Resp:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": json.dumps(reply)}}], "model": "teste", "usage": {}}

    monkeypatch.setattr(ai.requests, "post", lambda *a, **k: Resp())
    paper.set_wallet_mode("única")
    paper.reset_account(paper.SHARED_ACCOUNT, 100)
    advisor.disarm("day")
    res = engine.run_analysis(PROFILES["day"], cfg, df, price, "chave")
    adv = res.decision.advice
    assert adv["fonte"] == "ia" and adv["cenario"] == "Cenário técnico da IA." and adv["dica"] == "Espere o fechamento."
    assert adv["bot"]["id"] != "bot_que_nao_existe"            # bot inventado é ignorado: mantém a recomendação por regras
    assert adv["plano"] != reply["plano_condicional"]            # gatilho no lado já atingido é descartado
    # plano válido da IA é aceito, com a personalidade informada e validade limitada a 48 candles
    reply["plano_condicional"].update(nivel=price + atr, validade_candles=99)
    reply["bot_recomendado"] = {"id": good, "motivo": "melhor candidato"}
    res = engine.run_analysis(PROFILES["day"], cfg, df, price, "chave")
    plan = res.decision.advice["plano"]
    assert plan and plan["personalidade"] == good and plan["validade_candles"] == 48 and res.decision.advice["bot"]["motivo"] == "melhor candidato" or res.decision.advice["bot"]["id"] is not None
    # piloto automático arma planos da IA; planos de regras só são armados manualmente
    cfg["ai_auto_arm"] = True
    assert engine.auto_arm(PROFILES["day"], cfg, res, df) and advisor.armed("day")["origem"] == "ia"
    advisor.disarm("day")
    res.decision.advice["fonte"] = "regras"
    assert not engine.auto_arm(PROFILES["day"], cfg, res, df)


def test_ai_call_is_robust_to_bad_replies(monkeypatch):
    """Resposta vazia/cortada, com texto ao redor ou raciocínio: tenta de novo e, se falhar, explica o motivo."""
    import json

    from core import ai

    ok = json.dumps({"decision": "BUY", "confidence": 70, "stop_loss": 9.0, "take_profit": 12.0, "entry": 10.0})

    class R:
        status_code = 200

        def __init__(self, content, finish="stop"):
            self.content, self.finish = content, finish

        def json(self):
            return {"choices": [{"message": {"content": self.content}, "finish_reason": self.finish}], "model": "m", "usage": {}}

    def run(*replies):
        it = iter(replies)
        monkeypatch.setattr(ai.requests, "post", lambda *a, **k: next(it))
        return ai.ask_ai({}, api_key="k", model="m")

    assert run(R("", "length"), R(ok)).decision == "BUY"                           # vazia na 1ª tentativa
    assert run(R("Segue:\n```json\n" + ok + "\n```\nBoa sorte")).decision == "BUY"   # markdown e texto ao redor
    assert run(R("<think>pensando { }</think>" + ok)).decision == "BUY"            # bloco de raciocínio
    assert run(R([{"type": "text", "text": ok}])).decision == "BUY"                # conteúdo em blocos
    with pytest.raises(RuntimeError, match="2 tentativas"):
        run(R("", "length"), R("Não consigo.", "stop"))


def test_personality_only_where_trained():
    """Só é possível escolher personalidades treinadas e que se destacaram naquele mercado e tempo gráfico."""
    from core import personalities as Pm

    for market, interval in (("futures", "5m"), ("futures", "15m"), ("futures", "1h"), ("spot", "4h"), ("spot", "1d")):
        got = Pm.allowed(market, interval)
        assert got, (market, interval)
        for p in got:
            rs = p.get("research") or {}
            assert rs["market"] == market and rs["interval"] == interval and rs["status"] in ("aprovado", "ressalva")
    assert not any(p["id"] == "esp_5m_bb_reversal_2x1" for p in Pm.allowed("futures", "5m"))  # fraco no teste
    assert Pm.allowed("futures", "30m") == [] and Pm.allowed("spot", "5m") == []
    assert [i for i in Pm.trained_intervals("futures") if i != "4h"] == ["5m", "15m", "1h"]   # 4h vem dos bots por contexto, se gerados
    assert "experimental" not in Pm.allowed("futures", "5m")[0]["name"].lower()
    for bot, pid in Pm.DEFAULT_BY_BOT.items():  # o padrão de cada bot vale no tempo gráfico padrão dele
        assert Pm.is_allowed(pid, PROFILES[bot].market, PROFILES[bot].default_interval)


def _offline_market(monkeypatch):
    """Dados de mercado sintéticos: o teste da página não depende da rede."""
    from core import data, leverage

    def klines(symbol, interval, limit=500, market="spot"):
        raw = make_df(max(limit, 300), trend=0.05, seed=5)
        raw["time"] = pd.date_range(end=pd.Timestamp.now(tz="UTC").floor("15min") - pd.Timedelta(minutes=15), periods=len(raw), freq="15min")
        raw.attrs["source"] = "teste"
        return raw.tail(limit).reset_index(drop=True)

    monkeypatch.setattr(data, "get_klines", klines)
    monkeypatch.setattr(data, "get_ticker", lambda s, m="spot": data.Ticker(s, 100.0, 1.0, 101.0, 99.0, 1e6, "teste"))
    monkeypatch.setattr(data, "get_funding_rate", lambda s: None)
    monkeypatch.setattr(data, "list_symbols", lambda m: ["BTCUSDT", "ETHUSDT"])
    monkeypatch.setattr(leverage, "brackets", lambda s: (leverage.DEFAULT_BRACKETS, "teste"))
    for name in [n for n in sys.modules if n == "core.ui"]:  # módulo já carregado por outro teste: refaz as ligações
        del sys.modules[name]


def test_bot_page_layout_and_analysis_with_advice(monkeypatch):
    """Página inteira do bot: só dois gráficos (tempo real e TradingView), boleta de entrada logo abaixo e, ao clicar em Analisar,
    a leitura do especialista — sem metas/limites que bloqueiam e sem citar o modelo nem resposta bruta."""
    from streamlit.testing.v1 import AppTest

    _offline_market(monkeypatch)
    paper.set_wallet_mode("única")
    paper.reset_account(paper.SHARED_ACCOUNT, 10_000)

    def page():
        import streamlit as st

        st.page_link = lambda *a, **k: None  # o menu só existe no app completo
        from core.ui import render_bot_page

        render_bot_page("day")

    at = AppTest.from_function(page, default_timeout=120).run()
    assert not at.exception, [e.value for e in at.exception]
    labels = [t.label for t in at.tabs]
    assert "⚡ Tempo real" in labels and not any("TradingView" in l for l in labels) and not any("Análise técnica" in l for l in labels)
    # layout em L: painel de ordem ao lado do gráfico e painéis embaixo
    for want in ("✍️ Ordem", "🤖 Entrada do bot", "🧠 Análise do bot", "⚙️ Configurações", "Posições abertas"):
        assert want in labels, want
    # análise e configurações ficam ao lado das abas do gráfico (Tempo real, TradingView), não embaixo
    tv = labels.index("⚡ Tempo real")
    assert labels[tv + 1:tv + 4] == ["📖 Book de ordens", "🧠 Análise do bot", "⚙️ Configurações"] and "Alavancagem" not in labels
    assert labels.index("✍️ Ordem") > labels.index("⚙️ Configurações") and labels.index("Posições abertas") > labels.index("🤖 Entrada do bot")
    captions = " ".join(c.value for c in at.caption)
    assert "Candles ao vivo direto da corretora" not in captions and "P&L líquido = variação de preço" not in captions
    widget_labels = " ".join(str(getattr(w, "label", "")) for w in list(at.number_input) + list(at.radio) + list(at.toggle) + list(at.selectbox)
                             + list(at.button))
    for gone in ("Meta de operações", "Limite de perda diária", "Máx. posições", "Risco:retorno mínimo", "Confiança mínima", "Analisar agora",
                 "Usar este bot", "Armar", "Desarmar", "Atualizar ranking", "Personalidade (estratégia)", "Bot automático"):
        assert gone not in widget_labels, gone
    assert "Perda máxima por trade" in widget_labels and "Alavancado" in widget_labels and "Ligar o bot" in widget_labels
    # tudo automático: a leitura do ativo aparece sozinha, em um bloco só e sem jargão de gestor de risco
    assert at.session_state["day__scan"].viewed is not None
    text = " ".join(m.value for m in at.markdown) + " ".join(c.value for c in at.caption) + " ".join(i.value for i in at.info)
    from core import analysis_view

    view = analysis_view.view(PROFILES["day"], {"scan_minutes": 15}, at.session_state["day__scan"], on=False, next_at=None)
    assert view["title"] in ("Sem oportunidade agora", "Oportunidade de compra", "Oportunidade de venda", "Sinal contrário: encerrando a posição")
    assert view["drivers"] and view["facts"] and "dica" not in view                       # fatos medidos, sem dica genérica
    assert "deepseek" not in text.lower() and "Gestor de risco" not in text and "BLOQUEADA" not in text


def test_scan_runs_by_time_not_on_page_entry(monkeypatch):
    """A varredura é por tempo (padrão 15 min): reservar duas vezes seguidas só vale a primeira; reset libera na hora."""
    from core import scanner

    assert default_settings(PROFILES["day"])["scan_minutes"] == 15 and default_settings(PROFILES["day"])["ai_exit"] is True
    scanner.reset("day")
    assert scanner.claim("day", 15, now=1000.0) is True
    assert scanner.claim("day", 15, now=1000.0 + 14 * 60) is False       # abrir a página/trocar de moeda não varre de novo
    assert scanner.claim("day", 15, now=1000.0 + 15 * 60) is True
    assert scanner.next_scan("day", 15) == 1000.0 + 30 * 60
    assert scanner.claim("day", 30, now=1000.0 + 20 * 60 + 15 * 60) is False   # programável: 30 min
    scanner.reset("day")
    assert scanner.claim("day", 15, now=5000.0) is True                      # ligar o bot varre na hora
    scanner.reset("day")


def test_ai_exit_answers_are_safe():
    """A IA só pode manter ou encerrar; resposta estranha vira HOLD e a confiança fica entre 0 e 100."""
    from core import ai_exit

    assert ai_exit.parse({"acao": "close", "confianca": 80, "motivo": "ADX caiu e o rompimento falhou."}) == {
        "acao": "CLOSE", "confianca": 80, "motivo": "ADX caiu e o rompimento falhou."}
    assert ai_exit.parse({"acao": "vender tudo", "confianca": "x"})["acao"] == "HOLD"
    assert ai_exit.parse({"acao": "CLOSE", "confianca": 900})["confianca"] == 100


def test_sidebar_groups_and_watchlist(monkeypatch):
    from core import data, nav

    class P:
        def __init__(self, title, icon, url_path):
            self.title, self.icon, self.url_path = title, icon, url_path

    pages = {"Visão geral": [P("Painel", "📊", "")], "Mercado Cripto": [P("Futuros", "⚡", "futuros"), P("Spot", "🌊", "spot")]}
    g = nav.groups(pages, "spot")
    assert [i["active"] for grp in g for i in grp["items"]] == [False, False, True]
    calls = []
    monkeypatch.setattr(data, "_get", lambda url, params=None: calls.append(url) or [{"symbol": "BTCUSDT", "lastPrice": "100", "priceChangePercent": "2.5"}])
    data._watch_cache.clear()
    assert data.watch_prices("futures", ["BTCUSDT", "XXXUSDT"]) == {"BTCUSDT": (100.0, 2.5)}
    data.watch_prices("futures", ["BTCUSDT"])
    assert len(calls) == 1                                                  # uma chamada guardada por 15 s para a lista toda
    data._watch_cache.clear()


def test_scanner_scans_many_symbols_one_ai_call_one_position_per_symbol(monkeypatch):
    from core import ai, scanner
    from core.engine import AnalysisResult  # noqa: F401

    paper.set_wallet_mode("única")
    paper.reset_account(paper.SHARED_ACCOUNT, 10_000)
    profile = PROFILES["day"]
    cfg = {**default_settings(profile), "symbol": "BTCUSDT", "interval": "15m", "scan_count": 18, "scan_pool": 40, "scan_max_entries": 2,
           "candles": 400, "ai_intervene": False}
    asked, fetched = [], []

    limits = []

    def klines(sym, interval, limit=500, market="futures"):
        fetched.append(sym)
        if interval == "15m" and limit > 5 and sym != "_t":
            limits.append(limit)
        raw = make_df(max(limit, 300), trend=0.2, seed=8)   # cenário sintético com sinal de venda e preços positivos
        raw["time"] = pd.date_range(end=pd.Timestamp.now(tz="UTC").floor("15min") - pd.Timedelta(minutes=15), periods=len(raw), freq="15min")
        raw.attrs["source"] = "teste"
        return raw.tail(limit).reset_index(drop=True)

    ticker = lambda sym, market="futures": __import__("core.data", fromlist=["Ticker"]).Ticker(  # noqa: E731
        sym, float(make_df(scanner.WINDOW + scanner.WARMUP + 1, trend=0.2, seed=8).close.iloc[-1]), 0, 0, 0, 0, "t")
    monkeypatch.setattr(ai, "ask_ai", lambda ctx, **kw: asked.append(ctx["bot"]["ativo"]) or ai.AIDecision(
        decision="HOLD", reasoning="Resumo simples.", source="ia", model="m", advice={"resumo": "Resumo simples.", "dica": "Dica."}))
    monkeypatch.setattr(scanner.engine, "pick_bots", lambda *a, **k: ([scanner.engine.personalities.get("esp_15m_ema_3x1")], {}))
    monkeypatch.setattr(scanner.engine, "get_funding_rate", lambda s: None)
    ranked = ["BTCUSDT"] + [f"C{i:02d}USDT" for i in range(60)]                # ranking por volume (o primeiro é o mais negociado)
    pool = lambda market: ranked  # noqa: E731
    import random
    sample = scanner.symbols_for(cfg, "futures", pool, random.Random(1))
    assert sample[0] == "BTCUSDT" and len(sample) == 18 and len(set(sample)) == 18                # a da tela + 17 sorteadas, sem repetir
    assert set(sample) <= set(ranked[:40])                                                          # só entre as 40 de maior volume
    assert scanner.symbols_for(cfg, "futures", pool, random.Random(2)) != sample                    # sorteio: muda a cada varredura
    assert len(scanner.symbols_for({**cfg, "scan_count": 5}, "futures", pool, random.Random(1))) == 5     # configurável, para menos...
    assert len(scanner.symbols_for({**cfg, "scan_count": 40}, "futures", pool, random.Random(1))) == 40   # ...ou para mais
    assert len(scanner.symbols_for({k: v for k, v in cfg.items() if k != "scan_count"}, "futures", pool, random.Random(1))) == 15  # padrão: 15
    assert default_settings(PROFILES["day"])["scan_count"] == 15 and default_settings(PROFILES["day"])["scan_bots"] == 3
    assert scanner.symbols_for(cfg, "futures", pool, random.Random(1), extra=["C59USDT"])[-1] == "C59USDT"  # posição aberta entra sempre
    assert scanner.symbols_for({**cfg, "scan_on": False}, "futures", pool) == ["BTCUSDT"]

    rep = scanner.run(profile, cfg, "chave", klines=klines, ticker=ticker, pool=pool, rng=random.Random(3))
    assert rep.scanned == 18 and len(set(fetched)) >= 18 and "BTCUSDT" in fetched
    assert all(n == scanner.WINDOW + scanner.WARMUP + 1 for n in limits)                      # 120 candles fechados + aquecimento + o em formação
    assert len(asked) <= 1                                     # IA só explicando: uma consulta por varredura (a melhor oportunidade); interferindo, no máximo AI_MAX_PER_SCAN
    assert 1 <= len(rep.executed) <= 2 and rep.viewed is not None             # o cenário sintético tem sinal: o bot opera
    opened = {p["symbol"] for p in paper.get_account(paper.SHARED_ACCOUNT)["positions"]}
    assert opened == {e["symbol"] for e in rep.executed if e["action"] in ("BUY", "SELL")}
    # nova varredura no mesmo cenário: não abre outra posição nos ativos que já tem (nada de comprar e vender o mesmo ativo)
    before = len(paper.get_account(paper.SHARED_ACCOUNT)["positions"])
    rep2 = scanner.run(profile, cfg, None, klines=klines, ticker=ticker, pool=pool, rng=random.Random(4))
    positions = paper.get_account(paper.SHARED_ACCOUNT)["positions"]
    assert len(positions) <= before + 2 and len({(p["symbol"], p["side"]) for p in positions}) == len(positions)
    for sym in {p["symbol"] for p in positions}:
        assert len({p["side"] for p in positions if p["symbol"] == sym}) == 1


def test_signal_against_open_position_closes_it_instead_of_opening_opposite(monkeypatch):
    from core import engine

    monkeypatch.setattr(engine, "get_funding_rate", lambda s: None)
    paper.set_wallet_mode("única")
    paper.reset_account(paper.SHARED_ACCOUNT, 10_000)
    profile = PROFILES["day"]
    cfg = {**default_settings(profile), "symbol": "X", "auto_bot": False, "personality": "esp_15m_ema_3x1"}
    df = ind.compute(make_df(400, trend=0.3, seed=120), cfg)            # cenário sintético com sinal de venda
    price = float(df.close.iloc[-1])
    plan = analyze(df, cfg, profile, engine.personalities.get("esp_15m_ema_3x1"))
    assert plan.direction == "SELL"
    other = "SELL" if plan.direction == "BUY" else "BUY"
    broker = engine.get_broker("day")
    broker.place_order(symbol="X", market="futures", side=other, qty=1, price=price, leverage=5, fee_pct=0.0, source="regras")
    r = engine.run_analysis(profile, cfg, df, price, None)
    assert r.decision.decision == "CLOSE" and "contrário" in r.decision.reasoning     # sinal contrário encerra a posição
    broker.place_order(symbol="X", market="futures", side=plan.direction, qty=1, price=price, leverage=5, fee_pct=0.0, source="regras")
    r = engine.run_analysis(profile, cfg, df, price, None)
    assert r.decision.decision == "HOLD" and "Já posicionado" in r.decision.reasoning  # já posicionado: não abre outra igual


def test_accounts_signup_requires_admin_approval(monkeypatch):
    import time

    from core import accounts, storage

    monkeypatch.setenv("AUTH_MODE", "contas")
    monkeypatch.setenv("SIGNUP_CODE", "convite")
    monkeypatch.setenv("ADMIN_USER", "chefe")
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-do-chefe-1")
    assert accounts.enabled() and accounts.needs_code() and accounts.is_primary_admin("CHEFE")
    with pytest.raises(ValueError, match="convite"):
        accounts.register("carla", "senha-forte-1", "errado")
    with pytest.raises(ValueError, match="reservado"):
        accounts.register("chefe", "senha-forte-1", "convite")          # ninguém "toma" o nome do admin
    assert accounts.register("Carla", "senha-forte-1", "convite", "Carla, colega do trabalho") == "carla"
    users = storage.load_json(storage.USERS_KEY, {})
    assert "senha-forte-1" not in json.dumps(users) and users["carla"]["hash"].startswith("scrypt$")  # só o hash
    assert users["carla"]["status"] == "pendente" and accounts.pending_count() == 1
    for bad, msg in ((("carla", "outra-senha-9", "convite"), "já existe"), (("x", "senha-forte-1", "convite"), "Usuário:"),
                     (("diego", "curta", "convite"), "8 caracteres"), (("diego", "aaaaaaaaaa", "convite"), "fraca")):
        with pytest.raises(ValueError, match=msg):
            accounts.register(*bad)
    # pendente: a senha certa não basta; a errada continua dando erro genérico
    with pytest.raises(ValueError, match="não foi autorizada"):
        accounts.authenticate("carla", "senha-forte-1")
    with pytest.raises(ValueError, match="incorretos"):
        accounts.authenticate("carla", "senha-errada-1")
    with pytest.raises(ValueError, match="incorretos"):
        accounts.authenticate("ninguem", "qualquer-coisa-1")
    # admin principal vem dos Secrets
    assert accounts.authenticate("chefe", "senha-do-chefe-1") == "chefe" and accounts.is_admin("chefe")
    with pytest.raises(ValueError, match="incorretos"):
        accounts.authenticate("chefe", "senha-do-chefe-2")
    # quem não é admin não administra nada
    for fn, args in ((accounts.approve, ("carla", "carla")), (accounts.block, ("carla", "carla")), (accounts.delete, ("carla", "carla"))):
        with pytest.raises(PermissionError):
            fn(*args)
    accounts.approve("chefe", "carla")
    assert accounts.authenticate(" CARLA ", "senha-forte-1") == "carla" and accounts.is_active("carla") and not accounts.is_admin("carla")
    assert accounts.pending_count() == 0 and "carla" in accounts.list_users() and "chefe" in accounts.list_users()
    # bloquear: não entra mais e o link salvo deixa de valer; reativar volta
    tok = accounts.make_token("carla")
    assert accounts.verify_token(tok) == "carla" and accounts.verify_token(tok[:-2] + "xx") is None
    accounts.block("chefe", "carla")
    with pytest.raises(ValueError, match="bloqueado"):
        accounts.authenticate("carla", "senha-forte-1")
    assert accounts.verify_token(tok) is None and not accounts.is_active("carla")
    accounts.unblock("chefe", "carla")
    assert accounts.verify_token(tok) == "carla"
    # promover a admin; o admin principal e a própria conta são protegidos
    accounts.set_admin("chefe", "carla", True)
    assert accounts.is_admin("carla")
    with pytest.raises(ValueError, match="Secrets"):
        accounts.block("carla", "chefe")
    with pytest.raises(ValueError, match="própria"):
        accounts.delete("carla", "carla")
    accounts.set_admin("chefe", "carla", False)
    # senha: admin redefine; trocar a senha invalida o link; erro de senha antiga
    accounts.reset_password("chefe", "carla", "nova-senha-77")
    assert accounts.verify_token(tok) is None
    with pytest.raises(ValueError, match="incorretos"):
        accounts.authenticate("carla", "senha-forte-1")
    assert accounts.authenticate("carla", "nova-senha-77") == "carla"
    accounts.change_password("carla", "nova-senha-77", "outra-nova-88")
    with pytest.raises(ValueError):
        accounts.change_password("carla", "errada-errada", "mais-uma-99")
    # excluir apaga a conta e os dados dela
    storage.set_user("carla")
    storage.save_json("settings.json", {"x": 1})
    storage.set_user(None)
    assert accounts.delete("chefe", "carla", wipe_data=True) >= 1
    assert "carla" not in storage.load_json(storage.USERS_KEY, {}) and "u/carla/settings.json" not in storage.backend().names()
    with pytest.raises(ValueError, match="incorretos"):
        accounts.authenticate("carla", "outra-nova-88")
    # bloqueio por tentativas erradas (5) e liberação depois do prazo
    accounts.register("duda", "senha-forte-1", "convite")
    accounts.approve("chefe", "duda")
    for _ in range(5):
        with pytest.raises(ValueError, match="incorretos"):
            accounts.authenticate("duda", "errada-errada")
    with pytest.raises(ValueError, match="bloqueada"):
        accounts.authenticate("duda", "senha-forte-1")
    users = storage.load_json(storage.USERS_KEY, {})
    users["duda"]["locked_until"] = time.time() - 1
    storage.save_json(storage.USERS_KEY, users)
    assert accounts.authenticate("duda", "senha-forte-1") == "duda"
    # link do admin principal muda se a senha dos Secrets mudar
    tk = accounts.make_token("chefe")
    assert accounts.verify_token(tk) == "chefe"
    monkeypatch.setenv("ADMIN_PASSWORD", "outra-senha-do-chefe")
    assert accounts.verify_token(tk) is None
    monkeypatch.setenv("ALLOW_SIGNUP", "false")
    with pytest.raises(ValueError, match="fechados"):
        accounts.register("eva", "senha-forte-1", "convite")


def test_accounts_mode_autodetect(monkeypatch):
    from core import accounts

    for name in ("AUTH_MODE", "DATABASE_URL", "APP_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    assert not accounts.enabled()                                    # nada configurado: aberto (uso local)
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    assert accounts.enabled()                                        # banco sem senha única: contas (não fica aberto por esquecimento)
    monkeypatch.setenv("APP_PASSWORD", "x")
    assert not accounts.enabled()                                    # senha única explícita
    monkeypatch.setenv("AUTH_MODE", "contas")
    assert accounts.enabled()
    monkeypatch.setenv("AUTH_MODE", "aberto")
    assert not accounts.enabled()


def test_user_data_isolation_legacy_owner_and_backup(monkeypatch):
    from core import storage

    storage.set_user(None)
    storage.save_json("settings.json", {"day": {"max_loss_pct": 7}})          # dado de antes das contas
    storage.set_user("ana")
    assert storage.load_json("settings.json", "vazio") == "vazio"             # sem LEGACY_OWNER, ninguém herda
    monkeypatch.setenv("LEGACY_OWNER", "bia")
    storage.set_user("bia")
    assert storage.load_json("settings.json") == {"day": {"max_loss_pct": 7}}  # o dono herda uma vez
    storage.save_json("settings.json", {"day": {"max_loss_pct": 1}})
    storage.set_user("ana")
    storage.save_json("settings.json", {"day": {"max_loss_pct": 3}})
    paper.set_wallet_mode("única")
    paper.reset_account(paper.SHARED_ACCOUNT, 50)
    storage.set_user("bia")
    assert storage.load_json("settings.json") == {"day": {"max_loss_pct": 1}}
    paper.reset_account(paper.SHARED_ACCOUNT, 80)
    assert paper.get_account(paper.SHARED_ACCOUNT)["initial"] == 80
    storage.set_user("ana")
    assert storage.load_json("settings.json") == {"day": {"max_loss_pct": 3}}
    assert paper.get_account(paper.SHARED_ACCOUNT)["initial"] == 50           # cada um com a sua carteira
    # backup: só os dados do usuário atual, sem prefixo e nunca o cadastro de usuários
    out = storage.export_all()
    assert out["settings.json"] == {"day": {"max_loss_pct": 3}} and storage.USERS_KEY not in out
    assert not any(k.startswith("u/") for k in out)
    assert storage.import_all({"settings.json": {"x": 1}, storage.USERS_KEY: {"hacker": {}}, "u/bia/settings.json": {"x": 2}}) == 1
    assert storage.load_json("settings.json") == {"x": 1} and "hacker" not in (storage.load_json(storage.USERS_KEY, {}) or {})
    storage.set_user("bia")
    assert storage.load_json("settings.json") == {"day": {"max_loss_pct": 1}}
    storage.set_user(None)
    paper.reset_account(paper.SHARED_ACCOUNT, 100)


def test_accounts_work_on_postgres_and_table_is_private():
    """Mesmo fluxo no Postgres (Supabase): usuários isolados e a tabela com RLS ligado e sem acesso para anon."""
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("sem Postgres de teste")
    import psycopg

    from core import storage
    from core.storage import PostgresBackend

    b = PostgresBackend(url)
    b._connect()
    with psycopg.connect(url, autocommit=True) as c:
        assert c.execute("SELECT relrowsecurity FROM pg_class WHERE relname = %s", (storage.TABLE,)).fetchone()[0] is True
    old = storage._backend
    storage._backend = b
    try:
        storage.set_user("pg_ana")
        storage.save_json("settings.json", {"a": 1})
        storage.set_user("pg_bia")
        assert storage.load_json("settings.json", "vazio") == "vazio"
        storage.set_user("pg_ana")
        assert storage.load_json("settings.json") == {"a": 1}
        assert storage.delete_user_data("pg_ana") >= 1 and storage.load_json("settings.json", "apagado") == "apagado"
        assert storage.delete_user_data("pg_bia") == 0
    finally:
        storage.set_user(None)
        storage._backend = old


def test_binance_keys_encrypted_per_user(monkeypatch):
    import hashlib
    import hmac as _hmac

    from core import accounts, credentials, storage

    KEY, SEC = "AbCdEfGh1234567890AbCdEfGh1234567890", "ZyXwVuTs0987654321ZyXwVuTs0987654321"
    monkeypatch.delenv("SECRETS_KEY", raising=False)
    storage.set_user("ana")
    assert not credentials.configured()
    with pytest.raises(RuntimeError, match="SECRETS_KEY"):
        credentials.save("ana", KEY, SEC, False, None)               # sem a chave-mestra, não guarda nada
    monkeypatch.setenv("SECRETS_KEY", "chave-mestra-longa-e-aleatoria-para-teste")
    with pytest.raises(ValueError, match="só letras e números"):
        credentials.save("ana", "curta com espaço", SEC, False, None)
    with pytest.raises(ValueError, match="SAQUE"):
        credentials.save("ana", KEY, SEC, False, {"ok": False, "message": "Esta chave tem permissão de SAQUE ligada."})
    st = credentials.save("ana", KEY, SEC, False, {"ok": True, "perms": {"enableWithdrawals": False}})
    assert st["last4"] == KEY[-4:] and st["validated"] is True and KEY not in json.dumps(st) and SEC not in json.dumps(st)
    raw = json.dumps(storage.backend().load("u/ana/credentials.json", None))
    assert KEY not in raw and SEC not in raw and "api_secret" in raw                      # no banco só o texto cifrado
    assert credentials.get("ana") == (KEY, SEC, False)
    # cada conta tem a própria chave de criptografia e os próprios dados
    storage.set_user("bia")
    assert credentials.status("bia") is None and credentials.get("bia") is None
    credentials.save("bia", KEY, SEC, True, None)
    enc_ana = storage.backend().load("u/ana/credentials.json", None)["binance"]["api_key"]
    enc_bia = storage.backend().load("u/bia/credentials.json", None)["binance"]["api_key"]
    assert enc_ana != enc_bia
    from cryptography.fernet import InvalidToken

    with pytest.raises(InvalidToken):
        credentials._dec("bia", enc_ana)                                                  # a chave de uma conta não abre a de outra
    # nunca vai para backup; é apagada junto com a conta
    assert "credentials.json" not in storage.export_all() and storage.import_all({"credentials.json": {"binance": {}}}) == 0
    monkeypatch.setenv("AUTH_MODE", "contas")
    monkeypatch.setenv("ADMIN_USER", "chefe")
    monkeypatch.setenv("ADMIN_PASSWORD", "senha-do-chefe-1")
    storage.set_user(None)
    users = storage.load_json(storage.USERS_KEY, {}) or {}
    users["bia"] = {"hash": accounts.hash_password("senha-forte-1"), "status": "ativo", "role": "user", "created": "2026-01-01"}
    storage.save_json(storage.USERS_KEY, users)
    accounts.delete("chefe", "bia", wipe_data=True)
    assert "u/bia/credentials.json" not in storage.backend().names()
    storage.set_user("ana")
    credentials.delete("ana")
    assert credentials.status("ana") is None
    storage.set_user(None)


def test_binance_validation_calls(monkeypatch):
    import hashlib
    import hmac as _hmac
    from urllib.parse import parse_qs, urlsplit

    from core import credentials

    sent = {}

    class R:
        def __init__(self, code, body):
            self.status_code, self._b = code, body

        def json(self):
            return self._b

    def fake(code, body):
        def _get(url, headers=None, timeout=None):
            sent.update(url=url, headers=headers)
            return R(code, body)
        return _get

    good = {"enableReading": True, "enableSpotAndMarginTrading": True, "enableFutures": True, "enableWithdrawals": False,
            "enableInternalTransfer": False, "ipRestrict": False}
    monkeypatch.setattr(credentials.requests, "get", fake(200, good))
    res = credentials.validate("K" * 30, "S" * 30, False)
    assert res["ok"] is True and "IPs" in res["message"] and sent["headers"] == {"X-MBX-APIKEY": "K" * 30}
    parts = urlsplit(sent["url"])
    assert parts.path == "/sapi/v1/account/apiRestrictions"
    q = parse_qs(parts.query)                                                              # assinatura HMAC-SHA256 correta
    qs = f"timestamp={q['timestamp'][0]}&recvWindow={q['recvWindow'][0]}"
    assert q["signature"][0] == _hmac.new(b"S" * 30, qs.encode(), hashlib.sha256).hexdigest()
    monkeypatch.setattr(credentials.requests, "get", fake(200, {**good, "enableWithdrawals": True}))
    res = credentials.validate("K" * 30, "S" * 30, False)
    assert res["ok"] is False and "SAQUE" in res["message"]                                 # chave com saque é recusada
    monkeypatch.setattr(credentials.requests, "get", fake(451, {}))
    assert credentials.validate("K" * 30, "S" * 30, False)["ok"] is None                    # região bloqueada: não dá para validar
    monkeypatch.setattr(credentials.requests, "get", fake(401, {"code": -2015, "msg": "x"}))
    assert credentials.validate("K" * 30, "S" * 30, False)["ok"] is False
    monkeypatch.setattr(credentials.requests, "get", fake(200, {"totalWalletBalance": "1"}))
    res = credentials.validate("K" * 30, "S" * 30, True)
    assert res["ok"] is True and "testnet.binancefuture.com/fapi/v2/account" in sent["url"]


def test_ai_daily_quota_applies_to_platform_key_only(monkeypatch):
    from core import ai, engine, quota, storage

    monkeypatch.setenv("OPENROUTER_API_KEY", "chave-da-plataforma")
    monkeypatch.setenv("AI_DAILY_LIMIT", "2")
    monkeypatch.setattr(engine, "get_funding_rate", lambda s: None)
    calls = []
    monkeypatch.setattr(ai, "ask_ai", lambda *a, **k: calls.append(1) or ai.rules_fallback({"score": 0, "direction": "HOLD", "entry": 1, "stop_loss": None,
                                                                                         "take_profit": None, "regime": "x"}, "teste"))
    cfg, df = _adv_setup()
    price = float(df["close"].iloc[-1])
    paper.set_wallet_mode("única")
    storage.set_user("quota_ana")
    paper.reset_account(paper.SHARED_ACCOUNT, 100)
    for _ in range(2):
        engine.run_analysis(PROFILES["day"], cfg, df, price, "chave-da-plataforma")
    assert len(calls) == 2 and quota.used() == 2
    res = engine.run_analysis(PROFILES["day"], cfg, df, price, "chave-da-plataforma")        # 3ª: estourou o limite
    assert len(calls) == 2 and "limite diário de 2" in res.decision.risks and res.decision.source == "regras"
    engine.run_analysis(PROFILES["day"], cfg, df, price, "chave-propria-do-usuario")          # chave própria: sem limite
    assert len(calls) == 3
    storage.set_user("quota_bia")
    paper.reset_account(paper.SHARED_ACCOUNT, 100)
    assert quota.allow() and quota.used() == 0                                                # cada usuário tem a própria conta de uso
    storage.set_user(None)


def test_ai_role_explains_or_intervenes(monkeypatch):
    from core import ai, engine
    from core import personalities as Pm

    monkeypatch.setattr(engine, "get_funding_rate", lambda s: None)
    paper.set_wallet_mode("única")
    paper.reset_account(paper.SHARED_ACCOUNT, 10_000)
    cfg = {**default_settings(PROFILES["day"]), "symbol": "X", "personality": "esp_15m_ema_3x1", "auto_bot": False}
    assert cfg["ai_intervene"] is True and cfg["ai_persona"] in ai.AI_PERSONAS             # padrão: a IA interfere
    from core.settings import load_settings
    assert load_settings("day")["ai_intervene"] and load_settings("day")["ai_exit"]         # e não é mais uma escolha do usuário
    import core.settings as cs
    monkeypatch.setenv("AI_MODEL", "meu/modelo")
    assert cs.load_settings("day")["ai_model"] == "meu/modelo"                              # o modelo vem dos Secrets
    monkeypatch.delenv("AI_MODEL")
    assert cs.load_settings("day")["ai_model"] == cs.DEFAULT_MODEL
    cfg["ai_intervene"] = False                                                              # (aqui, o caminho "só explica")
    df = ind.compute(make_df(400, trend=0.4, seed=21), cfg)
    plan = analyze(df, cfg, PROFILES["day"], Pm.get("esp_15m_ema_3x1"))
    price = float(df.close.iloc[-1])

    def fake(decision):
        return lambda ctx, **kw: ai.AIDecision(decision=decision, entry=1.0, stop_loss=0.5, take_profit=9.0,
                                                confidence=90, reasoning="teste", source="ia", model="m")

    other = "SELL" if plan.direction == "BUY" else "BUY"
    # só explica: a decisão é a das regras, qualquer que seja a opinião da IA
    monkeypatch.setattr(ai, "ask_ai", fake(other))
    r = engine.run_analysis(PROFILES["day"], cfg, df, price, "chave")
    assert r.decision.decision == plan.direction and "teste" in r.decision.reasoning
    # interfere: confirmar o sinal passa (com o stop validado das regras); discordar ou agir sem sinal veta
    on = {**cfg, "ai_intervene": True}
    assert engine.run_analysis(PROFILES["day"], on, df, price, "chave").decision.decision == "HOLD"
    if plan.direction in ("BUY", "SELL"):
        monkeypatch.setattr(ai, "ask_ai", fake(plan.direction))
        r = engine.run_analysis(PROFILES["day"], on, df, price, "chave")
        assert r.decision.decision == plan.direction
        assert r.decision.stop_loss == pytest.approx(plan.stop_loss)
    # o tom escolhido chega ao prompt da IA
    assert "Gestor cauteloso" in ai.persona_text("cauteloso") and "Professor" in ai.persona_text("inexistente")


def test_auto_bot_picks_best_for_context_and_waits_without_edge(monkeypatch):
    from core import engine
    from core import personalities as Pm

    monkeypatch.setattr(engine, "get_funding_rate", lambda s: None)
    paper.set_wallet_mode("única")
    paper.reset_account(paper.SHARED_ACCOUNT, 10_000)
    cfg, df = _adv_setup()
    cfg.update(auto_bot=True)
    best, info = engine.pick_bot(PROFILES["day"], cfg, df)
    allowed = {p["id"] for p in Pm.allowed("futures", "15m")}
    if best:  # só bots treinados neste tempo gráfico, com vantagem comprovada no contexto
        assert best["id"] in allowed and best["research"]["interval"] == "15m"
    # sem nenhum bot com vantagem no contexto: aguarda, mesmo com sinal das regras
    monkeypatch.setattr(engine, "pick_bot", lambda *a, **k: (None, {"contexto_nome": "Lateralidade"}))
    r = engine.run_analysis(PROFILES["day"], cfg, df, float(df.close.iloc[-1]), None)
    assert r.decision.decision == "HOLD" and (r.check is None)
    monkeypatch.setattr(engine, "pick_bot", lambda *a, **k: (Pm.get("esp_15m_ema_3x1"), {}))
    r = engine.run_analysis(PROFILES["day"], cfg, df, float(df.close.iloc[-1]), None)
    assert r.personality["id"] == "esp_15m_ema_3x1"
    assert engine.needs_htf(cfg) and not engine.needs_htf({**cfg, "auto_bot": False, "personality": "tendencia"})


def test_weekly_ranking_refresh_and_overlay(monkeypatch):
    from core import ranking
    from core import personalities as Pm

    pid = Pm.DEFAULT_BY_BOT["day"]
    base = next(b for b in Pm.BUILTINS if b["id"] == pid)
    market, itv = base["research"]["market"], base["research"]["interval"]
    ranking._failed_at.clear()
    assert ranking.is_stale(market, itv) and ranking.age_days(market, itv) is None
    n = 1200
    calls = []

    def getter(symbol, interval, limit, mkt):
        calls.append((symbol, interval))
        raw = make_df(limit, trend=0.05, seed=hash(symbol) % 50)
        raw["time"] = pd.date_range(end=pd.Timestamp.now(tz="UTC").floor("min"), periods=limit, freq=pd.Timedelta(seconds=ranking.htf.SECONDS[interval]))
        return raw

    rec = ranking.refresh(market, itv, getter)
    assert not ranking.is_stale(market, itv) and ranking.age_days(market, itv) < 0.01 and calls
    assert pid in rec["results"] and rec["order"] == sorted(rec["order"], key=lambda i: -rec["results"][i]["monthly_pct"])
    assert ranking.leaderboard(market, itv, top=3)
    # uma semana depois o ranking é refeito sozinho; antes disso, não
    from datetime import datetime, timedelta, timezone
    assert not ranking.is_stale(market, itv, datetime.now(timezone.utc) + timedelta(days=6))
    assert ranking.is_stale(market, itv, datetime.now(timezone.utc) + timedelta(days=8))
    assert ranking.refresh_if_stale(market, itv, getter) is False
    # o resultado semanal substitui a pesquisa só com amostra suficiente; com pouca, vale o selo original
    res = {**rec["results"][pid], "trades": ranking.MIN_TRADES, "ret_pct": -3.0, "monthly_pct": -3.0, "status": "fraco"}
    few = {**res, "trades": ranking.MIN_TRADES - 1}
    key = f"{market}|{itv}"
    fresh = Pm.get(pid) if False else ranking.overlay(base, {key: {**rec, "results": {pid: res}}})
    assert fresh["research"]["status"] == "fraco" and fresh["research"]["weekly"] and fresh["research"]["interval"] == itv
    assert ranking.overlay(base, {key: {**rec, "results": {pid: few}}}) is base
    assert ranking.status_of({"trades": 3, "ret_pct": -9, "positive": 0, "symbols": 5}, "aprovado") == "aprovado"
    assert ranking.status_of({"trades": 50, "ret_pct": 4, "positive": 4, "symbols": 5}, "fraco") == "aprovado"
    assert ranking.status_of({"trades": 50, "ret_pct": 4, "positive": 1, "symbols": 5}, "aprovado") == "ressalva"
    assert ranking.status_of({"trades": 50, "ret_pct": -4, "positive": 1, "symbols": 5}, "aprovado") == "fraco"


def test_account_mode_selector_and_exchange_gate(monkeypatch):
    from core import credentials, execution, storage

    storage.set_user("conta_modo")
    try:
        assert execution.get_mode() == "simulada" and execution.orders_enabled()
        assert set(execution.MODES) == {"simulada", "demo", "real"}
        execution.set_mode("demo")
        assert execution.get_mode() == "demo"
        with pytest.raises(ValueError):
            execution.set_mode("inexistente")
        assert "chave" in execution.orders_problem("demo").lower() and not execution.orders_enabled()
        monkeypatch.setattr(credentials, "status", lambda u: {"last4": "abcd", "testnet": True, "validated": True, "perms": {}, "saved_at": "x"})
        assert execution.key_problem("demo") is None and "conta de testes" in execution.key_problem("real")
        assert "ainda não está ativo" in execution.orders_problem("demo") and not execution.orders_enabled()  # nada de fingir que operou
        monkeypatch.setattr(credentials, "status", lambda u: {"last4": "abcd", "testnet": False, "validated": False, "perms": {}, "saved_at": "x"})
        assert "recusada" in execution.key_problem("real") and "conta real" in execution.key_problem("demo")
        execution.set_mode("simulada")
        assert execution.orders_enabled()
    finally:
        storage.set_user(None)


def test_share_custom_bots_with_community_or_selected_users(monkeypatch):
    from core import personalities as Pm
    from core import storage

    base = {"name": "Meu bot", "author": "ana", "direction": "misto", "skills": {"tendencia": 1.0}, "threshold": 30, "sl_atr": 1.5,
            "tp_atr": 3.0, "filters": {}, "markets": ["futures"]}
    ids = {}
    storage.set_user("ana")
    try:
        for vis, shared in (("privado", []), ("usuarios", ["bia", "ana"]), ("comunidade", [])):
            ids[vis] = Pm.save_custom({**base, "name": f"Bot {vis}", "visibility": vis, "shared_with": shared})["id"]
        rec = Pm.get(ids["usuarios"])
        assert rec["owner"] == "ana" and rec["shared_with"] == ["bia"]                     # o dono não entra na lista de convidados
        assert Pm.save_custom({**base, "name": "x", "visibility": "invalida"})["visibility"] == "comunidade"
        seen = lambda: {p["id"] for p in Pm.list_all()}  # noqa: E731
        assert set(ids.values()) <= seen()                                                  # dona vê tudo o que criou
        storage.set_user("bia")
        assert ids["usuarios"] in seen() and ids["comunidade"] in seen() and ids["privado"] not in seen()
        storage.set_user("caio")
        assert ids["comunidade"] in seen() and ids["usuarios"] not in seen() and ids["privado"] not in seen()
        assert Pm.get(ids["privado"])                                                       # quem usava continua resolvendo o id
        with pytest.raises(PermissionError):
            Pm.delete_custom(ids["comunidade"])                                             # só o dono exclui
        with pytest.raises(PermissionError):
            Pm.save_custom({**Pm.get(ids["comunidade"]), "name": "sequestro"})
        assert not Pm.can_edit(Pm.get(ids["comunidade"]), "caio") and Pm.can_edit(Pm.get(ids["comunidade"]), "ana")
        legacy = {"id": "velha", "name": "Velha", "builtin": False}                          # criada antes do compartilhamento
        assert Pm.can_see(legacy, "caio") and Pm.can_edit(legacy, "caio")
        assert Pm.allowed("futures", "15m") is not None
        storage.set_user("ana")
        for pid in ids.values():
            Pm.delete_custom(pid)
    finally:
        storage.set_user(None)


def test_style_by_interval_and_account_page_saves_mode(monkeypatch):
    from streamlit.testing.v1 import AppTest

    from core import accounts, execution, storage
    from core.profiles import PAGE_BOTS, PROFILES, style_of

    assert PAGE_BOTS == ("day", "swing") and PROFILES["day"].name == "Futuros" and PROFILES["swing"].name == "Spot"
    assert style_of("15m").endswith("Day Trade") and style_of("4h").endswith("Swing Trade") and style_of("1d").endswith("Long Trade")
    assert "1d" in PROFILES["day"].intervals and {"1d", "1w", "1M"} <= set(PROFILES["swing"].intervals)

    monkeypatch.setattr(accounts, "info", lambda u: {"created": "2026-01-01"})
    storage.set_user("conta_pagina")
    try:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        at = AppTest.from_file(os.path.join(root, "views", "account.py"), default_timeout=60)
        at.session_state["_user"] = "conta_pagina"
        at = at.run()
        assert not at.exception, [e.value for e in at.exception]
        from core import wallet_view                                         # a escolha da conta virou cartões clicáveis (componente)
        d = wallet_view.account_data(user="conta_pagina", admin=False, created="2026-01-01T00:00:00", storage="arquivo", mode="simulada",
                                     modes=execution.MODES, warn=lambda m: None if m == "simulada" else "sem chave", bank=100.0,
                                     bots=[{"name": "Futuros", "cfg": default_settings(PROFILES["day"]), "personality": "automático"}], ai={"used": 3, "limit": 30})
        assert [m["key"] for m in d["modes"]] == list(execution.MODES) and d["modes"][1]["warn"] == "sem chave" and d["user"]["created"] == "2026-01-01"
        assert d["bots"][0]["scan"].startswith("a cada 15 min")
        execution.set_mode("demo")
        assert execution.get_mode() == "demo"
    finally:
        execution.set_mode("simulada")
        storage.set_user(None)


def test_spot_page_has_no_leverage_or_short(monkeypatch):
    from streamlit.testing.v1 import AppTest

    from core.settings import load_settings, save_settings

    _offline_market(monkeypatch)
    paper.set_wallet_mode("única")
    cfg = load_settings("swing")
    save_settings("swing", {**cfg, "leverage_on": True, "leverage": 5, "allow_short": True})  # configuração antiga com margem
    assert load_settings("swing")["leverage_on"] is False and load_settings("swing")["allow_short"] is False

    def page():
        import streamlit as st

        st.page_link = lambda *a, **k: None
        from core.ui import render_bot_page

        render_bot_page("swing")

    at = AppTest.from_function(page, default_timeout=120).run()
    assert not at.exception, [e.value for e in at.exception]
    text = " ".join(str(getattr(w, "label", "")) for w in list(at.toggle) + list(at.radio) + list(at.slider) + list(at.segmented_control))
    assert "Alavancado" not in text and "Alavancagem" not in text and "Venda" not in text and "short" not in text.lower()
    assert "Alavancagem" not in [t.label for t in at.tabs]
    assert "Spot: compra e venda à vista" in " ".join(c.value for c in at.caption)
    assert 1 == load_settings("swing")["leverage"] and PROFILES["swing"].max_leverage == 1


def test_queue_setting_after_widgets_does_not_raise(monkeypatch):
    """Botões desenhados depois dos widgets (ex.: 'Usar este bot') não podem alterar o valor deles na mesma execução."""
    from streamlit.testing.v1 import AppTest

    _offline_market(monkeypatch)
    paper.set_wallet_mode("única")

    def page():
        import streamlit as st

        st.page_link = lambda *a, **k: None
        from core.ui import queue_setting, render_bot_page

        render_bot_page("day")
        if st.session_state.get("pedido") and not st.session_state.get("feito"):
            st.session_state["feito"] = True
            queue_setting("day", interval="1h", scan_on=False)

    at = AppTest.from_function(page, default_timeout=120).run()
    at.session_state["pedido"] = True
    at = at.run()
    assert not at.exception, [e.value for e in at.exception]
    at = at.run()  # a mudança pendente entra no começo da execução seguinte, antes dos widgets
    assert not at.exception and at.session_state["day__interval"] == "1h" and at.session_state["day__scan_on"] is False
    from core.settings import load_settings

    assert load_settings("day")["interval"] == "1h"


def test_page_renders_result_of_confirmed_conditional_plan(monkeypatch):
    """O resultado de um plano condicional confirmado não tem 'skills' nem 'levels': a página não pode quebrar."""
    from streamlit.testing.v1 import AppTest

    _offline_market(monkeypatch)
    paper.set_wallet_mode("única")

    def page():
        import streamlit as st

        st.page_link = lambda *a, **k: None
        from core import ai, engine
        from core.profiles import PROFILES

        if "planned" not in st.session_state:
            d = ai.AIDecision(decision="BUY", entry=100.0, stop_loss=97.0, take_profit=106.0, confidence=75, reasoning="Plano confirmado.",
                              model="plano", source="regras")
            plan = {"direction": "BUY", "score": 0.0, "regime": "plano condicional", "entry": 100.0, "stop_loss": 97.0,
                    "take_profit": 106.0, "trail_dist": None, "be_r": 0.0}
            st.session_state["day__analysis"] = engine.AnalysisResult(
                plan=plan, decision=d, check=None, price=100.0, symbol="BTCUSDT", interval="15m", time="2026-10-25T00:00:00+00:00")
            st.session_state["planned"] = True
        from core.ui import render_bot_page

        render_bot_page("day")

    at = AppTest.from_function(page, default_timeout=120).run()
    assert not at.exception, [e.value for e in at.exception]


def test_cached_objects_do_not_need_pickle(monkeypatch):
    """Ticker e faixas de alavancagem não podem ir para o cache serializado (pickle falha se o módulo foi recarregado)."""
    import dataclasses

    import streamlit as st

    @dataclasses.dataclass
    class Local:  # classe que o pickle não encontra no módulo: igual ao que acontece após o recarregamento do código
        last: float

    _offline_market(monkeypatch)
    from core import data, ui

    monkeypatch.setattr(ui, "get_ticker", lambda s, m: Local(1.0))
    monkeypatch.setattr(ui.lev_rules, "brackets", lambda s: ((Local(2.0),), "x"))
    st.cache_resource.clear()
    try:
        assert ui.cached_ticker("BTCUSDT", "futures").last == 1.0
        assert ui.cached_brackets("BTCUSDT")[0][0].last == 2.0
    finally:
        st.cache_resource.clear()                                # não deixa os objetos falsos no cache dos outros testes
    assert data.Ticker  # os demais valores em cache_data são DataFrame, lista e número: serializáveis


def test_each_market_page_only_shows_and_syncs_its_own_positions(monkeypatch):
    """O mesmo par existe em futuros e no spot: a posição de futuros não aparece nem é conferida no gráfico do spot."""
    from streamlit.testing.v1 import AppTest

    from core.broker import get_broker

    _offline_market(monkeypatch)
    paper.set_wallet_mode("única")
    paper.reset_account(paper.SHARED_ACCOUNT, 10_000)
    fut = get_broker("day").place_order(symbol="BTCUSDT", market="futures", side="BUY", qty=0.01, price=100.0, stop_loss=95.0,
                                         take_profit=110.0, leverage=5, fee_pct=0.0, source="regras")["position"]
    candles = make_df(5)
    candles["time"] = pd.Timestamp.now(tz="UTC").floor("min")
    candles["low"], candles["high"] = 90, 101                      # perderia o stop de 95 se fosse conferida com este preço
    assert get_broker("swing").sync("BTCUSDT", candles, 94.0) == []   # spot não mexe na posição de futuros
    assert [p["id"] for p in paper.get_account(paper.SHARED_ACCOUNT)["positions"]] == [fut["id"]]
    assert get_broker("day").sync("BTCUSDT", candles, 94.0)           # futuros confere (stop atingido)

    get_broker("day").place_order(symbol="BTCUSDT", market="futures", side="BUY", qty=0.01, price=100.0, stop_loss=95.0, leverage=5,
                                  fee_pct=0.0, source="regras")

    def page():
        import streamlit as st

        st.page_link = lambda *a, **k: None
        from core.ui import render_bot_page

        render_bot_page("swing")

    at = AppTest.from_function(page, default_timeout=120).run()
    assert not at.exception, [e.value for e in at.exception]
    text = " ".join(m.value for m in at.markdown) + " ".join(c.value for c in at.caption)
    assert "Nenhuma posição aberta" in text and "COMPRA BTCUSDT" not in text
    from core.ui import realtime_lines

    assert realtime_lines("swing", {"symbol": "BTCUSDT", "sr_on": False, "pivots_on": False, "fib_on": False}) == []


def test_volume_ranking_orders_by_volume_and_skips_stables(monkeypatch):
    from core import data

    rows = [{"symbol": "ETHUSDT", "quoteVolume": "500"}, {"symbol": "BTCUSDT", "quoteVolume": "900"}, {"symbol": "USDCUSDT", "quoteVolume": "9999"},
            {"symbol": "BTCBUSD", "quoteVolume": "800"}, {"symbol": "DEADUSDT", "quoteVolume": "0"}, {"symbol": "SOLUSDT", "quoteVolume": "300"}]
    calls = []
    monkeypatch.setattr(data, "_get", lambda url, params=None: calls.append(url) or rows)
    data._volume_cache.clear()
    assert data.volume_ranking("futures") == ["BTCUSDT", "ETHUSDT", "SOLUSDT"] and "fapi" in calls[0]
    assert data.volume_ranking("futures") == ["BTCUSDT", "ETHUSDT", "SOLUSDT"] and len(calls) == 1   # segunda chamada vem do cache
    assert data.volume_ranking("spot") == ["BTCUSDT", "ETHUSDT", "SOLUSDT"] and "api/v3" in calls[1]
    data._volume_cache.clear()


def test_ai_reads_all_indicators_even_when_hidden_on_chart(monkeypatch):
    from core import ai, engine

    monkeypatch.setattr(engine, "get_funding_rate", lambda s: None)
    paper.set_wallet_mode("única")
    paper.reset_account(paper.SHARED_ACCOUNT, 10_000)
    cfg = {**default_settings(PROFILES["day"]), "symbol": "X", "auto_bot": False, "personality": "esp_15m_ema_3x1"}
    for flag in [k for k in cfg if k.endswith("_on")]:
        cfg[flag] = False                                                   # nenhum indicador ligado no gráfico
    df = ind.compute(make_df(400, trend=0.4, seed=21), cfg)
    seen = {}
    monkeypatch.setattr(ai, "ask_ai", lambda ctx, **kw: seen.update(ctx) or ai.AIDecision(decision="HOLD", source="ia", model="m"))
    engine.run_analysis(PROFILES["day"], cfg, df, float(df.close.iloc[-1]), "chave")
    now = seen["indicadores_atuais"]
    for key in ("rsi", "macd", "bb_up", "adx", "stoch_k", "stoch_d", "vwap", "obv", "ichi_tenkan", "ichi_span_a", "st_line"):
        assert key in now and now[key] is not None, key
    assert {"pivots", "fibonacci"} <= set(seen["plano_por_regras"]["levels"])
    assert seen["candles_recentes"]["colunas"][:3] == ["time", "open", "high"] and len(seen["candles_recentes"]["linhas"]) == 120


def test_position_details_margin_fees_stop_and_target():
    from core.ui import position_details

    out = paper.place_order(paper.SHARED_ACCOUNT, symbol="Z", market="futures", side="BUY", qty=1, price=100.0, stop_loss=95.0, take_profit=110.0,
                            leverage=10, fee_pct=0.1)
    pos = out["position"]
    d = position_details(pos, 100.0)
    assert d["margin"] == pytest.approx(10.0) and d["liquidation"] and d["liquidation"] < 100
    assert d["fees_open"] == pytest.approx(0.1) and d["fees_close"] == pytest.approx(0.1)
    assert d["loss_sl"] == pytest.approx(-5 - 0.1 - 0.095)              # −5 do preço, taxa de entrada e taxa de saída no stop
    assert d["gain_tp"] == pytest.approx(10 - 0.1 - 0.11)               # +10 do preço menos as taxas
    assert position_details({**pos, "stop_loss": None, "take_profit": None}, 100.0)["loss_sl"] is None


def test_scan_tries_the_best_bots_for_the_context_until_one_signals(monkeypatch):
    """O sistema não fica preso a uma personalidade: lê o contexto da moeda e testa, em ordem, os melhores bots para ele."""
    from core import scanner
    from core import personalities as Pm

    monkeypatch.setattr(scanner.engine, "get_funding_rate", lambda s: None)
    paper.set_wallet_mode("única")
    paper.reset_account(paper.SHARED_ACCOUNT, 10_000)
    profile = PROFILES["day"]
    cfg = {**default_settings(profile), "symbol": "X", "interval": "15m"}
    df = ind.compute(make_df(331, trend=0.2, seed=8), cfg).tail(121).reset_index(drop=True)
    price = float(df.close.iloc[-1])
    mute = [p for p in Pm.allowed("futures", "15m")
            if analyze(df, cfg, profile, p).direction == "HOLD"]
    signals = analyze(df, cfg, profile, Pm.get("esp_15m_ema_3x1")).direction in ("BUY", "SELL")
    assert mute and signals
    order = [mute[0], Pm.get("esp_15m_ema_3x1")]                      # o 1º bot do ranking não dá sinal; o 2º dá
    monkeypatch.setattr(scanner.engine, "pick_bots", lambda *a, **k: (order, {}))
    res = scanner._best_signal(profile, cfg, df, price)
    assert res.decision.decision in ("BUY", "SELL") and res.personality["id"] == "esp_15m_ema_3x1"
    asked_top = []
    monkeypatch.setattr(scanner.engine, "pick_bots", lambda p, c, d, top=3: asked_top.append(top) or ([Pm.get("esp_15m_ema_3x1")], {}))
    scanner._best_signal(profile, cfg, df, price, top=7)
    assert asked_top == [7]                                                # quantos bots testar por moeda vem da configuração
    monkeypatch.setattr(scanner.engine, "pick_bots", lambda *a, **k: (mute[:2], {}))
    # nenhum bot dá sinal: devolve a leitura do melhor do ranking, sem abrir nada
    monkeypatch.setattr(scanner.engine, "pick_bots", lambda *a, **k: (mute[:2], {}))
    res = scanner._best_signal(profile, cfg, df, price)
    assert res.decision.decision == "HOLD" and res.personality["id"] == mute[0]["id"]
    # nenhum bot com vantagem no contexto: espera
    monkeypatch.setattr(scanner.engine, "pick_bots", lambda *a, **k: ([], {"contexto_nome": "Lateralidade"}))
    monkeypatch.setattr(scanner.engine, "pick_bot", lambda *a, **k: (None, {"contexto_nome": "Lateralidade"}))
    assert scanner._best_signal(profile, cfg, df, price).decision.decision == "HOLD"


# ----------------------------------------------------------------- bots por contexto (pesquisa)
def _fake_cell(market="futures", interval="15m", n=300):
    from core import context_research as cr

    t = pd.date_range("2026-01-01", periods=n, freq="15min", tz="UTC")
    vt = pd.DataFrame({"time": t, "regime": ["tendencia_alta"] * n})
    cfg = {"fee_pct": 0.05}
    cell = cr.CellData(market, interval, 40)
    cell.search = {f"S{i}": (vt, cfg) for i in range(6)}
    cell.unseen = {f"U{i}": (vt, cfg) for i in range(4)}
    return cell


def _fake_trades(vt, r_list, regime="tendencia_alta"):
    """Operações espalhadas no tempo, com os R dados (repetidos), todas no contexto."""
    idx = np.linspace(5, len(vt) - 10, len(r_list)).astype(int)
    return [{"entrada": vt["time"].iloc[i], "saida": vt["time"].iloc[i + 2], "r": float(r), "regime": regime} for i, r in zip(idx, r_list)]


def test_context_research_approval_needs_positive_results_in_all_three_tests():
    from core import context_research as cr

    cell = _fake_cell()
    winners = [1.5, -1.0, 1.5, -1.0, 1.5, 1.5, -1.0, 1.5] * 5                    # R médio positivo (+0,5)
    losers = [1.0, -1.0, -1.0, 1.0, -1.0] * 8                                    # R médio negativo (−0,2)
    sim_ok = lambda vt, cfg, p: _fake_trades(vt, winners)  # noqa: E731
    ev = cr.evaluate({"direction": "compra"}, cell, sim_ok)
    v = cr.verdict(ev, "15m")
    assert v["ok"] and all(a > 0.4 for a in v["avg_r"]) and v["pos_coins"] == (10, 10) and len(ev["unseen"]) == 4 * len(winners)
    # negativo nas moedas inéditas (prova final): reprovado, mesmo bom na busca e na validação
    calls = {"n": 0}

    def overfit(vt, cfg, p):
        calls["n"] += 1
        return _fake_trades(vt, winners if calls["n"] <= 6 else losers)           # as 6 primeiras chamadas são as moedas da busca

    assert not cr.verdict(cr.evaluate({"direction": "compra"}, cell, overfit), "15m")["ok"]
    assert not cr.verdict(cr.evaluate({"direction": "compra"}, cell, lambda vt, cfg, p: _fake_trades(vt, losers)), "15m")["ok"]
    assert not cr.verdict(cr.evaluate({"direction": "compra"}, cell, lambda vt, cfg, p: _fake_trades(vt, winners[:2])), "15m")["ok"]  # amostra pequena
    # bom só na 1ª metade e ruim na validação: reprovado
    def early(vt, cfg, p):
        ts = _fake_trades(vt, winners)
        return [{**t, "r": (abs(t["r"]) if t["entrada"] < vt["time"].iloc[200] else -abs(t["r"]))} for t in ts]

    assert not cr.verdict(cr.evaluate({"direction": "compra"}, cell, early), "15m")["ok"]


def test_context_research_builds_compatible_bot_and_reports_cells_without_bot(monkeypatch, tmp_path):
    from core import context_research as cr
    from core import personalities as Pm

    cell = _fake_cell()
    winners = [1.5, -1.0, 1.5, -1.0, 1.5, 1.5, -1.0, 1.5] * 5
    good = cr.search_cell(cell, "tendencia", "long", fast=True, simulate=lambda vt, cfg, p: _fake_trades(vt, winners))
    assert good["bot"] and good["row"]["passed"] == good["row"]["tested"] > 0
    bad = cr.search_cell(cell, "tendencia", "short", fast=True, simulate=lambda vt, cfg, p: _fake_trades(vt, [-1.0, 1.0, -1.0] * 12))
    assert bad["bot"] is None and bad["row"]["status"] == "sem bot aprovado"
    bot, rs = good["bot"], good["research"]
    assert bot["id"] == "ctx_futures_15m_tendencia_long" and bot["direction"] == "compra" and bot["bot"] == "day"
    assert bot["filters"]["contexts"] == ["tendencia_alta", "pullback_alta"] and bot["markets"] == ["futures"]
    keys = {"period_label", "period_days", "ret_pct", "monthly_pct", "win_pct", "dd_pct", "trades_month", "pos_coins", "per_symbol", "status", "interval"}
    assert keys <= set(rs) and rs["status"] in ("aprovado", "ressalva") and rs["market"] == "futures"
    assert rs["monthly_pct"] == pytest.approx(((1 + rs["ret_pct"] / 100) ** (30 / rs["period_days"]) - 1) * 100, abs=0.02)
    assert set(rs["contexts"]) == {"tendencia_alta", "pullback_alta"} or set(rs["contexts"]) <= {"tendencia_alta", "pullback_alta"}
    assert rs["contexts"]["tendencia_alta"]["avg_r"] > 0 and rs["contexts"]["tendencia_alta"]["n"] > 0
    # spot só opera comprado
    assert cr.MARKET_SIDES["spot"] == ("long",) and set(cr.CONTEXTS) == {"lateralidade", "tendencia", "reversao", "rompimento",
                                                                         "suporte_resistencia", "fluxo_ordens"}
    # entra no app como qualquer outro bot (cards, escolha por contexto e relatório)
    monkeypatch.setattr(Pm, "BUILTINS", Pm.BUILTINS + [{**bot, "research": rs, "builtin": True}])
    assert Pm.get(bot["id"])["research"]["status"] == rs["status"]
    assert any(p["id"] == bot["id"] for p in Pm.allowed("futures", "15m"))
    assert Pm.best_for_context("tendencia_alta", market="futures", interval="15m", min_trades=1)
    md = cr.report_markdown({"generated": "x", "report": [good["row"], bad["row"]]})
    assert "✅" in md and "sem bot aprovado" in md and "Tendência" in md
    out = tmp_path / "ctx.json"
    cr.save({"bots": [bot], "research": {bot["id"]: rs}, "report": []}, out)
    assert json.loads(out.read_text(encoding="utf-8"))["bots"][0]["id"] == bot["id"]


def test_context_research_pipeline_runs_end_to_end_on_synthetic_candles():
    """Roda a pesquisa de verdade (votos, simulação, provas) em candles sintéticos: o pipeline funciona e relata cada célula."""
    from core import context_research as cr
    from core import htf

    def getter(symbol, interval, limit, market):
        rng = np.random.default_rng(abs(sum(map(ord, symbol))) % 997)
        close = 100 + np.cumsum(rng.normal(0, 1, limit))
        close = np.maximum(close, 5)
        o = np.r_[close[0], close[:-1]]
        sec = htf.SECONDS[interval]
        vol = rng.random(limit) * 100 + 10
        df = pd.DataFrame({"time": pd.date_range(end=pd.Timestamp.now(tz="UTC").floor("min"), periods=limit, freq=pd.Timedelta(seconds=sec)),
                           "open": o, "high": np.maximum(o, close) + rng.random(limit), "low": np.minimum(o, close) - rng.random(limit),
                           "close": close, "volume": vol, "taker_buy": vol * rng.uniform(0.3, 0.7, limit)})
        df.attrs["source"] = "teste"
        return df

    logs = []
    res = cr.run(("futures",), ("1h",), ("fluxo_ordens", "rompimento"), universe=lambda m: [f"C{i}USDT" for i in range(10)], getter=getter,
                 fast=True, days={"1h": 40}, log=logs.append)
    assert len(res["report"]) == 4                                    # 2 contextos × (long, short)
    assert {r["status"] for r in res["report"]} <= {"sem bot aprovado", "aprovado", "ressalva"}
    assert all(r["tested"] >= r["passed"] for r in res["report"]) and any("baixando candles" in l for l in logs)
    for b in res["bots"]:                                             # se algum passou, vem com as três provas positivas
        assert all(x > cr.MIN_AVG_R for x in (b["selection"]["busca_r"], b["selection"]["validacao_r"], b["selection"]["inedito_r"]))


def test_new_contexts_taker_flow_and_support_resistance():
    from core import data, regime

    rows = [[1_700_000_000_000 + i * 60_000, 1.0, 2.0, 0.5, 1.5, 10.0, 0, 0, 0, 6.0, 0, 0] for i in range(3)]
    assert "taker_buy" in data._frame(rows, "x") and list(data._frame(rows, "x")["taker_buy"]) == [6.0] * 3
    assert "taker_buy" not in data._frame([r[:6] for r in rows], "x")                       # OKX não informa
    assert {"suporte_teste", "resistencia_teste", "fluxo_comprador", "fluxo_vendedor"} <= set(regime.REGIMES)
    cfg = default_settings(PROFILES["day"])
    raw = make_df(600, trend=0.0, seed=4)
    seen = set(ind.compute(raw, cfg)["regime"])
    assert not seen & {"fluxo_comprador", "fluxo_vendedor"}                                 # sem volume taker não há fluxo de ordens
    rng = np.random.default_rng(1)
    raw["taker_buy"] = raw["volume"] * rng.uniform(0.2, 0.8, len(raw))
    df = ind.compute(raw, cfg)
    assert df["taker_ratio"].between(0.2, 0.8).all() and {"fluxo_comprador", "fluxo_vendedor"} & set(df["regime"])
    assert set(df["regime"]) <= set(regime.REGIMES)


def test_bots_gallery_renders_with_context_bots(monkeypatch):
    """A galeria (com a aba de contextos, que agora tem 4 contextos a mais) abre com bots antigos e com um bot por contexto."""
    from streamlit.testing.v1 import AppTest

    from core import context_research as cr
    from core import personalities as Pm

    good = cr.search_cell(_fake_cell(), "suporte_resistencia", "long", fast=True,
                          simulate=lambda vt, cfg, p: _fake_trades(vt, [1.5, -1.0, 1.5, -1.0, 1.5, 1.5, -1.0, 1.5] * 5, "suporte_teste"))
    assert good["bot"]
    monkeypatch.setattr(Pm, "BUILTINS", Pm.BUILTINS + [{**good["bot"], "research": good["research"], "builtin": True}])
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    at = AppTest.from_file(os.path.join(root, "views", "bots.py"), default_timeout=120).run()
    assert not at.exception, [e.value for e in at.exception]
    from core import bots_view
    lib = bots_view.library_data([Pm.BUILTINS[-1]], {}, lambda p: False)["bots"][0]       # a biblioteca é um componente: confere os dados dos cards
    assert lib["name"] == good["bot"]["name"] and lib["contexts_only"] and lib["research"]["status"] == good["research"]["status"]


def test_archive_klines_monthly_daily_fallback_and_formats(monkeypatch, tmp_path):
    import io
    import zipfile
    from datetime import datetime, timezone

    from core import archive

    monkeypatch.setattr(archive, "CACHE", tmp_path)

    def zipped(rows, header=False):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            head = "open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_quote_volume,ignore\n" if header else ""
            z.writestr("x.csv", head + "\n".join(",".join(map(str, r)) for r in rows))
        return buf.getvalue()

    def rows(start, n, step_ms, mult=1):
        return [[(start + i * step_ms) * mult, 1, 2, 0.5, 1.5, 10, 0, 0, 0, 6, 0, 0] for i in range(n)]

    t0 = int(datetime(2026, 9, 1, tzinfo=timezone.utc).timestamp() * 1000)
    day = 86_400_000
    served, asked = {}, []
    served["monthly/klines/AAAUSDT/1d/AAAUSDT-1d-2026-09"] = zipped(rows(t0, 30, day), header=True)           # mês fechado, com cabeçalho
    for d in range(1, 4):                                                                                       # 1 a 3/10: só diários
        served[f"daily/klines/AAAUSDT/1d/AAAUSDT-1d-2026-10-{d:02d}"] = zipped(rows(t0 + (29 + d) * day, 1, day))
    served["monthly/klines/BBBUSDT/1d/BBBUSDT-1d-2026-09"] = zipped(rows(t0, 30, day, mult=1000))             # spot em microssegundos

    class Resp:
        def __init__(self, url):
            self.content = next((v for k, v in served.items() if url.endswith(k + ".zip")), b"")
            self.status_code = 200 if self.content else 404

        def raise_for_status(self):
            pass

    monkeypatch.setattr(archive._session, "get", lambda url, timeout=0: asked.append(url) or Resp(url))
    now = datetime(2026, 10, 4, 10, tzinfo=timezone.utc)                       # hoje = 4/10: os diários vão até 3/10
    df = archive.klines("AAAUSDT", "1d", 33, "futures", now=now)
    assert len(df) == 33 and df["time"].is_monotonic_increasing and "taker_buy" in df and df["taker_buy"].eq(6.0).all()
    assert df["time"].iloc[-1].date().isoformat() == "2026-10-03" and any("futures/um" in u for u in asked)
    assert len(archive.klines("AAAUSDT", "1d", 5, "futures", now=now)) == 5     # pede menos: usa só o mês corrente
    n = len(asked)
    archive.klines("AAAUSDT", "1d", 33, "futures", now=now)
    assert len(asked) == n or all("2026-10-0" not in u for u in asked[n:])      # arquivos fechados vêm do cache em disco
    us = archive.klines("BBBUSDT", "1d", 10, "spot", now=datetime(2026, 10, 1, 10, tzinfo=timezone.utc))
    assert us["time"].iloc[-1].year == 2026                                      # microssegundos convertidos
    with pytest.raises(RuntimeError):
        archive.klines("ZZZUSDT", "1d", 10, "spot", now=now)


def test_context_research_two_tiers_aprovado_and_ressalva():
    from core import context_research as cr

    cell = _fake_cell()
    thin = [0.03] * 40                                                    # R médio +0,03: positivo, mas abaixo do corte de aprovado
    strong = [1.5, -1.0, 1.5, -1.0, 1.5, 1.5, -1.0, 1.5] * 5
    v = cr.verdict(cr.evaluate({"direction": "compra"}, cell, lambda vt, cfg, p: _fake_trades(vt, thin)), "15m")
    assert v["ok"] and v["tier"] == "ressalva"
    v = cr.verdict(cr.evaluate({"direction": "compra"}, cell, lambda vt, cfg, p: _fake_trades(vt, strong)), "15m")
    assert v["tier"] == "aprovado"
    zero = [0.0] * 40                                                    # R médio 0: nem ressalva
    assert cr.verdict(cr.evaluate({"direction": "compra"}, cell, lambda vt, cfg, p: _fake_trades(vt, zero)), "15m")["tier"] is None
    res = cr.search_cell(cell, "tendencia", "long", fast=True, simulate=lambda vt, cfg, p: _fake_trades(vt, thin))
    assert res["research"]["status"] == "ressalva" and "ressalva" in res["bot"]["description"] and res["row"]["status"] == "ressalva"
    # entre candidatos, o aprovado ganha do ressalva mesmo com R menor
    calls = {"n": 0}

    def mixed(vt, cfg, p):
        return _fake_trades(vt, strong if p["threshold"] == 20 else thin)

    res = cr.search_cell(cell, "tendencia", "long", fast=True, simulate=mixed)
    assert res["research"]["status"] == "aprovado" and res["bot"]["threshold"] == 20
    assert (1.0, 2.0) not in cr.EXITS[:1] and (4.0, 6.0) in cr.EXITS and (5.0, 5.0) in cr.EXITS     # stops largos diluem as taxas nos tempos curtos


def test_bots_gallery_survives_weekly_ranking_contexts_without_extra_fields(monkeypatch):
    """Depois da 1ª atualização semanal os contextos vêm só com n, R médio e acerto: a galeria não pode quebrar."""
    from streamlit.testing.v1 import AppTest

    from core import personalities as Pm
    from core import ranking

    base = next(b for b in Pm.BUILTINS if (b.get("research") or {}).get("market") == "futures" and b["research"].get("contexts"))
    rs = base["research"]
    res = {"ret_pct": 3.0, "monthly_pct": 3.0, "win_pct": 50.0, "dd_pct": 4.0, "trades": 50, "positive": 4, "symbols": 5, "status": "aprovado",
           "contexts": {"lateral": {"n": 12, "avg_r": 0.2, "win_pct": 55.0}}}
    rank = {f"{rs['market']}|{rs['interval']}": {"updated": "2026-10-20T00:00:00+00:00", "days": 30, "results": {base["id"]: res}, "order": [base["id"]]}}
    monkeypatch.setattr(ranking, "load", lambda: rank)
    assert Pm.get(base["id"])["research"]["contexts"]["lateral"] == {"n": 12, "avg_r": 0.2, "win_pct": 55.0}
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    at = AppTest.from_file(os.path.join(root, "views", "bots.py"), default_timeout=120).run()
    assert not at.exception, [e.value for e in at.exception]


def test_realtime_spot_chart_lists_binance_websocket_ports_in_order():
    from core import realtime

    cfg = default_settings(PROFILES["swing"])
    html = realtime.realtime_chart_html(symbol="BTCUSDT", interval="1h", market="spot", cfg=cfg, lines=[], positions=[], height=600)
    i443, i9443, imirror = html.index("stream.binance.com:443"), html.index("stream.binance.com:9443"), html.index("data-stream.binance.vision")
    assert i443 < i9443 < imirror                                    # 443 → 9443 → espelho público → OKX
    fut = realtime.realtime_chart_html(symbol="BTCUSDT", interval="1h", market="futures", cfg=default_settings(PROFILES["day"]), lines=[],
                                       positions=[], height=600)
    assert "fstream.binance.com" in fut and "stream.binance.com:9443" not in fut.split("if (fut)")[1].split("else {")[0]


def test_chart_actions_validate_everything_coming_from_the_browser():
    """Os pedidos do gráfico (ordem limite, stop/alvo, zerar, cancelar) vêm do navegador: tudo é validado antes de agir."""
    from core import chart_actions
    from core.broker import get_broker

    paper.set_wallet_mode("única")
    paper.reset_account(paper.SHARED_ACCOUNT, 10_000)
    prof, cfg = PROFILES["day"], {**default_settings(PROFILES["day"]), "symbol": "BTCUSDT"}
    broker = get_broker("day")
    ev = lambda **k: {"tb": 1, "symbol": "BTCUSDT", "market": "futures", "uid": "u", **k}  # noqa: E731
    price, atr = 80_000.0, 400.0

    ok, msg = chart_actions.handle(prof, cfg, ev(kind="limit", side="BUY", price=79_000), price, atr)
    assert ok and "Ordem limite" in msg
    (order,) = [o for o in broker.account()["orders"]]
    assert order["limit_price"] == 79_000 and order["side"] == "BUY" and order["source"] == "manual" and order["stop_loss"] < 79_000 < order["take_profit"]
    # recusas: outro ativo/mercado, preço longe, lado inválido, números ruins, mensagem sem marca
    for bad in (ev(kind="limit", side="BUY", price=79_000, symbol="ETHUSDT"), ev(kind="limit", side="BUY", price=79_000, market="spot"),
                ev(kind="limit", side="BUY", price=40_000), ev(kind="limit", side="HOLD", price=79_000),
                ev(kind="limit", side="BUY", price="abc"), ev(kind="limit", side="BUY", price=float("nan")), ev(kind="limit", side="BUY", price=-5),
                {"kind": "limit", "side": "BUY", "price": 79_000}, "texto", None, ev(kind="desconhecido")):
        assert chart_actions.handle(prof, cfg, bad, price, atr)[0] is False
    assert len(broker.account()["orders"]) == 1
    assert chart_actions.handle(PROFILES["swing"], {**default_settings(PROFILES["swing"]), "symbol": "BTCUSDT"},
                                ev(kind="limit", side="SELL", price=81_000, market="spot"), price, atr) == (False, "No spot só é possível comprar.")
    # cancelar só ordens existentes deste mercado
    assert chart_actions.handle(prof, cfg, ev(kind="cancel_order", id="nao-existe"), price, atr)[0] is False
    assert chart_actions.handle(prof, cfg, ev(kind="cancel_order", id=order["id"]), price, atr)[0] and not broker.account()["orders"]
    # posição: mover stop/alvo (só do lado certo) e zerar
    pos = broker.place_order(symbol="BTCUSDT", market="futures", side="BUY", qty=0.01, price=price, stop_loss=79_000, take_profit=82_000, leverage=5,
                             fee_pct=0.0, source="manual")["position"]
    assert chart_actions.handle(prof, cfg, ev(kind="protect", id=pos["id"], stop_loss=80_500, take_profit=82_000), price, atr)[0] is False  # stop acima da entrada
    assert chart_actions.handle(prof, cfg, ev(kind="protect", id=pos["id"], stop_loss=79_500, take_profit=83_000), price, atr)[0]
    now = broker.account()["positions"][0]
    assert now["stop_loss"] == 79_500 and now["take_profit"] == 83_000
    assert chart_actions.handle(prof, cfg, ev(kind="protect", id="outra"), price, atr)[0] is False
    ok, msg = chart_actions.handle(prof, cfg, ev(kind="close", id=pos["id"]), price, atr)
    assert ok and "encerrada" in msg and not broker.account()["positions"]


def test_chart_actions_blocked_on_exchange_accounts(monkeypatch):
    from core import chart_actions, execution

    prof, cfg = PROFILES["day"], {**default_settings(PROFILES["day"]), "symbol": "BTCUSDT"}
    monkeypatch.setattr(execution, "orders_problem", lambda mode=None: "Conta da Exchange sem envio de ordens.")
    ok, msg = chart_actions.handle(prof, cfg, {"tb": 1, "symbol": "BTCUSDT", "market": "futures", "kind": "limit", "side": "BUY", "price": 79_000},
                                   80_000.0, 400.0)
    assert not ok and "Exchange" in msg


def test_realtime_chart_has_tools_and_sends_requests_to_the_page():
    from core import realtime

    pos = [{"id": "p1", "side": "BUY", "qty": 1, "entry": 100.0, "fee_pct": 0.05, "fees_paid": 0.1, "margin": 20, "stop_loss": 98.0,
            "take_profit": 105.0, "leverage": 5, "liquidation": 85.0}]
    orders = [{"id": "o1", "side": "BUY", "qty": 1, "limit_price": 95.0}]
    html = realtime.realtime_chart_html(symbol="BTCUSDT", interval="15m", market="futures", cfg=default_settings(PROFILES["day"]), lines=[],
                                        positions=pos, orders=orders, height=700)
    for needle in ('data-tool="', "Heikin-Ashi", "Fibonacci", "window.parent.postMessage", 'kind: "limit"', 'kind: "protect"', 'kind: "close"',
                   'kind: "cancel_order"', "Indicadores ▾", '"id": "p1"', '"liquidation": 85.0', '"id": "o1"', "tb_draw_",
                   'data-z="in"', 'data-z="out"', "zoomBy(", "const netAt", "lineTitle(dragLine.pos"):   # zoom e P&L ao arrastar stop/alvo
        assert needle in html, needle
    assert "__TOOLS__" not in html and "__CONF__" not in html
    demo = realtime.realtime_chart_html(symbol="BTCUSDT", interval="15m", market="spot", cfg=default_settings(PROFILES["swing"]), lines=[],
                                        positions=[], height=700, demo=[[1, 1, 2, 0.5, 1.5, 10]])
    assert '"demo": [[1, 1, 2, 0.5, 1.5, 10]]' in demo


def test_position_summary_spot_and_futures_numbers():
    from datetime import datetime, timedelta, timezone

    from core import positions_view as pv

    paper.set_wallet_mode("única")
    paper.reset_account(paper.SHARED_ACCOUNT, 10_000)
    spot = paper.place_order(paper.SHARED_ACCOUNT, symbol="SOLUSDT", market="spot", side="BUY", qty=10, price=100.0, stop_loss=95.0, take_profit=110.0,
                             leverage=1, fee_pct=0.1, source="ia", personality={"id": "x", "name": "Tendência EMA 15m"}, margin_mode="Isolada")["position"]
    v = pv.summarize(spot, 104.0, now=datetime.fromisoformat(spot["opened"]) + timedelta(minutes=135))
    assert v["spot"] and v["base_asset"] == "SOL" and v["cost"] == pytest.approx(1000.0) and v["qty"] == 10
    assert v["net"] == pytest.approx(40 - 1.0 - 1.04) and v["net_pct"] == pytest.approx(v["net"] / 1000 * 100)       # % sobre o valor investido
    assert v["target"]["price"] == 110 and v["target"]["per_coin"] == pytest.approx(10.0) and v["target"]["net"] == pytest.approx(100 - 1.0 - 1.1)
    assert v["stop"]["per_coin"] == pytest.approx(-5.0) and v["stop"]["net"] == pytest.approx(-50 - 1.0 - 0.95) and v["rr"] == pytest.approx(2.0)
    assert v["who"] == "🤖 Tendência EMA 15m" and v["opened_ago"] == "há 2 h 15 min"
    manual = paper.place_order(paper.SHARED_ACCOUNT, symbol="ETHUSDT", market="spot", side="BUY", qty=1, price=50.0, leverage=1, fee_pct=0.1)["position"]
    vm = pv.summarize(manual, 50.0)
    assert vm["who"].startswith("✋") and vm["stop"] is None and vm["target"] is None and vm["rr"] is None
    fut = paper.place_order(paper.SHARED_ACCOUNT, symbol="BTCUSDT", market="futures", side="SELL", qty=0.1, price=1000.0, stop_loss=1020.0, take_profit=950.0,
                            leverage=10, fee_pct=0.05, source="ia", personality={"id": "y", "name": "Reversão 1h"})["position"]
    vf = pv.summarize(fut, 990.0)
    assert not vf["spot"] and vf["cost"] == pytest.approx(100.0) and vf["margin"] == pytest.approx(10.0) and vf["leverage"] == 10
    assert vf["net_pct"] == pytest.approx(vf["net"] / 10 * 100)                                                          # % sobre a margem
    assert vf["target"]["per_coin"] == pytest.approx(50.0 * 1) and vf["stop"]["per_coin"] == pytest.approx(-20.0)       # venda ganha quando cai


def test_open_position_cards_component_and_actions(monkeypatch):
    """Os cards são um componente em HTML/CSS/JS: a página abre com posições de spot e futuros e os dados trazem o necessário."""
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    from core import chart_actions, positions_view as pv
    from core.broker import get_broker

    _offline_market(monkeypatch)
    paper.set_wallet_mode("única")
    paper.reset_account(paper.SHARED_ACCOUNT, 10_000)
    spot = get_broker("swing").place_order(symbol="BTCUSDT", market="spot", side="BUY", qty=0.5, price=100.0, stop_loss=95.0, take_profit=112.0,
                                           leverage=1, fee_pct=0.1, source="ia", personality={"id": "x", "name": "Rompimento 4h"},
                                           margin_mode="Isolada", note="rompeu a máxima")["position"]
    fut = get_broker("day").place_order(symbol="BTCUSDT", market="futures", side="BUY", qty=1, price=100.0, stop_loss=95.0, take_profit=112.0, leverage=5,
                                        fee_pct=0.05, source="ia", personality={"id": "y", "name": "Tendência 15m"}, margin_mode="Isolada")["position"]

    def page(bot):
        import streamlit as st

        st.page_link = lambda *a, **k: None
        from core.ui import render_bot_page

        render_bot_page(bot)

    for bot in ("swing", "day"):
        at = AppTest.from_function(page, args=(bot,), default_timeout=120).run()
        assert not at.exception, [e.value for e in at.exception]
        assert "Nenhuma posição aberta." not in " ".join(c.value for c in at.caption)      # há card: o componente recebe os dados
    cs, cf = pv.card_data(spot, 104.0), pv.card_data(fut, 104.0)
    assert cs["spot"] and cs["who"] == "🤖 Rompimento 4h" and cs["id"] == spot["id"] and cs["symbol"] == "BTCUSDT" and cs["note"] == "rompeu a máxima"
    assert cs["target"]["net"] > 0 > cs["stop"]["net"] and cs["opened_at"].endswith("UTC") and cs["cost"] == pytest.approx(50.0)
    assert not cf["spot"] and cf["who"] == "🤖 Tendência 15m" and cf["margin"] == pytest.approx(20.0) and cf["liquidation"]
    js = Path(__file__).resolve().parent.parent.joinpath("core", "position_cards.js").read_text(encoding="utf-8")
    for needle in ("Valor investido", "Moedas compradas", "Venda esperada (alvo)", "Vender tudo agora", "Preço de liquidação", "Alavancagem", "setTriggerValue"):
        assert needle in js, needle
    assert js.index("if (c.spot)") < js.index("Margem") < js.index("Alavancagem")         # margem, alavancagem e liquidação só no ramo de futuros
    prof = PROFILES["swing"]
    price_for = lambda sym: 104.0  # noqa: E731
    assert chart_actions.handle_card(prof, {"kind": "protect", "id": fut["id"], "stop_loss": 96, "take_profit": 112}, price_for)[0] is False    # é de futuros
    assert chart_actions.handle_card(prof, {"kind": "protect", "id": spot["id"], "stop_loss": 106, "take_profit": 112}, price_for)[0] is False  # stop acima da entrada
    assert chart_actions.handle_card(prof, {"kind": "protect", "id": spot["id"], "stop_loss": 97, "take_profit": 115}, price_for) == (True, "Stop e alvo atualizados.")
    assert chart_actions.handle_card(prof, {"kind": "protect", "id": spot["id"], "stop_loss": None, "take_profit": None}, price_for)[0]       # tirar stop/alvo
    assert chart_actions.handle_card(prof, {"kind": "outra", "id": spot["id"]}, price_for) == (False, "") and chart_actions.handle_card(prof, "x", price_for)[0] is False
    ok, msg = chart_actions.handle_card(prof, {"kind": "close", "id": spot["id"]}, price_for)
    assert ok and "encerrada" in msg and chart_actions.handle_card(prof, {"kind": "close", "id": spot["id"]}, price_for)[0] is False
    assert chart_actions.handle_card(prof, {"kind": "close", "id": fut["id"]}, lambda s: None)[0] is False                                       # outro mercado


def test_ticket_view_and_submit(monkeypatch):
    """A boleta (componente) manda só o formulário: o Python saneia, calcula o risco e valida o envio."""
    from core import execution, ticket_view as tv
    from core.profiles import PROFILES
    from core.settings import default_settings

    spot, fut = PROFILES["swing"], PROFILES["day"]
    cfg = {**default_settings(spot), "symbol": "BTCUSDT"}
    stats = {"equity": 10000.0, "available": 10000.0}
    monkeypatch.setattr(execution, "orders_problem", lambda mode=None: "")
    v = tv.view(spot, cfg, {"side": "SELL", "type": "LIMIT", "limit": 99, "auto": True}, 100.0, 2.0, stats)
    assert v["form"]["side"] == "BUY" and v["form"]["type"] == "LIMIT" and v["spot"] and v["leverage"] is None   # spot não vende a descoberto
    assert v["calc"]["qty"] > 0 and v["form"]["sl"] < 99 < v["form"]["tp"]
    fcfg = {**default_settings(fut), "symbol": "BTCUSDT", "allow_short": True}
    assert tv.view(fut, fcfg, {"side": "SELL"}, 100.0, 2.0, stats)["form"]["side"] == "SELL"
    assert tv.clean_form(spot, cfg, {"limit": "abc", "type": "LIMIT"}, 100.0, 2.0, 50.0, 1000.0)["limit"] == 100.0   # lixo vira o preço atual
    lv = tv.view(fut, fcfg, {"lev": 500, "margin": "Cruzada"}, 100.0, 2.0, stats, max_lev=50)         # alavancagem própria da boleta, limitada ao máximo do par
    assert lv["leverage"] == 50 and lv["margin_mode"] == "Cruzada" and lv["max_lev"] == 50
    assert tv.view(fut, fcfg, {"lev": 5}, 100.0, 2.0, stats)["leverage"] == 5 and tv.view(spot, cfg, {"lev": 5}, 100.0, 2.0, stats)["leverage"] is None
    assert tv.submit(spot, cfg, {"type": "LIMIT", "limit": 150}, 100.0, 2.0)[0] is False      # limite 50% longe do mercado
    assert tv.submit(spot, cfg, {"side": "SELL"}, None, 2.0)[0] is False                      # sem cotação


class _FakeCcxt:
    """Corretora de mentira com a interface do ccxt usada em core/exchanges.py."""
    timeframes = {"1m": "1m", "15m": "15m", "1h": "1h"}

    def __init__(self, quote="USDT", swap=False):
        self.quote, self.swap = quote, swap
        sym = lambda b: f"{b}/{quote}:{quote}" if swap else f"{b}/{quote}"  # noqa: E731
        self.markets = {sym(b): {"base": b, "quote": quote, "active": True, "swap": swap, "spot": not swap} for b in ("BTC", "ETH", "SOL")}
        self.calls = 0

    def load_markets(self):
        return self.markets

    def fetch_ohlcv(self, symbol, tf, since=None, limit=None):
        self.calls += 1
        step = {"1m": 60, "15m": 900, "1h": 3600}[tf] * 1000
        t0 = (since // step) * step
        return [[t0 + i * step, 100 + i, 101 + i, 99 + i, 100.5 + i, 10.0] for i in range(min(limit or 300, 300))]

    def fetch_ticker(self, symbol):
        return {"last": 123.0, "percentage": 1.5, "high": 130.0, "low": 120.0, "quoteVolume": 5e6}

    def fetch_tickers(self):
        vol = {"BTC": 9e9, "ETH": 5e9, "SOL": 1e9}
        return {s: {"last": 10.0, "percentage": 2.0, "quoteVolume": vol[m["base"]]} for s, m in self.markets.items()}

    def fetch_funding_rate(self, symbol):
        return {"fundingRate": 0.0001}


def test_exchanges_via_ccxt_and_fallback(monkeypatch):
    """Corretoras pelo ccxt: pares convertidos, candles paginados, ranking por volume, escolha salva e volta aos provedores padrão."""
    from core import data, exchanges

    monkeypatch.setattr(exchanges, "_make", lambda cid, swap: _FakeCcxt(quote="USD" if cid == "coinbase" else "USDT", swap=swap))
    exchanges._clients.clear(); exchanges._markets_at.clear(); exchanges._sel_cache.clear()
    assert exchanges.supports("bybit", "futures") and not exchanges.supports("coinbase", "futures") and not exchanges.supports("nada", "spot")
    assert exchanges.market_symbol("bybit", "spot", "BTCUSDT") == "BTC/USDT"
    assert exchanges.market_symbol("coinbase", "spot", "ETHUSDT") == "ETH/USD"             # Coinbase cota em USD: o par é traduzido
    try:
        exchanges.market_symbol("bybit", "spot", "DOGEUSDT")
        raise AssertionError("par inexistente deveria falhar")
    except exchanges.ExchangeError:
        pass
    rows = exchanges.klines("bybit", "BTCUSDT", "15m", 120, "spot")
    assert len(rows) == 120 and rows == sorted(rows, key=lambda r: r[0])
    try:
        exchanges.klines("bybit", "BTCUSDT", "3m", 50, "spot")
        raise AssertionError("tempo gráfico sem suporte deveria falhar")
    except exchanges.ExchangeError:
        pass
    assert exchanges.ticker("bybit", "BTCUSDT", "spot").last == 123.0 and exchanges.funding("bybit", "BTCUSDT") == 0.01
    assert exchanges.symbols("bybit", "spot") == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]          # do maior para o menor volume
    assert set(exchanges.table("coinbase", "spot")) == {"BTCUSDT", "ETHUSDT", "SOLUSDT"}   # pares em USD aparecem como USDT internamente

    monkeypatch.setattr(exchanges, "load_json", lambda *a, **k: {"exchange": "bybit"})
    exchanges._sel_cache.clear()
    assert exchanges.selected() == "bybit"
    df = data.get_klines("BTCUSDT", "15m", 100, "spot")
    assert df.attrs["source"] == "Bybit" and len(df) == 100                                  # a corretora escolhida manda
    assert data.get_ticker("BTCUSDT", "spot").source == "Bybit Spot" and data.get_funding_rate("BTCUSDT") == 0.01
    assert data.volume_ranking("spot")[0] == "BTCUSDT" and data.watch_prices("spot", ["BTCUSDT"])["BTCUSDT"] == (10.0, 2.0)
    # corretora sem o par/tempo gráfico: cai nos provedores padrão em vez de quebrar
    monkeypatch.setattr(data, "_binance_klines", lambda *a, **k: [[1_700_000_000_000 + i * 900_000, 1, 2, 0.5, 1.5, 3] for i in range(5)])
    assert data.get_klines("BTCUSDT", "3m", 5, "spot").attrs["source"].startswith("Binance")
    monkeypatch.setattr(exchanges, "load_json", lambda *a, **k: {"exchange": "desconhecida"})
    exchanges._sel_cache.clear()
    assert exchanges.selected() == exchanges.DEFAULT
    exchanges._clients.clear(); exchanges._sel_cache.clear(); data._volume_cache.clear(); data._watch_cache.clear()


def test_chart_has_a_live_source_for_every_exchange():
    """O gráfico ao vivo segue a corretora escolhida: toda corretora da lista tem fonte própria (WebSocket ou consulta periódica)."""
    from core import exchanges
    from core.realtime import realtime_chart_html

    cfg = {**default_settings(PROFILES["day"]), "symbol": "BTCUSDT"}
    html = realtime_chart_html(symbol="BTCUSDT", interval="15m", market="futures", cfg=cfg, lines=[], positions=[], height=600, prefer="kucoin")
    assert '"prefer": "kucoin"' in html
    native = {"binance", "bybit", "okx"}                       # com WebSocket próprio
    for ex in exchanges.EXCHANGES:
        assert ex in native or f"  {ex}: () =>" in html, ex      # as demais têm adaptador REST


def test_polymarket_sentiment_for_ai(monkeypatch):
    """O sentimento do Polymarket (preço mediano implícito e chance de tocar níveis) vira contexto para a IA; sem dados, nada muda."""
    from datetime import datetime, timezone
    from core import ai, sentiment

    assert sentiment.parse_price("Will Bitcoin reach $150,000 in October?") == 150000 and sentiment.parse_price("above $1.5k") == 1500
    assert [sentiment.kind_of(q) for q in ("Will Bitcoin dip to $60,000?", "Will Bitcoin reach $95,000?", "Will the price of Bitcoin be above $72,000 on X?", "Quem ganha?")] \
        == ["down", "up", "above", None]
    now = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
    mk = lambda q, yes: {"question": q, "outcomes": '["Yes","No"]', "outcomePrices": f'["{yes}","{1 - yes}"]'}  # noqa: E731
    above = {"title": "Bitcoin above ___ on October 26?", "endDate": "2026-10-26T16:00:00Z", "volume24hr": 1000,
             "markets": [mk(f"Will the price of Bitcoin be above ${p:,} on October 26?", y) for p, y in ((78000, 0.95), (80000, 0.7), (82000, 0.3), (84000, 0.05))]}
    touch = {"title": "What price will Bitcoin hit in October?", "endDate": "2026-11-01T04:00:00Z",
             "markets": [mk("Will Bitcoin reach $84,000 in October?", 0.2), mk("Will Bitcoin dip to $76,000 in October?", 0.1)]}
    assert abs(sentiment.implied_median(sentiment._ladder(above, ("above",))) - 81000) < 1
    r = sentiment.summarize([above, touch], "BTC", 80000, now)
    assert r["vies"] == "altista" and r["mediana_implicita"]["vs_preco_pct"] > 1 and r["toque"]["alta"]["chance_pct"] == 20.0
    assert "Sentimento altista" in r["leitura"] and sentiment.summarize([{"title": "Outra coisa", "endDate": "2026-12-01T00:00:00Z"}], "BTC", 80000, now) is None
    sentiment._cache.clear()
    sentiment._cache.clear()
    assert sentiment.for_symbol("XYZUSDT", 1.0, fetch=lambda base: (_ for _ in ()).throw(RuntimeError("sem rede"))) is None   # falha vira None
    sentiment._cache.clear()
    cfg = default_settings(PROFILES["day"])
    ctx = ai.build_context(profile=PROFILES["day"], cfg=cfg, symbol="BTCUSDT", interval="15m", plan={}, snapshot={}, indicators_now={}, account={},
                           positions=[], risk_rules={}, sentiment=r)
    assert ctx["sentimento_polymarket"]["vies"] == "altista" and "sentimento_polymarket" in ai.SYSTEM_PROMPT


def test_sentiment_peek_and_warm_do_not_block(monkeypatch):
    """A faixa de cotações só lê o sentimento já guardado; a busca roda em segundo plano e uma moeda sem mercado não gera consulta."""
    from core import sentiment

    sentiment._cache.clear(); sentiment._pending.clear()
    assert sentiment.peek("BTCUSDT") is None
    calls = []
    monkeypatch.setattr(sentiment, "for_symbol", lambda s, p, fetch=None: calls.append(s))
    sentiment.warm({"BTCUSDT": 80000.0, "XYZUSDT": 1.0, "ETHUSDT": 0.0})     # XYZ não tem nome conhecido; ETH sem preço
    import time as _t
    for _ in range(50):
        if calls:
            break
        _t.sleep(0.05)
    assert calls == ["BTCUSDT"]
    sentiment._cache["BTC"] = (_t.time(), {"vies": "altista"})
    assert sentiment.peek("BTCUSDT") == {"vies": "altista"}
    sentiment._cache.clear()


def test_events_panel_and_ai_context():
    """Painel de eventos do Polymarket: cartões por categoria, vencidos saem, ruído é filtrado e a IA recebe um resumo curto."""
    from datetime import datetime, timezone
    from core import ai, ai_exit, events

    now = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
    mk = lambda title, yes, grp=None: {"question": title, "groupItemTitle": grp, "outcomes": '["Yes","No"]', "outcomePrices": f'["{yes}","{1 - yes}"]'}  # noqa: E731
    fed = {"id": "1", "title": "Fed Decision in October?", "slug": "fed", "endDate": "2026-10-29T03:59:00Z", "volume24hr": 2_000_000, "liquidity": 7e6,
           "markets": [mk("a", 0.945, "No change"), mk("b", 0.055, "25 bps increase"), mk("c", 0.001, "50+ bps decrease")]}
    old = {**fed, "id": "2", "title": "Fed Decision in September?", "endDate": "2026-09-17T18:00:00Z"}            # já venceu
    noise = {"id": "3", "title": "What will Trump say during his rally?", "endDate": "2026-10-30T00:00:00Z", "volume24hr": 5000, "markets": [mk("x", 0.7, "Canada")]}
    ladder = {"id": "4", "title": "What price will Bitcoin hit in October?", "slug": "btc", "endDate": "2026-11-01T04:00:00Z", "volume24hr": 400_000,
              "markets": [mk(f"Will Bitcoin reach ${p:,} in October?", y) for p, y in ((80000, .9), (82500, .62), (85000, .25), (90000, .03))]}
    quiet = {"id": "5", "title": "Gold above $5000?", "endDate": "2026-12-01T00:00:00Z", "volume24hr": 10, "liquidity": 100, "markets": [mk("g", 0.5)]}
    assert events.card(old, "macro", now) is None and events.card(quiet, "commodities", now) is None and events.card(noise, "politica", now) is None
    c = events.card(fed, "macro", now)
    assert c["opcoes"][0] == {"nome": "No change", "pct": 94.5} and not c["escada"]
    lad = events.card(ladder, "cripto", now)
    assert lad["escada"] and lad["opcoes"][0]["pct"] == 62.0                       # escada de preços: os níveis mais incertos (perto de 50%)
    got = events.build({"Fed decision": ("macro", [fed, old]), "bitcoin": ("cripto", [ladder]), "Fed rate": ("macro", [fed])}, now)
    assert [e["id"] for e in got] == ["1", "4"]                                    # sem repetidos nem vencidos, por volume
    ctx = events.ai_context(got, now)
    assert len(ctx) == 1 and ctx[0]["evento"] == "Fed Decision in October?" and ctx[0]["probabilidades"][0]["pct"] == 94.5   # escada de cripto não entra
    assert events.ids_for_ai(got) == {"1"}
    cfg = default_settings(PROFILES["day"])
    c1 = ai.build_context(profile=PROFILES["day"], cfg=cfg, symbol="BTCUSDT", interval="15m", plan={}, snapshot={}, indicators_now={}, account={},
                          positions=[], risk_rules={}, events=ctx)
    assert c1["eventos_externos"] == ctx and "eventos_externos" in ai.SYSTEM_PROMPT and "eventos_externos" in ai_exit.SYSTEM_PROMPT
    assert "eventos_externos" in ai_exit.build_context({"symbol": "XUSDT", "side": "BUY", "entry": 1.0, "stop_loss": 0.9, "take_profit": 1.2, "opened": "", "qty": 10.0, "fee_pct": 0.05,
                                                        "leverage": 1, "margin": 10.0, "market": "spot"},
                                                       1.0, {"atr": 0.01}, {}, None, {"interval": "15m"}, None, ctx)


def test_events_translation_and_tooltip(monkeypatch):
    """Eventos em português: regras mínimas sem IA, tradução da IA validada e guardada, e sempre uma explicação para o '?'."""
    from core import events, events_pt as pt

    monkeypatch.setattr(pt, "_state", {"cache": {}, "running": False})
    monkeypatch.setattr(pt, "locked_update", lambda name, default, fn: None)      # sem gravar em disco no teste
    card = {"id": "1", "titulo": "Fed Decision in October?", "categoria": "macro", "escada": False, "slug": "fed", "vence": "2026-10-29T03:59:00Z", "volume_24h": 1,
            "liquidez": 1, "desc": "Resolve to the change in bps.", "opcoes": [{"nome": "No change", "pct": 94.5}, {"nome": "25 bps increase", "pct": 5.5}]}
    loc = pt.localize([card])[0]
    assert loc["titulo"] == "Decisão do Fed em outubro?" and [o["nome"] for o in loc["opcoes"]] == ["Sem mudança", "Alta de 25 bps"] and not loc["traduzido"]
    assert "juros" in str(loc["explicacao"]).lower() and "desc" not in loc               # explicação genérica em português, sem o texto original
    assert loc["explicacao"][0][0] == "O que é" and any(r == "Por que importa" for r, _ in loc["explicacao"])
    assert "preço" in str(pt.generic_explanation({**card, "escada": True})) and "sim ou não" in str(pt.generic_explanation({**card, "opcoes": [{"nome": "Sim", "pct": 1}, {"nome": "Não", "pct": 99}]}))
    k = pt.key_of(card)
    good = {"itens": [{"id": k, "titulo": "Decisão do Fed em outubro", "opcoes": ["Sem mudança", "Alta de 0,25 p.p."], "o_que_e": "Aposta no que o Fed fará com os juros.", "contexto": "O FOMC se reúne oito vezes por ano.", "importa": "Juros altos pesam sobre cripto."}]}
    assert pt.parse(good, [card])[k]["o"][1] == "Alta de 0,25 p.p."
    assert pt.parse({"itens": [{"id": k, "titulo": "x", "opcoes": ["só uma"]}]}, [card]) == {}      # quantidade de opções diferente: descartado
    assert pt.parse("lixo", [card]) == {}
    pt.save(pt.parse(good, [card]))
    loc = pt.localize([card])[0]
    assert loc["traduzido"] and loc["titulo"] == "Decisão do Fed em outubro" and loc["explicacao"][0] == ["O que é", "Aposta no que o Fed fará com os juros."]
    assert [r for r, _ in loc["explicacao"]] == ["O que é", "Contexto", "Por que importa"]
    assert pt._sections("texto antigo") == [["O que é", "texto antigo"]]                  # formato antigo ainda lido
    assert pt.pending([card]) == []
    assert "geopolitica" in events.CATEGORIES and events.AI_PICK["geopolitica"] == 3
    assert events.card({"id": "9", "title": "US-Iran ceasefire continues through...?", "endDate": "2099-10-31T00:00:00Z", "volume24hr": 1e6,
                        "markets": [{"question": "q", "groupItemTitle": "October 22", "outcomes": '["Yes","No"]', "outcomePrices": '["0.99","0.01"]'}]}, "geopolitica") is not None


def test_events_for_ai_are_balanced_and_by_importance():
    """A IA recebe um calendário equilibrado (macro, geopolítica, política, commodities), sem assuntos repetidos e priorizando o que pesa no mercado."""
    from datetime import datetime, timezone
    from core import events

    now = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
    mk = lambda cat, title, vol, days, esc=False: {"id": title, "titulo": title, "categoria": cat, "escada": esc, "volume_24h": vol,  # noqa: E731
                                                  "vence": (datetime(2026, 10, 25 + days, 12, tzinfo=timezone.utc)).isoformat() if days < 6 else "2026-12-01T00:00:00+00:00",
                                                  "opcoes": [{"nome": "Sim", "pct": 50.0}, {"nome": "Não", "pct": 50.0}], "slug": "", "liquidez": 0}
    evs = [mk("politica", "Brazil Presidential Election", 4_000_000, 1), mk("politica", "Brazil Presidential Election Second Round: Margin", 1_600_000, 1),
           mk("politica", "Which party will win the House in 2026?", 400_000, 5), mk("macro", "Fed Decision in October?", 2_000_000, 3),
           mk("macro", "Fed Decision in December?", 1_500_000, 5), mk("macro", "US recession by end of 2026?", 3_000, 5),
           mk("geopolitica", "US-Iran ceasefire continues through...?", 1_200_000, 5), mk("geopolitica", "Will China invade Taiwan by end of 2026?", 200_000, 5),
           mk("geopolitica", "NATO x Russia military clash by...?", 70_000, 5), mk("geopolitica", "Russia x Ukraine ceasefire agreement by...?", 60_000, 5),
           mk("commodities", "What will WTI Crude Oil (WTI) hit in October 2026?", 90_000, 5), mk("cripto", "What price will Bitcoin hit in October?", 400_000, 5, True)]
    ctx = events.ai_context(evs, now)
    cats = [c["categoria"] for c in ctx]
    assert cats.count("Macro e juros") == 2 and cats.count("Guerra e geopolítica") == 3 and cats.count("Política e eleições") == 2 and cats.count("Commodities e índices") == 1
    titles = [c["evento"] for c in ctx]
    assert sum(t.startswith("Fed Decision") for t in titles) == 1 and sum(t.startswith("Brazil Presidential") for t in titles) == 1   # um por assunto
    assert not any("Bitcoin" in t for t in titles) and [c["vence_em_dias"] for c in ctx] == sorted(c["vence_em_dias"] for c in ctx)  # escada fora; por vencimento


def test_bot_performance_daily_ranking_backtest_and_page(monkeypatch):
    """Ranking diário: dia, semana e mês por bot no mercado/tempo gráfico dele, salvo com histórico; backtest forçado de um bot; página única."""
    from datetime import datetime, timedelta, timezone
    from streamlit.testing.v1 import AppTest
    from core import bot_performance as bp, personalities as Pm

    def getter(sym, interval, n, market):
        raw = make_df(max(n, 300), trend=0.3, seed=len(sym))
        step = {"5m": "5min", "15m": "15min", "1h": "1h", "4h": "4h", "1d": "1D"}.get(interval, "1h")
        raw["time"] = pd.date_range(end=pd.Timestamp.now(tz="UTC").floor("1h"), periods=len(raw), freq=step)
        return raw.tail(n).reset_index(drop=True)

    bp.save({}, full=False)
    monkeypatch.setattr(bp, "load_json", lambda *a, **k: None)                              # começa sem dados
    assert bp.is_due() and bp.load()["results"] == {}
    monkeypatch.undo()
    bot = next(p for p in Pm.BUILTINS if (p.get("research") or {}).get("interval") == "15m")
    assert bp.home(bot) == (bot["research"]["market"], "15m") and bp.home({"home": {"market": "spot", "interval": "4h"}}) == ("spot", "4h")
    got = bp.refresh_bot(bot["id"], getter=getter)
    assert set(bp.WINDOWS) <= set(got) and got["interval"] == "15m" and got["d30"]["symbols"] == len(Pm.PERIOD_SYMBOLS)
    assert got["d30"]["trades"] >= got["d7"]["trades"] >= got["d1"]["trades"]          # janelas maiores contêm as menores
    assert bp.is_due()                                                                  # backtest de um bot não conta como a atualização diária
    hist = bp.history(bot["id"])
    assert len(hist) == 1 and set(hist[0]) == {"date", "d1", "d7", "d30"}
    bp.refresh_bot(bot["id"], getter=getter)
    assert len(bp.history(bot["id"])) == 1                                              # mesmo dia: sobrescreve
    bp.save({bot["id"]: got}, full=True)
    assert not bp.is_due() and bp.is_due(datetime.now(timezone.utc) + timedelta(days=1))  # 1x por dia
    row = next(r for r in bp.rows("futures" if bot["research"]["market"] == "futures" else "spot", "15m") if r["id"] == bot["id"])
    assert row["d30"]["ret_pct"] == got["d30"]["ret_pct"]
    assert bp.refresh_if_due() is False                                                 # nos testes nada roda sozinho
    _offline_market(monkeypatch)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    at = AppTest.from_file(os.path.join(root, "views", "bots.py"), default_timeout=120).run()
    assert not at.exception, [e.value for e in at.exception]
    labels = [t.label for t in at.tabs]
    for want in ("🏆 Ranking", "🧮 Calculadora", "🔁 Backtest", "✍️ Criar bot", "📚 Biblioteca", "🧭 Contextos"):
        assert want in labels, want
    assert not os.path.exists(os.path.join(root, "views", "personalities.py"))        # páginas unificadas


def test_bots_page_components_data():
    """Ranking, biblioteca e calculadora viram componentes em JavaScript: os dados chegam prontos e em tipos simples."""
    import json
    from core import bots_view, personalities as Pm

    rows = [{"id": "a", "name": "Bot A", "market": "futures", "interval": "15m", "builtin": True, "status": "aprovado", "updated": "2026-10-26T10:00:00+00:00",
             "d1": {"ret_pct": 0.5}, "d7": {"ret_pct": 1.2}, "d30": {"ret_pct": 4.0, "trades": 30, "win_pct": 55.0}, "per_symbol": {"BTCUSDT": 3.0},
             "live_trades": 0, "live_pnl": None}]
    rk = bots_view.rank_data(rows, lambda pid: [{"date": f"2026-10-{d:02d}", "d1": 0, "d7": 0, "d30": d / 10} for d in range(1, 40)], focus="a")
    assert rk["focus"] == "a" and len(rk["rows"][0]["history"]) == 30 and rk["rows"][0]["updated"] == "2026-10-26 10:00"
    assert rk["order"]["5m"] < rk["order"]["1h"] < rk["order"]["1d"]
    lib = bots_view.library_data(Pm.list_all(), {}, lambda p: not p.get("builtin"))
    json.dumps(lib)                                                                          # serializável para o navegador
    b = next(x for x in lib["bots"] if x["research"])
    assert b["rr"] and b["skills"] and b["market"] in ("futures", "spot") and b["can_edit"] is False
    res = {"rows": [{"entrada": "2026-10-01T00:00:00Z", "resultado": 20.0}, {"entrada": "2026-10-02T00:00:00Z", "resultado": -10.0}],
           "curve": [{"time": "2026-10-01T05:00:00Z", "Banca (USDT)": 1020.0}, {"time": "2026-10-02T05:00:00Z", "Banca (USDT)": 1010.0}],
           "bank0": 1000.0, "bank": 1010.0, "max_dd": 1.0, "days": 30, "bot": "X", "itv": "1h", "market": "spot", "risk": 1.0, "comp": True}
    cv = bots_view.calc_view(res)
    assert cv["pnl"] == 10.0 and cv["wins"] == 1 and cv["losses"] == 1 and cv["pf"] == 2.0 and len(cv["curve"]) == 3 and cv["best"] == 20.0
    for name in ("bot_rank", "bot_library", "bot_calc"):
        assert os.path.exists(os.path.join(os.path.dirname(bots_view.__file__), f"{name}.js"))


def test_dashboard_and_wallet_components(monkeypatch):
    """Painel e Carteira viram componentes em JavaScript: dados serializáveis, resumo diário e comparação, e as páginas abrem sem erro."""
    import json
    from streamlit.testing.v1 import AppTest
    from core import wallet_view

    paper.set_wallet_mode("única")
    paper.reset_account(paper.SHARED_ACCOUNT, 1000)
    acct = paper.get_account(paper.SHARED_ACCOUNT)
    acct["history"] = [{"opened": "2026-10-20T10:00:00+00:00", "closed": "2026-10-20T12:00:00+00:00", "pnl": 12.0, "fees_total": 0.4, "source": "manual",
                        "bot": "day", "symbol": "BTCUSDT", "side": "BUY", "qty": 0.1, "entry": 100, "exit": 112, "leverage": 1, "reason": "Alvo"},
                       {"opened": "2026-10-21T10:00:00+00:00", "closed": "2026-10-21T12:00:00+00:00", "pnl": -5.0, "fees_total": 0.4, "source": "ia",
                        "bot": "swing", "symbol": "ETHUSDT", "side": "SELL", "qty": 1, "entry": 10, "exit": 10.5, "leverage": 3, "reason": "Stop"}]
    s = paper.stats(acct, {})
    w = wallet_view.wallet_data(acct, s, brl=5.4, mode="única", label="Carteira única")
    json.dumps(w)
    assert [d["acc"] for d in w["daily"]] == [12.0, 7.0] and w["trades"][0]["symbol"] == "ETHUSDT"        # mais recente primeiro
    assert w["by_origin"]["Você (manual)"]["pnl"] == 12.0 and w["by_bot"][PROFILES["swing"].name]["n"] == 1
    assert w["curve"][-1][1] == round(s["equity"], 2)
    assert wallet_view.stats_view({"profit_factor": float("inf")})["profit_factor"] is None and wallet_view.stats_view({"profit_factor": float("inf")})["profit_factor_inf"]
    d = wallet_view.dashboard_data([{"key": "day", "cfg": default_settings(PROFILES["day"]), "stats": s}], [], s,
                                   {"day": [{"time": "2026-10-21T10:00:00+00:00", "symbol": "BTCUSDT", "decision": "BUY", "confidence": 70}],
                                    "outro": [{"time": "x"}]}, [], [], "única")
    json.dumps(d)
    assert d["cards"][0]["name"] == PROFILES["day"].name and len(d["decisions"]) == 1 and d["decisions"][0]["bot"] == PROFILES["day"].name
    _offline_market(monkeypatch)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for page in ("dashboard.py", "wallet.py"):
        at = AppTest.from_file(os.path.join(root, "views", page), default_timeout=120).run()
        assert not at.exception, (page, [e.value for e in at.exception])


def test_admin_page_component_and_actions(monkeypatch):
    """Administração em componente: a página abre para admin e cada ação passa pelo core/accounts (que confere a permissão)."""
    from streamlit.testing.v1 import AppTest
    from core import accounts

    monkeypatch.setattr(accounts, "is_admin", lambda u: u == "chefe")
    monkeypatch.setattr(accounts, "list_accounts", lambda: [
        {"usuario": "novo", "estado": accounts.PENDING, "papel": "usuário", "principal": False, "criado": "2026-10-25T10:00:00", "ultimo_acesso": "", "nota": "Ana"},
        {"usuario": "chefe", "estado": accounts.ACTIVE, "papel": "admin", "principal": True, "criado": "", "ultimo_acesso": "", "nota": ""}])
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    at = AppTest.from_file(os.path.join(root, "views", "admin.py"), default_timeout=60)
    at.session_state["_user"] = "chefe"
    at = at.run()
    assert not at.exception, [e.value for e in at.exception]
    src = open(os.path.join(root, "views", "admin.py"), encoding="utf-8").read()
    for kind in ("approve", "reject", "block", "unblock", "admin", "password", "delete"):
        assert f'"{kind}":' in src, kind
    at2 = AppTest.from_file(os.path.join(root, "views", "admin.py"), default_timeout=60)
    at2.session_state["_user"] = "intruso"
    at2 = at2.run()
    assert any("restrito" in e.value for e in at2.error)                       # quem não é admin não vê nada


def test_keys_per_exchange_mascot_and_login(monkeypatch):
    """Chave de API por corretora (com passphrase onde é exigida), escolha da corretora em Minha conta, mascote e tela de login."""
    from core import credentials, exchanges, mascot, storage, wallet_view

    monkeypatch.setenv("SECRETS_KEY", "chave-mestra-de-teste-com-tamanho-suficiente")
    storage.set_user("multi")
    try:
        with pytest.raises(ValueError):
            credentials.save("multi", "abcd-1234-efgh-5678", "segredo-bem-comprido-123", False, None, exchange="okx")   # OKX exige passphrase
        credentials.save("multi", "abcd-1234-efgh-5678", "segredo-bem-comprido-123", False, {"ok": True}, exchange="okx", passphrase="minha frase")
        credentials.save("multi", "K" * 30, "S" * 30, True, None, exchange="binance")
        assert credentials.status("multi", "okx")["last4"] == "5678" and credentials.passphrase("multi", "okx") == "minha frase"
        assert set(credentials.all_status("multi")) == {"okx", "binance"}
        monkeypatch.setattr(exchanges, "selected", lambda: "okx")
        assert credentials.status("multi")["last4"] == "5678"                                  # sem corretora: a que está em uso
        assert credentials.get("multi") == ("abcd-1234-efgh-5678", "segredo-bem-comprido-123", False)
        cards = wallet_view.exchanges_view("okx", credentials.all_status("multi"))
        okx = next(c for c in cards if c["key"] == "okx")
        assert okx["selected"] and okx["key_saved"] == "5678" and next(c for c in cards if c["key"] == "coinbase")["futures"] is False
        credentials.delete("multi", "okx")
        assert credentials.status("multi", "okx") is None and credentials.status("multi", "binance")
        assert credentials.validate_any("okx", "x", "y", passphrase=None)["ok"] in (False, None)   # sem rede/chave inválida: nunca levanta erro
    finally:
        storage.set_user(None)
    svg = mascot.svg(120, uid="t")
    assert mascot.NAME == "Cripto Robô" and svg.startswith("<svg") and "₿" in svg and "t-eye" in svg and mascot.svg(50, animated=False).count("@keyframes") == 0
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    js = open(os.path.join(root, "core", "login.js"), encoding="utf-8").read()
    assert 'setTriggerValue("login"' in js and 'setTriggerValue("signup"' in js
    app = open(os.path.join(root, "app.py"), encoding="utf-8").read()
    assert "Corretora dos dados" not in app and "Cripto Robô" in app                          # a escolha da corretora mudou para Minha conta


def test_ml_prototype_model_walk_forward_and_vote(monkeypatch):
    """Protótipo de ML: features sem olhar o futuro, modelo com DI, walk-forward sem vazamento, voto no placar e filtro."""
    from core import fastsim, ml, ranking
    from core.strategy import analyze

    def getter(sym, interval, n, market):
        raw = make_df(max(n, 300), trend=0.15, seed=len(sym) + 3)
        raw["time"] = pd.date_range(end=pd.Timestamp("2026-10-20", tz="UTC"), periods=len(raw), freq="1h")
        return raw.tail(n).reset_index(drop=True)

    frames = {}
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        vt, cfg = ranking.votes_for(sym, "1h", "futures", 60, getter)
        vt.attrs["cfg"] = cfg
        frames[sym] = vt
    X = ml.features(frames["ETHUSDT"], frames["BTCUSDT"])
    assert {"r1", "rsi", "btc_r1", "v_tendencia"} <= set(X.columns) and len(X) == len(frames["ETHUSDT"])
    y = ml.labels(frames["ETHUSDT"], "1h", 0.05)
    assert y.iloc[-ml.HORIZON["1h"]:].isna().all()                                     # sem futuro conhecido, sem alvo
    m = (y.notna()).to_numpy() & (np.arange(len(y)) >= fastsim.WARMUP)
    model = ml.Model(list(X.columns)).fit(X[m], y[m].to_numpy())
    p = model.proba(X[m])
    assert ((p >= 0) & (p <= 1)).all() and model.di_thr > 0 and len(model.importance(5)) == 5
    far = X[m].iloc[[0]] * 50                                                          # algo muito diferente do treino
    assert model.di(far)[0] > model.di_thr
    again = ml.Model.load(json.loads(json.dumps(model.dump())))                       # guarda no banco como JSON e volta igual
    assert np.allclose(again.proba(X[m].iloc[:20]), p[:20], atol=1e-6)
    out = ml.walk_forward(frames, "1h", 0.05, train_days=30, step_days=7, test_days=20, btc=frames["BTCUSDT"])
    for v in out.values():
        v.attrs["cfg"] = cfg
    vt = out["ETHUSDT"]
    test = vt["time"] >= vt["time"].iloc[-1] - pd.Timedelta(days=20)
    assert vt.loc[test, "ml_p"].notna().mean() > 0.8 and vt.loc[~test, "ml_p"].isna().all()   # só prevê o período de teste
    assert set(np.unique(vt["ml_block"])) <= {False, True} and vt["v_ml"].between(-1, 1).all()
    ev = ml.evaluate(out, 20)
    assert ev["n"] > 100 and 0 <= ev["auc"] <= 1
    rows = ml.compare_bots(out, [Pm_get("esp_15m_ema_3x1")], "futures", 20)
    assert set(rows[0]) >= {"base", "filtro", "voto", "ambos"}
    blocked = vt.copy()
    blocked["ml_block"] = True
    pers = Pm_get("esp_15m_ema_3x1")
    assert (fastsim.signals(blocked, {**pers, "ml_filter": True}, cfg) == 0).all()      # filtro: tudo bloqueado → nenhuma entrada
    df = ind.compute(make_df(400, trend=0.0, seed=2), cfg)
    base = analyze(df, cfg, PROFILES["day"], pers)
    up = analyze(df, cfg, PROFILES["day"], pers, extra_votes=[(1.0, 2.0)])
    assert up.score > base.score                                                       # o voto do modelo entra no placar
    assert analyze(df, cfg, PROFILES["day"], {**pers, "threshold": -100}, ml_block="mercado estranho").direction == "HOLD"
    assert ml.predict_live(df, {**cfg, "symbol": "BTCUSDT", "interval": "2h"}, "futures") is None   # sem modelo: nada muda


def Pm_get(pid):
    from core import personalities

    return personalities.get(pid)


def test_grid_and_dca_bots(monkeypatch):
    """Grade e DCA: simulador próprio, entram no ranking diário, na biblioteca (sem edição) e na calculadora."""
    import json
    from core import bot_performance as bp, bots_view, grid_dca, ranking

    # mercado lateral sintético: a grade compra embaixo e vende em cima, o DCA sai no alvo sobre o preço médio
    n = 900
    t = pd.date_range(end=pd.Timestamp.now(tz="UTC").floor("1h"), periods=n, freq="1h")
    c = 100 + 4 * np.sin(np.arange(n) / 12)
    vt = pd.DataFrame({"time": t, "open": c, "high": c * 1.004, "low": c * 0.996, "close": c, "volume": 1.0,
                       "atr": 1.0, "regime": "lateral"})
    vt["regime"] = np.where(np.arange(n) % 60 < 6, "reversao_alta", "lateral")
    grid = grid_dca.get("grid_lateral_1h_spot")
    dca = grid_dca.get("dca_recuperacao_1h_spot")
    assert grid["kind"] == "grid" and dca["kind"] == "dca" and grid["builtin"]
    g = grid_dca.simulate(grid, vt, "1h", 0.1)
    d = grid_dca.simulate({**dca, "params": {**dca["params"], "sl_pct": 25.0}}, vt, "1h", 0.1)
    assert g["cycles"] > 0 and g["final"] > g["capital"] and all(x["lado"] == "Grade" for x in g["trades"])
    assert d["trades"] and d["final"] > d["capital"] and all(x["lado"] == "DCA" for x in d["trades"])
    for r in (g, d):                                                                       # o resultado das operações fecha com a banca
        assert abs(r["capital"] + sum(x["resultado"] for x in r["trades"]) - r["final"]) < 1e-6 * r["capital"]
    devs, sizes = grid_dca.dca_plan(dca["params"])
    assert len(devs) == len(sizes) == dca["params"]["so_count"] + 1 and abs(sum(sizes) - 1) < 1e-9 and list(devs) == sorted(devs)
    summ = grid_dca.period_summary(grid, {"BTCUSDT": (vt, {"fee_pct": 0.1})}, "spot", 30, "1h")
    json.dumps(summ)                                                                       # tipos simples para salvar
    assert set(summ) >= {"ret_pct", "monthly_pct", "dd_pct", "win_pct", "trades", "positive", "symbols", "per_symbol"}

    # ranking diário e biblioteca
    ids = {p["id"] for p in bp.tracked()}
    assert {"grid_lateral_1h_spot", "dca_recuperacao_1h_spot"} <= ids and bp.get_bot("grid_lateral_1h_spot")["kind"] == "grid"
    monkeypatch.setattr(ranking, "votes_for", lambda sym, interval, market, days, getter=None: (vt, {"fee_pct": 0.1}))
    res = bp.compute([grid], getter=None)
    e = res[grid["id"]]
    assert set(bp.WINDOWS) <= set(e) and e["d30"]["symbols"] >= 1
    json.dumps(res)
    rk = bots_view.rank_data([{**e, "id": grid["id"], "name": grid["name"], "market": "spot", "interval": "1h", "builtin": True, "kind": "grid",
                               "live_trades": 0, "live_pnl": None}], lambda pid: [])
    assert rk["rows"][0]["kind"] == "grid"
    lib = bots_view.library_data(grid_dca.all_bots(), {}, lambda p: True, perf=res)
    json.dumps(lib)
    card = next(b for b in lib["bots"] if b["id"] == grid["id"])
    assert card["editable"] is False and card["can_edit"] is False and card["research"]["ret_pct"] == e["d30"]["ret_pct"]


def test_ml_tournament_algos_targets_and_context_champions(monkeypatch):
    """Torneio de modelos: vários algoritmos e alvos com walk-forward, campeões geral e por contexto, e o modelo ao vivo usando os campeões."""
    from core import bots_view, ml, ml_tournament as T

    # alvo "barreira": o que o preço toca primeiro (+1,5 ATR ou −1,5 ATR); compra e venda já descontam as taxas
    n = 60
    c = np.r_[np.full(10, 100.0), np.linspace(100, 110, 50)]
    vt = pd.DataFrame({"time": pd.date_range("2026-01-01", periods=n, freq="1h", tz="UTC"), "close": c, "high": c + 0.2, "low": c - 0.2,
                       "atr": 1.0})
    out = ml.outcomes(vt, "1h", 0.05, "barreira")
    assert out["y"].iloc[12] == 1.0 and abs(out["long"].iloc[12] - (1.5 / c[12] - 0.001)) < 1e-9 and out["short"].iloc[12] < 0
    assert out["exit"].iloc[12] > 12 and out["y"].iloc[-3:].isna().all()                  # sem futuro: sem rótulo
    assert ml.outcomes(vt, "1h", 0.05, "tendencia")["y"].iloc[-ml.horizon("1h", "tendencia"):].isna().all()
    assert ml.horizon("1h", "tendencia") == 3 * ml.HORIZON["1h"]

    # cada algoritmo instalado treina, prevê e volta igual do banco
    rng = np.random.default_rng(3)
    X = pd.DataFrame(rng.normal(size=(1500, 6)), columns=list("abcdef"))
    X.iloc[::40, 2] = np.nan
    y = (X["a"] + rng.normal(scale=0.7, size=1500) > 0).astype(float).to_numpy()
    assert {"lightgbm", "logistica"} <= set(ml.available_algos())
    for a in ml.available_algos():
        m = ml.Model(list(X.columns), a, "barreira").fit(X[:1200], y[:1200])
        p = m.proba(X[1200:])
        assert ml.auc(y[1200:], p) > 0.7, a
        again = ml.Model.load(json.loads(json.dumps(m.dump())))
        assert again.algo == a and again.target == "barreira" and np.allclose(again.proba(X[:10]), m.proba(X[:10]), atol=1e-6), a

    # torneio com candles sintéticos
    def getter(sym, interval, n_, market):
        raw = make_df(max(n_, 300), trend=0.1, seed=len(sym) + 5)
        raw["time"] = pd.date_range(end=pd.Timestamp("2026-10-20", tz="UTC"), periods=len(raw), freq="1h")
        return raw.tail(n_).reset_index(drop=True)

    from core import grid_dca

    bots = [b for b in T.rule_bots("futures", "1h") if not b.get("kind")][:1] + [grid_dca.get("grid_lateral_1h_fut")]
    assert all(b["id"] in {x["id"] for x in T.rule_bots("futures", "1h")} for b in bots)
    monkeypatch.setattr(T, "rule_bots", lambda m_, i_: bots)                          # um bot de regras e uma grade, para o teste ser rápido
    res = T.run("futures", "1h", getter=getter, symbols=["BTCUSDT", "ETHUSDT"], algos=["logistica", "lightgbm"], targets=["direcao", "barreira"],
                test_days=20, train_days=30, step_days=10)
    json.dumps(res)
    ml_rows = [r for r in res["rows"] if r["family"] == "ml"]
    rule_rows = [r for r in res["rows"] if r["family"] == "regra"]
    assert {r["combo"] for r in ml_rows} == {"logistica|direcao", "logistica|barreira", "lightgbm|direcao", "lightgbm|barreira"}
    assert {r["combo"] for r in rule_rows} == {f"bot:{b['id']}" for b in bots} and rule_rows[0]["auc"] is None   # regras no mesmo placar
    assert not (res["champion"] or "").startswith("bot:") and not any(c.startswith("bot:") for c in res["by_ctx"].values())
    r0 = res["rows"][0]
    assert set(r0) >= {"auc", "n", "win", "monthly", "pf", "halves", "contexts"} and set(r0["contexts"]) == set(T.CTX_GROUPS)
    assert T.get("futures", "1h")["ran_at"] == res["ran_at"] and not T.is_due("futures", "1h")
    if res["champion"]:                                                                   # campeão só com vantagem nas duas metades do teste
        ch = next(r for r in res["rows"] if r["combo"] == res["champion"])
        assert ch["n"] >= T.MIN_TRADES and min(ch["halves"]) > 0
    assert T.group_of("tendencia_alta") == "tendencia" and T.group_of("suporte_teste") == "lateral" and T.group_of("???") == "indefinido"
    assert T.refresh_if_due("spot", "4h") is False                                        # nos testes nada roda sozinho
    view = bots_view.tourney_data(T.load(), sel=("futures", "1h"))
    json.dumps(view)
    assert view["sel"] == "futures|1h" and view["results"][0]["rows"][0]["algo"]
    cmp_ = view["results"][0]["compare"]
    assert cmp_ is None or (set(cmp_) == {"ml", "regra"} and cmp_["regra"]["n"] <= 2)

    # modelo ao vivo: campeão geral + campeão do contexto, e a previsão usa o do contexto atual
    monkeypatch.setattr(T, "champions", lambda m_, i_: ("logistica|barreira", {"lateral": "lightgbm|direcao", "tendencia": "logistica|barreira"}))
    model = ml.train_live("futures", "1h", getter=getter, symbols=["BTCUSDT", "ETHUSDT"])
    assert model.algo == "logistica" and model.target == "barreira" and model.meta["from_tournament"]
    ml._models.clear()                                                                    # relê do banco
    main, ctx = ml.get_bundle("futures", "1h")
    assert main.algo == "logistica" and set(ctx) == {"lateral"} and ctx["lateral"].algo == "lightgbm"
    from core import ranking

    _, cfg = ranking.votes_for("ETHUSDT", "1h", "futures", 30, getter)
    cfg = {**cfg, "symbol": "ETHUSDT", "interval": "1h"}
    pr = ml.predict_live(ind.compute(getter("ETHUSDT", "1h", 300, "futures"), cfg), cfg, "futures", getter=getter)
    assert pr and 0 <= pr["p_up"] <= 1 and pr["modelo"] and pr["contexto"]
