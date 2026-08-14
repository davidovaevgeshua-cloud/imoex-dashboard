"""
Инкрементально дополняет imoex_factors.csv свежими строками из
последних CSV: imoex_daily, usdrub_daily, brent_daily, ofz5y_cache, cnyrub_moex.

Логика:
  1. Читаем существующий imoex_factors.csv (базу с 2014 года)
  2. Читаем свежие компонентные ряды
  3. Собираем DataFrame с новыми датами (после max(factors.date))
  4. Расчитываем brent_rub и brent_rub_ma3m (3-месячное скользящее)
  5. Добавляем новые строки в factors, сохраняем
"""
import pandas as pd
import numpy as np
import os as _os

WORKDIR = _os.environ.get("WORKDIR", "/home/user/workspace")

# ================================================================
# Читаем базовый ряд factors
# ================================================================
factors = pd.read_csv(f"{WORKDIR}/imoex_factors.csv", parse_dates=["date"])
last_date = factors["date"].max()
print(f"factors: {len(factors)} строк, последняя дата {last_date.date()}")

# ================================================================
# Читаем свежие компонентные ряды
# ================================================================
imoex = pd.read_csv(f"{WORKDIR}/imoex_daily.csv", parse_dates=["date"])
usdrub = pd.read_csv(f"{WORKDIR}/usdrub_daily.csv", parse_dates=["date"])
brent = pd.read_csv(f"{WORKDIR}/brent_daily.csv", parse_dates=["date"])
ofz = pd.read_csv(f"{WORKDIR}/ofz5y_cache.csv", parse_dates=["date"])
cnyrub = pd.read_csv(f"{WORKDIR}/cnyrub_moex.csv", parse_dates=["date"])[["date", "cnyrub"]]

# usdrub_cbr — резерв: если MOEX USDRUB отвалится (после 12.06.2024), используем ЦБ
try:
    cbr = pd.read_csv(f"{WORKDIR}/usdrub_cbr.csv", parse_dates=["date"])
    cbr = cbr.rename(columns={"usdrub_cbr": "usdrub_cbr"})
except Exception:
    cbr = pd.DataFrame(columns=["date", "usdrub_cbr"])

for name, df in [("imoex", imoex), ("usdrub", usdrub), ("brent", brent),
                 ("ofz", ofz), ("cnyrub", cnyrub), ("cbr", cbr)]:
    if len(df):
        print(f"  {name}: {len(df)} строк, {df['date'].min().date()} → {df['date'].max().date()}")

# ================================================================
# Строим "новые" строки: даты > last_date, есть IMOEX
# ================================================================
new_imoex = imoex[imoex["date"] > last_date].copy()
print(f"\nНовых дат IMOEX: {len(new_imoex)}")

if len(new_imoex) == 0:
    print("Нет новых данных, выходим")
    raise SystemExit(0)

# Слева-мерджим все факторы к новым датам IMOEX
new = new_imoex[["date", "imoex"]].copy()
new = new.merge(usdrub[["date", "usdrub"]], on="date", how="left")
new = new.merge(brent[["date", "brent"]], on="date", how="left")
new = new.merge(ofz[["date", "ofz5y"]], on="date", how="left")
new = new.merge(cnyrub[["date", "cnyrub"]], on="date", how="left")

if len(cbr):
    new = new.merge(cbr[["date", "usdrub_cbr"]], on="date", how="left")
    # Если usdrub NaN, но есть usdrub_cbr — используем ЦБ
    new["usdrub"] = new["usdrub"].fillna(new["usdrub_cbr"])
    new = new.drop(columns=["usdrub_cbr"])

# yahoo backup — если usdrub_daily пусто (MOEX всё ещё под санкциями)
new["usdrub_yahoo"] = new["usdrub"]  # пока просто копия

# brent_rub = brent × usdrub. Если brent NaN (свежего Brent ещё нет) — берём последний
last_brent = factors["brent"].dropna().iloc[-1]
new["brent"] = new["brent"].ffill().fillna(last_brent)
new["brent_rub"] = new["brent"] * new["usdrub"]

# brent_rub_ma3m — 3-месячное (63 торговых дня) скользящее среднее.
# Считаем на объединённом factors + new, чтобы взять хвост из истории
combined = pd.concat([factors[["date", "brent_rub"]], new[["date", "brent_rub"]]], ignore_index=True)
combined = combined.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
combined["brent_rub_ma3m"] = combined["brent_rub"].rolling(63, min_periods=1).mean()
ma3m_map = combined.set_index("date")["brent_rub_ma3m"]
new["brent_rub_ma3m"] = new["date"].map(ma3m_map)

# Порядок колонок как в existing factors
cols = ["date", "imoex", "usdrub", "brent", "ofz5y", "brent_rub", "brent_rub_ma3m", "usdrub_yahoo", "cnyrub"]
new = new[cols]

# ffill критичные пропуски (ofz5y после выходных)
for c in ["ofz5y", "usdrub", "brent"]:
    if new[c].isna().any():
        # берём последнее значение из старого factors
        last_val = factors[c].dropna().iloc[-1] if factors[c].dropna().size else np.nan
        new[c] = new[c].ffill().fillna(last_val)

print(f"\nНовые строки:")
print(new.to_string(index=False))

# ================================================================
# Дописываем и сохраняем
# ================================================================
result = pd.concat([factors, new], ignore_index=True)
result = result.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)

# Пересчитаем brent_rub_ma3m на всём хвосте (последние 100 дней) — на всякий
tail_mask = result["date"] >= result["date"].max() - pd.Timedelta(days=100)
result.loc[tail_mask, "brent_rub_ma3m"] = (
    result["brent_rub"].rolling(63, min_periods=1).mean().loc[tail_mask]
)

result.to_csv(f"{WORKDIR}/imoex_factors.csv", index=False)
print(f"\nfactors теперь: {len(result)} строк, до {result['date'].max().date()}")
print("saved imoex_factors.csv")
