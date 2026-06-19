"""Phase 2 — characterize edge per HTF×LTF combo via SMC retest model.

SMC retest model:
  1. ob_vc born at born_ms
  2. Wait until first opposite Williams N=2 confirms (fract_confirm_ms)
     — это «displacement bounce done», цена на противоположном экстремуме
  3. ESCAPE check: at fract_confirm, was price OUTSIDE ob_zone?
     LONG: was bar.close > ob_zone.hi at any point in [born_ms, fract_confirm_ms]?
     SHORT: bar.close < ob_zone.lo?
     If not — это не классический retest setup, mark as "no_escape"
  4. RETEST touch: first 1m bar after fract_confirm_ms where price re-enters zone
     LONG: bar.low ≤ ob_zone.hi
     SHORT: bar.high ≥ ob_zone.lo
  5. Entry at zone edge, SL at opposite edge, TP1/TP2 = 1R/2R away from entry
  6. Triple-barrier: first hit within horizon wins

Метрики:
  N             — число ob_vc rows
  P_escape      — % с clean escape from zone
  P_retest|esc  — % retest after escape (before invalidation + horizon)
  P_R1|retest   — TP1 first
  P_R2|retest   — TP2 first
  P_SL|retest   — SL first
  EV_R          — P_R1·1 + P_R2·1 (additional) - P_SL·1
  med_TTR_h     — median time from fract_confirm → retest touch

Output:
  data/ob_vc_phase2_rows.parquet — per-row outcome
  Summary stats in stdout.
"""
from __future__ import annotations
import sys, time, pathlib
import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path.home() / "smc-lib"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _lib import DATA_DIR, TFS_MS, ALL_HTFS, HTF_TO_LTF, load_1m

HORIZON_MULT = 3
HORIZON_MIN_MS = 6 * 60 * 60 * 1000  # min 6h


t0 = time.time()
print("=" * 78)
print("Phase 2 — edge characterization per HTF×LTF combo")
print("=" * 78)


# ─── Load ob_vc data + 1m bars ─────────────────────────────
print("\nLoading Phase 1 parquet...")
df = pd.read_parquet(DATA_DIR / "ob_vc_phase1.parquet")
print(f"  rows: {len(df):,}")

print("\nLoading 1m...")
rows_1m = load_1m()
t_arr = np.array([r[0] for r in rows_1m], dtype=np.int64)
h_arr = np.array([r[2] for r in rows_1m], dtype=np.float64)
l_arr = np.array([r[3] for r in rows_1m], dtype=np.float64)
c_arr = np.array([r[4] for r in rows_1m], dtype=np.float64)
print(f"  1m bars: {len(t_arr):,}")
END_MS = int(t_arr[-1])


def htf_ms(htf):
    if htf in TFS_MS: return TFS_MS[htf]
    if htf == "2d": return 2 * 1440 * 60_000
    if htf == "3d": return 3 * 1440 * 60_000
    raise ValueError(htf)


