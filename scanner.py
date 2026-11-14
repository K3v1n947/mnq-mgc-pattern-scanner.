#!/usr/bin/env python3
"""Expanded 15-minute futures pattern scanner (paper trading only).

Designed for CSV files produced by this repository's fetch_data.py:
    SYMBOL.csv -> timestamp,open,high,low,close

Candles and prices may be delayed. A pattern is a *pending* breakout, not an order.
"""

import csv
import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from pathlib import Path

# These are the 40 symbols presently requested by fetch_data.py.
# The scanner also discovers extra SYMBOL.csv files automatically.
EXPECTED_MARKETS = """
MNQ MES MYM M2K NQ ES YM RTY EMD MNK
MCL QM MNG QG
MGC QO SIL MHG
M6E M6B MCD M6A E7
MZS MZW MZC MZL MZM
MBT MET MSL MXP MXL MCA MLN MAV MSU
MTN MWN 10Y
""".split()

# Verified exchange tick increments (not dollar values). Other contracts are
# still pattern-scanned, but exact order levels are withheld pending verification.
# Check your trading platform's current symbol, tick increment and quote mapping.
TICKS = {
    "MNQ": "0.25", "MES": "0.25", "MYM": "1", "M2K": "0.1",
    "NQ": "0.25", "ES": "0.25", "YM": "1", "RTY": "0.1",
    "MNK": "5", "MCL": "0.01", "QM": "0.025", "MNG": "0.001",
    "QG": "0.005", "MGC": "0.1", "SIL": "0.005", "MHG": "0.0005",
    "M6E": "0.0001", "M6B": "0.0001", "MCD": "0.0001",
    "M6A": "0.0001", "MBT": "5", "MET": "0.5",
    "MSL": "0.05", "MXP": "0.0005",
    "MZS": "0.5", "MZW": "0.5", "MZC": "0.5",
    "MZL": "0.02", "MZM": "0.2", "10Y": "0.001",
}
PRIORITY = {"MNQ": 0.5, "MGC": 0.5, "MCL": 0.3}
MAX_SETUPS = 3
MAX_AGE_HOURS = 4  # Avoid presenting stale historical candles as current setups.
CENTRAL = ZoneInfo("America/Chicago")


def typical_weekend_pause(now):
    """Typical US futures weekend shutdown; do not issue signals during closure.

    This is a conservative gate, not an exchange calendar. Individual products,
    holidays, and exceptional sessions may have different opening times.
    During active sessions, the separate 4-hour freshness check still applies.
    """
    local = now.astimezone(CENTRAL)
    day = local.weekday()  # Monday=0, Sunday=6
    if day == 5:  # Saturday
        return True
    if day == 6 and local.hour < 17:  # Sunday before typical 5 PM CT reopen
        return True
    if day == 4 and local.hour >= 17:  # Friday after typical futures close
        return True
    return False


