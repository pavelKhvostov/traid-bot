"""etap_248 — Волна 3 / домены calendar+macro: детерминированные календарные события → range/big_day.

Все фичи известны ЗАРАНЕЕ (расписание ФРС, первая/последняя пятница, конец месяца,
праздники) → lookahead невозможен по построению. dow уже топ-драйвер range-модели —
копаем ту же жилу глубже.

Фичи (на дату дня d, без лагов — событие в этот день известно заранее):
  - is_fomc / days_to_fomc / is_post_fomc — день анонса ФРС (≈19:00 UTC) = vol-событие
  - is_nfp — первая пятница месяца (payrolls 13:30 UTC) = vol-событие
  - is_opex / is_quarterly_opex — последняя пятница (экспирация Deribit/CME)
  - is_turn_of_month — последние 2 / первые 2 дня месяца (ребаланс)
  - is_us_holiday — CME/NYSE закрыты (тонкий рынок)

Гипотеза: FOMC/NFP-дни = повышенный шанс big_day (vol-спайк), независимо от направления.
A/B на харнессе etap_204. KILL: ΔR²<0.01 И ΔAUC<0.01, либо is_fomc не поднимает big_day.

FOMC-даты: расписание ФРС 2020-2026 (announcement day). CPI пропущен — нужен точный
BLS-календарь (без него = шум); NFP/OPEX/turn детерминированы формулой.

Запуск: venv/Scripts/python.exe research/daily_engine/etap_248_calendar_pack.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import etap_204_daily_engine as E
from sklearn.metrics import r2_score, roc_auc_score

# Расписание FOMC (день анонса, UTC-дата). 2020-2025 — фактические; 2026 — плановые.
FOMC = [
    "2020-01-29", "2020-03-03", "2020-03-15", "2020-04-29", "2020-06-10", "2020-07-29",
    "2020-09-16", "2020-11-05", "2020-12-16",
    "2021-01-27", "2021-03-17", "2021-04-28", "2021-06-16", "2021-07-28", "2021-09-22",
    "2021-11-03", "2021-12-15",
    "2022-01-26", "2022-03-16", "2022-05-04", "2022-06-15", "2022-07-27", "2022-09-21",
    "2022-11-02", "2022-12-14",
    "2023-02-01", "2023-03-22", "2023-05-03", "2023-06-14", "2023-07-26", "2023-09-20",
    "2023-11-01", "2023-12-13",
    "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12", "2024-07-31", "2024-09-18",
    "2024-11-07", "2024-12-18",
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18", "2025-07-30", "2025-09-17",
    "2025-10-29", "2025-12-10",
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29", "2026-09-16",
    "2026-11-04", "2026-12-16",
]
FOMC = pd.to_datetime(FOMC, utc=True)

CAL_FEATS = ["is_fomc", "is_post_fomc", "days_to_fomc", "is_nfp",
             "is_opex", "is_quarterly_opex", "is_turn_of_month", "is_us_holiday"]


def calendar_features(dates: pd.DatetimeIndex) -> pd.DataFrame:
    d = pd.DatetimeIndex(dates)
    df = pd.DataFrame(index=d)
    fomc_norm = pd.DatetimeIndex(FOMC).normalize()
    dn = d.normalize()
    df["is_fomc"] = dn.isin(fomc_norm).astype(int)
    df["is_post_fomc"] = dn.isin(fomc_norm + pd.Timedelta(days=1)).astype(int)
    # дней до ближайшего будущего FOMC (известно заранее), кап 30
    fb = fomc_norm.sort_values().values
    dtf = []
    for x in dn.values:
        future = fb[fb >= x]
        dtf.append(min((future[0] - x) / np.timedelta64(1, "D"), 30) if len(future) else 30)
    df["days_to_fomc"] = dtf
    # NFP = первая пятница месяца
    df["is_nfp"] = ((d.weekday == 4) & (d.day <= 7)).astype(int)
    # OPEX = последняя пятница месяца
    last_fri = []
    for x in d:
        m_end = (x + pd.offsets.MonthEnd(0))
        lf = m_end - pd.Timedelta(days=(m_end.weekday() - 4) % 7)
        last_fri.append(x.normalize() == lf.normalize())
    df["is_opex"] = np.array(last_fri).astype(int)
    df["is_quarterly_opex"] = (df["is_opex"].values & d.month.isin([3, 6, 9, 12])).astype(int)
    # turn-of-month: последние 2 / первые 2 календарных дня
    dom = d.day; dim = d.days_in_month
    df["is_turn_of_month"] = (((dim - dom) <= 1) | (dom <= 2)).astype(int)
    # US holidays (CME/NYSE закрыты)
    try:
        from pandas.tseries.holiday import USFederalHolidayCalendar
        hol = USFederalHolidayCalendar().holidays(start=d.min(), end=d.max())
        df["is_us_holiday"] = dn.isin(pd.DatetimeIndex(hol).tz_localize("UTC")).astype(int)
    except Exception:
        df["is_us_holiday"] = 0
    return df


def main():
    data, feat_cols = E.assemble()
    cal = calendar_features(pd.DatetimeIndex(data["date"]))
    for c in CAL_FEATS:
        data[c] = cal[c].values
    db = data.dropna(subset=feat_cols + ["log_range"]).reset_index(drop=True)
    print(f"[data] {len(db)} строк, +{len(CAL_FEATS)} календарных фич")

    # сначала описательно: big_day-rate в событийные дни vs обычные
    print("\n■ big_day-rate (факт) в событийные дни:")
    base_rate = db["big_day"].mean()
    print(f"   обычный день: {base_rate:.2%}")
    for c in ["is_fomc", "is_post_fomc", "is_nfp", "is_opex", "is_turn_of_month", "is_us_holiday"]:
        ev = db[db[c] == 1]
        if len(ev) >= 20:
            print(f"   {c:<18} n={len(ev):>4}  big_day={ev['big_day'].mean():.2%}  "
                  f"(lift {ev['big_day'].mean()-base_rate:+.1%})")

    # A/B
    ra = E.walk_forward(db, feat_cols)
    rb = E.walk_forward(db, feat_cols + CAL_FEATS)
    def rep(res, tag):
        r2 = r2_score(res.log_range, np.log(res.prc.clip(lower=1e-6))); auc = roc_auc_score(res.big_day, res.pb)
        print(f"  {tag:<12} R²={r2:.4f}  AUC={auc:.4f}"); return r2, auc
    print("\n■ A/B OOS 2025-26:")
    r2a, auca = rep(ra, "A база"); r2b, aucb = rep(rb, "B +календарь")
    print(f"  Δ: R² {r2b-r2a:+.4f}  AUC {aucb-auca:+.4f}")

    from catboost import CatBoostClassifier, Pool
    ci = [(feat_cols + CAL_FEATS).index("asset")]
    tr = db[db.date < pd.Timestamp(E.OOS_START, tz="UTC")]
    clf = CatBoostClassifier(iterations=350, depth=4, learning_rate=0.03, l2_leaf_reg=8, random_seed=42, verbose=0)
    clf.fit(Pool(tr[feat_cols + CAL_FEATS], tr.big_day, cat_features=ci), verbose=0)
    imp = dict(zip(feat_cols + CAL_FEATS, clf.get_feature_importance(Pool(tr[feat_cols + CAL_FEATS], tr.big_day, cat_features=ci))))
    print("\n■ importance календарных (big_day-модель):")
    for c in sorted(CAL_FEATS, key=lambda x: -imp.get(x, 0)):
        print(f"   {c:<18} {imp.get(c,0):.2f}")
    print(f"   [якоря] atr_pct={imp.get('atr_pct',0):.1f} dow={imp.get('dow',0):.1f}")

    # годовая стабильность is_fomc → big_day
    print("\n■ is_fomc → big_day по годам (стабильность):")
    db["year"] = db.date.dt.year
    for y, g in db.groupby("year"):
        ev = g[g.is_fomc == 1]; ot = g[g.is_fomc == 0]
        if len(ev) >= 3:
            print(f"   {y}: FOMC big_day={ev['big_day'].mean():.0%} (n={len(ev)}) vs обычный {ot['big_day'].mean():.0%}")

    verdict = "KEEP" if (r2b - r2a >= 0.01 or aucb - auca >= 0.01) else "KILL"
    print(f"\nВЕРДИКТ волна-3 календарь: {verdict}")
    db.to_csv(HERE / "output" / "etap_248_calendar.csv", index=False)


if __name__ == "__main__":
    main()
