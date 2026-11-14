"""Download delayed 15-minute futures candles for paper-trading scans."""

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yfinance as yf

# Try each ticker independently: some micro/mini contracts may not be
# supported by the free Yahoo Finance feed.
MARKETS = {
    symbol: f"{symbol}=F"
    for symbol in """
        MNQ MES MYM M2K NQ ES YM RTY EMD MNK
        MCL QM MNG QG
        MGC QO SIL MHG
        M6E M6B MCD M6A E7
        MZS MZW MZC MZL MZM
        MBT MET MSL MXP MXL MCA MLN MAV MSU
        MTN MWN 10Y
    """.split()
}


def fetch_data(symbol, ticker):
    print(f"Downloading {symbol} candles ({ticker})...")

    try:
        data = yf.Ticker(ticker).history(
            period="5d",
            interval="15m",
            auto_adjust=False,
        )

        if data.empty:
            print(f"{symbol}: No data available.")
            return

        data = data.dropna(subset=["Open", "High", "Low", "Close"])
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
        rows = []

        for timestamp, candle in data.iterrows():
            candle_time = timestamp.to_pydatetime().astimezone(timezone.utc)
            if candle_time > cutoff:
                continue

            rows.append({
                "timestamp": candle_time.isoformat(),
                "open": float(candle["Open"]),
                "high": float(candle["High"]),
                "low": float(candle["Low"]),
                "close": float(candle["Close"]),
            })

        if len(rows) < 20:
            print(f"{symbol}: Not enough completed candles.")
            return

        filename = Path(f"{symbol}.csv")
        with filename.open("w", newline="") as file:
            writer = csv.DictWriter(
                file,
                fieldnames=["timestamp", "open", "high", "low", "close"],
            )
            writer.writeheader()
            writer.writerows(rows)

        print(f"{symbol}: Saved {len(rows)} candles.")
        print(f"Latest candle: {rows[-1]['timestamp']}")

    except Exception as error:
        print(f"{symbol}: Download failed: {error}")


if __name__ == "__main__":
    for symbol, ticker in MARKETS.items():
        fetch_data(symbol, ticker)
