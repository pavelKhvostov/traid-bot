"""etap_246 — Волна 2 / домен derivs: funding + Open Interest → big_day/range/trend-hold.

Данные (проверены живыми запросами через системный прокси):
  - funding: fapi.binance.com/fapi/v1/fundingRate, BTC с 2019-09 (3 выплаты/день)
  - OI 5m: data.binance.vision futures/um/daily/metrics/{SYM}/...zip, BTC с 2020-09,
    ETH/SOL с 2021-12 (sum_open_interest + L/S ratios)

ДВА теста с заранее заданными kill-критериями:
  derivs-1 (funding-crowding): funding_z30 + |funding|-перцентиль (shift1) в
    range/big_day A/B (харнесс etap_204). KILL: ΔR²<0.01 И ΔAUC<0.01, либо
    importance ниже dow, либо коллинеарность с atr_pct убивает инкремент.
  derivs-2 (ΔOI × ход): утренний (00→08 UTC) квадрант [цена↑/↓ × OI↑/↓] →
    «утренний ход продолжился до конца дня». Гипотеза: цена↑OI↑ (новые деньги)
    держится лучше, чем цена↑OI↓ (short squeeze, топливо кончилось).
    KILL: разница continuation-rate между OI↑ и OI↓ (в одном направлении цены)
    <5пп, ИЛИ знак нестабилен >2 лет из доступных.

Запуск: venv/Scripts/python.exe research/daily_engine/etap_246_derivs_funding_oi.py
"""
from __future__ import annotations
import sys, io, zipfile, time
from pathlib import Path
import numpy as np, pandas as pd
import requests

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import etap_204_daily_engine as E
from sklearn.metrics import r2_score, roc_auc_score

OUT = HERE / "output"
SYMBOLS = E.SYMBOLS
OI_START = {"BTCUSDT": "2020-09-01", "ETHUSDT": "2021-12-01", "SOLUSDT": "2021-12-01"}


# ---------------- грабберы (резюмируемый кэш) ----------------
def grab_funding(sym: str) -> pd.DataFrame:
    cache = OUT / f"etap_246_funding_{sym}.csv"
    if cache.exists():
        return pd.read_csv(cache, parse_dates=["t"])
    rows, cur = [], int(pd.Timestamp("2019-09-01", tz="UTC").timestamp() * 1000)
    end = int(pd.Timestamp.now(tz="UTC").timestamp() * 1000)
    while cur < end:
        d = requests.get("https://fapi.binance.com/fapi/v1/fundingRate",
                         params=dict(symbol=sym, startTime=cur, limit=1000), timeout=20).json()
        if not isinstance(d, list) or not d:
            break
        rows += d; cur = d[-1]["fundingTime"] + 1
        if len(d) < 1000:
            break
    f = pd.DataFrame(rows)
    f["t"] = pd.to_datetime(f["fundingTime"], unit="ms", utc=True)
    f["funding"] = pd.to_numeric(f["fundingRate"])
    f = f[["t", "funding"]].drop_duplicates("t")
    f.to_csv(cache, index=False)
    return f


def grab_oi(sym: str) -> pd.DataFrame:
    """Компактный дневной OI: oi_open(00:05), oi_08, oi_eod + дневные L/S ratio. Резюмируемо."""
    cache = OUT / f"etap_246_oi_{sym}.csv"
    have = pd.read_csv(cache, parse_dates=["date"]) if cache.exists() else pd.DataFrame()
    have_days = set(have["date"].dt.strftime("%Y-%m-%d")) if len(have) else set()
    start = pd.Timestamp(OI_START[sym], tz="UTC")
    end = pd.Timestamp.now(tz="UTC").normalize() - pd.Timedelta(days=1)
    sess = requests.Session()
    new = []
    for day in pd.date_range(start, end, freq="D"):
        ds = day.strftime("%Y-%m-%d")
        if ds in have_days:
            continue
        url = f"https://data.binance.vision/data/futures/um/daily/metrics/{sym}/{sym}-metrics-{ds}.zip"
        try:
            z = sess.get(url, timeout=20)
            if z.status_code != 200:
                continue
            zf = zipfile.ZipFile(io.BytesIO(z.content))
            df = pd.read_csv(zf.open(zf.namelist()[0]))
        except Exception:
            continue
        df["create_time"] = pd.to_datetime(df["create_time"], utc=True)
        df = df.sort_values("create_time")
        oi = pd.to_numeric(df["sum_open_interest"])
        h = df["create_time"].dt.hour
        oi_08 = oi[h == 8]
        new.append(dict(date=day, oi_open=float(oi.iloc[0]), oi_eod=float(oi.iloc[-1]),
                        oi_08=float(oi_08.iloc[0]) if len(oi_08) else np.nan,
                        ls_top=pd.to_numeric(df["sum_toptrader_long_short_ratio"]).mean(),
                        ls_all=pd.to_numeric(df["count_long_short_ratio"]).mean()))
    if new:
        have = pd.concat([have, pd.DataFrame(new)], ignore_index=True)
        have = have.drop_duplicates("date").sort_values("date")
        have.to_csv(cache, index=False)
    return have


