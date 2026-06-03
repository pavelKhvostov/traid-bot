"""Прогнать 6683 ob_vc-событий через эксперта по зонам (LookupModel).

Для каждого события вычисляем P_hit_D на момент signal_time и смотрим,
коррелирует ли уверенность эксперта с прибыльностью сделки.

Caveat: модель тренируется на ВСЁМ btc_full (включая будущие точки данных
относительно event-времени) — это lookahead для quick-scoping анализа.
Для production-фильтра нужна walk-forward retrain (отдельная задача).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

SMC_LIB = Path.home() / "smc-lib"
TRAID_BOT = Path.home() / "traid-bot"
sys.path.insert(0, str(SMC_LIB))
sys.path.insert(0, str(SMC_LIB / "projects"))
sys.path.insert(0, str(SMC_LIB / "prediction-algo"))
sys.path.insert(0, str(TRAID_BOT))

from data import load_btc_1m
from resample import resample_one
from model import LookupModel
from elements.ob_vc.code import HTF_TO_LTF  # noqa

# Reuse scanner from backtest
sys.path.insert(0, str(SMC_LIB / "projects" / "strategy_ob_vc_v1rules"))
from backtest import scan_ob_vc_events, TFS, HTFS  # noqa


def build_event_features(events: list[dict], df_1m: pd.DataFrame) -> pd.DataFrame:
    """For each event @ signal_time, compute (tf, type, side, distance_pct, age_bars)."""
    rows = []
    closes = df_1m["close"]
    for ev in events:
        st = ev["signal_time"]
        # Price at signal_time (last 1m close at or before)
        idx = closes.index.searchsorted(st, side="right") - 1
        if idx < 0:
            continue
        price_now = float(closes.iloc[idx])

        ob_lo, ob_hi = ev["ob_htf_zone"]
        zone_mid = (ob_lo + ob_hi) / 2
        if zone_mid > price_now:
            side = "above"
            distance_pct = max(0.0, (ob_lo - price_now) / price_now * 100)
        else:
            side = "below"
            distance_pct = max(0.0, (price_now - ob_hi) / price_now * 100)

        # Age bars in HTF terms
        htf = ev["ob_htf_tf"]
        tf_minutes = {"1h": 60, "2h": 120}[htf]
        age_minutes = (st - ev["ob_cur_time"]).total_seconds() / 60.0
        age_bars = max(0, int(age_minutes // tf_minutes))

        rows.append({
            "signal_time": st,
            "tf": htf,
            "type": "ob_vc",
            "direction": ev["direction"].lower(),  # model expects lowercase
            "lo": ob_lo,
            "hi": ob_hi,
            "level": np.nan,
            "width": ob_hi - ob_lo,
            "side": side,
            "distance_pct": distance_pct,
            "age_bars": age_bars,
            "mitigation_model": "wick-fill",  # canon for ob_vc
            "born_ts": ev["ob_cur_time"],
            "price_at_signal": price_now,
            "fvg_tf_match": ev["fvg_tf"],
        })
    return pd.DataFrame(rows)


def main():
    t0 = time.time()

    print("[exp] loading 1m BTC...")
    df_1m = load_btc_1m()

    end_ts = df_1m.index[-1] + pd.Timedelta(minutes=1)
    print("[exp] resampling 4 TFs...")
    resampled = {tf: resample_one(df_1m, tf, end_ts) for tf in TFS}

    all_events = []
    for htf in HTFS:
        print(f"[exp] scanning ob_vc HTF={htf}...")
        events = scan_ob_vc_events(resampled, df_1m, htf)
        all_events.extend(events)
    print(f"[exp] total events: {len(all_events)}")

    print("[exp] building event features...")
    snap_df = build_event_features(all_events, df_1m)
    print(f"  {len(snap_df)} rows")

    # Train LookupModel on full btc_full (lookahead caveat noted)
    print("[exp] loading btc_full.csv (training data)...")
    t1 = time.time()
    ds = pd.read_csv(Path.home() / "Desktop" / "btc_full.csv")
    ds["cut_off_ts"] = pd.to_datetime(ds["cut_off_ts"], utc=True)
    print(f"  {len(ds):,} rows in {time.time()-t1:.1f}s")

    print("[exp] fitting LookupModel...")
    t1 = time.time()
    # Add placeholder labels (predict_row doesn't need them, but predict() does add_buckets)
    snap_df["hit_12h"] = False
    snap_df["hit_D"] = False
    snap_df["first_hit_above"] = False
    snap_df["first_hit_below"] = False
    model = LookupModel.fit(ds, min_count=50, alpha=1.0)
    print(f"  fit in {time.time()-t1:.1f}s")

    print("[exp] predicting...")
    t1 = time.time()
    preds = model.predict(snap_df)
    print(f"  predict in {time.time()-t1:.1f}s")

    snap_df["P_hit_D"] = preds["P_hit_D"].to_numpy()
    snap_df["P_hit_12h"] = preds["P_hit_12h"].to_numpy()
    if "P_first_hit_above" in preds.columns:
        snap_df["P_first_above"] = preds["P_first_hit_above"].to_numpy()
        snap_df["P_first_below"] = preds["P_first_hit_below"].to_numpy()
    snap_df["bucket_used"] = preds["bucket_used"].to_numpy()
    snap_df["n_train"] = preds["n_train"].to_numpy()

    # Join with trades.csv
    trades = pd.read_csv(SMC_LIB / "projects" / "strategy_ob_vc_v1rules" / "trades.csv")
    trades["signal_time"] = pd.to_datetime(trades["signal_time"], utc=True)

    merged = trades.merge(
        snap_df[["signal_time", "tf", "direction", "side", "distance_pct", "age_bars",
                 "P_hit_D", "P_hit_12h", "n_train", "bucket_used"]],
        left_on=["signal_time", "htf"],
        right_on=["signal_time", "tf"],
        how="left",
    )
    # Direction lower-case match
    merged["direction"] = merged["direction_x"]
    merged["direction_model"] = merged["direction_y"].str.upper()
    matched = merged["direction"] == merged["direction_model"]
    print(f"\n[exp] joined: {matched.sum()}/{len(merged)} trades matched to events")

    enriched = merged[matched].copy()

    out_csv = SMC_LIB / "projects" / "strategy_ob_vc_v1rules" / "trades_with_expert.csv"
    enriched.to_csv(out_csv, index=False)
    print(f"[exp] saved enriched trades to {out_csv}")

    # Bucket analysis
    print("\n" + "=" * 80)
    print("Distribution of P_hit_D across ALL events (incl. no_entry filtered)")
    print("=" * 80)
    print("Bins: [0.0-0.5) [0.5-0.7) [0.7-0.8) [0.8-0.9) [0.9-0.95) [0.95-1.0]")
    bins = [0, 0.5, 0.7, 0.8, 0.9, 0.95, 1.01]
    snap_df["P_bucket"] = pd.cut(snap_df["P_hit_D"], bins=bins, right=False,
                                  labels=["<0.5", "0.5-0.7", "0.7-0.8", "0.8-0.9", "0.9-0.95", "0.95+"])
    print(snap_df["P_bucket"].value_counts().sort_index().to_string())

    print("\n" + "=" * 80)
    print("Per-bucket trade outcomes (closed trades only)")
    print("=" * 80)
    closed = enriched[enriched["outcome"].isin(["win", "loss", "flat"])].copy()
    closed["P_bucket"] = pd.cut(closed["P_hit_D"], bins=bins, right=False,
                                 labels=["<0.5", "0.5-0.7", "0.7-0.8", "0.8-0.9", "0.9-0.95", "0.95+"])
    rows_out = []
    for bk, g in closed.groupby("P_bucket", observed=False):
        if len(g) == 0:
            continue
        wins = (g["R"] > 0).sum()
        n = len(g)
        rows_out.append({
            "P_bucket": bk,
            "n": n,
            "WR_pct": round(wins / n * 100, 1),
            "total_R": round(g["R"].sum(), 1),
            "R_per_tr_mean": round(g["R"].mean(), 3),
            "median_R": round(g["R"].median(), 2),
        })
    print(pd.DataFrame(rows_out).to_string(index=False))

    # Also show cumulative — what if we kept only P_hit_D >= threshold?
    print("\n" + "=" * 80)
    print("Cumulative filter: keep trades with P_hit_D >= X (closed trades only)")
    print("=" * 80)
    rows_out = []
    for th in [0.0, 0.5, 0.7, 0.75, 0.8, 0.85, 0.9, 0.925, 0.95]:
        kept = closed[closed["P_hit_D"] >= th]
        if len(kept) == 0:
            continue
        wins = (kept["R"] > 0).sum()
        n = len(kept)
        rows_out.append({
            "P_hit_D_threshold": th,
            "n_kept": n,
            "kept_pct": round(n / len(closed) * 100, 1),
            "WR_pct": round(wins / n * 100, 1),
            "total_R": round(kept["R"].sum(), 1),
            "R_per_tr_mean": round(kept["R"].mean(), 3),
            "trades_per_year": round(n / 6.0, 0),
        })
    print(pd.DataFrame(rows_out).to_string(index=False))

    print(f"\n[exp] TOTAL elapsed: {(time.time()-t0)/60:.1f} min")


if __name__ == "__main__":
    main()
