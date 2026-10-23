"""Mercados além da cripto: Forex, Commodities, Índices e Ações da B3 (dados do Yahoo Finance, carteira simulada em dólar).

Cada instrumento tem um código curto (ex.: ``EURUSD``, ``GC``, ``BVSP``, ``PETR4``), o símbolo do Yahoo, o símbolo do TradingView e a
moeda em que o preço é cotado. A carteira da plataforma é em dólar (USDT ≈ USD): lucros e perdas em outras moedas (BRL, JPY, EUR…)
são convertidos pela cotação do momento (``fx_usd``).

As regras são simulações educativas: alavancagem, spread e corretagem aproximados, sem swap overnight, sem dividendos e sem
restrições de lote da corretora. Ações da B3 só compradas, sem alavancagem."""
from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass

CRYPTO_MARKETS = ("futures", "spot")

_CCY = {"EUR": "Euro", "USD": "Dólar", "GBP": "Libra", "JPY": "Iene", "CHF": "Franco suíço", "AUD": "Dólar australiano", "CAD": "Dólar canadense",
        "NZD": "Dólar neozelandês", "BRL": "Real", "MXN": "Peso mexicano", "ZAR": "Rand sul-africano", "TRY": "Lira turca", "SEK": "Coroa sueca",
        "NOK": "Coroa norueguesa", "SGD": "Dólar de Singapura", "HKD": "Dólar de Hong Kong"}


@dataclass(frozen=True)
class Instrument:
    code: str
    yahoo: str
    name: str
    quote: str          # moeda em que o preço é cotado
    tv: str             # símbolo no TradingView
    group: str = ""


@dataclass(frozen=True)
class MarketInfo:
    key: str
    label: str            # nome na tela
    icon: str
    instruments: tuple
    intervals: tuple
    default_interval: str
    default_symbol: str
    max_leverage: int
    default_leverage: int
    fee_pct: float        # por lado (spread/corretagem aproximados)
    slippage_pct: float
    qty_step: float       # menor fração negociável
    allow_short: bool
    delay_note: str
    unit: str             # como a quantidade é chamada
    description: str


def _fx() -> tuple:
    pairs = ("EURUSD GBPUSD USDJPY USDCHF AUDUSD USDCAD NZDUSD EURGBP EURJPY GBPJPY AUDJPY EURCHF EURAUD EURCAD GBPCHF GBPAUD CHFJPY CADJPY NZDJPY AUDNZD "
             "USDBRL EURBRL GBPBRL USDMXN USDZAR USDTRY USDSEK USDNOK USDSGD USDHKD").split()
    out = []
    for p in pairs:
        a, b = p[:3], p[3:]
        grp = "Principais" if p in "EURUSD GBPUSD USDJPY USDCHF AUDUSD USDCAD NZDUSD".split() else "Reais (BRL)" if "BRL" in p else \
            "Cruzamentos" if "USD" not in p else "Exóticos"
        out.append(Instrument(p, f"{p}=X", f"{a}/{b} — {_CCY[a]} × {_CCY[b]}", b, f"FX_IDC:{p}", grp))
    return tuple(out)