# ---------------- derivs-1: funding в range/big_day ----------------
def funding_daily(sym):
    f = grab_funding(sym)
    f["day"] = f["t"].dt.normalize()
    g = f.groupby("day")["funding"].sum().to_frame("fund_sum")     # сумма выплат за день
    g["fund_z30"] = (g["fund_sum"] - g["fund_sum"].rolling(30).mean()) / g["fund_sum"].rolling(30).std()
    g["fund_abs_pct"] = g["fund_sum"].abs().rolling(365).rank(pct=True)
    g = g.shift(1)                                                  # as-of t-1
    g["asset"] = sym
    return g.reset_index().rename(columns={"day": "date"})


def test_derivs1():
    print("\n" + "=" * 76); print("derivs-1: funding-crowding → range/big_day (A/B)"); print("=" * 76)
    data, feat_cols = E.assemble()
    fund = pd.concat([funding_daily(s) for s in SYMBOLS], ignore_index=True)
    fund["date"] = pd.to_datetime(fund["date"], utc=True)
    data = data.merge(fund[["date", "asset", "fund_z30", "fund_abs_pct"]], on=["date", "asset"], how="left")
    FF = ["fund_z30", "fund_abs_pct"]
    cov = data[FF].notna().all(axis=1).mean()
    db = data.dropna(subset=feat_cols + FF + ["log_range"]).reset_index(drop=True)
    print(f"  покрытие funding-фич: {cov*100:.0f}%, строк A/B: {len(db)}")
    ra = E.walk_forward(db, feat_cols); rb = E.walk_forward(db, feat_cols + FF)
    def rep(res, tag):
        r2 = r2_score(res.log_range, np.log(res.prc.clip(lower=1e-6))); auc = roc_auc_score(res.big_day, res.pb)
        print(f"  {tag:<12} R²={r2:.4f}  AUC={auc:.4f}"); return r2, auc
    r2a, auca = rep(ra, "A база"); r2b, aucb = rep(rb, "B +funding")
    print(f"  Δ: R² {r2b-r2a:+.4f}  AUC {aucb-auca:+.4f}")
    # importance vs dow/atr
    from catboost import CatBoostRegressor, Pool
    ci = [(feat_cols + FF).index("asset")]; tr = db[db.date < pd.Timestamp(E.OOS_START, tz="UTC")]
    reg = CatBoostRegressor(iterations=400, depth=5, learning_rate=0.03, l2_leaf_reg=6, random_seed=42, verbose=0)
    reg.fit(Pool(tr[feat_cols + FF], tr.log_range, cat_features=ci), verbose=0)
    imp = dict(zip(feat_cols + FF, reg.get_feature_importance(Pool(tr[feat_cols + FF], tr.log_range, cat_features=ci))))
    print(f"  importance: fund_z30={imp.get('fund_z30',0):.2f} fund_abs_pct={imp.get('fund_abs_pct',0):.2f} | dow={imp.get('dow',0):.1f} atr_pct={imp.get('atr_pct',0):.1f}")
    verdict = "KEEP" if (r2b-r2a >= 0.01 or aucb-auca >= 0.01) else "KILL"
    print(f"  ВЕРДИКТ derivs-1: {verdict}")


