"""Этап 47 (1.1.7-edition): Полный forensic 1.1.7 с поиском разделяющих фич.

Реплика etap_47_111_2_full_forensic под 1.1.7. Берём closed trades из
расширенного 6.3y backtest и считаем 30+ фич per trade.

Features (как у Андрея):
  - Hull MA на 1h/4h/12h/1d, длины 49/78/100/160
  - ASVK ema_3 zone на 1h, 4h
  - MH bw2 color + MF sign на 1h, 4h
  - Pro-trend EMA200 на 1h, 4h, 1d
  - Hour-of-day, weekday, session
  - FVG width %, OB depth %, ATR ratio 1h/4h
  - Daily-open premium/discount

Phase A: SAFE baseline 1.1.7 6.3y → closed trades CSV
Phase B: extract features at signal_time (с safe lookup — last CLOSED bar)
Phase C: per-feature segment WR/total_R
Phase D: hull length sensitivity (49/78/100/160 × 1h/4h/12h/1d)
Phase E: композитный score filter (top fich, n>=20, WR>=baseline+3pp)
Phase F: year-by-year breakdown best filter
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

_ELEMENTS = _ROOT / "research" / "elements_study"
if str(_ELEMENTS) not in _sys.path:
    _sys.path.insert(0, str(_ELEMENTS))

from pathlib import Path

import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df
from etap_35_strategy_111_forensic import (
    asvk_adjusted_rsi,
    asvk_dynamic_levels,
    asvk_zone_label,
    compute_atr,
    ema_fast,
    hull_ma,
    money_flow_ha,
    money_hands_bw2,
)

SYMBOL = "BTCUSDT"
TRADES_CSV = Path("signals/backtest_strategy_1_1_7.csv")
OUT_DIR = Path("research/1_1_7/forensic/output")
OUT_DIR.mkdir(parents=True, exist_ok=True)


# ---------- safe lookup (last CLOSED bar) — anti-lookahead из etap_47 ----------

def safe_label(label_series: pd.Series, ts: pd.Timestamp) -> str:
    """Last CLOSED bar's label (idx - 1 чтобы избежать FORMING bar)."""
    idx = label_series.index.searchsorted(ts, side="right") - 1
    if idx < 1:
        return "na"
    val = label_series.iloc[idx - 1]
    return val if pd.notna(val) else "na"


def safe_value(series: pd.Series, ts: pd.Timestamp) -> float:
    idx = series.index.searchsorted(ts, side="right") - 1
    if idx < 1:
        return np.nan
    v = series.iloc[idx - 1]
    return float(v) if pd.notna(v) else np.nan


def parse_utc3_to_utc(s: str) -> pd.Timestamp:
    if pd.isna(s) or s == "":
        return pd.NaT
    return (pd.Timestamp(s, tz="UTC") - pd.Timedelta(hours=3))


# ---------- precompute indicator label series ----------

def hull_trend_labels(close: pd.Series, hull: pd.Series) -> pd.Series:
    """For each bar: 'up' if close > hull[-2], 'down' otherwise."""
    h2 = hull.shift(2)
    return pd.Series(
        np.where(close > h2, "up", np.where(close < h2, "down", "na")),
        index=close.index,
    )


def ema200_align_labels(close: pd.Series, ema: pd.Series) -> pd.Series:
    return pd.Series(
        np.where(close > ema, "above", np.where(close < ema, "below", "na")),
        index=close.index,
    )


def asvk_zone_labels(ema_3: pd.Series, above: pd.Series, below: pd.Series) -> pd.Series:
    labels = []
    for i in range(len(ema_3)):
        e = ema_3.iloc[i]
        a = above.iloc[i]
        b = below.iloc[i]
        if pd.isna(e) or pd.isna(a) or pd.isna(b):
            labels.append("na")
        elif e > a:
            labels.append("red")
        elif e > 50 + (a - 50) * 0.5:
            labels.append("yellow_OB")
        elif e < b:
            labels.append("green")
        elif e < 50 - (50 - b) * 0.5:
            labels.append("yellow_OS")
        else:
            labels.append("neutral")
    return pd.Series(labels, index=ema_3.index)


def mh_color_labels(bw2: pd.Series, sma14: pd.Series) -> pd.Series:
    labels = []
    for i in range(len(bw2)):
        v = bw2.iloc[i]
        s = sma14.iloc[i]
        if pd.isna(v) or pd.isna(s):
            labels.append("na")
        elif v > 0:
            labels.append("green" if v >= s else "grey_from_green")
        elif v < 0:
            labels.append("red" if v <= s else "grey_from_red")
        else:
            labels.append("neutral")
    return pd.Series(labels, index=bw2.index)