_COM = (
    ("CL", "Petróleo WTI", "NYMEX:CL1!", "Energia"), ("BZ", "Petróleo Brent", "ICEEUR:BRN1!", "Energia"), ("NG", "Gás natural", "NYMEX:NG1!", "Energia"),
    ("RB", "Gasolina", "NYMEX:RB1!", "Energia"), ("HO", "Óleo de aquecimento", "NYMEX:HO1!", "Energia"),
    ("GC", "Ouro", "COMEX:GC1!", "Metais"), ("SI", "Prata", "COMEX:SI1!", "Metais"), ("PL", "Platina", "NYMEX:PL1!", "Metais"),
    ("PA", "Paládio", "NYMEX:PA1!", "Metais"), ("HG", "Cobre", "COMEX:HG1!", "Metais"),
    ("ZC", "Milho", "CBOT:ZC1!", "Agro"), ("ZS", "Soja", "CBOT:ZS1!", "Agro"), ("ZW", "Trigo", "CBOT:ZW1!", "Agro"), ("ZO", "Aveia", "CBOT:ZO1!", "Agro"),
    ("ZL", "Óleo de soja", "CBOT:ZL1!", "Agro"), ("ZM", "Farelo de soja", "CBOT:ZM1!", "Agro"), ("KC", "Café", "ICEUS:KC1!", "Agro"),
    ("SB", "Açúcar", "ICEUS:SB1!", "Agro"), ("CT", "Algodão", "ICEUS:CT1!", "Agro"), ("CC", "Cacau", "ICEUS:CC1!", "Agro"),
    ("LE", "Boi gordo", "CME:LE1!", "Pecuária"), ("HE", "Porco magro", "CME:HE1!", "Pecuária"), ("OJ", "Suco de laranja", "ICEUS:OJ1!", "Agro"),
)
_IDX = (
    ("BVSP", "^BVSP", "Ibovespa (Brasil)", "BRL", "BMFBOVESPA:IBOV"), ("GSPC", "^GSPC", "S&P 500 (EUA)", "USD", "SP:SPX"),
    ("NDX", "^NDX", "Nasdaq 100 (EUA)", "USD", "NASDAQ:NDX"), ("DJI", "^DJI", "Dow Jones (EUA)", "USD", "DJ:DJI"),
    ("RUT", "^RUT", "Russell 2000 (EUA)", "USD", "TVC:RUT"), ("GDAXI", "^GDAXI", "DAX (Alemanha)", "EUR", "XETR:DAX"),
    ("FTSE", "^FTSE", "FTSE 100 (Reino Unido)", "GBP", "FTSE:UKX"), ("FCHI", "^FCHI", "CAC 40 (França)", "EUR", "EURONEXT:PX1"),
    ("STOXX50E", "^STOXX50E", "Euro Stoxx 50 (Europa)", "EUR", "TVC:SX5E"), ("IBEX", "^IBEX", "IBEX 35 (Espanha)", "EUR", "BME:IBC"),
    ("N225", "^N225", "Nikkei 225 (Japão)", "JPY", "TVC:NI225"), ("HSI", "^HSI", "Hang Seng (Hong Kong)", "HKD", "TVC:HSI"),
    ("KS11", "^KS11", "Kospi (Coreia do Sul)", "KRW", "KRX:KOSPI"), ("SSEC", "000001.SS", "Xangai Composto (China)", "CNY", "SSE:000001"),
    ("AXJO", "^AXJO", "ASX 200 (Austrália)", "AUD", "ASX:XJO"), ("GSPTSE", "^GSPTSE", "S&P/TSX (Canadá)", "CAD", "TSX:TSX"),
    ("BSESN", "^BSESN", "Sensex (Índia)", "INR", "BSE:SENSEX"), ("TWII", "^TWII", "Taiex (Taiwan)", "TWD", "TWSE:TAIEX"),
    ("MXX", "^MXX", "IPC (México)", "MXN", "BMV:ME"),
)
_B3 = (
    ("PETR4", "Petrobras PN", "Energia"), ("VALE3", "Vale ON", "Mineração"), ("ITUB4", "Itaú Unibanco PN", "Bancos"), ("BBDC4", "Bradesco PN", "Bancos"),
    ("BBAS3", "Banco do Brasil ON", "Bancos"), ("SANB11", "Santander Brasil", "Bancos"), ("BPAC11", "BTG Pactual", "Bancos"), ("ITSA4", "Itaúsa PN", "Bancos"),
    ("ABEV3", "Ambev ON", "Consumo"), ("WEGE3", "WEG ON", "Indústria"), ("B3SA3", "B3 ON", "Financeiro"), ("SUZB3", "Suzano ON", "Papel e celulose"),
    ("KLBN11", "Klabin", "Papel e celulose"), ("RENT3", "Localiza ON", "Serviços"), ("LREN3", "Lojas Renner ON", "Varejo"), ("MGLU3", "Magazine Luiza ON", "Varejo"),
    ("RADL3", "Raia Drogasil ON", "Varejo"), ("ASAI3", "Assaí ON", "Varejo"), ("PCAR3", "Pão de Açúcar ON", "Varejo"), ("PRIO3", "PRIO ON", "Energia"),
    ("VBBR3", "Vibra Energia ON", "Energia"), ("UGPA3", "Ultrapar ON", "Energia"), ("CSAN3", "Cosan ON", "Energia"), ("ENEV3", "Eneva ON", "Energia elétrica"),
    ("GGBR4", "Gerdau PN", "Siderurgia"), ("GOAU4", "Metalúrgica Gerdau PN", "Siderurgia"), ("CSNA3", "CSN ON", "Siderurgia"), ("USIM5", "Usiminas PNA", "Siderurgia"),
    ("EQTL3", "Equatorial ON", "Energia elétrica"), ("CMIG4", "Cemig PN", "Energia elétrica"), ("TAEE11", "Taesa", "Energia elétrica"),
    ("ENGI11", "Energisa", "Energia elétrica"), ("CPFE3", "CPFL Energia ON", "Energia elétrica"), ("EGIE3", "Engie Brasil ON", "Energia elétrica"),
    ("SBSP3", "Sabesp ON", "Saneamento"), ("HAPV3", "Hapvida ON", "Saúde"), ("RDOR3", "Rede D'Or ON", "Saúde"), ("FLRY3", "Fleury ON", "Saúde"),
    ("HYPE3", "Hypera ON", "Saúde"), ("QUAL3", "Qualicorp ON", "Saúde"), ("RAIL3", "Rumo ON", "Logística"), ("VIVT3", "Vivo ON", "Telecom"),
    ("TIMS3", "TIM ON", "Telecom"), ("NATU3", "Natura ON", "Consumo"), ("ALPA4", "Alpargatas PN", "Consumo"), ("BEEF3", "Minerva ON", "Alimentos"),
    ("SMTO3", "São Martinho ON", "Alimentos"), ("SLCE3", "SLC Agrícola ON", "Agro"), ("TOTS3", "Totvs ON", "Tecnologia"), ("LWSA3", "Locaweb ON", "Tecnologia"),
    ("CASH3", "Méliuz ON", "Tecnologia"), ("COGN3", "Cogna ON", "Educação"), ("YDUQ3", "Yduqs ON", "Educação"), ("CYRE3", "Cyrela ON", "Construção"),
    ("MRVE3", "MRV ON", "Construção"), ("MULT3", "Multiplan ON", "Shoppings"), ("CVCB3", "CVC ON", "Turismo"), ("BBSE3", "BB Seguridade ON", "Seguros"),
    ("IRBR3", "IRB Brasil ON", "Seguros"), ("BRAP4", "Bradespar PN", "Mineração"),
)

