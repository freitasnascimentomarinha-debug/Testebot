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


def test_check_trade_blocks_daily_goal():
    cfg = default_settings(PROFILES["day"])
    stats = {"trades_today": cfg["max_trades_day"], "pnl_today": 0, "open_positions": 0, "equity": 10000, "available": 10000}
    chk = risk.check_trade(cfg, stats, "BUY", 100, 97, 110, "futures")
    assert not chk.allowed and any("Meta" in r for r in chk.reasons)


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


def test_limit_scopes_you_vs_bot():
    from core.broker import get_broker

    paper.set_wallet_mode("única")
    paper.reset_account(paper.SHARED_ACCOUNT, 10_000)
    day, swing = get_broker("day"), get_broker("swing")
    # 2 ordens suas e 1 do bot no Day Trade; 1 do bot no Swing com prejuízo realizado
    for src in ("manual", "manual", "ia"):
        day.place_order(symbol="X", market="futures", side="BUY", qty=1, price=100, leverage=5, fee_pct=0.0, source=src)
    pos = swing.place_order(symbol="Y", market="spot", side="BUY", qty=1, price=100, fee_pct=0.0, source="ia")["position"]
    swing.close_position(pos["id"], 50)  # −50 na carteira

    cfg = default_settings(PROFILES["day"])
    cfg.update(limits_trades_scope="bot", limits_pnl_scope="bot")
    s = day.limit_stats(cfg, {"X": 100})
    assert (s["trades_today"], s["open_positions"], s["pnl_today"]) == (1, 1, 0)
    cfg.update(limits_trades_scope="pagina", limits_pnl_scope="carteira")
    s = day.limit_stats(cfg, {"X": 100})
    assert (s["trades_today"], s["open_positions"]) == (3, 3) and s["pnl_today"] == pytest.approx(-50)

    # Ordens manuais: contam as operações da página; o escopo "bot" de resultado vira "página"
    cfg.update(limits_trades_scope="bot", limits_pnl_scope="bot", max_trades_day=3, daily_max_loss=40)
    manual = day.limit_stats(cfg, {"X": 100}, manual=True)
    chk = risk.check_trade(cfg, manual, "BUY", 100, 97, 110, "futures")
    assert "operacoes" in chk.kinds and "pnl" not in chk.kinds
    assert chk.blocking(risk.MANUAL_BLOCKS["livre"]) == []
    assert chk.blocking(risk.MANUAL_BLOCKS["todos"])
    cfg["limits_pnl_scope"] = "carteira"
    chk = risk.check_trade(cfg, day.limit_stats(cfg, {"X": 100}, manual=True), "BUY", 100, 97, 110, "futures")
    assert chk.blocking(risk.MANUAL_BLOCKS["pnl"])  # perda de −50 na carteira ≥ limite de 40


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
        if pl.direction == "BUY":
            assert pl.stop_loss < pl.entry < pl.take_profit
        if pl.direction == "SELL":
            assert pl.take_profit < pl.entry < pl.stop_loss


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

def test_ai_filter_mode(monkeypatch):
    from core import ai, engine
    from core import personalities as Pm

    monkeypatch.setattr(engine, "get_funding_rate", lambda s: None)
    paper.set_wallet_mode("única")
    paper.reset_account(paper.SHARED_ACCOUNT, 10_000)
    cfg = {**default_settings(PROFILES["day"]), "symbol": "X", "personality": "esp_15m_ema_3x1", "ai_min_confidence": 0}
    df = ind.compute(make_df(400, trend=0.4, seed=21), cfg)
    plan = analyze(df, cfg, PROFILES["day"], Pm.get("esp_15m_ema_3x1"))

    def fake(decision):
        return lambda ctx, **kw: ai.AIDecision(decision=decision, entry=1.0, stop_loss=0.5, take_profit=9.0,
                                                confidence=90, reasoning="teste", source="ia")

    other = "SELL" if plan.direction == "BUY" else "BUY"
    monkeypatch.setattr(ai, "ask_ai", fake(other))
    r = engine.run_analysis(PROFILES["day"], cfg, df, float(df.close.iloc[-1]), "chave")
    assert r.decision.decision == "HOLD"  # IA contra as regras (ou sem sinal delas): vetado
    if plan.direction in ("BUY", "SELL"):
        monkeypatch.setattr(ai, "ask_ai", fake(plan.direction))
        r = engine.run_analysis(PROFILES["day"], cfg, df, float(df.close.iloc[-1]), "chave")
        assert r.decision.decision == plan.direction
        assert r.decision.stop_loss == pytest.approx(plan.stop_loss)  # usa o stop validado das regras
    monkeypatch.setattr(ai, "ask_ai", fake(other))
    r = engine.run_analysis(PROFILES["day"], {**cfg, "ai_mode": "livre"}, df, float(df.close.iloc[-1]), "chave")
    assert r.decision.decision == other  # modo livre: a IA decide
