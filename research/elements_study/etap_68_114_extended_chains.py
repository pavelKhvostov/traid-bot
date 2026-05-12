"""Этап 68: расширенный survey доп. цепочек от FVG-d/12h.

Из etap_66 победители B (+21R) и F (+19R). Здесь пробуем больше вариаций:

  G: FVG-12h -> OB-6h -> OB-1h -> FVG-15m   (12h + 6h макро, 1h mid)
  H: FVG-12h -> OB-6h -> OB-2h -> FVG-15m   (12h макро, 6h+2h как в F)
  I: FVG-12h -> OB-4h -> OB-2h -> FVG-15m   (как E, но с 12h макро)
  J: FVG-d   -> OB-4h -> OB-1h -> FVG-20m   (A с 20m entry)
  K: FVG-12h -> OB-4h -> OB-1h -> FVG-20m   (B с 20m entry)
  L: FVG-d   -> OB-6h -> OB-2h -> FVG-20m   (F с 20m entry)
  M: FVG-12h -> OB-4h -> OB-1h -> FVG-30m   (B с 30m entry)
  N: FVG-12h -> OB-4h -> FVG-30m            (3-stage: skip mid OB, FVG-30m entry)
  O: FVG-12h -> OB-6h -> FVG-30m            (3-stage)
  P: FVG-12h -> OB-4h -> FVG-1h pro         (B-style 3-stage)
  Q: FVG-12h -> OB-6h -> FVG-1h pro         (F-style 3-stage)
  R: FVG-12h -> OB-4h -> FVG-2h pro         (D с 12h макро)

Все: any_edge OB-в-FVG, overlap FVG-в-FVG, deep-FVG entry, USER SL, RR sweep.
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

from collections import defaultdict
import time
import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_1 import detect_ob_pair, detect_fvg

import importlib.util
_spec = importlib.util.spec_from_file_location(
    "etap66_core", str(_Path(__file__).parent / "etap_66_114_chains_survey.py")
)
_e66 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_e66)

# Patch TF_HOURS / LIFE_DAYS to add 20m, 30m
_e66.TF_HOURS["20m"] = 20/60
_e66.TF_HOURS["30m"] = 0.5
_e66.LIFE_DAYS["20m"] = 0.5
_e66.LIFE_DAYS["30m"] = 0.75

SYMBOL = "BTCUSDT"
START_DATE = "2020-01-01"


def main():
    t0 = time.time()
    print("[INFO] load data")
    df_1d = load_df(SYMBOL, "1d")
    df_4h = load_df(SYMBOL, "4h")
    df_1h = load_df(SYMBOL, "1h")
    df_12h = compose_from_base(df_1h, "12h")
    df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_1m = load_df(SYMBOL, "1m")
    df_15m = compose_from_base(df_1m, "15m")
    df_20m = compose_from_base(df_1m, "20m")
    df_30m = compose_from_base(df_1m, "30m")

    cutoff = pd.Timestamp(START_DATE, tz="UTC")
    for nm, ref in [("df_1d", df_1d), ("df_4h", df_4h), ("df_1h", df_1h),
                     ("df_12h", df_12h), ("df_6h", df_6h), ("df_2h", df_2h),
                     ("df_15m", df_15m), ("df_20m", df_20m), ("df_30m", df_30m)]:
        pass
    df_1d = df_1d[df_1d.index >= cutoff].copy()
    df_4h = df_4h[df_4h.index >= cutoff].copy()
    df_1h = df_1h[df_1h.index >= cutoff].copy()
    df_12h = df_12h[df_12h.index >= cutoff].copy()
    df_6h = df_6h[df_6h.index >= cutoff].copy()
    df_2h = df_2h[df_2h.index >= cutoff].copy()
    df_15m = df_15m[df_15m.index >= cutoff].copy()
    df_20m = df_20m[df_20m.index >= cutoff].copy()
    df_30m = df_30m[df_30m.index >= cutoff].copy()
    df_1m = df_1m[df_1m.index >= cutoff]

    for tf, df in [("1d", df_1d), ("12h", df_12h), ("6h", df_6h),
                    ("4h", df_4h), ("2h", df_2h), ("1h", df_1h),
                    ("15m", df_15m), ("20m", df_20m), ("30m", df_30m)]:
        df["atr14"] = _e66.compute_atr(df, 14)

    # EMA200 for pro-trend
    df_1h["ema200"] = df_1h["close"].ewm(span=200, adjust=False).mean()
    df_2h["ema200"] = df_2h["close"].ewm(span=200, adjust=False).mean()

    print("[INFO] collect zones")
    fvgs_1d = _e66.collect_fvgs(df_1d, df_1d["atr14"], "1d")
    fvgs_12h = _e66.collect_fvgs(df_12h, df_12h["atr14"], "12h")
    obs_4h = _e66.collect_obs(df_4h, df_4h["atr14"], "4h")
    obs_6h = _e66.collect_obs(df_6h, df_6h["atr14"], "6h")
    obs_2h = _e66.collect_obs(df_2h, df_2h["atr14"], "2h")
    obs_1h = _e66.collect_obs(df_1h, df_1h["atr14"], "1h")
    fvgs_15m = _e66.collect_fvgs(df_15m, df_15m["atr14"], "15m")
    fvgs_20m = _e66.collect_fvgs(df_20m, df_20m["atr14"], "20m")
    fvgs_30m = _e66.collect_fvgs(df_30m, df_30m["atr14"], "30m")

    def fvgs_with_pro(df_e):
        out = []
        ema = df_e["ema200"].to_numpy()
        cl = df_e["close"].to_numpy()
        for idx in range(2, len(df_e) - 1):
            f = _e66.detect_fvg(df_e, idx)
            if f is None: continue
            a = float(df_e["atr14"].iloc[idx])
            if pd.isna(a) or a <= 0: continue
            em = float(ema[idx]); ccl = float(cl[idx])
            pro = ((f.direction == "LONG" and ccl > em) or
                   (f.direction == "SHORT" and ccl < em))
            out.append({"tf": "x", "direction": f.direction,
                         "bottom": f.bottom, "top": f.top, "atr": a,
                         "time": f.c2_time, "idx": idx,
                         "c0_time": f.c0_time, "pro_trend": pro})
        return out

    fvgs_1h_pro = fvgs_with_pro(df_1h)
    fvgs_2h_pro = fvgs_with_pro(df_2h)

    print(f"[INFO] zones: FVG-d={len(fvgs_1d)}, FVG-12h={len(fvgs_12h)}, "
          f"OB-6h={len(obs_6h)}, OB-4h={len(obs_4h)}, OB-2h={len(obs_2h)}, "
          f"OB-1h={len(obs_1h)}, FVG-15m={len(fvgs_15m)}, "
          f"FVG-20m={len(fvgs_20m)}, FVG-30m={len(fvgs_30m)}")

    chains = [
        ("G: FVG-12h->OB-6h->OB-1h->FVG-15m",
            lambda: _e66.detect_4stage(fvgs_12h, obs_6h, "OB", obs_1h, "OB",
                                        fvgs_15m, "12h", "6h", "1h", "15m", df_12h)),
        ("H: FVG-12h->OB-6h->OB-2h->FVG-15m",
            lambda: _e66.detect_4stage(fvgs_12h, obs_6h, "OB", obs_2h, "OB",
                                        fvgs_15m, "12h", "6h", "2h", "15m", df_12h)),
        ("I: FVG-12h->OB-4h->OB-2h->FVG-15m",
            lambda: _e66.detect_4stage(fvgs_12h, obs_4h, "OB", obs_2h, "OB",
                                        fvgs_15m, "12h", "4h", "2h", "15m", df_12h)),
        ("J: FVG-d->OB-4h->OB-1h->FVG-20m",
            lambda: _e66.detect_4stage(fvgs_1d, obs_4h, "OB", obs_1h, "OB",
                                        fvgs_20m, "1d", "4h", "1h", "20m", df_1d)),
        ("K: FVG-12h->OB-4h->OB-1h->FVG-20m",
            lambda: _e66.detect_4stage(fvgs_12h, obs_4h, "OB", obs_1h, "OB",
                                        fvgs_20m, "12h", "4h", "1h", "20m", df_12h)),
        ("L: FVG-d->OB-6h->OB-2h->FVG-20m",
            lambda: _e66.detect_4stage(fvgs_1d, obs_6h, "OB", obs_2h, "OB",
                                        fvgs_20m, "1d", "6h", "2h", "20m", df_1d)),
        ("M: FVG-12h->OB-4h->OB-1h->FVG-30m",
            lambda: _e66.detect_4stage(fvgs_12h, obs_4h, "OB", obs_1h, "OB",
                                        fvgs_30m, "12h", "4h", "1h", "30m", df_12h)),
        ("N: FVG-12h->OB-4h->FVG-30m (3-stage)",
            lambda: _e66.detect_3stage(fvgs_12h, obs_4h, "OB",
                                        # We need fvgs_30m with pro_trend=True flag; treat all as pro
                                        [dict(z, pro_trend=True) for z in fvgs_30m],
                                        "12h", "4h", "30m", df_12h, None, None)),
        ("O: FVG-12h->OB-6h->FVG-30m (3-stage)",
            lambda: _e66.detect_3stage(fvgs_12h, obs_6h, "OB",
                                        [dict(z, pro_trend=True) for z in fvgs_30m],
                                        "12h", "6h", "30m", df_12h, None, None)),
        ("P: FVG-12h->OB-4h->FVG-1h pro (3-stage)",
            lambda: _e66.detect_3stage(fvgs_12h, obs_4h, "OB", fvgs_1h_pro,
                                        "12h", "4h", "1h", df_12h, None, None)),
        ("Q: FVG-12h->OB-6h->FVG-1h pro (3-stage)",
            lambda: _e66.detect_3stage(fvgs_12h, obs_6h, "OB", fvgs_1h_pro,
                                        "12h", "6h", "1h", df_12h, None, None)),
        ("R: FVG-12h->OB-4h->FVG-2h pro (3-stage)",
            lambda: _e66.detect_3stage(fvgs_12h, obs_4h, "OB", fvgs_2h_pro,
                                        "12h", "4h", "2h", df_12h, None, None)),
    ]

    RR_LIST = [1.5, 1.8, 2.0, 2.5]
    all_results = []

    for label, build_fn in chains:
        print(f"\n{'='*78}\n{label}\n{'='*78}")
        chain_setups = build_fn()
        seen = set(); uniq = []
        for s in chain_setups:
            k = (s["signal_time"], s["direction"], round(s["fvg_b"], 2), round(s["fvg_t"], 2))
            if k in seen: continue
            seen.add(k); uniq.append(s)
        print(f"  setups: {len(uniq)}")
        if len(uniq) == 0:
            continue

        print(f"\n  no_dom:")
        for rr in RR_LIST:
            df = _e66.evaluate(uniq, rr, df_1m, df_1d, only_dom=False)
            m = _e66.report_metrics(df)
            if m:
                print(f"    RR={rr}: n={m['n']:>3} WR={m['wr']:5.1f}% "
                      f"total={m['total']:+6.1f}R bad={m['bad']}/{m['n_yrs']}")
                all_results.append({"label": label, "rr": rr, "dom": False,
                                     "setups": len(uniq), **m})

        print(f"  +do_match:")
        for rr in RR_LIST:
            df = _e66.evaluate(uniq, rr, df_1m, df_1d, only_dom=True)
            m = _e66.report_metrics(df)
            if m:
                print(f"    RR={rr}: n={m['n']:>3} WR={m['wr']:5.1f}% "
                      f"total={m['total']:+6.1f}R bad={m['bad']}/{m['n_yrs']}")
                all_results.append({"label": label, "rr": rr, "dom": True,
                                     "setups": len(uniq), **m})

    print(f"\n\n{'='*80}\nFINAL RANKINGS\n{'='*80}")

    print(f"\n--- TOP 12 by total R (no bad-year filter) ---")
    by_total = sorted(all_results, key=lambda x: x["total"], reverse=True)
    for r in by_total[:12]:
        dom = "+do_match" if r["dom"] else "no_dom"
        print(f"  {r['label'][:42]:<42} RR={r['rr']} {dom:<10} "
              f"n={r['n']:>3} WR={r['wr']:5.1f}% total={r['total']:+6.1f}R "
              f"bad={r['bad']}/{r['n_yrs']}")

    print(f"\n--- TOP 12 by total R (bad_yrs <= 1) ---")
    clean = sorted([r for r in all_results if r["bad"] <= 1],
                   key=lambda x: x["total"], reverse=True)
    for r in clean[:12]:
        dom = "+do_match" if r["dom"] else "no_dom"
        print(f"  {r['label'][:42]:<42} RR={r['rr']} {dom:<10} "
              f"n={r['n']:>3} WR={r['wr']:5.1f}% total={r['total']:+6.1f}R "
              f"bad={r['bad']}/{r['n_yrs']}")

    print(f"\n--- BEST PER CHAIN ---")
    by_chain = defaultdict(list)
    for r in all_results: by_chain[r["label"]].append(r)
    for label, rs in by_chain.items():
        best = max(rs, key=lambda x: x["total"])
        dom = "+do_match" if best["dom"] else "no_dom"
        print(f"  {label[:42]:<42}: RR={best['rr']} {dom:<10} "
              f"total={best['total']:+6.1f}R WR={best['wr']:.1f}% "
              f"bad={best['bad']}/{best['n_yrs']}")

    print(f"\n[TIME] {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