# ─── Triple-barrier on 1m ──────────────────────────────────
def triple_barrier(direction, born_ms, valid_until_ms, ob_lo, ob_hi, horizon_ms):
    """Returns dict:
       touched, touch_ms, touch_invalid (touch after invalidation),
       sl_hit, r1_hit, r2_hit, first_hit (in {sl,r1,r2,none}),
       ttt_ms (time to touch), ttr1_ms, mfe_R, mae_R.
    """
    out = {"touched": False, "touch_ms": None, "touch_invalid": False,
           "sl_hit": False, "r1_hit": False, "r2_hit": False,
           "first_hit": "none", "ttt_ms": None, "ttr1_ms": None,
           "mfe_R": np.nan, "mae_R": np.nan}

    R = ob_hi - ob_lo
    if R <= 0:
        return out
    if direction == "long":
        entry = ob_hi
        sl = ob_lo
        tp1 = entry + R
        tp2 = entry + 2 * R
    else:
        entry = ob_lo
        sl = ob_hi
        tp1 = entry - R
        tp2 = entry - 2 * R

    # Find touch: first 1m bar after born_ms where price enters zone
    i_start = int(np.searchsorted(t_arr, born_ms))
    if i_start >= len(t_arr):
        return out

    touch_idx = None
    for i in range(i_start, len(t_arr)):
        if direction == "long":
            # Enter zone: bar.low ≤ ob_hi
            if l_arr[i] <= ob_hi:
                touch_idx = i; break
        else:
            if h_arr[i] >= ob_lo:
                touch_idx = i; break

    if touch_idx is None:
        return out

    touch_ms = int(t_arr[touch_idx])
    out["touched"] = True
    out["touch_ms"] = touch_ms
    out["ttt_ms"] = touch_ms - born_ms
    if touch_ms >= valid_until_ms:
        out["touch_invalid"] = True
        # Don't measure reaction past invalidation
        return out

    # Measure outcome within horizon
    end_ms = min(touch_ms + horizon_ms, valid_until_ms + horizon_ms)
    i_end = int(np.searchsorted(t_arr, end_ms))
    i_end = min(i_end, len(t_arr) - 1)
    if i_end <= touch_idx:
        return out

    # Walk forward bar-by-bar; first hit wins
    mfe = 0.0; mae = 0.0
    first_hit = "none"
    ttr1_idx = None
    for j in range(touch_idx, i_end + 1):
        hi, lo = float(h_arr[j]), float(l_arr[j])
        if direction == "long":
            # favourable = up, adverse = down
            mfe = max(mfe, hi - entry)
            mae = max(mae, entry - lo)
            # Check first hit (SL, TP1, TP2)
            sl_touch = (lo <= sl)
            tp1_touch = (hi >= tp1)
            tp2_touch = (hi >= tp2)
        else:
            mfe = max(mfe, entry - lo)
            mae = max(mae, hi - entry)
            sl_touch = (hi >= sl)
            tp1_touch = (lo <= tp1)
            tp2_touch = (lo <= tp2)

        if first_hit == "none":
            # Bar resolution: SL/TP both possible — conservative pick SL first if both
            if sl_touch and (tp1_touch or tp2_touch):
                first_hit = "sl"
                out["sl_hit"] = True
                break
            elif sl_touch:
                first_hit = "sl"; out["sl_hit"] = True
                break
            elif tp2_touch:
                first_hit = "r2"; out["r1_hit"] = True; out["r2_hit"] = True
                ttr1_idx = j; break
            elif tp1_touch:
                first_hit = "r1"; out["r1_hit"] = True
                ttr1_idx = j
                # keep scanning for r2 within horizon
        elif first_hit == "r1":
            if direction == "long":
                if hi >= tp2:
                    out["r2_hit"] = True; first_hit = "r2"; break
            else:
                if lo <= tp2:
                    out["r2_hit"] = True; first_hit = "r2"; break

    out["first_hit"] = first_hit
    if ttr1_idx is not None:
        out["ttr1_ms"] = int(t_arr[ttr1_idx]) - touch_ms
    out["mfe_R"] = mfe / R
    out["mae_R"] = mae / R
    return out


# ─── Iterate parquet rows ──────────────────────────────────
print("\nRunning triple-barrier on each row...")
results = []
for k, row in enumerate(df.itertuples()):
    if k % 5000 == 0 and k > 0:
        print(f"  {k:,} / {len(df):,}")
    horizon_ms = max(HORIZON_MULT * htf_ms(row.htf), HORIZON_MIN_MS)
    r = triple_barrier(
        row.direction, int(row.born_ms), int(row.valid_until_ms),
        float(row.ob_zone_lo), float(row.ob_zone_hi), horizon_ms,
    )
    results.append(r)

print(f"  {len(df):,} / {len(df):,}  ✓")

res_df = pd.DataFrame(results)
out_df = pd.concat([df.reset_index(drop=True), res_df.reset_index(drop=True)], axis=1)
out_path = DATA_DIR / "ob_vc_phase2_rows.parquet"
out_df.to_parquet(out_path, index=False)
print(f"\nSaved → {out_path.relative_to(pathlib.Path.home())}")


