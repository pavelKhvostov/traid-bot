"""Этап 28: ICT-book фильтры на топ-3 кандидатов.

Тестируем 4 идеи из ICT Trading book на existing trades CSV:
  T1: hour-of-day filter (07:00 - 17:00 UTC = LO+NYO sessions)
  T2: weekday filter (Mon-Thu, исключаем Friday distribution)
  T3: D.O Premium/Discount (LONG если close < daily_open, SHORT если close > D.O)
  T4: ALL combined

Применяем к C2, C3, C6 (existing CSVs from etap_15 v7).
Не пересчитываем simulate — просто фильтруем outcome rows.
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

from pathlib import Path
import pandas as pd

from data_manager import load_df

OUT_DIR = Path("research/elements_study/output")
SYMBOL = "BTCUSDT"

CANDIDATES = [
    ("C2", "OB-6h x FVG-2h pro RR=1.0"),
    ("C3", "OB-12h x FVG-2h pro RR=1.0"),
    ("C6", "FRACT2X-1d+4h x FVG-2h pro RR=1.0"),
]


def load_daily():
    """1d data — для извлечения D.O (daily open) на каждую дату."""
    df = load_df(SYMBOL, "1d")
    df = df[df.index >= pd.Timestamp("2020-01-01", tz="UTC")].copy()
    return df


def attach_features(df_trades, df_1d):
    df = df_trades.copy()
    df["trigger_time"] = pd.to_datetime(df["trigger_time"])
    df["hour"] = df["trigger_time"].dt.hour
    df["weekday"] = df["trigger_time"].dt.dayofweek  # 0=Mon, 4=Fri, 5=Sat, 6=Sun
    df["date"] = df["trigger_time"].dt.normalize()
    # join D.O (daily open) на дату trigger
    do = df_1d["open"].copy()
    do.index = pd.to_datetime(do.index).normalize()
    do.name = "daily_open"
    df = df.merge(do, left_on="date", right_index=True, how="left")
    return df


def stats(df_filtered, total_n_orig):
    closed = df_filtered[df_filtered["outcome"].isin(["win", "loss"])]
    if closed.empty:
        return {"n_total": len(df_filtered), "n_closed": 0,
                "WR": 0.0, "total_R": 0.0, "R_tr": 0.0, "freq_ratio": 0.0}
    n = len(df_filtered); nc = len(closed)
    w = (closed["outcome"] == "win").sum()
    return {
        "n_total": n, "n_closed": int(nc),
        "WR": round(w/nc*100, 1),
        "total_R": round(closed["R"].sum(), 1),
        "R_tr": round(closed["R"].mean(), 3),
        "freq_ratio": round(n / total_n_orig, 2),
    }


def apply_filter_T1(df):
    """Hour ∈ [7, 17] UTC."""
    return df[(df["hour"] >= 7) & (df["hour"] < 17)]


def apply_filter_T2(df):
    """Weekday Mon-Thu (0-3)."""
    return df[df["weekday"] <= 3]


def apply_filter_T3(df):
    """D.O premium/discount.
    LONG: trigger entry < daily_open (discount)
    SHORT: trigger entry > daily_open (premium)
    """
    long_mask = (df["direction"] == "LONG") & (df["entry"] < df["daily_open"])
    short_mask = (df["direction"] == "SHORT") & (df["entry"] > df["daily_open"])
    return df[long_mask | short_mask]


def apply_filter_T4(df):
    """All combined."""
    return apply_filter_T3(apply_filter_T2(apply_filter_T1(df)))


def main():
    print("[INFO] loading 1d data for D.O")
    df_1d = load_daily()
    print(f"  1d rows: {len(df_1d)}")

    print("\n[INFO] applying filters per candidate")
    summary_rows = []
    for cid, name in CANDIDATES:
        csv = OUT_DIR / f"etap15_{cid}_trades.csv"
        if not csv.exists():
            print(f"[WARN] {csv} not found")
            continue
        df = pd.read_csv(csv)
        df = attach_features(df, df_1d)
        # baseline
        n_orig = len(df)
        bl = stats(df, n_orig)
        bl_row = {"id": cid, "filter": "BASELINE", "n_total": bl["n_total"],
                   "n_closed": bl["n_closed"], "WR": bl["WR"],
                   "total_R": bl["total_R"], "R_tr": bl["R_tr"], "freq": 1.00}
        summary_rows.append(bl_row)
        # T1: hour
        df1 = apply_filter_T1(df); s1 = stats(df1, n_orig)
        summary_rows.append({"id": cid, "filter": "T1 hour 7-17",
                              "n_total": s1["n_total"], "n_closed": s1["n_closed"],
                              "WR": s1["WR"], "total_R": s1["total_R"],
                              "R_tr": s1["R_tr"], "freq": s1["freq_ratio"]})
        # T2: weekday
        df2 = apply_filter_T2(df); s2 = stats(df2, n_orig)
        summary_rows.append({"id": cid, "filter": "T2 Mon-Thu",
                              "n_total": s2["n_total"], "n_closed": s2["n_closed"],
                              "WR": s2["WR"], "total_R": s2["total_R"],
                              "R_tr": s2["R_tr"], "freq": s2["freq_ratio"]})
        # T3: D.O
        df3 = apply_filter_T3(df); s3 = stats(df3, n_orig)
        summary_rows.append({"id": cid, "filter": "T3 D.O prem/disc",
                              "n_total": s3["n_total"], "n_closed": s3["n_closed"],
                              "WR": s3["WR"], "total_R": s3["total_R"],
                              "R_tr": s3["R_tr"], "freq": s3["freq_ratio"]})
        # T4: combined
        df4 = apply_filter_T4(df); s4 = stats(df4, n_orig)
        summary_rows.append({"id": cid, "filter": "T4 ALL combined",
                              "n_total": s4["n_total"], "n_closed": s4["n_closed"],
                              "WR": s4["WR"], "total_R": s4["total_R"],
                              "R_tr": s4["R_tr"], "freq": s4["freq_ratio"]})

    summary = pd.DataFrame(summary_rows)
    summary.to_csv(OUT_DIR / "etap28_ict_filters.csv", index=False)
    print("\n=== ICT FILTERS RESULTS ===")
    print(summary.to_string(index=False))

    # ----- analysis: best filter per candidate -----
    print("\n=== BEST FILTER PER CANDIDATE (by R/tr improvement vs baseline) ===")
    for cid, name in CANDIDATES:
        sub = summary[summary["id"] == cid].copy()
        baseline = sub[sub["filter"] == "BASELINE"].iloc[0]
        sub["R_tr_delta"] = sub["R_tr"] - baseline["R_tr"]
        sub["WR_delta"] = sub["WR"] - baseline["WR"]
        print(f"\n--- {cid}: {name} ---")
        print(sub[["filter", "n_total", "WR", "WR_delta", "total_R",
                    "R_tr", "R_tr_delta", "freq"]].to_string(index=False))


if __name__ == "__main__":
    main()
