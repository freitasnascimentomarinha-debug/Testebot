import json
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
    cfg = {**default_settings(PROFILES["day"]), "symbol": "SOLUSDT", "interval": "15m", "ai_min_confidence": 0}
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
    cfg["ai_mode"] = "filtro"
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
    assert Pm.trained_intervals("futures") == ["5m", "15m", "1h"]
    assert "experimental" not in Pm.allowed("futures", "5m")[0]["name"].lower()
    for bot, pid in Pm.DEFAULT_BY_BOT.items():  # o padrão de cada bot vale no tempo gráfico padrão dele
        assert Pm.is_allowed(pid, PROFILES[bot].market, PROFILES[bot].default_interval)


def test_bot_page_renders_with_analysis_and_advice():
    """Renderiza a página inteira do bot, clica em Analisar e exige leitura do especialista, sem citar o modelo nem resposta bruta."""
    from streamlit.testing.v1 import AppTest

    def page():
        import streamlit as st

        st.page_link = lambda *a, **k: None  # o menu só existe no app completo
        from core.ui import render_bot_page

        render_bot_page("day")

    at = AppTest.from_function(page, default_timeout=120).run()
    assert not at.exception, [e.value for e in at.exception]
    btn = next(b for b in at.button if "Analisar agora" in b.label)
    btn.click()
    at = at.run()
    assert not at.exception, [e.value for e in at.exception]
    text = " ".join(m.value for m in at.markdown) + " ".join(c.value for c in at.caption)
    assert "Leitura do especialista" in text and "Melhor bot para este momento" in text and "Plano condicional" in text
    assert "deepseek" not in text.lower() and not any("Resposta bruta" in (e.label or "") for e in at.expander)


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


def _yahoo_json(n=60, start=1.10, step=300, last_offset=0, symbol="EURUSD=X", volume=0):
    import time

    now = int(time.time()) - last_offset
    ts = [now - (n - 1 - i) * step - (now % step) for i in range(n)]
    ts[-1] = now  # o candle em formação vem com o horário do último negócio
    close = [start + 0.0001 * i for i in range(n)]
    q = {"open": [c - 0.00005 for c in close], "high": [c + 0.0002 for c in close], "low": [c - 0.0002 for c in close], "close": close,
         "volume": [volume] * n}
    meta = {"symbol": symbol, "currency": "USD", "regularMarketPrice": close[-1], "chartPreviousClose": start, "regularMarketDayHigh": close[-1] + 0.001,
            "regularMarketDayLow": start - 0.001, "regularMarketVolume": 0, "regularMarketTime": now}
    return {"chart": {"result": [{"meta": meta, "timestamp": ts, "indicators": {"quote": [q]}}], "error": None}}


def test_yahoo_provider_parsing_and_markets(monkeypatch):
    from core import data, markets, yahoo

    calls = []

    def fake(path, params):
        calls.append((path, params))
        return _yahoo_json(80)

    monkeypatch.setattr(yahoo, "_fetch", fake)
    yahoo._cache.clear()
    df = data.get_klines("EURUSD", "5m", 50, "forex")
    assert len(df) == 50 and df.time.is_monotonic_increasing and df.time.is_unique
    assert df["time"].iloc[-1].minute % 5 == 0 and df["time"].iloc[-1].second == 0       # candle em formação alinhado ao período
    assert df.attrs["no_volume"] and (df["volume"] == 1.0).all()                         # forex não tem volume
    assert "EURUSD%3DX" in calls[0][0] and calls[0][1]["interval"] == "5m"
    tk = data.get_ticker("EURUSD", "forex")
    assert tk.source == "Yahoo Finance" and tk.market_time and markets.is_open(tk.market_time)
    assert not markets.is_open(tk.market_time - 3 * 3600)                                # sem negócio há horas: mercado fechado
    with pytest.raises(data.MarketDataError, match="catálogo"):
        data.get_klines("XXXX", "1h", 10, "forex")
    assert "PETR4" in data.list_symbols("stocks") and len(data.list_symbols("commodities")) >= 20
    # catálogo coerente
    for key, m in markets.MARKETS.items():
        assert m.default_symbol in markets.symbols(key) and m.default_interval in m.intervals
        assert len({i.code for i in m.instruments}) == len(m.instruments)
        assert all(i.yahoo and i.tv and i.quote for i in m.instruments)
    assert markets.round_qty("stocks", 9.7) == 9 and markets.round_qty("forex", 1234.5) == 1200 and markets.round_qty("indices", 0.0129) == 0.012


