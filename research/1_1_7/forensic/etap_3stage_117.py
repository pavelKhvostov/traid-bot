"""3-stage optimization для Strategy 1.1.7 (Andrei-style).

Stage 1: entry_pct sweep — где в FVG ставить entry (0.1..0.9)
Stage 2: SL formula sweep — на winner entry
Stage 3: RR sweep — на winner entry+SL

Каждый stage:
  - Считает n_total, n_closed, NO_ENTRY%, NOT_FILLED%, WR, total R, R/tr
  - Выбирает winner по композитной метрике: total R (главное) при n >= порога
  - Затем перечисляет индикаторные фильтры — каждый по отдельности,
    показывая prefilter/postfilter delta. Не комбинируем — даём пользователю
    список усилителей.

База: 6.3y BTC, 454 deduped setups, без фильтров.
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

import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df
from etap_35_strategy_111_forensic import hull_ma

SYMBOL = "BTCUSDT"
BACKTEST_CSV = "signals/backtest_strategy_1_1_7.csv"
FEATURES_CSV = "research/1_1_7/forensic/output/etap_47_111_7_trades_features.csv"


def parse_utc3(s):
    if pd.isna(s) or s == "":
        return pd.NaT
    return pd.Timestamp(s, tz="UTC") - pd.Timedelta(hours=3)


def parse_zone(s):
    a, b = s.split("-")
    return float(a), float(b)


def main():
    print("=" * 72)
    print(" 3-STAGE OPTIMIZATION  Strategy 1.1.7  (6.3y BTC, БЕЗ фильтров)")
    print("=" * 72)

    df = pd.read_csv(BACKTEST_CSV)
    df["signal_time_utc"] = df["fvg_c2_time"].apply(parse_utc3)
    df["fvg_b"], df["fvg_t"] = zip(*df["fvg_zone"].apply(parse_zone))
    df["ob_b"], df["ob_t"] = zip(*df["ob_zone"].apply(parse_zone))
    df["poi_b"], df["poi_t"] = zip(*df["poi_zone"].apply(parse_zone))
    df = df.dropna(subset=["signal_time_utc"]).reset_index(drop=True)

    # features for indicator overlay (Stage 1/2/3 enhancers)
    feat = pd.read_csv(FEATURES_CSV)
    feat["ts"] = pd.to_datetime(feat["signal_time"], utc=True)
    df = df.merge(
        feat[["ts", "asvk_4h", "mh_4h_color", "weekday", "session",
              "hull_4h_L160", "hull_1h_L160", "hull_12h_L78",
              "ema200_4h", "ema200_1h", "mh_4h_color_align", "mh_4h_mf_align"]],
        left_on="signal_time_utc", right_on="ts", how="left",
    )

    df_1m = load_df(SYMBOL, "1m")
    ts_arr = df_1m.index.values
    h_arr = df_1m["high"].to_numpy(dtype=float)
    l_arr = df_1m["low"].to_numpy(dtype=float)

    def simulate(direction, entry, sl, tp, start, timeout_days=14):
        st = start.tz_localize(None) if start.tz else start
        end = st + pd.Timedelta(days=timeout_days)
        i0 = np.searchsorted(ts_arr, np.datetime64(st))
        i1 = np.searchsorted(ts_arr, np.datetime64(end))
        if i1 <= i0:
            return "no_data", 0.0
        h = h_arr[i0:i1]; l = l_arr[i0:i1]
        risk = abs(entry - sl)
        if risk <= 0:
            return "invalid", 0.0
        if direction == "LONG":
            am = l <= entry
            if not am.any():
                return "not_filled", 0.0
            act = int(np.argmax(am))
            if (h[:act] >= tp).any() or (l[:act] <= sl).any():
                return "no_entry", 0.0
            h2 = h[act:]; l2 = l[act:]
            sh = l2 <= sl; th = h2 >= tp
            si = int(np.argmax(sh)) if sh.any() else len(h2)
            ti = int(np.argmax(th)) if th.any() else len(h2)
            if si == len(h2) and ti == len(h2):
                return "open", 0.0
            return ("loss", -1.0) if si <= ti else ("win", (tp - entry) / risk)
        am = h >= entry
        if not am.any():
            return "not_filled", 0.0
        act = int(np.argmax(am))
        if (l[:act] <= tp).any() or (h[:act] >= sl).any():
            return "no_entry", 0.0
        h2 = h[act:]; l2 = l[act:]
        sh = h2 >= sl; th = l2 <= tp
        si = int(np.argmax(sh)) if sh.any() else len(h2)
        ti = int(np.argmax(th)) if th.any() else len(h2)
        if si == len(h2) and ti == len(h2):
            return "open", 0.0
        return ("loss", -1.0) if si <= ti else ("win", (entry - tp) / risk)

    def build(row, entry_pct, sl_variant, rr):
        d = row["direction"]
        fb, ft = row["fvg_b"], row["fvg_t"]
        ob_b, ob_t = row["ob_b"], row["ob_t"]
        poi_b, poi_t = row["poi_b"], row["poi_t"]
        if d == "LONG":
            entry = fb + entry_pct * (ft - fb)
            if sl_variant == "ob_full": sl = ob_b
            elif sl_variant == "ob_inside_15": sl = ob_b + 0.15 * (ob_t - ob_b)
            elif sl_variant == "ob_inside_35": sl = ob_b + 0.35 * (ob_t - ob_b)
            elif sl_variant == "ob_inside_50": sl = ob_b + 0.50 * (ob_t - ob_b)
            elif sl_variant == "poi_extreme": sl = poi_b
            elif sl_variant == "asym_3565":
                sl = ob_b + 0.35 * (fb - ob_b)
            else: return None
            if sl >= entry: return None
            tp = entry + rr * (entry - sl)
        else:
            entry = ft - entry_pct * (ft - fb)
            if sl_variant == "ob_full": sl = ob_t
            elif sl_variant == "ob_inside_15": sl = ob_t - 0.15 * (ob_t - ob_b)
            elif sl_variant == "ob_inside_35": sl = ob_t - 0.35 * (ob_t - ob_b)
            elif sl_variant == "ob_inside_50": sl = ob_t - 0.50 * (ob_t - ob_b)
            elif sl_variant == "poi_extreme": sl = poi_t
            elif sl_variant == "asym_3565":
                sl = ob_t - 0.65 * (ob_t - ft)
            else: return None
            if sl <= entry: return None
            tp = entry - rr * (sl - entry)
        return entry, sl, tp

    def run_config(rows_df, entry_pct, sl_variant, rr):
        outs, rs = [], []
        for _, row in rows_df.iterrows():
            s = build(row, entry_pct, sl_variant, rr)
            if s is None:
                outs.append("invalid"); rs.append(0.0); continue
            entry, sl, tp = s
            out, r = simulate(row["direction"], entry, sl, tp, row["signal_time_utc"])
            outs.append(out); rs.append(r)
        outs = pd.Series(outs, index=rows_df.index)
        rs = pd.Series(rs, index=rows_df.index)
        n_total = len(rows_df)
        n_inv = (outs == "invalid").sum()
        n_no_e = (outs == "no_entry").sum()
        n_not_f = (outs == "not_filled").sum()
        n_open = (outs == "open").sum()
        n_cl = outs.isin(["win", "loss"]).sum()
        wr = (outs == "win").sum() / n_cl * 100 if n_cl else 0
        total = rs.sum()
        r_tr = total / n_cl if n_cl else 0
        return {
            "n_total": n_total, "n_inv": n_inv, "n_no_e": n_no_e,
            "n_not_f": n_not_f, "n_open": n_open, "n_cl": n_cl,
            "wr": wr, "total": total, "r_tr": r_tr,
            "outs": outs, "rs": rs,
        }

    # ============== STAGE 1: entry_pct sweep ==============
    print("\n" + "=" * 72)
    print(" STAGE 1: entry_pct sweep  (sl=ob_full, RR=1.0)")
    print("=" * 72)
    print(f"{'entry':<7} {'n_cl':<5} {'WR':<6} {'NO_E':<5} {'NOT_F':<6} {'total':<8} {'R/tr':<7}")
    stage1_best = None
    for ep in [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]:
        r = run_config(df, ep, "ob_full", 1.0)
        flag = ""
        if stage1_best is None or r["total"] > stage1_best[1]["total"]:
            stage1_best = (ep, r)
            flag = " ←"
        print(f"{ep:<7} {r['n_cl']:<5} {r['wr']:<6.1f} "
              f"{r['n_no_e']:<5} {r['n_not_f']:<6} "
              f"{r['total']:+7.1f} {r['r_tr']:+7.3f}{flag}")
    ep_winner = stage1_best[0]
    print(f"\nStage 1 WINNER: entry_pct = {ep_winner}  "
          f"(total={stage1_best[1]['total']:+.1f}R, n_cl={stage1_best[1]['n_cl']})")

    # ============== STAGE 2: SL formula sweep ==============
    print("\n" + "=" * 72)
    print(f" STAGE 2: SL formula sweep  (entry={ep_winner}, RR=1.0)")
    print("=" * 72)
    print(f"{'sl':<16} {'n_cl':<5} {'WR':<6} {'NO_E':<5} {'NOT_F':<6} {'total':<8} {'R/tr':<7}")
    stage2_best = None
    for sv in ["ob_full", "ob_inside_15", "ob_inside_35", "ob_inside_50",
                "poi_extreme", "asym_3565"]:
        r = run_config(df, ep_winner, sv, 1.0)
        flag = ""
        if stage2_best is None or r["total"] > stage2_best[1]["total"]:
            stage2_best = (sv, r)
            flag = " ←"
        print(f"{sv:<16} {r['n_cl']:<5} {r['wr']:<6.1f} "
              f"{r['n_no_e']:<5} {r['n_not_f']:<6} "
              f"{r['total']:+7.1f} {r['r_tr']:+7.3f}{flag}")
    sl_winner = stage2_best[0]
    print(f"\nStage 2 WINNER: sl = {sl_winner}  "
          f"(total={stage2_best[1]['total']:+.1f}R, n_cl={stage2_best[1]['n_cl']})")

    # ============== STAGE 3: RR sweep ==============
    print("\n" + "=" * 72)
    print(f" STAGE 3: RR sweep  (entry={ep_winner}, sl={sl_winner})")
    print("=" * 72)
    print(f"{'RR':<6} {'n_cl':<5} {'WR':<6} {'NO_E':<5} {'NOT_F':<6} {'total':<8} {'R/tr':<7}")
    stage3_best_total = None
    stage3_best_rtr = None
    for rr in [1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0, 3.5, 4.0, 5.0]:
        r = run_config(df, ep_winner, sl_winner, rr)
        flag = ""
        if stage3_best_total is None or r["total"] > stage3_best_total[1]["total"]:
            stage3_best_total = (rr, r)
        if r["n_cl"] >= 50 and (stage3_best_rtr is None or r["r_tr"] > stage3_best_rtr[1]["r_tr"]):
            stage3_best_rtr = (rr, r)
        print(f"{rr:<6} {r['n_cl']:<5} {r['wr']:<6.1f} "
              f"{r['n_no_e']:<5} {r['n_not_f']:<6} "
              f"{r['total']:+7.1f} {r['r_tr']:+7.3f}")
    print(f"\nStage 3 WINNER by total R: RR = {stage3_best_total[0]}  "
          f"(total={stage3_best_total[1]['total']:+.1f}R, R/tr={stage3_best_total[1]['r_tr']:+.3f})")
    print(f"Stage 3 WINNER by R/tr (n>=50): RR = {stage3_best_rtr[0]}  "
          f"(total={stage3_best_rtr[1]['total']:+.1f}R, R/tr={stage3_best_rtr[1]['r_tr']:+.3f})")

    # ============== INDICATOR OVERLAY на winning config ==============
    rr_winner = stage3_best_total[0]
    print("\n" + "=" * 72)
    print(f" INDICATOR OVERLAY  (entry={ep_winner}, sl={sl_winner}, RR={rr_winner})")
    print(" Each filter applied solo. Pre-filter baseline shown for comparison.")
    print("=" * 72)
    base_r = run_config(df, ep_winner, sl_winner, rr_winner)
    print(f"BASELINE (no filter): n={base_r['n_cl']:<3} WR={base_r['wr']:.1f}% "
          f"total={base_r['total']:+.1f}R  R/tr={base_r['r_tr']:+.3f}\n")

    indicators = [
        ("weekday != Sunday",             df["weekday"] != "Sunday"),
        ("session != London",             df["session"] != "London"),
        ("session = NY",                  df["session"] == "NY"),
        ("session = off",                 df["session"] == "off"),
        ("asvk_4h != red",                df["asvk_4h"] != "red"),
        ("asvk_4h in (yellow_OS, green)", df["asvk_4h"].isin(["yellow_OS", "green"])),
        ("mh_4h != green/grey_green",     ~df["mh_4h_color"].isin(["green", "grey_from_green"])),
        ("mh_4h = red",                   df["mh_4h_color"] == "red"),
        ("mh_4h_mf counter (1.1.7-style)", df["mh_4h_mf_align"] == "counter"),
        ("hull_4h_L160 aligned",          df["hull_4h_L160"] == "aligned"),
        ("hull_1h_L160 aligned",          df["hull_1h_L160"] == "aligned"),
        ("hull_12h_L78 counter",          df["hull_12h_L78"] == "counter"),
        ("ema200_4h aligned",             df["ema200_4h"] == "aligned"),
        ("ema200_1h counter",             df["ema200_1h"] == "counter"),
        ("Thu+Fri+Sat",                   df["weekday"].isin(["Thursday","Friday","Saturday"])),
        ("ob_tf = 2h",                    df["ob_tf"] == "2h"),
        ("fvg_tf = 20m",                  df["fvg_tf"] == "20m"),
    ]

    print(f"{'filter':<38} {'n_cl':<5} {'WR':<6} {'total':<8} {'R/tr':<7} {'Δtot':<7} {'ΔR/tr':<7}")
    for name, mask in indicators:
        sub = df[mask.fillna(False)]
        if len(sub) < 30:
            continue
        r = run_config(sub, ep_winner, sl_winner, rr_winner)
        d_total = r["total"] - base_r["total"]
        d_rtr = r["r_tr"] - base_r["r_tr"]
        flag = " ***" if (d_rtr >= 0.1 and r["n_cl"] >= 50) else (" !" if d_rtr <= -0.1 else "")
        print(f"{name:<38} {r['n_cl']:<5} {r['wr']:<6.1f} "
              f"{r['total']:+7.1f} {r['r_tr']:+7.3f} "
              f"{d_total:+6.1f} {d_rtr:+6.3f}{flag}")


if __name__ == "__main__":
    main()
