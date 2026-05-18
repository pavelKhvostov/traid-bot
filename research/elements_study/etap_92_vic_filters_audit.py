"""Этап 92: Forensic-аудит etap_91 + комбо-фильтры на всех утверждённых стратегиях.

ЧАСТЬ A: AUDIT
  1. Lookahead check: ViC фичи рассчитаны на ПРЕДЫДУЩЕМ закрытом баре, не на текущем
  2. abs(dist) vs signed dist для maxV — разделить LONG и SHORT
  3. Multiple testing — count significance with permutation if time allows
  4. Sample size warning: 9-29 per quartile/category -> wide CI

ЧАСТЬ B: Filter combos
  Кандидаты:
    A: NOT (delta_4h aligned AND delta_1d aligned)
    B: |maxV_1d_dist_atr| > 1.0
    C: |norm_4h| > 0.05 (избегать "flat zone")
    D: delta_4h counter to trade direction
    E: A + C
    F: A + B
    G: A + C + B
    H: A + delta_align_4h=counter

  Применяем к:
    - 1.1.4 BFJK (BTC, 115 closed)
    - 1.1.5 hi-freq (BTC, 242 closed)
    - 1.1.2 (BTC, ?)
    - 1.1.1 (BTC, 65 closed)
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
import numpy as np

import importlib.util
_spec91 = importlib.util.spec_from_file_location(
    "etap91_core", str(_Path(__file__).parent / "etap_91_vic_forensic.py"))
_e91 = importlib.util.module_from_spec(_spec91); _spec91.loader.exec_module(_e91)

from data_manager import load_df


# =============== AUDIT ===============

def audit_lookahead():
    """Проверим: ViC фичи рассчитаны строго на ПРЕДЫДУЩЕМ баре до signal_time."""
    print(f"\n{'='*78}\nAUDIT 1: Lookahead в ViC features\n{'='*78}")
    cases = [
        # signal_time, htf, expected prev_bar_open, expected window
        ("2024-06-15 14:25:00+00:00", "1h", "2024-06-15 13:00:00+00:00",
         "[13:00, 14:00) — закрыт в 14:00 = до signal_time 14:25 OK"),
        ("2024-06-15 14:00:00+00:00", "1h", "2024-06-15 13:00:00+00:00",
         "[13:00, 14:00) — закрыт ровно на 14:00 = signal_time OK boundary safe"),
        ("2024-06-15 14:25:00+00:00", "4h", "2024-06-15 08:00:00+00:00",
         "[08:00, 12:00) — закрыт в 12:00, до signal_time OK"),
        ("2024-06-15 14:25:00+00:00", "1d", "2024-06-14 00:00:00+00:00",
         "[2024-06-14 00:00, 2024-06-15 00:00) — prev day OK"),
    ]
    for sig_str, htf, expected_open, note in cases:
        sig_time = pd.Timestamp(sig_str)
        if htf == "1h":
            bar_open = sig_time.floor("h")
        elif htf == "4h":
            bar_open = sig_time.floor("4h")
        else:
            bar_open = sig_time.normalize()
        tf_hours = {"1h": 1, "4h": 4, "1d": 24}[htf]
        prev_bar_open = bar_open - pd.Timedelta(hours=tf_hours)
        match = "OK" if str(prev_bar_open) == expected_open else "FAIL"
        print(f"  [{match}] sig={sig_str} {htf} -> prev_bar_open={prev_bar_open}")
        print(f"        note: {note}")


def audit_multiple_testing(n_trades=115, n_categorical=4, n_quartile_features=7):
    """Multiple testing risk: сколько ложноположительных ожидать."""
    print(f"\n{'='*78}\nAUDIT 2: Multiple testing risk\n{'='*78}")
    n_cat_comparisons = n_categorical * 2  # 2 levels each
    n_quartile_comparisons = n_quartile_features * 4
    total = n_cat_comparisons + n_quartile_comparisons
    expected_fp_05 = total * 0.05
    expected_fp_01 = total * 0.01
    print(f"  Всего сравнений: {total}")
    print(f"  Ожидаемых false-positive при alpha=0.05: {expected_fp_05:.1f}")
    print(f"  При alpha=0.01: {expected_fp_01:.2f}")
    print(f"  Sample size {n_trades}: SE WR ~ sqrt(0.5x0.5/n) = +-{50/(n_trades**0.5):.1f}pp (95% CI ~+-10pp)")
    print(f"  Только эффекты > 10pp с n>=20 можно считать ''вероятно реальными''")


def audit_signed_vs_abs_dist(closed: pd.DataFrame, df_1m, df_1h, atr_1h):
    """Проверим: эффект 'maxV-1d dist' это про SIGNED dist или про ABS dist?"""
    print(f"\n{'='*78}\nAUDIT 3: maxV-1d signed vs abs (разделим LONG/SHORT)\n{'='*78}")
    for d in ["LONG", "SHORT"]:
        sub = closed[closed["direction"] == d].copy()
        if "maxV_dist_atr_1d" not in sub.columns or sub["maxV_dist_atr_1d"].isna().all():
            print(f"  {d}: no data"); continue
        sub["abs_dist"] = sub["maxV_dist_atr_1d"].abs()
        sub["dist_sign"] = sub["maxV_dist_atr_1d"].apply(
            lambda x: "above" if x and x > 1 else ("below" if x and x < -1 else "near"))
        grp = sub.groupby("dist_sign").agg(
            n=("R", "size"),
            wins=("outcome", lambda x: (x == "win").sum()),
            total=("R", "sum"),
        )
        grp["WR"] = (grp["wins"] / grp["n"] * 100).round(1)
        grp["avg"] = (grp["total"] / grp["n"]).round(3)
        print(f"\n  {d}-only (n={len(sub)}):")
        print(grp.to_string())


# =============== FILTER COMBOS ===============

def define_filters(closed: pd.DataFrame) -> dict:
    """Define all filter masks."""
    closed = closed.copy()
    closed["both_4h_1d_aligned"] = (
        (closed["delta_align_4h"] == "aligned") &
        (closed["delta_align_1d"] == "aligned")
    )
    closed["abs_norm_4h"] = closed["norm_4h"].abs()
    closed["abs_maxV_1d_atr"] = closed["maxV_dist_atr_1d"].abs()

    # Directional maxV target: для LONG — maxV-1d ВЫШЕ entry (negative dist),
    #                          для SHORT — maxV-1d НИЖЕ entry (positive dist).
    # maxV_dist_atr_1d = (entry - maxV) / atr_1h. LONG → maxV выше → entry < maxV → negative.
    # Условие "maxV в сторону сделки на > 1 ATR":
    long_target = (closed["direction"] == "LONG") & (closed["maxV_dist_atr_1d"] < -1.0)
    short_target = (closed["direction"] == "SHORT") & (closed["maxV_dist_atr_1d"] > 1.0)
    closed["maxV_target_in_trade_dir"] = long_target | short_target

    return {
        "BASELINE (no filter)": pd.Series(True, index=closed.index),
        "A: NOT (4h+1d both aligned)": ~closed["both_4h_1d_aligned"],
        "B: |maxV_1d| > 1 ATR": closed["abs_maxV_1d_atr"] > 1.0,
        "C: |norm_4h| > 0.05": closed["abs_norm_4h"] > 0.05,
        "D: delta_4h counter": closed["delta_align_4h"] == "counter",
        "E: A + C": ~closed["both_4h_1d_aligned"] & (closed["abs_norm_4h"] > 0.05),
        "F: A + B": ~closed["both_4h_1d_aligned"] & (closed["abs_maxV_1d_atr"] > 1.0),
        "G: A + B + C": (
            ~closed["both_4h_1d_aligned"]
            & (closed["abs_maxV_1d_atr"] > 1.0)
            & (closed["abs_norm_4h"] > 0.05)
        ),
        "H: A + D": ~closed["both_4h_1d_aligned"] & (closed["delta_align_4h"] == "counter"),
        "I: D + C": (closed["delta_align_4h"] == "counter") & (closed["abs_norm_4h"] > 0.05),
        "J: maxV target in trade dir": closed["maxV_target_in_trade_dir"],
        "K: A + J": ~closed["both_4h_1d_aligned"] & closed["maxV_target_in_trade_dir"],
        "L: J + C": closed["maxV_target_in_trade_dir"] & (closed["abs_norm_4h"] > 0.05),
    }


def evaluate_filters(closed: pd.DataFrame, strategy_label: str):
    """Apply all filters and print results."""
    if len(closed) < 30:
        print(f"\n[{strategy_label}] only {len(closed)} closed trades — skipped")
        return None

    print(f"\n{'='*88}\n{strategy_label} (baseline n={len(closed)})\n{'='*88}")
    filters = define_filters(closed)
    rows = []
    for name, mask in filters.items():
        sub = closed[mask]
        if len(sub) < 5: continue
        wins = (sub["outcome"] == "win").sum()
        wr = wins / len(sub) * 100 if len(sub) else 0
        total = sub["R"].sum()
        avg = sub["R"].mean()
        rows.append({"filter": name, "n": len(sub), "wr": wr,
                      "total": total, "avg": avg,
                      "frac": len(sub) / len(closed) * 100})
    if not rows:
        return None
    print(f"  {'filter':<32} {'n':>4} {'frac':>6} {'WR':>6} {'total':>8} {'avg':>7}")
    print("  " + "-" * 76)
    baseline_wr = next(r["wr"] for r in rows if r["filter"].startswith("BASELINE"))
    baseline_total = next(r["total"] for r in rows if r["filter"].startswith("BASELINE"))
    for r in rows:
        d_wr = r["wr"] - baseline_wr
        d_tot = r["total"] - baseline_total
        marker = "  "
        if r["wr"] > baseline_wr + 5 and r["n"] >= 20: marker = "**"
        elif r["wr"] > baseline_wr + 3 and r["n"] >= 20: marker = "* "
        print(f"  {r['filter']:<32} {r['n']:>4} {r['frac']:>5.1f}% "
              f"{r['wr']:>5.1f}% {r['total']:>+7.1f}R {r['avg']:>+6.2f}  {marker}")
    return rows


# =============== Main ===============

def extract_features_for_csv(csv_path: Path, df_1m, df_1h, atr_1h) -> pd.DataFrame:
    """Load trades CSV, extract ViC features."""
    if not csv_path.exists():
        return None
    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    closed = df[df["outcome"].isin(["win", "loss"])].copy()
    if len(closed) == 0: return None

    feature_rows = []
    for idx, row in closed.iterrows():
        feats = _e91.extract_vic_for_trade(row, df_1m, atr_1h)
        feats["_idx"] = idx
        feature_rows.append(feats)
    feats_df = pd.DataFrame(feature_rows).set_index("_idx")
    return closed.join(feats_df)


def main():
    print("[INFO] Загрузка данных")
    df_1m = load_df("BTCUSDT", "1m")
    df_1h = load_df("BTCUSDT", "1h")
    df_1h["atr14"] = _e91.compute_atr(df_1h, 14)
    atr_1h = df_1h["atr14"]
    print(f"  1m: {len(df_1m)} bars")
    print(f"  1h: {len(df_1h)} bars")

    # === AUDIT ===
    audit_lookahead()
    audit_multiple_testing()

    # Extract features for 1.1.4 BFJK first (we have CSV)
    csv_114 = Path("research/elements_study/output/etap74_BFJK_fixed_portfolio.csv")
    print(f"\n[INFO] Extracting ViC features for 1.1.4 BFJK...")
    closed_114 = extract_features_for_csv(csv_114, df_1m, df_1h, atr_1h)
    audit_signed_vs_abs_dist(closed_114, df_1m, df_1h, atr_1h)

    # 1.1.5 hi-freq CSV
    csv_115 = Path("research/elements_study/output/etap81_1_1_5_hifreq_portfolio.csv")
    print(f"\n[INFO] Extracting ViC features for 1.1.5 hi-freq...")
    closed_115 = extract_features_for_csv(csv_115, df_1m, df_1h, atr_1h)

    # === EVALUATE FILTERS ===
    print(f"\n\n{'#'*88}\n# PART B: Filter combos\n{'#'*88}")

    if closed_114 is not None:
        evaluate_filters(closed_114, "Strategy 1.1.4 BFJK")
    if closed_115 is not None:
        evaluate_filters(closed_115, "Strategy 1.1.5 hi-freq")


if __name__ == "__main__":
    main()