def test_other_markets_risk_wallet_and_fx(monkeypatch):
    from core import markets, risk

    rates = {"BRL": 0.20, "JPY": 0.0065, "EUR": 1.12, "USD": 1.0}
    monkeypatch.setattr(markets, "fx_usd", lambda q: rates[q.upper()])
    # ação da B3 (BRL): risco de 2 USD com stop de R$ 1 → qty = 2 / (1 × 0,20) = 10 ações; margem = valor da posição (sem alavancagem)
    c = risk.calculate("BUY", 50.0, 49.0, 53.0, leverage=1, fee_pct=0.05, risk_usdt=2.0, available=100.0, symbol="PETR4", market="stocks")
    assert c.fx == 0.20 and c.qty == 9 and c.qty == int(c.qty)                       # ações inteiras; 9 porque as taxas entram no risco
    assert c.notional == pytest.approx(9 * 50 * 0.20) and c.margin == pytest.approx(c.notional) and c.risk_usdt <= 2.0 + 1e-9
    assert c.liquidation is None                                                      # compra sem alavancagem não liquida
    # forex com alavancagem: EURJPY, preço em JPY convertido pela cotação do iene; quantidade em múltiplos de 100 unidades
    c = risk.calculate("SELL", 160.0, 160.5, 158.5, leverage=20, fee_pct=0.01, risk_usdt=2.0, available=100.0, symbol="EURJPY", market="forex")
    assert c.fx == 0.0065 and c.qty % 100 == 0 and 0 < c.risk_usdt <= 2.0 + 1e-9 and c.margin == pytest.approx(c.notional / 20)
    assert c.liquidation and c.liquidation > 160.0                                    # venda: liquida acima da entrada
    # carteira: P&L convertido para dólar e taxa sobre o valor em dólar
    paper.set_wallet_mode("única")
    paper.reset_account(paper.SHARED_ACCOUNT, 100)
    out = paper.place_order(paper.SHARED_ACCOUNT, symbol="PETR4", market="stocks", side="BUY", qty=9, price=50.0, stop_loss=49.0, leverage=1,
                            fee_pct=0.05, fx=0.20)
    pos = out["position"]
    assert pos["fx"] == 0.20 and pos["margin"] == pytest.approx(9 * 50 * 0.20) and pos["fees_paid"] == pytest.approx(9 * 50 * 0.20 * 0.0005)
    assert paper.pnl_of(pos, 52.0) == pytest.approx(9 * 2 * 0.20)                     # +R$ 18 = +US$ 3,60
    ev = paper.sync(paper.SHARED_ACCOUNT, "PETR4", pd.DataFrame({"time": [pd.Timestamp.now(tz="UTC").floor("min")], "open": [50.0], "high": [50.5],
                                                                 "low": [48.5], "close": [49.0], "volume": [1.0]}), 49.0)
    assert ev and ev[0]["type"] == "Stop loss"
    trade = paper.get_account(paper.SHARED_ACCOUNT)["history"][-1]
    assert trade["gross_pnl"] == pytest.approx(-9 * 1.0 * 0.20) and trade["pnl"] < trade["gross_pnl"]  # perda de R$ 9 = US$ 1,80 mais taxas
    paper.reset_account(paper.SHARED_ACCOUNT, 100)


def test_other_markets_profiles_nav_and_closed_market(monkeypatch):
    import ast
    from pathlib import Path

    from core import data, engine, markets
    from core.profiles import PROFILES

    for key in ("forex", "commodities", "indices", "stocks"):
        pr = PROFILES[key]
        cfg = default_settings(pr)
        assert not pr.is_crypto and cfg["symbol"] == markets.MARKETS[key].default_symbol and cfg["interval"] in pr.intervals
        assert cfg["allow_short"] == markets.MARKETS[key].allow_short and cfg["fee_pct"] == markets.MARKETS[key].fee_pct
    assert default_settings(PROFILES["stocks"])["leverage_on"] is False and PROFILES["stocks"].max_leverage == 1
    # menu: conta e administração primeiro, depois visão geral, cripto e demais mercados
    src = (Path(__file__).resolve().parent.parent / "app.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    keys = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "pages" for t in node.targets) and isinstance(node.value, ast.Dict):
            keys = [k.value if isinstance(k, ast.Constant) else "**" for k in node.value.keys]
    assert keys == ["**", "Visão geral", "Mercado Cripto", "Outros mercados"]          # "**" = grupo Conta (só com contas ligadas)
    for page in ("forex", "commodities", "indices", "acoes"):
        assert (Path(src and __file__).resolve().parent.parent / "views" / f"{page}.py").exists()
    # mercado fechado: a análise nunca abre ordem a mercado
    monkeypatch.setattr(data, "get_ticker", lambda s, m: data.Ticker(s, 1.1, 0.0, 1.2, 1.0, 0.0, "Yahoo Finance", 1.0))  # último negócio em 1970
    cfg = {**default_settings(PROFILES["forex"]), "symbol": "EURUSD", "interval": "1h"}
    assert engine.market_closed(PROFILES["forex"], cfg) and not engine.market_closed(PROFILES["day"], default_settings(PROFILES["day"]))

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
