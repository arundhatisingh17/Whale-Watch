from datetime import datetime, timezone

import requests

# Coinbase's public candle endpoint - free, no API key, and reachable from the US
# (Binance's api.binance.com returns 451 here). Candles are 1-minute OHLC.
CANDLES_URL = "https://api.exchange.coinbase.com/products/{product}/candles"

# WETH tracks ETH's price, WBTC tracks BTC's, so the wrapped tokens use the same feed.
PRODUCT_FOR = {
    "WETH": "ETH-USD",
    "ETH": "ETH-USD",
    "WBTC": "BTC-USD",
    "BTC": "BTC-USD",
}

GRANULARITY = 60  # seconds per candle


def _iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def _candles(product, start_ts, end_ts):
    resp = requests.get(
        CANDLES_URL.format(product=product),
        params={"start": _iso(start_ts), "end": _iso(end_ts), "granularity": GRANULARITY},
        headers={"User-Agent": "WhaleWatch"},
        timeout=10,
    )
    resp.raise_for_status()
    # Each candle is [time, low, high, open, close, volume]; Coinbase returns newest first.
    return sorted(resp.json(), key=lambda c: c[0])


def _close_near(candles, target_ts):
    """Closing price of the candle nearest target_ts, or None if there are no candles."""
    if not candles:
        return None
    return min(candles, key=lambda c: abs(c[0] - target_ts))[4]


def price_move(product, transfer_ts, window_seconds=60):
    """Price of `product` just before the transfer and just after, and the change across it.

    Reads one window either side of the transfer, so pct_change is simply
    (price_after - price_before) / price_before. Resolution is one minute - the finest the
    keyless Coinbase feed provides. window_complete is False when the "after" candle has not
    happened yet, so that price is still provisional.
    """
    candles = _candles(product, transfer_ts - window_seconds - GRANULARITY,
                       transfer_ts + window_seconds + GRANULARITY)
    if not candles:
        return None

    before = _close_near(candles, transfer_ts - window_seconds)
    after = _close_near(candles, transfer_ts + window_seconds)
    pct = round((after - before) / before * 100, 3) if before else None

    return {
        "product": product,
        "price_before": before,
        "price_after": after,
        "pct_change": pct,
        "window_complete": candles[-1][0] >= transfer_ts + window_seconds,
    }
