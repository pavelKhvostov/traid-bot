"""Forensic-анализ Strategy 1.1.7 — те же фичи что etap_35 (Андрей на 1.1.1).

Берём 76 closed trades из signals/backtest_strategy_1_1_7.csv. Для каждого
считаем features at signal_time (fvg_c2_time, конвертированный из UTC+3 в UTC):

  - Hull MA(78) trend на 1d / 4h / 1h
  - ASVK Custom RSI ema_3 zone на 1h
  - Money Hands bw2 color на 1h
  - Money Hands MF sign на 1h
  - EMA200 align на 4h / 1h / 15m
  - ICT hour / weekday / session / daily-open premium-discount

Per-feature WR/total_R + composite score filter — точно как 1.1.1.
Сравнение с baseline (WR 52.6%, +4R на 76 closed).

CSV всех trades + features → output/etap_111_7_trades_features.csv.
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

# Подкладываем elements_study в путь для импорта etap_35 helpers.
_ELEMENTS = _ROOT / "research" / "elements_study"
if str(_ELEMENTS) not in _sys.path:
    _sys.path.insert(0, str(_ELEMENTS))

from pathlib import Path

import numpy as np
import pandas as pd

from data_manager import load_df
from etap_35_strategy_111_forensic import (
    asof_value,
    asvk_adjusted_rsi,
    asvk_dynamic_levels,
    asvk_zone_label,
    daily_open_pos,
    ema_fast,
    ema_trend,
    hull_ma,
    hull_trend,
    mh_color_label,
    money_flow_ha,
    money_hands_bw2,
    report_segment,
    segment,
)

SYMBOL = "BTCUSDT"
TRADES_CSV = Path("signals/backtest_strategy_1_1_7.csv")
OUT_DIR = Path("research/1_1_7/forensic/output")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def parse_utc3_to_utc(s: str) -> pd.Timestamp:
    """CSV хранит времена в UTC+3 как 'YYYY-MM-DD HH:MM'. Возвращаем UTC."""
    if pd.isna(s) or s == "":
        return pd.NaT
    return (pd.Timestamp(s, tz="UTC") - pd.Timedelta(hours=3))


def session_label(hour_utc: int) -> str:
    if 0 <= hour_utc < 7:
        return "Asia"
    if 7 <= hour_utc < 12:
        return "London"
    if 12 <= hour_utc < 17:
        return "NY"
    return "off"


def main():
    print("[INFO] Forensic 1.1.7 — features at signal_time")
    print(f"  trades: {TRADES_CSV}")

    df = pd.read_csv(TRADES_CSV)
    df = df[df["outcome"].isin(["WIN", "LOSS"])].copy()
    print(f"  closed trades: {len(df)}")

    # signal_time (UTC) = fvg_c2_time (UTC+3) - 3h
    df["signal_time_utc"] = df["fvg_c2_time"].apply(parse_utc3_to_utc)
    df = df.dropna(subset=["signal_time_utc"]).reset_index(drop=True)
    print(f"  after drop NaT: {len(df)}")

    df["R"] = df["pnl_r"].astype(float)
    df["outcome_lc"] = df["outcome"].str.lower()
    df["entry"] = df["entry"].astype(float)
    baseline_n = len(df)
    baseline_wr = (df["outcome_lc"] == "win").sum() / baseline_n * 100
    baseline_R = df["R"].sum()
    print(f"  baseline: n={baseline_n}  WR={baseline_wr:.1f}%  total={baseline_R:+.1f}R")

    print("\n[INFO] load indicators data")
    df_1d = load_df(SYMBOL, "1d")
    df_4h = load_df(SYMBOL, "4h")
    df_1h = load_df(SYMBOL, "1h")
    df_15m = load_df(SYMBOL, "15m")
    for d, name in [(df_1d, "1d"), (df_4h, "4h"), (df_1h, "1h"), (df_15m, "15m")]:
        print(f"  {name}: {len(d)} bars  range [{d.index[0]} .. {d.index[-1]}]")

    print("\n[INFO] compute indicators")
    hull_len = 78
    hull_1d = hull_ma(df_1d["close"], hull_len)
    hull_4h = hull_ma(df_4h["close"], hull_len)
    hull_1h = hull_ma(df_1h["close"], hull_len)
    ema200_4h = pd.Series(ema_fast(df_4h["close"].to_numpy(), 200), index=df_4h.index)
    ema200_1h = pd.Series(ema_fast(df_1h["close"].to_numpy(), 200), index=df_1h.index)
    ema200_15m = pd.Series(ema_fast(df_15m["close"].to_numpy(), 200), index=df_15m.index)

    asvk_ema3_1h = asvk_adjusted_rsi(df_1h["close"])
    asvk_above_1h, asvk_below_1h = asvk_dynamic_levels(asvk_ema3_1h, lookback=200)

    bw2_1h, sma14_1h = money_hands_bw2(df_1h)
    mf_1h = money_flow_ha(df_1h)

    print("\n[INFO] extract features at each signal_time")
    rows = []
    for _, t in df.iterrows():
        ts = t["signal_time_utc"]
        direction = t["direction"]
        entry = t["entry"]

        # Hull trends — "aligned" если совпадает с направлением сетапа.
        def hull_align(series, ref_close):
            res = hull_trend(ref_close, series, ts)
            if res == "na":
                return "na"
            if direction == "LONG":
                return "aligned" if res == "up" else "counter"
            return "aligned" if res == "down" else "counter"

        hull_1d_a = hull_align(hull_1d, df_1d["close"])
        hull_4h_a = hull_align(hull_4h, df_4h["close"])
        hull_1h_a = hull_align(hull_1h, df_1h["close"])

        # EMA200 align — close vs ema200 (на 4h/1h/15m).
        def ema_align(close_series, ema_series):
            res = ema_trend(close_series, ema_series, ts)
            if res == "na":
                return "na"
            if direction == "LONG":
                return "aligned" if res == "above" else "counter"
            return "aligned" if res == "below" else "counter"

        ema200_4h_a = ema_align(df_4h["close"], ema200_4h)
        ema200_1h_a = ema_align(df_1h["close"], ema200_1h)
        ema200_15m_a = ema_align(df_15m["close"], ema200_15m)

        # ASVK zone (на 1h).
        asvk_zone = asvk_zone_label(asvk_ema3_1h, asvk_above_1h, asvk_below_1h, ts)

        # Money Hands bw2 color (на 1h).
        mh_color = mh_color_label(bw2_1h, sma14_1h, ts)

        # MF sign — aligned/counter.
        mf_val = asof_value(mf_1h, ts)
        if np.isnan(mf_val):
            mh_mf = "na"
        else:
            mf_dir = "pos" if mf_val > 0 else ("neg" if mf_val < 0 else "zero")
            if direction == "LONG":
                mh_mf = "aligned" if mf_dir == "pos" else (
                    "counter" if mf_dir == "neg" else "zero")
            else:
                mh_mf = "aligned" if mf_dir == "neg" else (
                    "counter" if mf_dir == "pos" else "zero")

        # ICT.
        hour = int(ts.hour)
        weekday = ts.day_name()
        session = session_label(hour)
        do_pos = daily_open_pos(df_1d, ts, entry)
        if direction == "SHORT" and do_pos in ("premium", "discount"):
            # для SHORT premium == "aligned" (короткий из вершины), discount == counter
            do_align = "aligned" if do_pos == "premium" else "counter"
        elif direction == "LONG" and do_pos in ("premium", "discount"):
            do_align = "aligned" if do_pos == "discount" else "counter"
        else:
            do_align = "na"

        rows.append({
            "signal_time": ts.isoformat(),
            "direction": direction,
            "outcome": t["outcome_lc"],
            "R": t["R"],
            "hull_1d": hull_1d_a,
            "hull_4h": hull_4h_a,
            "hull_1h": hull_1h_a,
            "ema200_4h": ema200_4h_a,
            "ema200_1h": ema200_1h_a,
            "ema200_15m": ema200_15m_a,
            "asvk_zone_1h": asvk_zone,
            "mh_color_1h": mh_color,
            "mh_mf_1h": mh_mf,
            "hour": hour,
            "weekday": weekday,
            "session": session,
            "do_align": do_align,
            "ob_tf": t["ob_tf"],
            "fvg_tf": t["fvg_tf"],
        })

    feat = pd.DataFrame(rows)
    csv_path = OUT_DIR / "etap_111_7_trades_features.csv"
    feat.to_csv(csv_path, index=False)
    print(f"  saved: {csv_path}  ({len(feat)} rows)")

    print("\n" + "=" * 72)
    print(f"FEATURE REPORTS — baseline WR={baseline_wr:.1f}%  total={baseline_R:+.1f}R  n={baseline_n}")
    print("=" * 72)

    features_to_report = [
        "hull_1d", "hull_4h", "hull_1h",
        "ema200_4h", "ema200_1h", "ema200_15m",
        "asvk_zone_1h", "mh_color_1h", "mh_mf_1h",
        "session", "do_align",
        "ob_tf", "fvg_tf", "direction",
    ]
    for feature in features_to_report:
        report_segment("", feat, feature, baseline_wr, baseline_R)

    # ---------- composite score filter ----------
    print("\n" + "=" * 72)
    print("COMPOSITE SCORE FILTER (top positive features, n>=20)")
    print("=" * 72)

    # Топ-5 фич выберем динамически — те где aligned даёт WR >= baseline+5 и n>=20.
    score_features: list[tuple[str, str]] = []
    candidates = ["hull_1d", "hull_4h", "hull_1h",
                  "ema200_4h", "ema200_1h", "ema200_15m",
                  "mh_mf_1h", "do_align"]
    for f in candidates:
        if f not in feat.columns:
            continue
        sub = feat[feat[f] == "aligned"]
        if len(sub) >= 20:
            wr = (sub["outcome"] == "win").sum() / len(sub) * 100
            if wr - baseline_wr >= 5:
                score_features.append((f, "aligned"))
                print(f"  + include: {f}=aligned (n={len(sub)} WR={wr:.1f}%)")

    if not score_features:
        print("  [WARN] нет фич с WR >= baseline+5pp")
        return

    print(f"\n  Score = count of aligned features among {len(score_features)} predictors")
    feat["score"] = sum(
        (feat[f] == val).astype(int) for f, val in score_features
    )

    print("\n  Score buckets:")
    for sc in sorted(feat["score"].unique()):
        sub = feat[feat["score"] == sc]
        n = len(sub)
        wins = (sub["outcome"] == "win").sum()
        wr = wins / n * 100 if n else 0
        total = sub["R"].sum()
        print(f"    score={sc}: n={n:>3}  WR={wr:5.1f}%  total={total:+6.1f}R  "
              f"avg={total/n if n else 0:+.3f}")


if __name__ == "__main__":
    main()
