"""Forensic-анализ Strategy 1.1.3 — те же индикаторы что для 1.1.2 / 1.1.7.

Baseline: 6.3y BTC, fvg_variant=v1, macro_mode=untouched, RR=2.2.
Params (из stage3_v1_compare_ep): entry_pct=0.0, sl_pct=0.60 inside OB-htf.

Output: research/1_1_3/optimize/output/forensic_1_1_3_features.csv
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
    asvk_adjusted_rsi, asvk_dynamic_levels, compute_atr,
    ema_fast, hull_ma, money_flow_ha, money_hands_bw2,
)
from strategies.strategy_1_1_3 import detect_strategy_1_1_3_signals

SYMBOL = "BTCUSDT"
DAYS_BACK = 2310  # 6.3y
ENTRY_PCT = 0.0    # close c2 inside FVG. v1 winner.
SL_PCT = 0.60      # inside OB-htf
RR = 2.2

OUT_DIR = Path("research/1_1_3/optimize/output")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def safe_label(s, ts):
    idx = s.index.searchsorted(ts, side="right") - 1
    if idx < 1: return "na"
    v = s.iloc[idx - 1]
    return v if pd.notna(v) else "na"


def safe_value(s, ts):
    idx = s.index.searchsorted(ts, side="right") - 1
    if idx < 1: return np.nan
    v = s.iloc[idx - 1]
    return float(v) if pd.notna(v) else np.nan


def hull_trend_labels(close, hull):
    h2 = hull.shift(2)
    return pd.Series(np.where(close > h2, "up", np.where(close < h2, "down", "na")), index=close.index)


def ema200_labels(close, ema):
    return pd.Series(np.where(close > ema, "above", np.where(close < ema, "below", "na")), index=close.index)


def asvk_zone_labels(ema_3, above, below):
    labels = []
    for i in range(len(ema_3)):
        e = ema_3.iloc[i]; a = above.iloc[i]; b = below.iloc[i]
        if pd.isna(e) or pd.isna(a) or pd.isna(b): labels.append("na"); continue
        if e > a: labels.append("red")
        elif e > 50 + (a - 50) * 0.5: labels.append("yellow_OB")
        elif e < b: labels.append("green")
        elif e < 50 - (50 - b) * 0.5: labels.append("yellow_OS")
        else: labels.append("neutral")
    return pd.Series(labels, index=ema_3.index)


def mh_color_labels(bw2, sma14):
    labels = []
    for i in range(len(bw2)):
        v = bw2.iloc[i]; s = sma14.iloc[i]
        if pd.isna(v) or pd.isna(s): labels.append("na"); continue
        if v > 0: labels.append("green" if v >= s else "grey_from_green")
        elif v < 0: labels.append("red" if v <= s else "grey_from_red")
        else: labels.append("neutral")
    return pd.Series(labels, index=bw2.index)


def aligned(direction, label, up="up", down="down"):
    if label == "na": return None
    if direction == "LONG": return label == up
    return label == down


def hull_align(d, lbl):
    a = aligned(d, lbl, "up", "down")
    return "aligned" if a else ("counter" if a is False else "na")


def ema200_align(d, lbl):
    a = aligned(d, lbl, "above", "below")
    return "aligned" if a else ("counter" if a is False else "na")


def mh_color_align(d, color):
    if color == "na": return "na"
    bull = color in ("green", "grey_from_red")
    bear = color in ("red", "grey_from_green")
    if d == "LONG": return "aligned" if bull else ("counter" if bear else "neutral")
    return "aligned" if bear else ("counter" if bull else "neutral")


def mh_mf_align(d, v):
    if np.isnan(v): return "na"
    pos = v > 0
    if d == "LONG": return "aligned" if pos else "counter"
    return "aligned" if not pos else "counter"


def do_align(d, entry, df_1d, ts):
    idx = df_1d.index.searchsorted(ts, side="right") - 1
    if idx < 0: return "na"
    do = df_1d["open"].iloc[idx]
    if entry > do: lbl = "premium"
    elif entry < do: lbl = "discount"
    else: return "mid"
    if d == "LONG": return "aligned" if lbl == "discount" else "counter"
    return "aligned" if lbl == "premium" else "counter"


def session_label(h):
    if h < 7: return "Asia"
    if h < 12: return "London"
    if h < 17: return "NY"
    return "off"


def simulate(d, entry, sl, tp, ts, ts_arr, h_arr, l_arr):
    st = ts.tz_localize(None) if ts.tz else ts
    end = st + pd.Timedelta(days=30)
    i0 = np.searchsorted(ts_arr, np.datetime64(st))
    i1 = np.searchsorted(ts_arr, np.datetime64(end))
    if i1 <= i0: return "no_data", 0.0
    h = h_arr[i0:i1]; l = l_arr[i0:i1]
    risk = abs(entry - sl)
    if risk <= 0: return "invalid", 0.0
    if d == "LONG":
        am = l <= entry
        if not am.any(): return "not_filled", 0.0
        act = int(np.argmax(am))
        if (h[:act] >= tp).any() or (l[:act] <= sl).any(): return "no_entry", 0.0
        h2 = h[act:]; l2 = l[act:]
        sh = l2 <= sl; th = h2 >= tp
        si = int(np.argmax(sh)) if sh.any() else len(h2)
        ti = int(np.argmax(th)) if th.any() else len(h2)
        if si == len(h2) and ti == len(h2): return "open", 0.0
        return ("loss", -1.0) if si <= ti else ("win", RR)
    am = h >= entry
    if not am.any(): return "not_filled", 0.0
    act = int(np.argmax(am))
    if (l[:act] <= tp).any() or (h[:act] >= sl).any(): return "no_entry", 0.0
    h2 = h[act:]; l2 = l[act:]
    sh = h2 >= sl; th = l2 <= tp
    si = int(np.argmax(sh)) if sh.any() else len(h2)
    ti = int(np.argmax(th)) if th.any() else len(h2)
    if si == len(h2) and ti == len(h2): return "open", 0.0
    return ("loss", -1.0) if si <= ti else ("win", RR)


def main():
    print("=" * 72)
    print(f"  Forensic 1.1.3 — Indicator overlay (6.3y BTC, RR=2.2)")
    print(f"  fvg_variant=v1, macro_mode=untouched, entry_pct={ENTRY_PCT}, sl_pct={SL_PCT}")
    print("=" * 72)

    print("\n[INFO] loading data")
    df_1d = load_df(SYMBOL, "1d")
    df_12h = load_df(SYMBOL, "12h")
    df_4h = load_df(SYMBOL, "4h")
    df_1h = load_df(SYMBOL, "1h")
    df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_15m = load_df(SYMBOL, "15m")
    df_1m = load_df(SYMBOL, "1m")
    print(f"  bars: 1d={len(df_1d)} 4h={len(df_4h)} 1h={len(df_1h)} 1m={len(df_1m)}")

    today = pd.Timestamp.utcnow().normalize()
    if today.tz is None: today = today.tz_localize("UTC")
    cutoff = today - pd.Timedelta(days=DAYS_BACK)
    df_1d_f = df_1d[df_1d.index >= cutoff]
    df_12h_f = df_12h[df_12h.index >= cutoff]

    print("\n[INFO] detect 1.1.3 signals")
    sigs = detect_strategy_1_1_3_signals(
        df_1d_f, df_12h_f, df_4h, df_6h, df_1h, df_2h,
        fvg_variant="v1", macro_mode="untouched", verbose=False,
    )
    print(f"  raw signals: {len(sigs)}")

    # dedup по (signal_time, direction, mid-entry)
    seen = set()
    uniq = []
    for s in sigs:
        fvg_b, fvg_t = s["fvg_zone"]
        if s["direction"] == "LONG":
            e_d = round(fvg_b + 0.5 * (fvg_t - fvg_b), 2)
        else:
            e_d = round(fvg_t - 0.5 * (fvg_t - fvg_b), 2)
        key = (s["signal_time"], s["direction"], e_d)
        if key in seen: continue
        seen.add(key)
        uniq.append(s)
    print(f"  deduped: {len(uniq)}")

    print("\n[INFO] simulate RR=2.2")
    ts_arr = df_1m.index.values
    h_arr = df_1m["high"].to_numpy(dtype=float)
    l_arr = df_1m["low"].to_numpy(dtype=float)

    trades = []
    for s in uniq:
        d = s["direction"]
        fvg_b, fvg_t = s["fvg_zone"]
        ob_b, ob_t = s["ob_htf_zone"]
        if d == "LONG":
            entry = fvg_b + ENTRY_PCT * (fvg_t - fvg_b)
            sl = ob_b + SL_PCT * (ob_t - ob_b)
            if sl >= entry: continue
            tp = entry + RR * (entry - sl)
        else:
            entry = fvg_t - ENTRY_PCT * (fvg_t - fvg_b)
            sl = ob_t - SL_PCT * (ob_t - ob_b)
            if sl <= entry: continue
            tp = entry - RR * (sl - entry)
        ts = s["signal_time"]
        if not isinstance(ts, pd.Timestamp): ts = pd.Timestamp(ts)
        if ts.tz is None: ts = ts.tz_localize("UTC")
        outcome, r = simulate(d, entry, sl, tp, ts, ts_arr, h_arr, l_arr)
        trades.append({
            "signal_time": ts, "direction": d,
            "entry": round(entry, 2), "sl": round(sl, 2), "tp": round(tp, 2),
            "outcome": outcome, "R": r,
        })
    print(f"  simulated: {len(trades)}")

    closed = [t for t in trades if t["outcome"] in ("win", "loss")]
    n_cl = len(closed)
    wr = sum(1 for t in closed if t["outcome"] == "win") / n_cl * 100 if n_cl else 0
    total_R = sum(t["R"] for t in trades)
    print(f"  closed: {n_cl}  WR: {wr:.1f}%  total: {total_R:+.1f}R\n")

    if n_cl == 0:
        print("[WARN] no closed trades, exit")
        return

    print("[INFO] compute indicators")
    hull_lengths = [49, 78, 100, 160]
    tf_data = {"1d": df_1d, "12h": compose_from_base(df_1h, "12h"),
                "4h": df_4h, "1h": df_1h}
    hull_labels = {}
    for tf, d in tf_data.items():
        for L in hull_lengths:
            h = hull_ma(d["close"], L)
            hull_labels[f"{tf}_L{L}"] = hull_trend_labels(d["close"], h)
    ema_labels = {}
    for tf, d in [("1d", df_1d), ("4h", df_4h), ("1h", df_1h), ("15m", df_15m)]:
        ema = pd.Series(ema_fast(d["close"].to_numpy(), 200), index=d.index)
        ema_labels[tf] = ema200_labels(d["close"], ema)
    asvk_zones = {}
    for tf, d in [("1h", df_1h), ("4h", df_4h)]:
        ema3 = asvk_adjusted_rsi(d["close"])
        a, b = asvk_dynamic_levels(ema3, lookback=200)
        asvk_zones[tf] = asvk_zone_labels(ema3, a, b)
    mh_colors = {}; mh_mfs = {}
    for tf, d in [("1h", df_1h), ("4h", df_4h)]:
        bw2, sma14 = money_hands_bw2(d)
        mh_colors[tf] = mh_color_labels(bw2, sma14)
        mh_mfs[tf] = money_flow_ha(d)
    atr_series = {"1h": compute_atr(df_1h, 14), "4h": compute_atr(df_4h, 14)}
    print("  indicators ready")

    print("\n[INFO] extract features")
    rows = []
    for t in trades:
        if t["outcome"] not in ("win", "loss"): continue
        ts = t["signal_time"]; d = t["direction"]; entry = t["entry"]
        f = {
            "signal_time": ts.isoformat(), "direction": d,
            "outcome": t["outcome"], "R": t["R"],
            "entry": entry, "sl": t["sl"], "tp": t["tp"],
        }
        for key, lbl in hull_labels.items():
            f[f"hull_{key}"] = hull_align(d, safe_label(lbl, ts))
        for tf, lbl in ema_labels.items():
            f[f"ema200_{tf}"] = ema200_align(d, safe_label(lbl, ts))
        for tf, lbl in asvk_zones.items():
            f[f"asvk_{tf}"] = safe_label(lbl, ts)
        for tf, c_series in mh_colors.items():
            color = safe_label(c_series, ts)
            f[f"mh_{tf}_color"] = color
            f[f"mh_{tf}_color_align"] = mh_color_align(d, color)
        for tf, mf_s in mh_mfs.items():
            f[f"mh_{tf}_mf_align"] = mh_mf_align(d, safe_value(mf_s, ts))
        f["hour"] = int(ts.hour)
        f["weekday"] = ts.day_name()
        f["session"] = session_label(int(ts.hour))
        f["do_align"] = do_align(d, entry, df_1d, ts)
        a1 = safe_value(atr_series["1h"], ts)
        a4 = safe_value(atr_series["4h"], ts)
        if not np.isnan(a1) and not np.isnan(a4) and a4 > 0:
            r_ = a1 / a4
            f["atr_ratio_bin"] = "low" if r_ < 0.4 else ("med" if r_ < 0.6 else "high")
        else:
            f["atr_ratio_bin"] = "na"
        rows.append(f)

    feat_df = pd.DataFrame(rows)
    csv = OUT_DIR / "forensic_1_1_3_features.csv"
    feat_df.to_csv(csv, index=False)
    print(f"  saved: {csv}  ({len(feat_df)} rows × {len(feat_df.columns)} cols)")

    base_wr = (feat_df["outcome"] == "win").sum() / len(feat_df) * 100
    base_R = feat_df["R"].sum()
    print(f"\n{'='*72}\n  PER-FEATURE  baseline n={len(feat_df)} WR={base_wr:.1f}% total={base_R:+.1f}R\n{'='*72}")

    def seg(f):
        g = feat_df.groupby(f).agg(
            n=("R", "size"),
            wins=("outcome", lambda x: (x == "win").sum()),
            total_R=("R", "sum"),
        )
        g["WR"] = g["wins"] / g["n"] * 100
        g["d_pp"] = g["WR"] - base_wr
        g["avg_R"] = g["total_R"] / g["n"]
        return g.sort_values("WR", ascending=False)

    interesting = [c for c in feat_df.columns
                    if c not in ("signal_time","direction","outcome","R","entry","sl","tp")]
    for f in interesting:
        g = seg(f)
        if (g["n"] >= 10).sum() == 0: continue
        print(f"\n--- {f} ---")
        for cat, row in g.iterrows():
            n = int(row["n"])
            flag = ""
            if n >= 10 and abs(row["d_pp"]) >= 5:
                flag = " ***" if row["d_pp"] > 0 else " !"
            print(f"  {cat!s:<22} n={n:>4} WR={row['WR']:5.1f}% "
                  f"(d={row['d_pp']:+5.1f}pp) total={row['total_R']:+6.1f}R "
                  f"avg={row['avg_R']:+.3f}{flag}")

    print(f"\n{'='*72}\n  COMPOSITE FILTER  (n>=20, d_pp>=3)\n{'='*72}")
    candidates = []
    for f in interesting:
        for cat in feat_df[f].unique():
            sub = feat_df[feat_df[f] == cat]
            n = len(sub)
            if n < 20: continue
            wr = (sub["outcome"] == "win").sum() / n * 100
            d = wr - base_wr
            if d >= 3:
                candidates.append((f, cat, n, wr, d, sub["R"].sum()))
    candidates.sort(key=lambda x: x[4], reverse=True)
    print("\nTop candidates by d_pp:")
    for f, cat, n, wr, d, total in candidates[:15]:
        print(f"  {f}={cat!s:<20} n={n:>3} WR={wr:.1f}% d={d:+.1f}pp total={total:+.1f}R")

    selected = []; used = set()
    for f, cat, *_ in candidates:
        if f not in used:
            selected.append((f, cat)); used.add(f)
        if len(selected) >= 5: break
    if not selected:
        print("\n[WARN] no enhancers"); return
    print(f"\nSelected enhancers: {selected}")
    feat_df["score"] = sum((feat_df[f] == cat).astype(int) for f, cat in selected)
    print(f"\nScore distribution (max={len(selected)}):")
    for sc in sorted(feat_df["score"].unique()):
        sub = feat_df[feat_df["score"] == sc]
        n = len(sub); wr = (sub["outcome"] == "win").sum() / n * 100 if n else 0
        total = sub["R"].sum(); avg = total / n if n else 0
        print(f"  score={sc}: n={n:>4} WR={wr:5.1f}% total={total:+6.1f}R avg={avg:+.3f}")


if __name__ == "__main__":
    main()
