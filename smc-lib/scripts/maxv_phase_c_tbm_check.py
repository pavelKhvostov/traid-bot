"""Phase (c) — TBM labeling check.

Verifies:
1) Column structure
2) Label distribution (+1 / 0 / -1)
3) No lookahead — touch_ts >= formed_ts + parent_TF
4) PT/SL/t1 sanity — barrier hits within reasonable distance
"""
from pathlib import Path
import pandas as pd
import numpy as np

events = pd.read_parquet(Path.home() / "Desktop/maxv_master_6m.parquet")
touches = pd.read_parquet(Path.home() / "Desktop/maxv_touches_6m.parquet")

print(f"\n{'='*70}\nPhase (c): TBM labeling check\n{'='*70}")
print(f"\nEvents:  {len(events):>5} rows, {len(events.columns)} cols")
print(f"Touches: {len(touches):>5} rows, {len(touches.columns)} cols")

print(f"\n--- Events columns ---")
print(list(events.columns))
print(f"\n--- Touches columns ---")
print(list(touches.columns))

print(f"\n--- Events sample ---")
print(events.head(3).to_string())
print(f"\n--- Touches sample ---")
print(touches.head(3).to_string())

print(f"\n--- Touches dtypes ---")
print(touches.dtypes)

print(f"\n--- Label distribution (touches) ---")
print(touches["label"].value_counts(dropna=False).sort_index())
print(f"P(+1) = {(touches['label']==1).mean():.3f}")
print(f"P(-1) = {(touches['label']==-1).mean():.3f}")
print(f"P( 0) = {(touches['label']==0).mean():.3f}")

print(f"\n--- TF distribution ---")
print(touches["tf"].value_counts())

print(f"\n--- Position distribution (from events) ---")
if "position" in events.columns:
    print(events["position"].value_counts())

print(f"\n--- Lookahead check ---")
# touch_ts must be >= formed_ts + parent_TF_ms (so touch is AFTER parent candle closed)
if "touch_ts" in touches.columns and "formed_ts" in touches.columns:
    tf_ms_map = {"12h": 12*3600*1000, "D": 24*3600*1000, "2D": 48*3600*1000,
                 "3D": 72*3600*1000, "W": 7*24*3600*1000}
    if "tf" in touches.columns:
        touches["parent_tf_ms"] = touches["tf"].map(tf_ms_map)
        touches["min_valid_touch"] = touches["formed_ts"] + touches["parent_tf_ms"]
        early = touches[touches["touch_ts"] < touches["min_valid_touch"]]
        print(f"  Early touches (lookahead suspicion): {len(early)} / {len(touches)}")
        if len(early) > 0:
            print(f"  ⚠️ POTENTIAL LOOKAHEAD: touches before parent_TF close")
            print(early[["tf", "formed_ts", "touch_ts", "min_valid_touch"]].head(5))
        else:
            print(f"  ✓ All touches AFTER parent_TF close — no lookahead")
        touches["delay_min"] = (touches["touch_ts"] - touches["min_valid_touch"]) / 60_000
        print(f"  Touch delay (min after parent close): "
              f"median={touches['delay_min'].median():.0f}min  "
              f"p25={touches['delay_min'].quantile(0.25):.0f}  "
              f"p75={touches['delay_min'].quantile(0.75):.0f}")

print(f"\n--- Force distribution check ---")
if "force" in touches.columns:
    print(f"  force min={touches['force'].min():.3f}  max={touches['force'].max():.3f}  "
          f"mean={touches['force'].mean():.3f}")

print(f"\n--- TBM exit checks ---")
for col in ["barrier_hit_ts", "exit_ts", "exit_price"]:
    if col in touches.columns:
        print(f"  {col}: present")

if "barrier_hit_ts" in touches.columns and "touch_ts" in touches.columns:
    touches["holding_min"] = (touches["barrier_hit_ts"] - touches["touch_ts"]) / 60_000
    print(f"  Holding time (touch → barrier): "
          f"median={touches['holding_min'].median():.0f}min  "
          f"max={touches['holding_min'].max():.0f}min")

print(f"\n--- Label vs force (sanity) ---")
if "force" in touches.columns:
    df_pos = touches[touches["label"] != 0]
    for q in [0.1, 0.3, 0.5, 0.7, 0.9]:
        thr = df_pos["force"].quantile(q)
        sub = df_pos[df_pos["force"] >= thr]
        p_react = (sub["label"] == 1).mean() if len(sub) > 0 else 0
        print(f"  force ≥ q{q:.0%} ({thr:.3f}): n={len(sub):>4}  P(react)={p_react*100:5.1f}%")

print(f"\n{'='*70}\nDONE Phase (c)\n{'='*70}")