def read_candles(symbol):
    path = Path(f"{symbol}.csv")
    if not path.is_file():
        return [], "NO DATA: download file missing"
    records = []
    try:
        with path.open(newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            required = {"timestamp", "open", "high", "low", "close"}
            if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
                return [], "INVALID DATA: CSV columns missing"
            for row in reader:
                try:
                    stamp = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
                    if stamp.tzinfo is None:
                        stamp = stamp.replace(tzinfo=timezone.utc)
                    stamp = stamp.astimezone(timezone.utc)
                    candle = {k: float(row[k]) for k in ("open", "high", "low", "close")}
                    if not all(math.isfinite(v) for v in candle.values()):
                        continue
                    if (candle["low"] > candle["high"] or
                        candle["high"] < max(candle["open"], candle["close"]) or
                        candle["low"] > min(candle["open"], candle["close"])):
                        continue
                    candle["timestamp"] = stamp
                    records.append(candle)
                except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
                    continue
    except OSError as exc:
        return [], f"INVALID DATA: {exc}"
    records.sort(key=lambda r: r["timestamp"])
    # Keep the last record for duplicate timestamps.
    records = list({r["timestamp"]: r for r in records}.values())
    if len(records) < 20:
        return records, f"INSUFFICIENT DATA: {len(records)} valid candles (need 20)"
    return records, None


def price_on_tick(value, tick, upward):
    step = Decimal(tick)
    scaled = Decimal(str(value)) / step
    mode = ROUND_CEILING if upward else ROUND_FLOOR
    return (scaled.to_integral_value(rounding=mode) * step).normalize()


def analyze(symbol, candles, now):
    previous, current = candles[-2:]
    age_hours = (now - current["timestamp"]).total_seconds() / 3600
    if age_hours < -0.5:
        return None, "BAD TIMESTAMP: candle is in the future"
    if typical_weekend_pause(now):
        return None, (f"WEEKEND PAUSE: last candle {current['timestamp'].isoformat()}; "
                      "no actionable signals during typical futures weekend closure")
    if age_hours > MAX_AGE_HOURS:
        return None, (f"STALE DATA: last candle {current['timestamp'].isoformat()} "
                      f"({age_hours:.1f}h old)")

    closes = [c["close"] for c in candles]
    fast = sum(closes[-5:]) / 5
    slow = sum(closes[-20:]) / 20
    bullish = (previous["close"] < previous["open"] and
               current["close"] > current["open"] and
               current["open"] <= previous["close"] and
               current["close"] >= previous["open"])
    bearish = (previous["close"] > previous["open"] and
               current["close"] < current["open"] and
               current["open"] >= previous["close"] and
               current["close"] <= previous["open"])

    if bullish and fast > slow:
        direction = "LONG"
    elif bearish and fast < slow:
        direction = "SHORT"
    else:
        return None, "No confirmed engulfing pattern with 5/20 trend filter"

    # Use recent range to rank patterns across instruments with different prices.
    recent = candles[-15:]
    ranges = [max(c["high"] - c["low"], 0) for c in recent]
    average_range = sum(ranges) / len(ranges)
    if average_range <= 0:
        return None, "INVALID DATA: zero trading range"
    body = abs(current["close"] - current["open"])
    strength = abs(fast - slow) / average_range + body / average_range
    strength += PRIORITY.get(symbol, 0)

    result = {
        "symbol": symbol,
        "direction": direction,
        "timestamp": current["timestamp"],
        "score": strength,
        "levels": None,
    }
    tick = TICKS.get(symbol)
    if tick is None:
        return result, "PATTERN FOUND: verify exchange tick size before giving levels"

    t = float(tick)
    if direction == "LONG":
        entry = price_on_tick(current["high"] + t, tick, True)
        stop = price_on_tick(min(previous["low"], current["low"]) - t, tick, False)
        risk = entry - stop
        target = price_on_tick(float(entry + risk * 2), tick, True)
    else:
        entry = price_on_tick(current["low"] - t, tick, False)
        stop = price_on_tick(max(previous["high"], current["high"]) + t, tick, True)
        risk = stop - entry
        target = price_on_tick(float(entry - risk * 2), tick, False)
    if risk <= 0:
        return None, "INVALID DATA: stop/entry risk is nonpositive"
    result["levels"] = (entry, stop, target)
    return result, "QUALIFIED: pending breakout, not filled"


def main():
    now = datetime.now(timezone.utc)
    available_symbols = {
        f.stem.upper() for f in Path(".").glob("*.csv")
        if f.stem.isalnum() and len(f.stem) <= 5
    }
    symbol_order = EXPECTED_MARKETS + sorted(available_symbols - set(EXPECTED_MARKETS))
    rows = []
    qualified = []
    awaiting_tick_check = []
    valid_count = 0

    for symbol in symbol_order:
        candles, issue = read_candles(symbol)
        if issue:
            rows.append((symbol, issue))
            continue
        valid_count += 1
        result, status = analyze(symbol, candles, now)
        rows.append((symbol, status))
        if result:
            if result["levels"]:
                qualified.append(result)
            else:
                awaiting_tick_check.append(result)

    qualified.sort(key=lambda s: (-s["score"], s["symbol"]))
    chosen = qualified[:MAX_SETUPS]

    print("EXPANDED FUTURES PATTERN SCANNER — PAPER TRADING ONLY")
    print(f"Run time (UTC): {now.isoformat(timespec='seconds')}")
    print("Source: downloaded 15-minute Yahoo Finance futures CSVs (may be delayed).")
    local_now = now.astimezone(CENTRAL)
    print(f"Central time: {local_now.isoformat(timespec='seconds')}")
    if typical_weekend_pause(now):
        print("Session status: WEEKEND PAUSE (typical US futures schedule).")
        print("Friday candles are retained for analysis, but no new setup is actionable.")
    else:
        print("Session status: ACTIVE/OTHER; checking each candle's 4-hour freshness.")
        print("Note: holidays and individual exchange hours are not checked.")
    print(f"Markets checked: {len(symbol_order)}; valid CSVs: {valid_count}")
    print(f"Qualified setups: {len(qualified)}; shown: {len(chosen)}; "
          f"patterns awaiting tick verification: {len(awaiting_tick_check)}")
    print("\n=== TOP PAPER-TRADING SETUPS (MAX 3) ===")
    if not chosen:
        if typical_weekend_pause(now):
            print("Weekend pause: no actionable setups. Re-check after the session reopens.")
        else:
            print("No qualifying, fresh setups with verified ticks. DO NOT force a trade.")
    for rank, setup in enumerate(chosen, 1):
        entry, stop, target = setup["levels"]
        print(f"\n{rank}. {setup['symbol']} — {setup['direction']} PENDING BREAKOUT")
        print(f"Candle time (UTC): {setup['timestamp'].isoformat()}")
        print("Pattern: engulfing candle + 5/20 SMA trend filter")
        print(f"Entry trigger (not filled): {entry}")
        print(f"Illustrative stop loss:   {stop}")
        print(f"Illustrative take profit: {target}")
        print("Target reward/risk: approximately 2:1 before fees/slippage")
        print("Verify the futures contract and Plus500 quote/tick mapping before demo use.")
    if awaiting_tick_check:
        print("\n=== PATTERNS REQUIRING TICK-SIZE VERIFICATION ===")
        for setup in awaiting_tick_check:
            print(f"{setup['symbol']}: {setup['direction']} at "
                  f"{setup['timestamp'].isoformat()} — no price levels issued")
    print("\n=== FULL MARKET COVERAGE / DIAGNOSTICS ===")
    for symbol, status in rows:
        print(f"{symbol}: {status}")
    print("\nNOTE: signals are for paper-trading research, not live trade calls.")
    if valid_count == 0:
        raise SystemExit("ERROR: no valid market CSV files were available")


if __name__ == "__main__":
    main()