MARKETS: dict[str, MarketInfo] = {
    "forex": MarketInfo(
        key="forex", label="Forex", icon="💱", instruments=_fx(), intervals=("5m", "15m", "30m", "1h", "4h", "1d"), default_interval="4h",
        default_symbol="EURUSD", max_leverage=30, default_leverage=10, fee_pct=0.01, slippage_pct=0.005, qty_step=100.0, allow_short=True,
        delay_note="Cotações do Yahoo Finance, quase em tempo real. Mercado aberto de domingo à noite a sexta à noite (UTC).",
        unit="unidades da moeda base", description="Pares de moedas, comprado ou vendido, com alavancagem simulada de até 30×."),
    "commodities": MarketInfo(
        key="commodities", label="Commodities", icon="🛢️",
        instruments=tuple(Instrument(c, f"{c}=F", n, "USD", tv, g) for c, n, tv, g in _COM), intervals=("15m", "30m", "1h", "4h", "1d"),
        default_interval="4h", default_symbol="GC", max_leverage=20, default_leverage=5, fee_pct=0.03, slippage_pct=0.01, qty_step=0.01,
        allow_short=True, delay_note="Contratos futuros contínuos (Yahoo Finance), com possível atraso de até 15 min. Há pausa diária e fecham no fim de semana.",
        unit="unidades do contrato", description="Petróleo, gás, metais, grãos e outros contratos futuros, simulados como CFDs (compra e venda)."),
    "indices": MarketInfo(
        key="indices", label="Índices", icon="📈",
        instruments=tuple(Instrument(c, y, n, q, tv, "Brasil" if c == "BVSP" else "Mundo") for c, y, n, q, tv in _IDX),
        intervals=("15m", "30m", "1h", "4h", "1d"), default_interval="1h", default_symbol="BVSP", max_leverage=20, default_leverage=5,
        fee_pct=0.02, slippage_pct=0.01, qty_step=0.001, allow_short=True,
        delay_note="Cotações do Yahoo Finance, com possível atraso de até 15 min. Cada bolsa opera no seu horário.",
        unit="unidades do índice", description="Ibovespa e principais bolsas do mundo, simulados como CFDs (compra e venda) com alavancagem de até 20×."),
    "stocks": MarketInfo(
        key="stocks", label="Ações Brasil (B3)", icon="🇧🇷",
        instruments=tuple(Instrument(c, f"{c}.SA", f"{c} — {n}", "BRL", f"BMFBOVESPA:{c}", g) for c, n, g in _B3),
        intervals=("5m", "15m", "30m", "1h", "1d"), default_interval="1h", default_symbol="PETR4", max_leverage=1, default_leverage=1,
        fee_pct=0.05, slippage_pct=0.03, qty_step=1.0, allow_short=False,
        delay_note="Ações da B3 pelo Yahoo Finance, com atraso de cerca de 15 min. Pregão das 10h às 17h55 (Brasília), de segunda a sexta.",
        unit="ações", description="Ações brasileiras à vista, só compradas, sem alavancagem, em reais convertidos para a carteira em dólar."),
}
_BY_CODE = {m: {i.code: i for i in info.instruments} for m, info in MARKETS.items()}