# ---------------- derivs-2: ΔOI квадрант → продолжение ----------------
def test_derivs2():
    print("\n" + "=" * 76); print("derivs-2: утренний ΔOI×ход → продолжение до конца дня"); print("=" * 76)
    allrows = []
    for sym in SYMBOLS:
        oi = grab_oi(sym)
        if len(oi) < 200:
            print(f"  {sym}: OI данных мало ({len(oi)}), пропуск"); continue
        oi["date"] = pd.to_datetime(oi["date"], utc=True)
        h1 = E.pd.read_csv(ROOT / "data" / f"{sym}_1h.csv", index_col=0, parse_dates=True)
        if h1.index.tz is None: h1.index = h1.index.tz_localize("UTC")
        for _, r in oi.iterrows():
            day = r["date"]
            bars = h1[(h1.index >= day) & (h1.index < day + pd.Timedelta(days=1))]
            if len(bars) < 20 or not np.isfinite(r["oi_08"]) or r["oi_open"] <= 0:
                continue
            o0 = bars["open"].iloc[0]
            if o0 <= 0:
                continue
            b08 = bars[bars.index.hour == 8]
            if len(b08) == 0: continue
            c08 = b08["open"].iloc[0]                 # цена на 08:00
            ceod = bars["close"].iloc[-1]
            mv_m = c08 / o0 - 1                        # утренний ход 00→08
            mv_d = ceod / o0 - 1                       # дневной ход 00→EOD
            doi = r["oi_08"] / r["oi_open"] - 1        # ΔOI за утро
            if abs(mv_m) < 1e-4: continue
            cont = int(np.sign(mv_d) == np.sign(mv_m) and abs(mv_d) > abs(mv_m))  # ход продолжился
            allrows.append(dict(date=day, asset=sym, year=day.year,
                                price_up=int(mv_m > 0), oi_up=int(doi > 0), cont=cont))
    d = pd.DataFrame(allrows)
    print(f"  дней с OI+ценой: {len(d)} ({d.asset.nunique()} монет, {d.date.min().date()}…{d.date.max().date()})")
    print(f"\n  Continuation-rate по квадрантам (утро):")
    print(f"  {'цена':>6} {'OI':>4} {'n':>5} {'cont%':>7}")
    quad = {}
    for (pu, ou), g in d.groupby(["price_up", "oi_up"]):
        lab_p = "↑" if pu else "↓"; lab_o = "↑" if ou else "↓"
        quad[(pu, ou)] = g["cont"].mean()
        print(f"  {lab_p:>6} {lab_o:>4} {len(g):>5} {g['cont'].mean()*100:>6.1f}%")
    # ключевой контраст: при цене↑ OI↑ vs OI↓ ; при цене↓ OI↑ vs OI↓
    for pu, lab in [(1, "цена ↑"), (0, "цена ↓")]:
        up = quad.get((pu, 1), np.nan); dn = quad.get((pu, 0), np.nan)
        print(f"  {lab}: OI↑ {up*100:.1f}% vs OI↓ {dn*100:.1f}%  Δ={abs(up-dn)*100:.1f}пп")
    # годовая стабильность ключевого контраста (цена↑: OI↑−OI↓)
    print(f"\n  Годовая стабильность (цена↑, OI↑ − OI↓):")
    signs = []
    for y, g in d[d.price_up == 1].groupby("year"):
        u = g[g.oi_up == 1]["cont"].mean(); n = g[g.oi_up == 0]["cont"].mean()
        diff = (u - n) * 100; signs.append(np.sign(diff))
        print(f"    {y}: Δ={diff:+.1f}пп (OI↑ n={ (g.oi_up==1).sum() }, OI↓ n={ (g.oi_up==0).sum() })")
    flips = sum(1 for i in range(1, len(signs)) if signs[i] != signs[i-1])
    base_diff = abs(quad.get((1,1),0) - quad.get((1,0),0)) * 100
    verdict = "KEEP" if base_diff >= 5 and flips <= 1 else "KILL"
    print(f"  ВЕРДИКТ derivs-2: {verdict} (контраст {base_diff:.1f}пп, смен знака {flips})")
    d.to_csv(OUT / "etap_246_oi_quadrants.csv", index=False)


def main():
    print("[grab] funding (дёшево) + OI metrics (S3 дампы, резюмируемо)...")
    test_derivs1()
    test_derivs2()


if __name__ == "__main__":
    main()
