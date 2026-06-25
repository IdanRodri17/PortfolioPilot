"""
yfinance wrapper for stock price retrieval.

Single point of contact with the yfinance library. Nodes never import
yfinance directly — they call functions defined here.

Why the wrapper:
    - Testability: this function is trivial to mock or call in isolation.
    - Replaceability: if yfinance is rate-limited (SRS section 12), the
      swap to Alpha Vantage or another provider stays contained to this file.
    - Error contract: yfinance has several failure modes (empty data on
      invalid tickers, exceptions on network issues, silent partials on
      rate limits). The wrapper normalizes them into one exception.

Concurrency note:
    yfinance is synchronous and blocks the event loop. V1 calls it directly
    (acceptable for a single-symbol demo). V2+ will wrap calls with
    asyncio.to_thread + asyncio.gather to parallelize multi-asset fetches.
"""

import threading
import time
from datetime import date, timedelta
from functools import lru_cache

import httpx
import yfinance as yf


class StockDataError(Exception):
    """Raised when stock price data cannot be retrieved for a symbol."""


# Curated crypto tickers -> CoinGecko coin ids (V16). CoinGecko prices by id and
# many coins share a ticker, so we map the common ones explicitly rather than do
# an ambiguous symbol->id lookup. Extend as holdings require.
CRYPTO_IDS: dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "ADA": "cardano",
    "XRP": "ripple",
    "DOGE": "dogecoin",
    "DOT": "polkadot",
    "MATIC": "matic-network",
    "LTC": "litecoin",
    "LINK": "chainlink",
    "AVAX": "avalanche-2",
    "BNB": "binancecoin",
    "USDT": "tether",
    "USDC": "usd-coin",
}

_COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"


def is_crypto(symbol: str) -> bool:
    """True if `symbol` is a known crypto ticker (priced via CoinGecko)."""
    return symbol.strip().upper() in CRYPTO_IDS


def is_tase(symbol: str) -> bool:
    """True if `symbol` is a Tel Aviv Stock Exchange ticker (yfinance ".TA")."""
    return symbol.strip().upper().endswith(".TA")


def _normalize_money(currency_code: str | None, price: float) -> tuple[str, float]:
    """Map a quoted price to a display currency + amount (V16).

    Yahoo quotes TASE in agorot ('ILA' = 1/100 of a shekel), so agorot is
    converted to shekels and tagged ILS. ILS stays ILS; everything else falls
    back to USD (the app's base currency).
    """
    code = (currency_code or "USD").upper()
    if code == "ILA":
        return "ILS", round(price / 100, 2)
    if code == "ILS":
        return "ILS", round(price, 2)
    return "USD", round(price, 2)


_FX_FALLBACK = 3.7
_FX_TTL_SECONDS = 3600.0
# {"rate": float, "ts": monotonic-seconds}. Only *successful* fetches are stored,
# so a transient failure (e.g. a network hiccup at startup) can never poison the
# value for the life of the process — the next call simply retries.
_fx_cache: dict[str, float] = {}
# Serializes the read-check-fetch-write cycle so concurrent callers (multiple
# reports, the alert sweep — and now risk_agent's P/L) can't write a half-updated
# cache or stampede the fetch (V20).
_fx_lock = threading.Lock()


def _ils_per_usd() -> float:
    """ILS per 1 USD (yfinance 'ILS=X'), for converting TASE values into the
    USD base so a mixed-currency portfolio aggregates correctly. Cached for an
    hour on success only; on failure it reuses the last good rate (even if stale)
    or a sane default, without caching it so a recovered network is picked up.
    Thread-safe: the whole check-fetch-write cycle is guarded by _fx_lock."""
    with _fx_lock:
        now = time.monotonic()
        rate = _fx_cache.get("rate")
        ts = _fx_cache.get("ts", 0.0)
        if rate is not None and (now - ts) < _FX_TTL_SECONDS:
            return rate
        try:
            hist = yf.Ticker("ILS=X").history(period="5d")
            if not hist.empty:
                fresh = float(hist["Close"].iloc[-1])
                if fresh > 0:
                    _fx_cache["rate"] = fresh
                    _fx_cache["ts"] = now
                    return fresh
        except Exception:
            pass
        return rate if rate is not None else _FX_FALLBACK


def usd_ils_rate() -> float:
    """Public accessor for the USD->ILS rate (ILS per 1 USD) — used by the
    base-currency display toggle (V17)."""
    return _ils_per_usd()


