
import csv
from pathlib import Path

TICKS = {
    "MNQ": 0.25,
    "MGC": 0.10,
    "MCL": 0.01,
    "MES": 0.25,
    "MYM": 1.00,
    "M2K": 0.10
}

def scan(symbol):
    path = Path(f"{symbol}.csv")

    if not path.exists():
        print(f"{symbol}: Waiting for candle data.")
        return

    with path.open(newline="") as file:
        candles = list(csv.DictReader(file))

    if len(candles) < 20:
        print(f"{symbol}: Need at least 20 candles.")
        return

    for candle in candles:
        for field in ("open", "high", "low", "close"):
            candle[field] = float(candle[field])

    previous, current = candles[-2:]
    closes = [c["close"] for c in candles]

    fast = sum(closes[-5:]) / 5
    slow = sum(closes[-20:]) / 20

    bullish = (
        previous["close"] < previous["open"]
        and current["close"] > current["open"]
        and current["open"] <= previous["close"]
        and current["close"] >= previous["open"]
    )

    bearish = (
        previous["close"] > previous["open"]
        and current["close"] < current["open"]
        and current["open"] >= previous["close"]
        and current["close"] <= previous["open"]
    )

    tick = TICKS[symbol]

    if bullish and fast > slow:
        direction = "LONG"
        entry = current["high"] + tick
        stop = min(previous["low"], current["low"]) - tick
        target = entry + 2 * (entry - stop)

    elif bearish and fast < slow:
        direction = "SHORT"
        entry = current["low"] - tick
        stop = max(previous["high"], current["high"]) + tick
        target = entry - 2 * (stop - entry)

    else:
        print(f"{symbol}: No confirmed setup.")
        return

    print(f"\n{symbol} - {direction} SETUP")
    print(f"Candle time: {current['timestamp']}")
    print("Pattern: Engulfing candle")
    print(f"Entry trigger: {entry:.2f}")
    print(f"Stop loss: {stop:.2f}")
    print(f"Take profit: {target:.2f}")
    print("Reward/risk: 2:1")
    print("PAPER TRADING ONLY")

for market in ("MNQ", "MGC", "MCL", "MES", "MYM", "M2K"):
    scan(market)