def is_crypto(market: str) -> bool:
    return market in CRYPTO_MARKETS


def info(market: str) -> MarketInfo:
    return MARKETS[market]


def symbols(market: str) -> list[str]:
    return [i.code for i in MARKETS[market].instruments]


def instrument(market: str, code: str) -> Instrument:
    try:
        return _BY_CODE[market][code]
    except KeyError:
        raise KeyError(f"{code} não está no catálogo de {market}") from None


def yahoo_symbol(market: str, code: str) -> str:
    return instrument(market, code).yahoo


def tv_symbol(market: str, code: str) -> str:
    return instrument(market, code).tv


def display_name(market: str, code: str) -> str:
    i = _BY_CODE.get(market, {}).get(code)
    return f"{code} · {i.name}" if i and not i.name.startswith(code) else (i.name if i else code)


# ------------------------------------------------------------------------------ conversão de moeda
_fx_cache: dict = {}
_fx_lock = threading.Lock()
FX_TTL = 120


def fx_usd(quote: str) -> float:
    """Quantos dólares vale 1 unidade da moeda de cotação (USD = 1). Usa o último valor conhecido se o Yahoo falhar."""
    quote = quote.upper()
    if quote == "USD":
        return 1.0
    now = time.time()
    with _fx_lock:
        hit = _fx_cache.get(quote)
        if hit and now - hit[0] < FX_TTL:
            return hit[1]
    from core import yahoo

    value = None
    for sym, inv in ((f"{quote}USD=X", False), (f"USD{quote}=X", True)):
        try:
            last = yahoo.quote(sym)["last"]
            if last > 0:
                value = 1 / last if inv else last
                break
        except Exception:  # noqa: BLE001
            continue
    with _fx_lock:
        if value is None:
            if hit:
                return hit[1]
            raise RuntimeError(f"Sem cotação para converter {quote} em dólar agora.")
        _fx_cache[quote] = (now, value)
    return value


def fx_for(market: str, code: str) -> float:
    """Fator de conversão do preço do instrumento para dólar (1.0 na cripto, cotada em USDT)."""
    if is_crypto(market):
        return 1.0
    return fx_usd(instrument(market, code).quote)


# ------------------------------------------------------------------------------ quantidade e horário
def round_qty(market: str, qty: float) -> float:
    if qty <= 0:
        return 0.0
    step = MARKETS[market].qty_step
    return math.floor(qty / step + 1e-9) * step if step >= 1 else round(math.floor(qty / step + 1e-9) * step, 6)


def is_open(market_time: float | None, now: float | None = None, tolerance_min: float = 30.0) -> bool:
    """Mercado aberto = houve negócio recente (o Yahoo atrasa até ~15 min em alguns mercados)."""
    if not market_time:
        return False
    return ((now or time.time()) - market_time) <= tolerance_min * 60