# ---------- align helpers (направление-aware) ----------

def aligned(direction, label, up="up", down="down"):
    if label == "na":
        return None
    if direction == "LONG":
        return label == up
    return label == down


def hull_align(direction: str, label: str) -> str:
    a = aligned(direction, label, "up", "down")
    return "aligned" if a else ("counter" if a is False else "na")


def ema200_align(direction: str, label: str) -> str:
    a = aligned(direction, label, "above", "below")
    return "aligned" if a else ("counter" if a is False else "na")


def mh_color_align(direction: str, color: str) -> str:
    if color == "na":
        return "na"
    bullish = color in ("green", "grey_from_red")
    bearish = color in ("red", "grey_from_green")
    if direction == "LONG":
        return "aligned" if bullish else ("counter" if bearish else "neutral")
    return "aligned" if bearish else ("counter" if bullish else "neutral")


def mh_mf_align(direction: str, mf_val: float) -> str:
    if np.isnan(mf_val):
        return "na"
    pos = mf_val > 0
    if direction == "LONG":
        return "aligned" if pos else "counter"
    return "aligned" if not pos else "counter"


def do_align(direction: str, entry: float, df_1d: pd.DataFrame, ts: pd.Timestamp) -> str:
    idx = df_1d.index.searchsorted(ts, side="right") - 1
    if idx < 0:
        return "na"
    do = df_1d["open"].iloc[idx]
    if entry > do:
        do_label = "premium"
    elif entry < do:
        do_label = "discount"
    else:
        return "mid"
    if direction == "LONG":
        return "aligned" if do_label == "discount" else "counter"
    return "aligned" if do_label == "premium" else "counter"


# ---------- main ----------

def session_label(hour: int) -> str:
    if hour < 7:
        return "Asia"
    if hour < 12:
        return "London"
    if hour < 17:
        return "NY"
    return "off"