def fetch_crypto_data(symbol: str) -> dict:
    """Fetch latest USD price + 24h change for a crypto symbol via CoinGecko.

    Returns the same {"price", "change_24h_percent"} shape as fetch_stock_data,
    so data_ingestion and risk_agent treat crypto and stocks uniformly. Raises
    StockDataError on any failure (unknown coin, network, malformed response) so
    the existing per-asset error tolerance applies.
    """
    coin_id = CRYPTO_IDS.get(symbol.strip().upper())
    if coin_id is None:
        raise StockDataError(f"Unknown crypto symbol '{symbol}'.")
    try:
        resp = httpx.get(
            _COINGECKO_URL,
            params={
                "ids": coin_id,
                "vs_currencies": "usd",
                "include_24hr_change": "true",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()[coin_id]
        price = data["usd"]
        change = data.get("usd_24h_change", 0.0)
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise StockDataError(
            f"Could not fetch crypto price for '{symbol}': {exc}"
        ) from exc
    return {
        "price": round(float(price), 2),
        "change_24h_percent": round(float(change), 2),
        "currency": "USD",
    }


def fetch_stock_data(symbol: str) -> dict:
    """Fetch latest price and 24h percent change for a single stock symbol.

    Args:
        symbol: Stock ticker, e.g., "AAPL". yfinance supports TASE
            tickers via the ".TA" suffix (e.g., "TEVA.TA").

    Returns:
        Dict with shape {"price": float, "change_24h_percent": float},
        matching the per-asset payload expected in
        PortfolioState.market_data.

    Raises:
        StockDataError: if no usable history is returned (invalid ticker,
            delisted, or yfinance rate-limited).
    """
    ticker = yf.Ticker(symbol)

    # period="5d" gives breathing room around weekends and US market
    # holidays — we always need at least two trading days for a 24h delta.
    history = ticker.history(period="5d")

    # yfinance can include rows with a NaN Close (an unfinished current-day bar,
    # a holiday gap). Drop them — a NaN price would otherwise poison composition,
    # P/L, and the JSON payload (NaN is not valid JSON and crashes the client).
    history = history.dropna(subset=["Close"])

    if history.empty or len(history) < 2:
        raise StockDataError(
            f"No usable price history for symbol '{symbol}'. "
            f"Check the ticker is valid and yfinance is not rate-limited."
        )

    latest_close = float(history["Close"].iloc[-1])
    previous_close = float(history["Close"].iloc[-2])
    change_24h_percent = (
        ((latest_close - previous_close) / previous_close) * 100
        if previous_close
        else 0.0
    )

    # TASE (.TA) is quoted in agorot (1/100 ₪). Convert agorot -> ILS -> USD so
    # the whole portfolio aggregates in one base currency (USD); a mixed ILS+USD
    # portfolio would otherwise count shekels as dollars. The editor still shows
    # the native ₪ per-share price via lookup_symbol.
    if is_tase(symbol):
        price = (latest_close / 100) / _ils_per_usd()
    else:
        price = latest_close

    return {
        "price": round(price, 2),
        "change_24h_percent": round(change_24h_percent, 2),
        "currency": "USD",
    }


def fetch_trending_quotes(symbols: list[str]) -> dict[str, dict]:
    """Batch price + 24h change for a list of US symbols in ONE yfinance call (V22).

    Used by the trending card, which needs ~10-12 quotes at once — per-symbol
    fetches would be slow and rate-limit-prone, so we use yf.download (a single
    request). NaN-safe (drops incomplete bars); returns {symbol: {price,
    change_24h_percent}} for whatever resolves. Best-effort: any failure yields a
    partial/empty dict rather than raising (the caller degrades gracefully).
    """
    out: dict[str, dict] = {}
    if not symbols:
        return out
    try:
        df = yf.download(
            symbols, period="5d", progress=False, auto_adjust=True, threads=True
        )
    except Exception:  # noqa: BLE001 — trending is non-critical; degrade
        logger.warning("fetch_trending_quotes: batch download failed")
        return out
    if df is None or getattr(df, "empty", True):
        return out
    try:
        close = df["Close"]
    except Exception:  # noqa: BLE001
        return out

    multi = hasattr(close, "columns")  # DataFrame (many tickers) vs Series (one)
    for symbol in symbols:
        try:
            series = close[symbol] if multi else close
            series = series.dropna()
            if len(series) < 2:
                continue
            latest = float(series.iloc[-1])
            previous = float(series.iloc[-2])
            if not (latest > 0 and previous > 0):
                continue
            out[symbol] = {
                "price": round(latest, 2),
                "change_24h_percent": round((latest - previous) / previous * 100, 2),
            }
        except Exception:  # noqa: BLE001 — skip one bad ticker, keep the rest
            continue
    return out


@lru_cache(maxsize=512)
def _lookup_symbol_cached(symbol: str) -> dict | None:
    """Cached inner lookup; `symbol` must already be normalized.

    lru_cache memoizes both a hit (the result dict) and a clean miss (None),
    but does NOT cache exceptions — so a transient fetch failure is retried on
    the next call rather than being stuck.
    """
    ticker = yf.Ticker(symbol)
    try:
        # .info is the canonical source for the company name, but it is slow
        # and rate-limit-prone — which is exactly why this is cached.
        info = ticker.info
    except Exception as exc:  # network error, rate-limit, or yfinance internals
        raise StockDataError(f"Could not look up symbol '{symbol}': {exc}") from exc

    name = info.get("longName") or info.get("shortName")
    raw_price = (
        info.get("regularMarketPrice")
        or info.get("currentPrice")
        or info.get("previousClose")
    )
    if not name or raw_price is None:
        # yfinance returns a sparse/empty info dict for an unknown ticker.
        return None
    # Use the quoted currency (agorot-aware) so the editor shows ₪ for TASE.
    currency, price = _normalize_money(info.get("currency"), float(raw_price))
    return {"name": name, "price": price, "currency": currency}


def lookup_symbol(symbol: str) -> dict | None:
    """Validate a ticker and return its company name + latest price.

    Args:
        symbol: Stock ticker, e.g. "AAPL". Case/whitespace insensitive.

    Returns:
        {"name": str, "price": float} for a known ticker, or None for an
        unknown one.

    Raises:
        StockDataError: only on a real fetch failure (network error or
            rate-limit) — NOT for an unknown ticker, which returns None. This
            split lets callers distinguish "typo" (block save) from "provider
            down" (allow save with a soft warning).
    """
    symbol = symbol.strip().upper()
    if not symbol:
        return None
    if is_crypto(symbol):
        # Known crypto -> price via CoinGecko; a fetch failure raises (caller
        # soft-warns), never a "not found" since it's in our map.
        data = fetch_crypto_data(symbol)
        return {
            "name": CRYPTO_IDS[symbol].replace("-", " ").title(),
            "price": data["price"],
            "currency": "USD",
        }
    return _lookup_symbol_cached(symbol)


@lru_cache(maxsize=512)
def _get_sector_cached(symbol: str) -> str:
    """Cached inner sector lookup; `symbol` must already be normalized."""
    try:
        sector = yf.Ticker(symbol).info.get("sector")
    except Exception:  # network, rate-limit, or partial/empty .info dict
        return "Uncategorized"
    return sector or "Uncategorized"


def get_sector(symbol: str) -> str:
    """Return an asset's sector via yfinance `.info`, cached per symbol.

    Never raises: a missing sector, an unknown ticker, or any fetch failure all
    degrade to "Uncategorized" (same posture as a failed news fetch), so one
    bad lookup never fails the macro branch. `.info` is slow and
    rate-limit-prone, hence the cache.
    """
    symbol = symbol.strip().upper()
    if not symbol:
        return "Uncategorized"
    return _get_sector_cached(symbol)


@lru_cache(maxsize=1024)
def _price_on_cached(symbol: str, iso_date: str) -> float | None:
    """Cached inner price-on-date; `symbol` normalized, `iso_date` = YYYY-MM-DD."""
    target = date.fromisoformat(iso_date)
    # Look back ~6 calendar days so a weekend + a holiday still resolve to the
    # nearest prior trading day. yfinance's `end` is exclusive, hence +1 day.
    start = (target - timedelta(days=6)).isoformat()
    end = (target + timedelta(days=1)).isoformat()
    try:
        hist = yf.Ticker(symbol).history(start=start, end=end)
    except Exception:  # network, rate-limit, invalid symbol
        return None
    if hist.empty:
        return None
    # History is date-ordered; the last row is the trading day on/before target.
    return round(float(hist["Close"].iloc[-1]), 2)


def price_on(symbol: str, on: date) -> float | None:
    """Closing price for `symbol` on `on`, or the nearest prior trading day.

    Returns None if nothing is retrievable (delisted, invalid, or a yfinance
    failure). Never raises — callers (V13 advice grading) degrade an
    unretrievable price to "insufficient_data". Cached per (symbol, date).
    """
    symbol = symbol.strip().upper()
    if not symbol:
        return None
    return _price_on_cached(symbol, on.isoformat())
