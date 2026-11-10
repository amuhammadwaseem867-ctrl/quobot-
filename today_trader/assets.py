"""Catalog of the real-market assets Quotex offers, grouped, with friendly
names. (OTC versions can't be analysed: their prices come from the broker.)"""
from __future__ import annotations

FOREX_MAJORS = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD"]
FOREX_CROSSES = [
    "EURGBP", "EURJPY", "EURCHF", "EURAUD", "EURCAD", "EURNZD",
    "GBPJPY", "GBPCHF", "GBPAUD", "GBPCAD", "GBPNZD",
    "AUDJPY", "AUDCAD", "AUDCHF", "AUDNZD",
    "CADJPY", "CADCHF", "CHFJPY", "NZDJPY", "NZDCAD", "NZDCHF",
]
FOREX_EXOTICS = ["USDINR", "USDPKR", "USDTRY", "USDMXN", "USDZAR", "USDSGD", "USDBRL"]
COMMODITIES = ["XAUUSD", "XAGUSD", "USOIL", "UKOIL", "NATGAS", "COPPER", "PLATINUM"]
INDICES = ["US500", "US30", "NAS100", "GER40", "UK100", "FRA40", "EU50", "JP225", "HK50", "AUS200"]
STOCKS = [
    "AAPL", "MSFT", "AMZN", "GOOGL", "META", "TSLA", "NVDA", "NFLX", "INTC", "AMD",
    "BA", "JPM", "V", "MCD", "KO", "PFE", "JNJ", "XOM", "DIS", "CSCO", "AXP", "BABA",
]
CRYPTO = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "LTCUSDT",
    "DOTUSDT", "LINKUSDT", "TRXUSDT", "AVAXUSDT", "BCHUSDT", "ATOMUSDT", "SHIBUSDT", "TONUSDT",
]

GROUPS = {
    "majors": FOREX_MAJORS,
    "crosses": FOREX_CROSSES,
    "forex": FOREX_MAJORS + FOREX_CROSSES,
    "exotics": FOREX_EXOTICS,
    "commodities": COMMODITIES,
    "indices": INDICES,
    "stocks": STOCKS,
    "crypto": CRYPTO,
}
GROUPS["all"] = (FOREX_MAJORS + FOREX_CROSSES + FOREX_EXOTICS + COMMODITIES + INDICES + STOCKS + CRYPTO)

# What people type -> the bot's symbol
ALIASES = {
    "GOLD": "XAUUSD", "SILVER": "XAGUSD", "OIL": "USOIL", "WTI": "USOIL", "CRUDE": "USOIL",
    "BRENT": "UKOIL", "GAS": "NATGAS", "SP500": "US500", "S&P500": "US500", "SPX": "US500",
    "DOW": "US30", "DJI": "US30", "NASDAQ": "NAS100", "NDX": "NAS100", "DAX": "GER40",
    "FTSE": "UK100", "CAC": "FRA40", "NIKKEI": "JP225", "HANGSENG": "HK50",
    "APPLE": "AAPL", "MICROSOFT": "MSFT", "AMAZON": "AMZN", "GOOGLE": "GOOGL", "FACEBOOK": "META",
    "TESLA": "TSLA", "NVIDIA": "NVDA", "NETFLIX": "NFLX", "INTEL": "INTC", "BOEING": "BA",
    "MCDONALDS": "MCD", "COCACOLA": "KO", "PFIZER": "PFE", "EXXON": "XOM", "DISNEY": "DIS",
    "CISCO": "CSCO", "ALIBABA": "BABA",
    "BTC": "BTCUSDT", "BITCOIN": "BTCUSDT", "ETH": "ETHUSDT", "ETHEREUM": "ETHUSDT",
    "BNB": "BNBUSDT", "SOL": "SOLUSDT", "SOLANA": "SOLUSDT", "XRP": "XRPUSDT", "RIPPLE": "XRPUSDT",
    "ADA": "ADAUSDT", "CARDANO": "ADAUSDT", "DOGE": "DOGEUSDT", "DOGECOIN": "DOGEUSDT",
    "LTC": "LTCUSDT", "LITECOIN": "LTCUSDT", "DOT": "DOTUSDT", "LINK": "LINKUSDT", "TRX": "TRXUSDT",
    "AVAX": "AVAXUSDT", "BCH": "BCHUSDT", "ATOM": "ATOMUSDT", "SHIB": "SHIBUSDT", "TON": "TONUSDT",
}

# Bot symbol -> Yahoo Finance ticker (forex pairs are mapped automatically)
YAHOO = {
    "XAUUSD": "GC=F", "XAGUSD": "SI=F", "USOIL": "CL=F", "UKOIL": "BZ=F", "NATGAS": "NG=F",
    "COPPER": "HG=F", "PLATINUM": "PL=F",
    "US500": "^GSPC", "US30": "^DJI", "NAS100": "^NDX", "GER40": "^GDAXI", "UK100": "^FTSE",
    "FRA40": "^FCHI", "EU50": "^STOXX50E", "JP225": "^N225", "HK50": "^HSI", "AUS200": "^AXJO",
}

KIND_NAMES = {
    "forex": "Forex", "exotics": "Exotic forex", "commodities": "Commodities",
    "indices": "Indices", "stocks": "US stocks", "crypto": "Crypto",
}


def normalize(name: str) -> str:
    s = name.upper().replace("/", "").replace("-", "").replace("_", "").replace(" ", "")
    s = s.removesuffix("OTC")
    return ALIASES.get(s, s)


def kind(symbol: str) -> str:
    for k in ("forex", "exotics", "commodities", "indices", "stocks", "crypto"):
        if symbol in GROUPS[k]:
            return k
    if symbol.endswith(("USDT", "USDC")):
        return "crypto"
    if len(symbol) == 6 and symbol.isalpha():
        return "forex"
    return "stocks"


def expand(names: list[str]) -> list[str]:
    """Turn ['forex', 'gold', 'BTC'] into a de-duplicated symbol list."""
    out: list[str] = []
    for n in names:
        key = n.lower()
        items = GROUPS[key] if key in GROUPS else [normalize(n)]
        for s in items:
            if s not in out:
                out.append(s)
    return out


def catalog_text() -> str:
    lines = []
    for k in ("majors", "crosses", "exotics", "commodities", "indices", "stocks", "crypto"):
        lines.append(f"{k}: " + ", ".join(GROUPS[k]))
    return "\n".join(lines)
