"""
Ежедневное обновление ряда Kalshi KXZELENSKYPUTIN-29-VPUT.
- Пытается взять candles за пропущенный диапазон.
- Если candles пустые, использует market last_price как snapshot за сегодня.
"""
import os
import requests
import pandas as pd
from datetime import datetime, timezone

WORKDIR = os.environ.get("WORKDIR", "/home/user/workspace")

TICKER = "KXZELENSKYPUTIN-29-VPUT"
SERIES = "KXZELENSKYPUTIN-29"
CSV_PATH = f"{WORKDIR}/kalshi_{TICKER}.csv"
BASE = "https://api.elections.kalshi.com/trade-api/v2"


def fetch_candles(start_ts, end_ts):
    url = f"{BASE}/series/{SERIES}/markets/{TICKER}/candlesticks"
    r = requests.get(url, params={
        "start_ts": start_ts, "end_ts": end_ts, "period_interval": 1440
    }, timeout=30)
    r.raise_for_status()
    candles = r.json().get("candlesticks", [])
    rows = []
    for c in candles:
        ts = c["end_period_ts"]
        p = None
        price = c.get("price", {})
        if price.get("close_dollars"):
            p = float(price["close_dollars"])
        elif price.get("mean_dollars"):
            p = float(price["mean_dollars"])
        else:
            bid = c.get("yes_bid", {}).get("close_dollars")
            ask = c.get("yes_ask", {}).get("close_dollars")
            if bid and ask:
                p = (float(bid) + float(ask)) / 2
        if p is not None:
            rows.append({
                "date": pd.to_datetime(ts, unit="s").normalize(),
                "p": p,
                "volume": float(c.get("volume_fp", 0)),
                "oi": float(c.get("open_interest_fp", 0)),
            })
    return pd.DataFrame(rows)


def fetch_market_snapshot():
    url = f"{BASE}/markets/{TICKER}"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    m = r.json().get("market", {})
    p = None
    if m.get("last_price_dollars"):
        p = float(m["last_price_dollars"])
    else:
        bid = m.get("yes_bid_dollars")
        ask = m.get("yes_ask_dollars")
        if bid and ask:
            p = (float(bid) + float(ask)) / 2
    oi = float(m.get("open_interest_fp", 0))
    return p, oi


existing = pd.read_csv(CSV_PATH, parse_dates=["date"])
last_date = existing["date"].max()
print(f"Существующий ряд: {len(existing)} дней, до {last_date.date()}")

today = pd.Timestamp.utcnow().normalize().tz_localize(None)
if last_date >= today:
    print("Уже актуально, ничего не делаю.")
else:
    start = int((last_date + pd.Timedelta(days=1)).timestamp())
    end = int((today + pd.Timedelta(days=1)).timestamp())
    try:
        new_df = fetch_candles(start, end)
        if len(new_df) > 0:
            new_df = new_df.groupby("date").agg(
                p=("p", "last"), volume=("volume", "sum"), oi=("oi", "last")
            ).reset_index()
            print(f"Candles за пропуск: {len(new_df)} дней")
        else:
            print("Candles пустые, беру snapshot из /markets/{ticker}")
            new_df = pd.DataFrame()
    except Exception as e:
        print(f"Candles error: {e}")
        new_df = pd.DataFrame()

    # Если candles ничего не дали, добавим одну строку — сегодняшний snapshot
    if len(new_df) == 0:
        try:
            p, oi = fetch_market_snapshot()
            if p is not None:
                new_df = pd.DataFrame([{
                    "date": today, "p": p, "volume": 0.0, "oi": oi
                }])
                print(f"Snapshot: p={p:.4f}, oi={oi:,.0f} за {today.date()}")
        except Exception as e:
            print(f"Snapshot error: {e}")

    if len(new_df) > 0:
        combined = pd.concat([existing, new_df], ignore_index=True)
        combined = combined.drop_duplicates(subset=["date"], keep="last").sort_values("date").reset_index(drop=True)
        combined.to_csv(CSV_PATH, index=False)
        print(f"Записано: {len(combined)} дней, последняя {combined['date'].max().date()}")
    else:
        print("Новых данных нет, файл не изменён.")
