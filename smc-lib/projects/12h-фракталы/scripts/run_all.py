"""Run all 14 B-scripts sequentially. Prints per-script summary + union basket.

Usage:
    cd ~/smc-lib/projects/12h-fractal-new/scripts
    python3 run_all.py
"""
from __future__ import annotations
import importlib
from _lib import load_12h, load_baseline, match_pivots, stats

SCRIPTS = [
    "B1C1_strict_S100_wide",
    "B1C2_strict_S50_age_wide",
    "B1C3_strict_S70_age50",
    "B1C4_strict_S50_htf_wide",
    "B1C5_vol_spike",
    "B1C6_retest",
    "B2C1_ob_sweep",
    "B2C2_ob_liq_sweep",
    "B3C1_maxv_sweep",
    "B4C1_hma78_sweep",
    "B4C2_hma200_sweep",
    "B5C1_vwap_w_aligned",
    "B8C1_force_div_reverse",
    "B9C1_p11_count",
]


def main():
    print("=" * 90)
    print("12h-fractal-new — Basket evaluator (all 14 BxCy)")
    print("=" * 90)

    bars = load_12h()
    pmap = match_pivots(bars, load_baseline())
    all_fires = set()

    # Reuse save_fires output: load each parquet after script ran.
    # Or run main() functions directly and collect via patching.
    # Простейший вариант: каждый скрипт уже сохраняет parquet в OUT_DIR — после
    # запусков читаем их обратно.
    import pandas as pd
    from _lib import OUT_DIR

    for mod_name in SCRIPTS:
        mod = importlib.import_module(mod_name)
        # каждый script — main() возвращает None; мы запускаем и затем читаем parquet
        try:
            mod.main()
        except Exception as e:
            print(f"  [ERR] {mod_name}: {e}")
            continue
        # Load fires from saved parquet
        code = mod_name.split("_")[0]
        p = OUT_DIR / f"{code}_fires.parquet"
        if not p.exists(): continue
        df = pd.read_parquet(p)
        for _, r in df.iterrows():
            all_fires.add((int(r["bar_idx"]), r["zone_direction"]))

    # Union basket
    n, conf, wr = stats(all_fires, pmap)
    print("\n" + "=" * 90)
    print(f"BASKET UNION (B1∪..∪B9):   n = {n}   conf = {conf}   WR = {wr:.2f}%")
    print("=" * 90)


if __name__ == "__main__":
    main()
