"""Этап 91: forensic-анализ удачных vs неудачных сделок утверждённых стратегий
через ViC ASVK индикатор.

ViC возможности (из Pine):
  1. maxV — close LTF-свечи с максимальным dirVolume (volume-based S/R level)
  2. bullV / bearV — total bull/bear volume в HTF баре
  3. delta = bullV - bearV — net imbalance
  4. norm = delta / total — нормализованный (-1..+1)
  5. Цвет свечи: 4 состояния (bull+pos, bull+neg, bear+neg, bear+pos)
     - "bull+neg" / "bear+pos" = дивергенция (price moved, but volume against)

Извлекаем для каждой сделки на момент signal_time:
  - delta_1h_aligned: знак delta-1h согласован с направлением сделки?
  - delta_4h_aligned
  - delta_1d_aligned
  - maxV_4h_dist_atr: расстояние entry -> maxV-4h в ATR-1h единицах
  - maxV_1d_dist_atr
  - vic_div_1h: есть ли дивергенция (bar bullish but delta negative или наоборот)
  - vic_div_4h
  - bull_pct_1h = bullV/(bullV+bearV) последнего 1h бара
  - bull_pct_4h
  - bull_pct_1d
  - volume_pctl_4h: percentile of last 4h volume vs last 30 days
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
import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df


# Pine LTF mapping for non-premium, mlt=100:
#   1h chart: tfC=3600 -> rs=36 -> max(60,36)=60s -> LTF=1m
#   4h chart: tfC=14400 -> rs=144 -> max(60,144)=144s -> from_seconds -> 3m or 1m
#   1d chart: tfC=86400 -> rs=864 -> max(60,864)=864s -> 15m
LTF_FOR_HTF = {"1h": 1, "4h": 3, "1d": 15}

# Valid Pine timeframes for from_seconds rounding (in seconds).
# Pine returns closest valid TF: 1m, 3m, 5m, 10m, 15m, 30m, 1h, 2h, 4h, 6h, 8h, 12h, 1d
PINE_VALID_TF_SEC = [60, 180, 300, 600, 900, 1800, 3600, 7200, 14400, 21600, 28800, 43200, 86400]


def calc_vic_features(df_ltf: pd.DataFrame, htf_open: pd.Timestamp, htf_tf: str) -> dict | None:
    """Считаем ViC фичи для одного HTF бара.

    htf_tf: '1h' | '4h' | '1d'
    Возвращает: {maxV, bullV, bearV, delta, norm, bar_close > bar_open}
    """
    tf_hours = {"1h": 1, "4h": 4, "1d": 24}[htf_tf]
    bar_end = htf_open + pd.Timedelta(hours=tf_hours)
    win = df_ltf[(df_ltf.index >= htf_open) & (df_ltf.index < bar_end)]
    if win.empty:
        return None

    bull = win[win["close"] > win["open"]]
    bear = win[win["close"] < win["open"]]

    bullV = float(bull["volume"].sum()) if not bull.empty else 0.0
    bearV = float(bear["volume"].sum()) if not bear.empty else 0.0
    vol = bullV + bearV
    delta = bullV - bearV
    norm = delta / vol if vol > 0 else 0.0

    max_bull = bull["volume"].max() if not bull.empty else 0
    max_bear = bear["volume"].max() if not bear.empty else 0
    maxV = None
    if max_bull > max_bear:
        maxV = float(bull.loc[bull["volume"].idxmax(), "close"])
    elif max_bear > 0:
        maxV = float(bear.loc[bear["volume"].idxmax(), "close"])

    bar_open = float(win.iloc[0]["open"])
    bar_close = float(win.iloc[-1]["close"])
    bar_dir = "bull" if bar_close > bar_open else ("bear" if bar_close < bar_open else "doji")

    return {
        "maxV": maxV,
        "bullV": bullV,
        "bearV": bearV,
        "delta": delta,
        "norm": norm,
        "vol": vol,
        "bar_dir": bar_dir,
        "bar_open": bar_open,
        "bar_close": bar_close,
    }


def get_aligned(value: float, direction: str) -> str:
    """Return 'aligned'/'counter'/'neutral' based on sign vs direction."""
    if value > 0:
        return "aligned" if direction == "LONG" else "counter"
    if value < 0:
        return "aligned" if direction == "SHORT" else "counter"
    return "neutral"


def get_divergence(bar_dir: str, delta: float) -> bool:
    """ViC divergence: bar и delta в разные стороны."""
    if bar_dir == "bull" and delta < 0: return True
    if bar_dir == "bear" and delta > 0: return True
    return False


def extract_vic_for_trade(row: pd.Series, df_1m: pd.DataFrame, atr_1h: pd.Series) -> dict:
    """Извлекаем все ViC фичи для одной сделки."""
    sig_time = pd.Timestamp(row["signal_time"])
    if sig_time.tz is None:
        sig_time = sig_time.tz_localize("UTC")
    direction = row["direction"]
    entry = float(row["entry"])

    # Округляем signal_time вниз к bar open для каждого HTF.
    def bar_open(ts, tf):
        return ts.floor("h") if tf == "1h" else (
            ts.floor("4h") if tf == "4h" else ts.normalize()
        )

    out = {}
    for htf in ["1h", "4h", "1d"]:
        bo = bar_open(sig_time, htf)
        # Берём ПРЕДЫДУЩИЙ закрытый бар (idx-1)
        tf_hours = {"1h": 1, "4h": 4, "1d": 24}[htf]
        prev_bar_open = bo - pd.Timedelta(hours=tf_hours)
        # Используем 1m данные (resampled to LTF) — но для скорости расчёт прямо с 1m
        feat = calc_vic_features(df_1m, prev_bar_open, htf)
        if feat is None:
            for k in ["delta_align", "norm", "div", "bull_pct", "maxV_dist_atr"]:
                out[f"{k}_{htf}"] = None
            continue
        out[f"delta_align_{htf}"] = get_aligned(feat["delta"], direction)
        out[f"norm_{htf}"] = feat["norm"]
        out[f"div_{htf}"] = get_divergence(feat["bar_dir"], feat["delta"])
        out[f"bull_pct_{htf}"] = feat["bullV"] / feat["vol"] if feat["vol"] > 0 else None

        # Расстояние от entry до maxV в ATR-1h:
        if feat["maxV"] and len(atr_1h) > 0:
            atr_idx = atr_1h.index.searchsorted(sig_time, side="right") - 1
            a = float(atr_1h.iloc[atr_idx]) if atr_idx >= 0 else 0
            if a > 0:
                out[f"maxV_dist_atr_{htf}"] = (entry - feat["maxV"]) / a
            else:
                out[f"maxV_dist_atr_{htf}"] = None
        else:
            out[f"maxV_dist_atr_{htf}"] = None

    return out


def compute_atr(df, period=14):
    high = df["high"]; low = df["low"]; pc = df["close"].shift(1)
    tr = pd.concat([(high-low),(high-pc).abs(),(low-pc).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def analyze_feature_split(closed: pd.DataFrame, feature: str, label: str):
    """Для categorical-фичи: показать WR per category."""
    if feature not in closed.columns:
        return
    grp = closed.groupby(feature, dropna=False).agg(
        n=("R", "size"),
        wins=("outcome", lambda x: (x == "win").sum()),
        total=("R", "sum"),
    )
    grp["WR"] = (grp["wins"] / grp["n"] * 100).round(1)
    grp["avg"] = (grp["total"] / grp["n"]).round(3)
    print(f"\n{label}:")
    print(grp.to_string())


def analyze_numeric_split(closed: pd.DataFrame, feature: str, label: str, bins: int = 4):
    """Для numeric-фичи: разбить на квартили и показать WR."""
    if feature not in closed.columns:
        return
    vals = closed[feature].dropna()
    if len(vals) < 10:
        print(f"\n{label}: too few non-null ({len(vals)})")
        return
    try:
        closed["_bin"] = pd.qcut(closed[feature], q=bins, duplicates="drop")
    except Exception as e:
        print(f"\n{label}: qcut failed ({e})")
        return
    grp = closed.groupby("_bin", observed=True).agg(
        n=("R", "size"),
        wins=("outcome", lambda x: (x == "win").sum()),
        total=("R", "sum"),
    )
    grp["WR"] = (grp["wins"] / grp["n"] * 100).round(1)
    grp["avg"] = (grp["total"] / grp["n"]).round(3)
    print(f"\n{label} (quartiles):")
    print(grp.to_string())


def main():
    print("[INFO] Загрузка трейдов и данных")
    csv_114 = Path("research/elements_study/output/etap74_BFJK_fixed_portfolio.csv")
    if not csv_114.exists():
        print(f"[ERROR] no {csv_114}")
        return
    df_trades = pd.read_csv(csv_114, encoding="utf-8-sig")
    closed = df_trades[df_trades["outcome"].isin(["win", "loss"])].copy()
    print(f"  1.1.4 BFJK closed trades: {len(closed)}")

    df_1m = load_df("BTCUSDT", "1m")
    df_1h = load_df("BTCUSDT", "1h")
    df_1h["atr14"] = compute_atr(df_1h, 14)
    atr_1h = df_1h["atr14"]

    print(f"  1m bars: {len(df_1m)}")
    print(f"  1h bars: {len(df_1h)}")

    # Extract features for each trade
    print(f"\n[INFO] Извлечение ViC фич для {len(closed)} сделок...")
    feature_rows = []
    for idx, row in closed.iterrows():
        feats = extract_vic_for_trade(row, df_1m, atr_1h)
        feats["_idx"] = idx
        feature_rows.append(feats)
    feats_df = pd.DataFrame(feature_rows).set_index("_idx")
    closed = closed.join(feats_df)

    print(f"\n{'='*88}")
    print(f"FORENSIC: что отделяет WIN от LOSS в 1.1.4 BFJK ({len(closed)} сделок)")
    print(f"{'='*88}")

    overall_wr = (closed["outcome"] == "win").mean() * 100
    overall_total = closed["R"].sum()
    print(f"\nBASELINE: WR {overall_wr:.1f}%, total {overall_total:+.1f}R, "
          f"avg {closed['R'].mean():+.2f}R, n={len(closed)}")

    # 1. Delta alignment per TF (categorical)
    print(f"\n--- 1. DELTA ALIGNMENT (знак delta vs направление сделки) ---")
    for htf in ["1h", "4h", "1d"]:
        analyze_feature_split(closed, f"delta_align_{htf}",
                                f"delta_{htf} alignment")

    # 2. Divergence per TF
    print(f"\n--- 2. ViC DIVERGENCE (bar и delta в разные стороны на ПРЕДЫДУЩЕМ баре) ---")
    for htf in ["1h", "4h", "1d"]:
        analyze_feature_split(closed, f"div_{htf}", f"divergence at {htf} prev bar")

    # 3. Normalized delta strength (quartiles)
    print(f"\n--- 3. NORM DELTA (квартили) ---")
    for htf in ["1h", "4h", "1d"]:
        analyze_numeric_split(closed, f"norm_{htf}", f"norm delta on {htf}")

    # 4. maxV proximity to entry (quartiles)
    print(f"\n--- 4. MaxV PROXIMITY (entry -> maxV в ATR-1h единицах) ---")
    for htf in ["4h", "1d"]:
        analyze_numeric_split(closed, f"maxV_dist_atr_{htf}",
                                f"maxV-{htf} dist in ATR-1h")

    # 5. Combine: delta_4h aligned + delta_1d aligned
    closed["delta_4h_1d_both_aligned"] = (
        (closed["delta_align_4h"] == "aligned") &
        (closed["delta_align_1d"] == "aligned")
    )
    analyze_feature_split(closed, "delta_4h_1d_both_aligned",
                            "delta_4h AND delta_1d aligned")

    # 6. Delta-1h aligned + delta-4h aligned
    closed["delta_1h_4h_both_aligned"] = (
        (closed["delta_align_1h"] == "aligned") &
        (closed["delta_align_4h"] == "aligned")
    )
    analyze_feature_split(closed, "delta_1h_4h_both_aligned",
                            "delta_1h AND delta_4h aligned")

    # 7. Bull-pct quartiles (last bar before signal)
    print(f"\n--- 7. BULL_PCT (доля bull volume в последнем баре) ---")
    for htf in ["1h", "4h", "1d"]:
        analyze_numeric_split(closed, f"bull_pct_{htf}", f"bull_pct on {htf} bar")

    # Top filter candidates
    print(f"\n\n{'='*88}\nFILTER CANDIDATES (top by WR boost):")
    print(f"{'='*88}")
    candidates = []
    for htf in ["1h", "4h", "1d"]:
        for col, lbl in [
            (f"delta_align_{htf}", "aligned"),
            (f"delta_align_{htf}", "counter"),
        ]:
            mask = closed[col] == lbl
            sub = closed[mask]
            if len(sub) < 15: continue
            wr = (sub["outcome"] == "win").mean() * 100
            tot = sub["R"].sum()
            avg = sub["R"].mean()
            candidates.append({
                "filter": f"{col}={lbl}",
                "n": len(sub), "wr": wr, "total": tot, "avg": avg,
                "wr_delta": wr - overall_wr
            })
    for c in sorted(candidates, key=lambda x: x["wr_delta"], reverse=True):
        print(f"  {c['filter']:<30} n={c['n']:>3} WR={c['wr']:5.1f}% "
              f"(d{c['wr_delta']:+.1f}pp) total={c['total']:+5.1f}R avg={c['avg']:+.2f}")


if __name__ == "__main__":
    main()