# ─── Aggregated stats ──────────────────────────────────────
def stats(group: pd.DataFrame, name: str):
    n = len(group)
    if n == 0:
        return None
    touched = group["touched"].sum()
    p_touch = touched / n
    tg = group[group["touched"] & ~group["touch_invalid"]]
    n_eligible = len(tg)
    p_r1 = tg["r1_hit"].mean() if n_eligible else 0
    p_r2 = tg["r2_hit"].mean() if n_eligible else 0
    p_sl = tg["sl_hit"].mean() if n_eligible else 0
    p_sl_first = (tg["first_hit"] == "sl").mean() if n_eligible else 0
    mfe = tg["mfe_R"].mean() if n_eligible else 0
    mae = tg["mae_R"].mean() if n_eligible else 0
    ttt_h = group.loc[group["touched"], "ttt_ms"].median() / 3_600_000 if touched else None
    return {
        "scope": name,
        "N": n,
        "P_touch": p_touch,
        "P_R1|t": p_r1, "P_R2|t": p_r2, "P_SL_first|t": p_sl_first,
        "mean_MFE_R": mfe, "mean_MAE_R": mae,
        "med_TTT_h": ttt_h,
        # Expected R: assume entry-zone fill, R1 hit yields +1R, SL hit yields -1R
        # Naive EV = P_R1 - P_SL_first
        "EV_R_naive": p_r1 - p_sl_first,
    }


print(f"\n{'='*100}")
print("PER (HTF, LTF) COMBO  —  ranked by EV_R_naive (P_R1 - P_SL_first)")
print(f"{'='*100}")
combo_stats = []
for htf in ALL_HTFS:
    for ltf in HTF_TO_LTF[htf]:
        g = out_df[(out_df.htf == htf) & (out_df.ltf == ltf)]
        s = stats(g, f"{htf}/{ltf}")
        if s: combo_stats.append(s)

cs = pd.DataFrame(combo_stats).sort_values("EV_R_naive", ascending=False)
print(f"\n{'combo':<10} {'N':>6} {'P_touch':>9} {'P_R1|t':>9} {'P_R2|t':>9} "
      f"{'P_SL1|t':>9} {'MFE_R':>7} {'MAE_R':>7} {'TTT_h':>7} {'EV_R':>7}")
print("-" * 100)
for _, r in cs.iterrows():
    print(f"{r['scope']:<10} {r['N']:>6,} "
          f"{r['P_touch']:>9.1%} {r['P_R1|t']:>9.1%} {r['P_R2|t']:>9.1%} "
          f"{r['P_SL_first|t']:>9.1%} {r['mean_MFE_R']:>7.2f} {r['mean_MAE_R']:>7.2f} "
          f"{r['med_TTT_h']:>7.1f} {r['EV_R_naive']:>+7.2f}")


print(f"\n{'='*100}")
print("PER HTF (any combo)")
print(f"{'='*100}")
print(f"\n{'htf':<5} {'N':>6} {'P_touch':>9} {'P_R1|t':>9} {'P_R2|t':>9} "
      f"{'P_SL1|t':>9} {'MFE_R':>7} {'MAE_R':>7} {'TTT_h':>7} {'EV_R':>7}")
print("-" * 100)
for htf in ALL_HTFS:
    g = out_df[out_df.htf == htf]
    s = stats(g, htf)
    if s:
        print(f"{s['scope']:<5} {s['N']:>6,} "
              f"{s['P_touch']:>9.1%} {s['P_R1|t']:>9.1%} {s['P_R2|t']:>9.1%} "
              f"{s['P_SL_first|t']:>9.1%} {s['mean_MFE_R']:>7.2f} {s['mean_MAE_R']:>7.2f} "
              f"{s['med_TTT_h']:>7.1f} {s['EV_R_naive']:>+7.2f}")


print(f"\nElapsed: {time.time() - t0:.1f}s")
