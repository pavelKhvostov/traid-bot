"""etap_247 — Волна 2 / домен options: DVOL (forward-looking IV) → range/big_day.

ГИПОТЕЗА (options-1, флагман): наша range-модель видит только ПРОШЛУЮ волатильность
(atr/rv/HAR). DVOL = крипто-VIX = ОЖИДАЕМАЯ рынком волатильность ВПЕРЁД (опционы).
Это единственный forward-источник. Должен дать инкремент к range R²0.50 / big_day 0.73.

Данные (проверено через прокси): Deribit public get_volatility_index_data,
BTC и ETH daily с 2021-03-24 (~5.2 года). SOL DVOL не существует → исключаем.

Фичи (as-of t-1): dvol_d1 (вчерашний close DVOL), dvol_chg5 (5д изменение),
dvol_z30 (z-score уровня). + VRP = implied_daily_vol − realized_daily_vol (options-2).

A/B на харнессе etap_204, НО только строки с DVOL (BTC+ETH, 2021-03+).
KILL: ΔR²<0.01 И ΔAUC<0.01, либо importance ниже atr_pct.

Запуск: venv/Scripts/python.exe research/daily_engine/etap_247_dvol_forward_iv.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd
import requests

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import etap_204_daily_engine as E
import vol_features as VF                          # HAR-RV: база теперь включает его
from sklearn.metrics import r2_score, roc_auc_score

OUT = HERE / "output"
CUR = {"BTCUSDT": "BTC", "ETHUSDT": "ETH"}     # SOL DVOL не существует


def grab_dvol(cur: str) -> pd.DataFrame:
    cache = OUT / f"etap_247_dvol_{cur}.csv"
    if cache.exists():
        return pd.read_csv(cache, parse_dates=["date"])
    start = int(pd.Timestamp("2021-03-24", tz="UTC").timestamp() * 1000)
    end = int(pd.Timestamp.now(tz="UTC").timestamp() * 1000)
    rows, cur_ts = [], start
    win = 900 * 86400 * 1000           # окно <1000 баров: иначе Deribit отдаёт ПОСЛЕДНИЕ 1000
    seen = set()
    while cur_ts < end:                 # идём ВПЕРЁД окнами (баг: широкое окно → только хвост)
        j = requests.get("https://www.deribit.com/api/v2/public/get_volatility_index_data",
                         params=dict(currency=cur, start_timestamp=cur_ts,
                                     end_timestamp=min(cur_ts + win, end), resolution=86400), timeout=20).json()
        data = j.get("result", {}).get("data", [])
        data = [d for d in data if d[0] not in seen]
        if not data:
            cur_ts += win; continue
        rows += data; seen.update(d[0] for d in data)
        cur_ts = max(d[0] for d in data) + 86400 * 1000
    df = pd.DataFrame(rows, columns=["t", "o", "h", "l", "dvol"])
    df["date"] = pd.to_datetime(df["t"], unit="ms", utc=True)
    df = df[["date", "dvol"]].drop_duplicates("date").sort_values("date")
    df.to_csv(cache, index=False)
    return df


def dvol_features(symbol: str) -> pd.DataFrame:
    cur = CUR[symbol]
    d = grab_dvol(cur)
    d = d.set_index("date")
    d["dvol_z30"] = (d["dvol"] - d["dvol"].rolling(30).mean()) / d["dvol"].rolling(30).std()
    d["dvol_chg5"] = d["dvol"].pct_change(5)
    feat = d[["dvol", "dvol_z30", "dvol_chg5"]].rename(columns={"dvol": "dvol_lvl"}).shift(1)  # as-of t-1
    feat["asset"] = symbol
    return feat.reset_index()


DV = ["dvol_lvl", "dvol_z30", "dvol_chg5"]


def main():
    print("[grab] DVOL BTC+ETH (Deribit, через прокси)...")
    data, feat_cols = E.assemble()
    # база включает интегрированный HAR-RV → проверяем инкремент DVOL СВЕРХ него
    har_long = []
    for s in CUR:
        h = VF.har_features(s)
        if len(h):
            hh = h.reset_index().rename(columns={"index": "date", h.index.name or "day": "date"})
            hh.columns = ["date"] + list(VF.VOL_FEATS)
            hh["asset"] = s
            har_long.append(hh)
    if har_long:
        hl = pd.concat(har_long, ignore_index=True); hl["date"] = pd.to_datetime(hl["date"], utc=True)
        data = data.merge(hl, on=["date", "asset"], how="left")
        feat_cols = feat_cols + [c for c in VF.VOL_FEATS if c in data.columns]
    dv = pd.concat([dvol_features(s) for s in CUR], ignore_index=True)
    dv["date"] = pd.to_datetime(dv["date"], utc=True)
    data = data.merge(dv[["date", "asset"] + DV], on=["date", "asset"], how="left")
    # только строки с DVOL (BTC+ETH, 2021-03+)
    db = data.dropna(subset=feat_cols + DV + ["log_range"]).reset_index(drop=True)
    print(f"  строк с DVOL: {len(db)} (активы: {sorted(db.asset.unique())}, "
          f"{db.date.min().date()}…{db.date.max().date()})")
    if len(db) < 500:
        print("  мало данных, стоп"); return

    ra = E.walk_forward(db, feat_cols)
    rb = E.walk_forward(db, feat_cols + DV)

    def rep(res, tag):
        r2 = r2_score(res.log_range, np.log(res.prc.clip(lower=1e-6)))
        auc = roc_auc_score(res.big_day, res.pb)
        print(f"  {tag:<12} R²={r2:.4f}  AUC={auc:.4f}  n={len(res)}"); return r2, auc

    print("\n■ A/B OOS 2025-26 (BTC+ETH, строки с DVOL):")
    r2a, auca = rep(ra, "A база"); r2b, aucb = rep(rb, "B +DVOL")
    print(f"  Δ: R² {r2b-r2a:+.4f}  AUC {aucb-auca:+.4f}")

    from catboost import CatBoostRegressor, Pool
    ci = [(feat_cols + DV).index("asset")]
    tr = db[db.date < pd.Timestamp(E.OOS_START, tz="UTC")]
    reg = CatBoostRegressor(iterations=400, depth=5, learning_rate=0.03, l2_leaf_reg=6, random_seed=42, verbose=0)
    reg.fit(Pool(tr[feat_cols + DV], tr.log_range, cat_features=ci), verbose=0)
    imp = dict(zip(feat_cols + DV, reg.get_feature_importance(Pool(tr[feat_cols + DV], tr.log_range, cat_features=ci))))
    print(f"  importance: dvol_lvl={imp.get('dvol_lvl',0):.2f} dvol_z30={imp.get('dvol_z30',0):.2f} "
          f"dvol_chg5={imp.get('dvol_chg5',0):.2f} | atr_pct={imp.get('atr_pct',0):.1f} har_rv_d={imp.get('har_rv_d',0):.1f} dow={imp.get('dow',0):.1f}")
    # per-year
    rb["year"] = rb.date.dt.year
    print("  по годам (R² база→+DVOL):")
    for y, g in rb.groupby("year"):
        ga = ra[ra.date.dt.year == y]
        print(f"    {y}: {r2_score(ga.log_range, np.log(ga.prc.clip(lower=1e-6))):.3f} → "
              f"{r2_score(g.log_range, np.log(g.prc.clip(lower=1e-6))):.3f}")
    verdict = "KEEP" if (r2b - r2a >= 0.01 or aucb - auca >= 0.01) else "KILL"
    print(f"\nВЕРДИКТ options-1 (DVOL): {verdict}")


if __name__ == "__main__":
    main()
