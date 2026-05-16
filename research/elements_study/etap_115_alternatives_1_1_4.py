"""etap_115: альтернативные автоследования для 1.1.4 BFJK.

Floating TP (etap_114) ухудшил 1.1.4 — режет profitable trades которые
статистически доходят до +2R. Нужны механизмы которые НЕ ТРОГАЮТ winners.

Тестируемые варианты:
  A. BE-ratchet @ +1R MFE (SL→BE)
  B. BE-ratchet @ +1.5R MFE
  C. Strict score-exit (threshold=-0.5, очень аккуратно)
  D. Strict score-exit (-0.7)
  E. Lock-step ratchet (SL→BE @ +1R, SL→+1R @ +2R, hard cap +3R)
  F. ATR trail (K=2.0, hard cap +3R)
  G. Conditional TP extension @ +2R via score (+0.25 → extend, else take TP)
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
import importlib.util as _ilu
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists(): _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path: _sys.path.insert(0, str(_ROOT))

from collections import defaultdict
from pathlib import Path
import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df

_E66 = Path(__file__).parent / "etap_66_114_chains_survey.py"
_spec = _ilu.spec_from_file_location("etap66_core", _E66)
_e66 = _ilu.module_from_spec(_spec); _sys.modules["etap66_core"] = _e66
_spec.loader.exec_module(_e66)

_E114 = Path(__file__).parent / "etap_114_floating_1_1_4.py"
_spec114 = _ilu.spec_from_file_location("etap114_core", _E114)
_e114 = _ilu.module_from_spec(_spec114); _sys.modules["etap114_core"] = _e114
_spec114.loader.exec_module(_e114)
collect_bfjk_setups = _e114.collect_bfjk_setups
simulate_baseline_rr = _e114.simulate_baseline_rr
stats = _e114.stats

_E103 = Path(__file__).parent / "etap_103_floating_tp.py"
_spec103 = _ilu.spec_from_file_location("etap103_core", _E103)
_e103 = _ilu.module_from_spec(_spec103); _sys.modules["etap103_core"] = _e103
_spec103.loader.exec_module(_e103)
build_score_series = _e103.build_score_series

RR_BASELINE = 2.0
MAX_HOLD_DAYS = 7


def compute_atr(df, period=14):
    h, l, pc = df["high"], df["low"], df["close"].shift(1)
    tr = pd.concat([(h-l), (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _walk_1m(s, df_1m):
    """Возвращает (entry, sl, risk, post_h, post_l, post_c, post_ts, activation, end) или None."""
    tup = _e66.build_orders(s)
    if tup is None: return None
    entry, sl = tup
    direction = s["direction"]
    risk = abs(entry - sl)
    if risk <= 0: return None
    tp_proxy = entry + RR_BASELINE * risk if direction == "LONG" else entry - RR_BASELINE * risk

    start = s["signal_time"]
    end = start + pd.Timedelta(days=MAX_HOLD_DAYS)
    et64 = np.datetime64(start.tz_localize(None) if start.tz else start)
    ee64 = np.datetime64(end.tz_localize(None) if end.tz else end)
    i0 = np.searchsorted(df_1m.index.values, et64)
    i1 = np.searchsorted(df_1m.index.values, ee64)
    if i1 <= i0: return None
    h = df_1m["high"].values[i0:i1].astype(np.float64)
    l = df_1m["low"].values[i0:i1].astype(np.float64)
    c = df_1m["close"].values[i0:i1].astype(np.float64)
    times = df_1m.index[i0:i1]
    n = len(h)

    # no_entry filter
    if direction == "LONG":
        ent_idxs = np.where(l <= entry)[0]
        tp_pre = np.where(h >= tp_proxy)[0]
    else:
        ent_idxs = np.where(h >= entry)[0]
        tp_pre = np.where(l <= tp_proxy)[0]
    ent_i = int(ent_idxs[0]) if ent_idxs.size else n + 1
    tp_pre_i = int(tp_pre[0]) if tp_pre.size else n + 1
    if tp_pre_i < ent_i: return {"outcome_pre": "no_entry"}
    if ent_i >= n: return {"outcome_pre": "nf"}
    activation = times[ent_i]
    return {
        "entry": entry, "sl": sl, "risk": risk, "direction": direction,
        "post_h": h[ent_i:], "post_l": l[ent_i:], "post_c": c[ent_i:],
        "post_ts": times[ent_i:], "activation": activation, "end_time": end,
    }


def _make_result(R, exit_time, exit_reason, entry, sl, tp, activation, max_R):
    outc = "win" if R > 0 else ("loss" if R < 0 else "flat")
    return {"outcome": outc, "R": float(R), "entry": entry, "sl": sl, "tp": tp,
            "exit_time": exit_time, "exit_reason": exit_reason,
            "entry_time": activation, "max_R": max_R}


# ========================================================================
# A. BE-ratchet @ +1R MFE — SL moves to entry when MFE ≥ +1R, TP +2R hard
# ========================================================================
def variant_be_ratchet(s, df_1m, mfe_trigger_R=1.0):
    w = _walk_1m(s, df_1m)
    if w is None: return None
    if "outcome_pre" in w:
        return {"outcome": w["outcome_pre"], "R": 0.0, "exit_reason": w["outcome_pre"]}
    direction = w["direction"]; entry = w["entry"]; sl = w["sl"]; risk = w["risk"]
    tp = entry + RR_BASELINE*risk if direction == "LONG" else entry - RR_BASELINE*risk
    post_h, post_l, post_ts = w["post_h"], w["post_l"], w["post_ts"]
    current_sl = sl; mfe_R = 0.0
    for i in range(len(post_h)):
        if direction == "LONG":
            mfe_R = max(mfe_R, (post_h[i] - entry)/risk)
            if mfe_R >= mfe_trigger_R: current_sl = max(current_sl, entry)  # to BE
            if post_l[i] <= current_sl:
                R = (current_sl - entry)/risk
                return _make_result(R, post_ts[i], "trail_be", entry, current_sl, tp, w["activation"], mfe_R)
            if post_h[i] >= tp:
                return _make_result(RR_BASELINE, post_ts[i], "tp", entry, current_sl, tp, w["activation"], mfe_R)
        else:
            mfe_R = max(mfe_R, (entry - post_l[i])/risk)
            if mfe_R >= mfe_trigger_R: current_sl = min(current_sl, entry)
            if post_h[i] >= current_sl:
                R = (entry - current_sl)/risk
                return _make_result(R, post_ts[i], "trail_be", entry, current_sl, tp, w["activation"], mfe_R)
            if post_l[i] <= tp:
                return _make_result(RR_BASELINE, post_ts[i], "tp", entry, current_sl, tp, w["activation"], mfe_R)
    # max hold
    last_c = float(w["post_c"][-1])
    R = (last_c - entry)/risk if direction == "LONG" else (entry - last_c)/risk
    return _make_result(R, post_ts[-1], "max_hold", entry, current_sl, tp, w["activation"], mfe_R)


# ========================================================================
# E. Lock-step ratchet: SL→BE @ +1R, SL→+1R @ +2R, hard cap +3R
# ========================================================================
def variant_lockstep(s, df_1m, cap_R=3.0):
    w = _walk_1m(s, df_1m)
    if w is None: return None
    if "outcome_pre" in w:
        return {"outcome": w["outcome_pre"], "R": 0.0, "exit_reason": w["outcome_pre"]}
    direction = w["direction"]; entry = w["entry"]; sl = w["sl"]; risk = w["risk"]
    tp_cap = entry + cap_R*risk if direction == "LONG" else entry - cap_R*risk
    post_h, post_l, post_ts = w["post_h"], w["post_l"], w["post_ts"]
    current_sl = sl; mfe_R = 0.0; locked_step = -1  # -1=none, 0=BE, 1=+1R
    for i in range(len(post_h)):
        if direction == "LONG":
            mfe_R = max(mfe_R, (post_h[i] - entry)/risk)
            if mfe_R >= 1.0 and locked_step < 0:
                current_sl = entry; locked_step = 0
            if mfe_R >= 2.0 and locked_step < 1:
                current_sl = entry + risk; locked_step = 1
            if post_l[i] <= current_sl:
                R = (current_sl - entry)/risk
                return _make_result(R, post_ts[i], f"lock_step_{locked_step}", entry, current_sl, tp_cap, w["activation"], mfe_R)
            if post_h[i] >= tp_cap:
                return _make_result(cap_R, post_ts[i], "cap", entry, current_sl, tp_cap, w["activation"], mfe_R)
        else:
            mfe_R = max(mfe_R, (entry - post_l[i])/risk)
            if mfe_R >= 1.0 and locked_step < 0:
                current_sl = entry; locked_step = 0
            if mfe_R >= 2.0 and locked_step < 1:
                current_sl = entry - risk; locked_step = 1
            if post_h[i] >= current_sl:
                R = (entry - current_sl)/risk
                return _make_result(R, post_ts[i], f"lock_step_{locked_step}", entry, current_sl, tp_cap, w["activation"], mfe_R)
            if post_l[i] <= tp_cap:
                return _make_result(cap_R, post_ts[i], "cap", entry, current_sl, tp_cap, w["activation"], mfe_R)
    last_c = float(w["post_c"][-1])
    R = (last_c - entry)/risk if direction == "LONG" else (entry - last_c)/risk
    return _make_result(R, post_ts[-1], "max_hold", entry, current_sl, tp_cap, w["activation"], mfe_R)


# ========================================================================
# C/D. Strict score-exit — high threshold (only catastrophic reversals)
# ========================================================================
def variant_strict_score(s, df_1m, df_1h, score_long, score_short,
                          threshold=-0.5, confirm=2):
    """Hard TP +2R. SL +sl. Score-exit ONLY when score <= threshold (strict)."""
    w = _walk_1m(s, df_1m)
    if w is None: return None
    if "outcome_pre" in w:
        return {"outcome": w["outcome_pre"], "R": 0.0, "exit_reason": w["outcome_pre"]}
    direction = w["direction"]; entry = w["entry"]; sl = w["sl"]; risk = w["risk"]
    tp = entry + RR_BASELINE*risk if direction == "LONG" else entry - RR_BASELINE*risk
    post_h, post_l, post_c, post_ts = w["post_h"], w["post_l"], w["post_c"], w["post_ts"]
    activation = w["activation"]; end_time = w["end_time"]
    score_series = score_long if direction == "LONG" else score_short

    h1_after = df_1h.index.searchsorted(activation, side="right")
    h1_end = df_1h.index.searchsorted(end_time, side="right")
    checkpoints = df_1h.index[h1_after:h1_end]
    closes_1h = df_1h["close"].values

    consec = 0; prev_post_idx = 0; mfe_R = 0.0
    for cp in checkpoints:
        cp64 = np.datetime64(cp.tz_localize(None) if cp.tz else cp)
        cur_post_idx = np.searchsorted(post_ts.values, cp64)
        if cur_post_idx > prev_post_idx:
            w_l = post_l[prev_post_idx:cur_post_idx]
            w_h = post_h[prev_post_idx:cur_post_idx]
            if direction == "LONG":
                mfe_R = max(mfe_R, (max(w_h) - entry)/risk)
                if (w_l <= sl).any():
                    idx = prev_post_idx + int(np.argmax(w_l <= sl))
                    return _make_result(-1.0, post_ts[idx], "sl", entry, sl, tp, activation, mfe_R)
                if (w_h >= tp).any():
                    idx = prev_post_idx + int(np.argmax(w_h >= tp))
                    return _make_result(RR_BASELINE, post_ts[idx], "tp", entry, sl, tp, activation, mfe_R)
            else:
                mfe_R = max(mfe_R, (entry - min(w_l))/risk)
                if (w_h >= sl).any():
                    idx = prev_post_idx + int(np.argmax(w_h >= sl))
                    return _make_result(-1.0, post_ts[idx], "sl", entry, sl, tp, activation, mfe_R)
                if (w_l <= tp).any():
                    idx = prev_post_idx + int(np.argmax(w_l <= tp))
                    return _make_result(RR_BASELINE, post_ts[idx], "tp", entry, sl, tp, activation, mfe_R)
        prev_post_idx = cur_post_idx
        score_idx = score_series.index.searchsorted(cp, side="right") - 1
        if score_idx < 0: continue
        sc = score_series.iloc[score_idx]
        if pd.isna(sc): continue
        if sc <= threshold: consec += 1
        else: consec = 0
        if consec >= confirm:
            cp_close_idx = df_1h.index.searchsorted(cp, side="right") - 2
            if cp_close_idx >= 0:
                px = float(closes_1h[cp_close_idx])
                R = (px - entry)/risk if direction == "LONG" else (entry - px)/risk
                return _make_result(R, cp, "score_early", entry, sl, tp, activation, mfe_R)
    last_c = float(post_c[-1])
    R = (last_c - entry)/risk if direction == "LONG" else (entry - last_c)/risk
    return _make_result(R, post_ts[-1], "max_hold", entry, sl, tp, activation, mfe_R)


# ========================================================================
# F. ATR trail (K × ATR distance from MFE), cap at cap_R
# ========================================================================
def variant_atr_trail(s, df_1m, atr_1h, K=2.0, cap_R=3.0):
    w = _walk_1m(s, df_1m)
    if w is None: return None
    if "outcome_pre" in w:
        return {"outcome": w["outcome_pre"], "R": 0.0, "exit_reason": w["outcome_pre"]}
    direction = w["direction"]; entry = w["entry"]; sl = w["sl"]; risk = w["risk"]
    activation = w["activation"]
    tp_cap = entry + cap_R*risk if direction == "LONG" else entry - cap_R*risk

    atr_idx = atr_1h.index.searchsorted(activation, side="right") - 1
    if atr_idx < 0 or pd.isna(atr_1h.iloc[atr_idx]):
        return {"outcome": "skip", "R": 0.0, "exit_reason": "no_atr"}
    atr_v = float(atr_1h.iloc[atr_idx])
    if atr_v <= 0:
        return {"outcome": "skip", "R": 0.0, "exit_reason": "bad_atr"}
    trail_dist = K * atr_v

    post_h, post_l, post_c, post_ts = w["post_h"], w["post_l"], w["post_c"], w["post_ts"]
    mfe_price = entry; mfe_R = 0.0
    if direction == "LONG":
        for i in range(len(post_h)):
            mfe_price = max(mfe_price, post_h[i])
            mfe_R = max(mfe_R, (mfe_price - entry)/risk)
            trail_price = mfe_price - trail_dist
            if post_l[i] <= sl:
                return _make_result(-1.0, post_ts[i], "sl", entry, sl, tp_cap, activation, mfe_R)
            if post_h[i] >= tp_cap:
                return _make_result(cap_R, post_ts[i], "cap", entry, sl, tp_cap, activation, mfe_R)
            if i > 0 and post_l[i] <= trail_price:
                R = (trail_price - entry)/risk
                return _make_result(R, post_ts[i], "atr_trail", entry, sl, tp_cap, activation, mfe_R)
    else:
        for i in range(len(post_l)):
            mfe_price = min(mfe_price, post_l[i])
            mfe_R = max(mfe_R, (entry - mfe_price)/risk)
            trail_price = mfe_price + trail_dist
            if post_h[i] >= sl:
                return _make_result(-1.0, post_ts[i], "sl", entry, sl, tp_cap, activation, mfe_R)
            if post_l[i] <= tp_cap:
                return _make_result(cap_R, post_ts[i], "cap", entry, sl, tp_cap, activation, mfe_R)
            if i > 0 and post_h[i] >= trail_price:
                R = (entry - trail_price)/risk
                return _make_result(R, post_ts[i], "atr_trail", entry, sl, tp_cap, activation, mfe_R)
    last_c = float(post_c[-1])
    R = (last_c - entry)/risk if direction == "LONG" else (entry - last_c)/risk
    return _make_result(R, post_ts[-1], "max_hold", entry, sl, tp_cap, activation, mfe_R)


# ========================================================================
# G. Conditional TP extension via score at +2R touch
# ========================================================================
def variant_tp_extension(s, df_1m, df_1h, score_long, score_short, cap_R=3.0,
                          extend_threshold=+0.25):
    """At +2R touch, check score. If score > extend_threshold → trail to cap_R; else take TP."""
    w = _walk_1m(s, df_1m)
    if w is None: return None
    if "outcome_pre" in w:
        return {"outcome": w["outcome_pre"], "R": 0.0, "exit_reason": w["outcome_pre"]}
    direction = w["direction"]; entry = w["entry"]; sl = w["sl"]; risk = w["risk"]
    tp_2r = entry + RR_BASELINE*risk if direction == "LONG" else entry - RR_BASELINE*risk
    tp_cap = entry + cap_R*risk if direction == "LONG" else entry - cap_R*risk
    post_h, post_l, post_c, post_ts = w["post_h"], w["post_l"], w["post_c"], w["post_ts"]
    activation = w["activation"]
    score_series = score_long if direction == "LONG" else score_short

    mfe_R = 0.0
    tp_touched = False
    current_sl = sl
    for i in range(len(post_h)):
        if direction == "LONG":
            mfe_R = max(mfe_R, (post_h[i] - entry)/risk)
            if post_l[i] <= current_sl:
                R = (current_sl - entry)/risk
                return _make_result(R, post_ts[i], "sl/trail", entry, current_sl, tp_2r, activation, mfe_R)
            if post_h[i] >= tp_cap:
                return _make_result(cap_R, post_ts[i], "cap", entry, current_sl, tp_cap, activation, mfe_R)
            if not tp_touched and post_h[i] >= tp_2r:
                # check score at this moment
                ts = post_ts[i]
                score_idx = score_series.index.searchsorted(ts, side="right") - 1
                if score_idx < 0:
                    return _make_result(RR_BASELINE, post_ts[i], "tp", entry, current_sl, tp_2r, activation, mfe_R)
                sc = score_series.iloc[score_idx]
                if pd.isna(sc) or sc <= extend_threshold:
                    return _make_result(RR_BASELINE, post_ts[i], "tp", entry, current_sl, tp_2r, activation, mfe_R)
                # extend: keep going, move SL to +1R
                current_sl = entry + risk
                tp_touched = True
        else:
            mfe_R = max(mfe_R, (entry - post_l[i])/risk)
            if post_h[i] >= current_sl:
                R = (entry - current_sl)/risk
                return _make_result(R, post_ts[i], "sl/trail", entry, current_sl, tp_2r, activation, mfe_R)
            if post_l[i] <= tp_cap:
                return _make_result(cap_R, post_ts[i], "cap", entry, current_sl, tp_cap, activation, mfe_R)
            if not tp_touched and post_l[i] <= tp_2r:
                ts = post_ts[i]
                score_idx = score_series.index.searchsorted(ts, side="right") - 1
                if score_idx < 0:
                    return _make_result(RR_BASELINE, post_ts[i], "tp", entry, current_sl, tp_2r, activation, mfe_R)
                sc = score_series.iloc[score_idx]
                if pd.isna(sc) or sc <= extend_threshold:
                    return _make_result(RR_BASELINE, post_ts[i], "tp", entry, current_sl, tp_2r, activation, mfe_R)
                current_sl = entry - risk
                tp_touched = True
    last_c = float(post_c[-1])
    R = (last_c - entry)/risk if direction == "LONG" else (entry - last_c)/risk
    return _make_result(R, post_ts[-1], "max_hold", entry, current_sl, tp_cap, activation, mfe_R)


def main():
    print("etap_115: Альтернативные автоследования для 1.1.4 BFJK (BTC 6.3y)")
    print()
    setups, df_1m, df_1h, df_2h = collect_bfjk_setups("BTCUSDT")
    print(f"  unique setups: {len(setups)}")
    score_long, score_short = build_score_series(df_1h)
    atr_1h = compute_atr(df_1h)

    # Baseline (canonical)
    base_trades = []
    for s in setups:
        r = simulate_baseline_rr(s, df_1m)
        if r is None: continue
        r["signal_time"] = s["signal_time"]; r["direction"] = s["direction"]
        base_trades.append(r)
    base = stats(base_trades, "BASELINE RR=2.0")

    variants = [
        ("A: BE-ratchet @ +1R",     lambda s: variant_be_ratchet(s, df_1m, 1.0)),
        ("A2: BE-ratchet @ +1.5R",  lambda s: variant_be_ratchet(s, df_1m, 1.5)),
        ("E: Lock-step (BE/+1R/+3cap)", lambda s: variant_lockstep(s, df_1m, 3.0)),
        ("E2: Lock-step cap=4",     lambda s: variant_lockstep(s, df_1m, 4.0)),
        ("C: Strict score th=-0.5", lambda s: variant_strict_score(s, df_1m, df_1h, score_long, score_short, -0.5, 2)),
        ("D: Strict score th=-0.7", lambda s: variant_strict_score(s, df_1m, df_1h, score_long, score_short, -0.7, 2)),
        ("F: ATR trail K=2.0 cap=3",lambda s: variant_atr_trail(s, df_1m, atr_1h, 2.0, 3.0)),
        ("F2: ATR trail K=2.5 cap=4",lambda s: variant_atr_trail(s, df_1m, atr_1h, 2.5, 4.0)),
        ("G: TP ext +0.25 cap=3",   lambda s: variant_tp_extension(s, df_1m, df_1h, score_long, score_short, 3.0, +0.25)),
        ("G2: TP ext +0.5 cap=4",   lambda s: variant_tp_extension(s, df_1m, df_1h, score_long, score_short, 4.0, +0.5)),
    ]

    print()
    print(f"  {'Variant':<32} {'n':>4} {'WR':>6} {'PnL':>9} {'medR':>6} {'maxR':>5} {'top5%':>6} {'bad':>5}  pass")
    print("  " + "-"*100)
    bwl = f"{base['W']}/{base['L']}"
    pass_b = "PASS" if base["median_R"] > 0 and base["top5_pct"] < 25 else "    "
    print(f"  {base['label']:<32} {base['n']:>4d} {base['wr']:>5.1f}% {base['pnl']:>+8.1f}R "
          f"{base['median_R']:>+5.2f} {base['max_R']:>+4.1f} {base['top5_pct']:>5.1f}% "
          f"{base['bad']}/{base['n_yrs']}  {pass_b}")
    results = [base]
    for label, fn in variants:
        trades = []
        for s in setups:
            r = fn(s)
            if r is None: continue
            r["signal_time"] = s["signal_time"]; r["direction"] = s["direction"]
            trades.append(r)
        st = stats(trades, label)
        if st is None:
            print(f"  {label:<32}: no closed"); continue
        pass_ = "PASS" if (st["median_R"] > 0 and st["top5_pct"] < 25) else "    "
        print(f"  {st['label']:<32} {st['n']:>4d} {st['wr']:>5.1f}% {st['pnl']:>+8.1f}R "
              f"{st['median_R']:>+5.2f} {st['max_R']:>+4.1f} {st['top5_pct']:>5.1f}% "
              f"{st['bad']}/{st['n_yrs']}  {pass_}")
        results.append(st)

    print()
    print("RANKED by PnL:")
    for r in sorted(results, key=lambda x: x["pnl"], reverse=True)[:8]:
        delta = r["pnl"] - base["pnl"]
        print(f"  {r['label']:<32}  PnL={r['pnl']:+7.1f}R  delta={delta:+5.1f}R  "
              f"WR={r['wr']:.1f}%  medR={r['median_R']:+.2f}  top5={r['top5_pct']:.1f}%  bad={r['bad']}/{r['n_yrs']}")


if __name__ == "__main__":
    main()