def main():
    print("[INFO] Forensic 1.1.7 — расширенный (etap_47 style)")
    print(f"  trades: {TRADES_CSV}")

    df = pd.read_csv(TRADES_CSV)
    df = df[df["outcome"].isin(["WIN", "LOSS"])].copy()
    print(f"  closed trades: {len(df)}")

    df["signal_time_utc"] = df["fvg_c2_time"].apply(parse_utc3_to_utc)
    df = df.dropna(subset=["signal_time_utc"]).reset_index(drop=True)
    df["R"] = df["pnl_r"].astype(float)
    df["outcome_lc"] = df["outcome"].str.lower()
    df["entry"] = df["entry"].astype(float)

    baseline_n = len(df)
    baseline_wr = (df["outcome_lc"] == "win").sum() / baseline_n * 100
    baseline_R = df["R"].sum()
    print(f"  baseline: n={baseline_n}  WR={baseline_wr:.1f}%  total={baseline_R:+.1f}R")

    print("\n[INFO] загружаем данные индикаторов")
    df_1d = load_df(SYMBOL, "1d")
    df_4h = load_df(SYMBOL, "4h")
    df_1h = load_df(SYMBOL, "1h")
    df_15m = load_df(SYMBOL, "15m")
    df_12h = compose_from_base(df_1h, "12h")
    for d, name in [(df_1d, "1d"), (df_12h, "12h"), (df_4h, "4h"), (df_1h, "1h"), (df_15m, "15m")]:
        print(f"  {name}: {len(d)}  [{d.index[0]} .. {d.index[-1]}]")

    print("\n[INFO] precompute indicators")
    hull_lengths = [49, 78, 100, 160]
    tf_data = {"1d": df_1d, "12h": df_12h, "4h": df_4h, "1h": df_1h}

    hull_labels: dict[str, pd.Series] = {}
    for tf, d in tf_data.items():
        for L in hull_lengths:
            h = hull_ma(d["close"], L)
            hull_labels[f"{tf}_L{L}"] = hull_trend_labels(d["close"], h)
    print(f"  hull labels: {len(hull_labels)} (4 TF × 4 lengths)")

    ema_labels: dict[str, pd.Series] = {}
    for tf, d in [("1d", df_1d), ("4h", df_4h), ("1h", df_1h), ("15m", df_15m)]:
        ema = pd.Series(ema_fast(d["close"].to_numpy(), 200), index=d.index)
        ema_labels[tf] = ema200_align_labels(d["close"], ema)

    asvk_zones: dict[str, pd.Series] = {}
    for tf, d in [("1h", df_1h), ("4h", df_4h)]:
        ema3 = asvk_adjusted_rsi(d["close"])
        above, below = asvk_dynamic_levels(ema3, lookback=200)
        asvk_zones[tf] = asvk_zone_labels(ema3, above, below)
    print(f"  ASVK zones computed: {list(asvk_zones)}")

    mh_colors: dict[str, pd.Series] = {}
    mh_mfs: dict[str, pd.Series] = {}
    for tf, d in [("1h", df_1h), ("4h", df_4h)]:
        bw2, sma14 = money_hands_bw2(d)
        mh_colors[tf] = mh_color_labels(bw2, sma14)
        mh_mfs[tf] = money_flow_ha(d)
    print(f"  MH colors + MF: {list(mh_colors)}")

    atr_series: dict[str, pd.Series] = {
        "1h": compute_atr(df_1h, 14),
        "4h": compute_atr(df_4h, 14),
    }

    print("\n[INFO] extract features per trade")
    rows = []
    for _, t in df.iterrows():
        ts = t["signal_time_utc"]
        direction = t["direction"]
        entry = t["entry"]

        feat = {
            "signal_time": ts.isoformat(),
            "direction": direction,
            "outcome": t["outcome_lc"],
            "R": t["R"],
            "ob_tf": t["ob_tf"],
            "fvg_tf": t["fvg_tf"],
        }

        # Hull alignment по 4 TF × 4 lengths = 16 features
        for key, lbl_series in hull_labels.items():
            lbl = safe_label(lbl_series, ts)
            feat[f"hull_{key}"] = hull_align(direction, lbl)

        # EMA200 alignment по 4 TF
        for tf, lbl_series in ema_labels.items():
            lbl = safe_label(lbl_series, ts)
            feat[f"ema200_{tf}"] = ema200_align(direction, lbl)

        # ASVK zone (raw label) + zone aligned проще не делать
        for tf, lbl_series in asvk_zones.items():
            feat[f"asvk_{tf}"] = safe_label(lbl_series, ts)

        # MH color alignment + MF sign
        for tf, c_series in mh_colors.items():
            color = safe_label(c_series, ts)
            feat[f"mh_{tf}_color"] = color
            feat[f"mh_{tf}_color_align"] = mh_color_align(direction, color)

        for tf, mf_series in mh_mfs.items():
            v = safe_value(mf_series, ts)
            feat[f"mh_{tf}_mf_align"] = mh_mf_align(direction, v)

        # ICT time
        feat["hour"] = int(ts.hour)
        feat["weekday"] = ts.day_name()
        feat["session"] = session_label(int(ts.hour))

        # Daily-open premium/discount
        feat["do_align"] = do_align(direction, entry, df_1d, ts)

        # ATR ratio
        atr_1h = safe_value(atr_series["1h"], ts)
        atr_4h = safe_value(atr_series["4h"], ts)
        if not np.isnan(atr_1h) and not np.isnan(atr_4h) and atr_4h > 0:
            ratio = atr_1h / atr_4h
            feat["atr_ratio_bin"] = ("low" if ratio < 0.4
                                     else "med" if ratio < 0.6 else "high")
        else:
            feat["atr_ratio_bin"] = "na"

        rows.append(feat)

    feat_df = pd.DataFrame(rows)
    csv_path = OUT_DIR / "etap_47_111_7_trades_features.csv"
    feat_df.to_csv(csv_path, index=False)
    print(f"  saved: {csv_path}  ({len(feat_df)} rows × {len(feat_df.columns)} cols)")

    # ---------- Phase C: per-feature WR/total_R ----------

    print("\n" + "=" * 72)
    print(f"PER-FEATURE SEGMENTS  (baseline WR={baseline_wr:.1f}%  total={baseline_R:+.1f}R)")
    print("=" * 72)

    def seg(feature: str, min_n: int = 15):
        g = feat_df.groupby(feature).agg(
            n=("R", "size"),
            wins=("outcome", lambda x: (x == "win").sum()),
            total_R=("R", "sum"),
        )
        g["WR"] = g["wins"] / g["n"] * 100
        g["d_pp"] = g["WR"] - baseline_wr
        g["avg_R"] = g["total_R"] / g["n"]
        return g.sort_values("WR", ascending=False)

    interesting = [
        c for c in feat_df.columns
        if c not in ("signal_time", "direction", "outcome", "R", "entry")
    ]
    for f in interesting:
        g = seg(f)
        # Печатаем только если есть категории с n>=15
        if (g["n"] >= 15).sum() == 0:
            continue
        print(f"\n--- {f} ---")
        for cat, row in g.iterrows():
            n = int(row["n"])
            flag = ""
            if n >= 15 and abs(row["d_pp"]) >= 5:
                flag = " ***" if row["d_pp"] > 0 else " !"
            print(f"  {cat!s:<22} n={n:>4} WR={row['WR']:5.1f}% (d={row['d_pp']:+5.1f}pp) "
                  f"total={row['total_R']:+6.1f}R  avg={row['avg_R']:+.3f}{flag}")

    # ---------- Phase D: hull length sensitivity ----------

    print("\n" + "=" * 72)
    print("PHASE D — HULL LENGTH SENSITIVITY (aligned only)")
    print("=" * 72)
    print(f"{'TF':<5} {'L':<5} {'n':<5} {'WR':<8} {'d_pp':<8} {'total':<10} {'avg':<8}")
    for tf in ["1d", "12h", "4h", "1h"]:
        for L in hull_lengths:
            col = f"hull_{tf}_L{L}"
            sub = feat_df[feat_df[col] == "aligned"]
            n = len(sub)
            if n == 0:
                continue
            wr = (sub["outcome"] == "win").sum() / n * 100
            total = sub["R"].sum()
            avg = total / n
            print(f"{tf:<5} {L:<5} {n:<5} {wr:<8.1f} {wr-baseline_wr:+7.1f} "
                  f"{total:+9.1f} {avg:+7.3f}")

    # ---------- Phase E: composite filter ----------

    print("\n" + "=" * 72)
    print("PHASE E — COMPOSITE SCORE FILTER  (top features, n>=20, d_pp>=3)")
    print("=" * 72)

    candidates: list[tuple[str, str]] = []
    for f in interesting:
        for cat in feat_df[f].unique():
            sub = feat_df[feat_df[f] == cat]
            n = len(sub)
            if n < 20:
                continue
            wr = (sub["outcome"] == "win").sum() / n * 100
            d_pp = wr - baseline_wr
            if d_pp >= 3:
                candidates.append((f, cat, n, wr, d_pp, sub["R"].sum()))

    candidates.sort(key=lambda x: x[4], reverse=True)
    print(f"\nCandidate features (top by d_pp):")
    for f, cat, n, wr, d_pp, total in candidates[:15]:
        print(f"  {f}={cat!s:<20} n={n:>3} WR={wr:.1f}% d={d_pp:+.1f}pp total={total:+.1f}R")

    if not candidates:
        print("\n  [WARN] нет фич с n>=20 и WR>=baseline+3pp")
        return

    # Берём top-5 неперекрывающихся фич (по разным feature columns)
    selected: list[tuple[str, str]] = []
    used_cols: set[str] = set()
    for f, cat, n, wr, d_pp, _ in candidates:
        if f not in used_cols:
            selected.append((f, cat))
            used_cols.add(f)
        if len(selected) >= 5:
            break

    print(f"\nSelected for score: {selected}")
    feat_df["score"] = sum(
        (feat_df[f] == cat).astype(int) for f, cat in selected
    )

    print(f"\nScore distribution (max={len(selected)}):")
    for sc in sorted(feat_df["score"].unique()):
        sub = feat_df[feat_df["score"] == sc]
        n = len(sub)
        wins = (sub["outcome"] == "win").sum()
        wr = wins / n * 100 if n else 0
        total = sub["R"].sum()
        avg = total / n if n else 0
        print(f"  score={sc}: n={n:>4}  WR={wr:5.1f}%  total={total:+6.1f}R  avg={avg:+.3f}")

    # ---------- Phase F: year-by-year best filter ----------

    print("\n" + "=" * 72)
    print(f"PHASE F — YEAR-BY-YEAR  (best filter: score>=ceil({len(selected)/2}))")
    print("=" * 72)

    threshold = max(2, (len(selected) + 1) // 2)
    filtered = feat_df[feat_df["score"] >= threshold]
    print(f"\nThreshold: score>={threshold}, filtered n={len(filtered)}")

    filtered = filtered.copy()
    filtered["year"] = pd.to_datetime(filtered["signal_time"]).dt.year
    for y in sorted(filtered["year"].unique()):
        sub = filtered[filtered["year"] == y]
        n = len(sub)
        wins = (sub["outcome"] == "win").sum()
        wr = wins / n * 100 if n else 0
        total = sub["R"].sum()
        print(f"  {y}: n={n:>3}  WR={wr:5.1f}%  total={total:+5.1f}R")

    # save filtered CSV
    out_csv = OUT_DIR / "etap_47_111_7_filtered_trades.csv"
    filtered.to_csv(out_csv, index=False)
    print(f"\nFiltered trades saved: {out_csv}")


if __name__ == "__main__":
    main()
