"""etap_243 — Волна 1 / модуль volmod: realized-vol эконометрика из 1m → range/big_day.

Кандидаты (workflow wf_5db33fd8, домен volmod, флагман volmod-1 TOP):
  - HAR-RV (Corsi): log_rv день/неделя/месяц — литературный стандарт прогноза RV
  - BNS jump detection: bipower variation → jump_frac (скачки vs непрерывная vola)
  - Realized semivariance (Barndorff-Nielsen): RS+ / RS- → асимметрия (down-vol)
  - Realized skewness / kurtosis (Amaya): хвосты внутридневного распределения
Все меры считаются ПО 1m-барам дня d, затем ЛАГируются (HAR-окна кончаются на d-1)
— строго as-of, без подглядывания в прогнозируемый день.

A/B: тот же walk-forward, что у продакшн range/big_day (импорт etap_204):
  A = текущие фичи; B = A + vol-эконометрика. Метрики: range R², big_day AUC,
  containment, importance новых фич vs atr_pct, permutation-null на R²-lift.

KILL (заранее): ΔR² < +0.01 И ΔAUC < +0.01 на OOS → закрыть; либо importance
всех новых ниже dow.

Запуск: venv/Scripts/python.exe research/daily_engine/etap_243_vol_econometrics.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import etap_204_daily_engine as E
from sklearn.metrics import r2_score, roc_auc_score

OUT = HERE / "output"
CACHE = OUT / "etap_243_rv_measures.csv"
SYMBOLS = E.SYMBOLS
MIN_COVER = 1380          # минимум 1m-баров в дне (из 1440) — иначе RV невалиден
RNG = np.random.RandomState(42)


def realized_measures_1m(sym: str) -> pd.DataFrame:
    """По 1m-барам считает дневные realized-меры (на дату самого дня d, БЕЗ лагов)."""
    p = ROOT / "data" / f"{sym}_1m.csv"      # sym уже = BTCUSDT/ETHUSDT/SOLUSDT
    df = pd.read_csv(p, usecols=["open_time", "close"], parse_dates=["open_time"])
    if df["open_time"].dt.tz is None:
        df["open_time"] = df["open_time"].dt.tz_localize("UTC")
    df = df.set_index("open_time").sort_index()
    r = np.log(df["close"]).diff()           # 1m лог-ретёрны
    g = pd.DataFrame({"r": r}).dropna()
    g["day"] = g.index.normalize()
    rows = []
    for day, x in g.groupby("day"):
        rr = x["r"].values
        n = len(rr)
        if n < MIN_COVER:
            continue
        rv = float(np.sum(rr**2))
        if rv <= 0:
            continue
        # bipower variation (BNS) → jump
        bv = (np.pi / 2.0) * float(np.sum(np.abs(rr[1:]) * np.abs(rr[:-1])))
        jump = max(rv - bv, 0.0)
        rs_plus = float(np.sum(rr[rr > 0] ** 2))
        rs_minus = float(np.sum(rr[rr < 0] ** 2))
        rskew = float(np.sqrt(n) * np.sum(rr**3) / (rv ** 1.5))
        rkurt = float(n * np.sum(rr**4) / (rv ** 2))
        rows.append(dict(day=day, asset=sym, n=n, rv=rv, bv=bv,
                         jump_frac=jump / rv, rs_asym=(rs_minus - rs_plus) / rv,
                         rskew=rskew, rkurt=rkurt))
    return pd.DataFrame(rows)


def build_har(meas: pd.DataFrame) -> pd.DataFrame:
    """HAR-лаги (день/неделя/месяц), все .shift(1) внутри актива → as-of t-1."""
    out = []
    for sym, x in meas.groupby("asset"):
        x = x.sort_values("day").copy()
        lrv = np.log(x["rv"].clip(lower=1e-12))
        x["har_rv_d"] = lrv.shift(1)
        x["har_rv_w"] = lrv.rolling(5).mean().shift(1)
        x["har_rv_m"] = lrv.rolling(22).mean().shift(1)
        x["rv_volvol"] = lrv.rolling(10).std().shift(1)          # vol-of-vol
        x["jump_d"] = x["jump_frac"].shift(1)
        x["jump_w"] = x["jump_frac"].rolling(5).mean().shift(1)
        x["rsasym_d"] = x["rs_asym"].shift(1)
        x["rsasym_w"] = x["rs_asym"].rolling(5).mean().shift(1)
        x["rskew_d"] = x["rskew"].shift(1)
        x["rkurt_d"] = x["rkurt"].shift(1)
        out.append(x)
    return pd.concat(out)


VOL_FEATS = ["har_rv_d", "har_rv_w", "har_rv_m", "rv_volvol",
             "jump_d", "jump_w", "rsasym_d", "rsasym_w", "rskew_d", "rkurt_d"]


def main():
    OUT.mkdir(exist_ok=True)
    if CACHE.exists():
        meas = pd.read_csv(CACHE, parse_dates=["day"])
        print(f"[cache] realized-меры из {CACHE.name}: {len(meas)} дней-активов")
    else:
        print("[compute] realized-меры из 1m (тяжело: BTC ~3.4M минут)...")
        meas = pd.concat([realized_measures_1m(s) for s in SYMBOLS], ignore_index=True)
        meas.to_csv(CACHE, index=False)
        print(f"[saved] {CACHE.name}: {len(meas)} дней-активов")
    if meas["day"].dt.tz is None:
        meas["day"] = meas["day"].dt.tz_localize("UTC")
    har = build_har(meas)[["day", "asset"] + VOL_FEATS].rename(columns={"day": "date"})

    # база — ровно как в проде
    data, feat_cols = E.assemble()
    data = data.merge(har, on=["date", "asset"], how="left")
    nb = data[VOL_FEATS].notna().all(axis=1).mean()
    print(f"[merge] vol-фичи покрывают {nb*100:.0f}% строк датасета")
    data_b = data.dropna(subset=feat_cols + VOL_FEATS + ["log_range"]).reset_index(drop=True)
    feat_b = feat_cols + VOL_FEATS

    print(f"\n[A/B] база={len(feat_cols)} фич, +vol={len(feat_b)} фич, строк (общий dropna)={len(data_b)}")
    # одинаковая выборка строк для честного A/B
    res_a = E.walk_forward(data_b, feat_cols)
    res_b = E.walk_forward(data_b, feat_b)

    def report(res, tag):
        half = res["k"] * res["prc"] * res["prev_close"]
        cont = ((res.high <= res.open + half) & (res.low >= res.open - half)).mean()
        r2 = r2_score(res["log_range"], np.log(res["prc"].clip(lower=1e-6)))
        auc = roc_auc_score(res["big_day"], res["pb"])
        print(f"  {tag:<14} range R²={r2:.4f}  big_day AUC={auc:.4f}  containment={cont:.0%}  n={len(res)}")
        return r2, auc

    print("\n■ OOS 2025-26:")
    r2a, auca = report(res_a, "A база")
    r2b, aucb = report(res_b, "B +vol")
    print(f"  Δ: range R² {r2b-r2a:+.4f}  big_day AUC {aucb-auca:+.4f}")

    # importance новых фич vs atr_pct/dow (на train < OOS)
    from catboost import CatBoostRegressor, CatBoostClassifier, Pool
    cat_idx = [feat_b.index("asset")]
    tr = data_b[data_b["date"] < pd.Timestamp(E.OOS_START, tz="UTC")]
    reg = CatBoostRegressor(iterations=400, depth=5, learning_rate=0.03, l2_leaf_reg=6, random_seed=42, verbose=0)
    reg.fit(Pool(tr[feat_b], tr["log_range"], cat_features=cat_idx), verbose=0)
    imp = dict(zip(feat_b, reg.get_feature_importance(Pool(tr[feat_b], tr["log_range"], cat_features=cat_idx))))
    print("\n■ Importance vol-фич (range-модель) vs якоря:")
    for f in sorted(VOL_FEATS, key=lambda x: -imp.get(x, 0)):
        print(f"   {f:12} {imp.get(f,0):.2f}")
    print(f"   [якоря] atr_pct={imp.get('atr_pct',0):.1f}  dow={imp.get('dow',0):.1f}  rv10={imp.get('rv10',0):.2f}  rv20={imp.get('rv20',0):.2f}")

    # permutation-null на R²-lift (шаффл vol-фич в train, 25 перм)
    print("\n■ Permutation-null на ΔR² (шаффл vol-блока, 25 перм):")
    nulls = []
    for p in range(25):
        d2 = data_b.copy()
        idx = RNG.permutation(len(d2))
        d2[VOL_FEATS] = d2[VOL_FEATS].values[idx]
        r = E.walk_forward(d2, feat_b)
        nulls.append(r2_score(r["log_range"], np.log(r["prc"].clip(lower=1e-6))) - r2a)
    nulls = np.array(nulls)
    real = r2b - r2a
    pval = float((nulls >= real).mean())
    print(f"   real ΔR² {real:+.4f}  null среднее {nulls.mean():+.4f} (макс {nulls.max():+.4f})  p={pval:.3f}")

    verdict = "KEEP" if (r2b - r2a >= 0.01 or aucb - auca >= 0.01) and pval < 0.1 else "KILL"
    print(f"\nВЕРДИКТ: {verdict}  (порог: ΔR²≥0.01 или ΔAUC≥0.01, и p<0.1)")
    data_b.to_csv(OUT / "etap_243_dataset.csv", index=False)


if __name__ == "__main__":
    main()
