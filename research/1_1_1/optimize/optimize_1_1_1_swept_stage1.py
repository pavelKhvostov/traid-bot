"""Stage 1 оптимизация — но ТОЛЬКО на SWEPT deduped трейдах (115).

Pipeline:
  1. Detect 237 raw signals
  2. Group по dedup-key (signal_time, direction, entry)
  3. В каждой группе проверить SWEPT для каждого пути (OB-htf prev/cur)
  4. Группа = SWEPT если ХОТЯ БЫ ОДИН путь swept
  5. Для оптимизации берём ОДИН представитель группы (первый swept путь)
  6. SL = ob_htf edge, TP = TP_const (entry=mid, RR=1), vary entry_pct
"""
from __future__ import annotations


# --- repo-root injection (Phase 3 refactor) ---
import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    if _ROOT.parent == _ROOT:
        raise RuntimeError("repo root not found")
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))
# --- end repo-root injection ---

from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_1 import detect_strategy_1_1_1_signals

DAYS_BACK = 1095
SYMBOL = "BTCUSDT"
ENTRY_GRID = np.arange(0.0, 1.01, 0.05)


def check_swept_for_path(sig: dict, df_1h: pd.DataFrame, df_2h: pd.DataFrame) -> bool | None:
    df_top = df_1h if sig["ob_htf_tf"] == "1h" else df_2h
    cur_time = pd.Timestamp(sig["ob_htf_cur_time"])
    prev_time = pd.Timestamp(sig["ob_htf_prev_time"])
    if cur_time.tz is None: cur_time = cur_time.tz_localize("UTC")
    if prev_time.tz is None: prev_time = prev_time.tz_localize("UTC")
    if prev_time not in df_top.index or cur_time not in df_top.index:
        return None
    prev_idx = df_top.index.get_loc(prev_time)
    if prev_idx < 2:
        return None
    cur_idx = df_top.index.get_loc(cur_time)
    c1_low = float(df_top.iloc[prev_idx]["low"])
    c2_low = float(df_top.iloc[cur_idx]["low"])
    c1_high = float(df_top.iloc[prev_idx]["high"])
    c2_high = float(df_top.iloc[cur_idx]["high"])
    n1_low = float(df_top.iloc[prev_idx - 1]["low"])
    n2_low = float(df_top.iloc[prev_idx - 2]["low"])
    n1_high = float(df_top.iloc[prev_idx - 1]["high"])
    n2_high = float(df_top.iloc[prev_idx - 2]["high"])
    if sig["direction"] == "LONG":
        return min(c1_low, c2_low) < min(n1_low, n2_low)
    return max(c1_high, c2_high) > max(n1_high, n2_high)


def precompute_signal(sig: dict, df_1m: pd.DataFrame) -> dict | None:
    fvg_b, fvg_t = sig["fvg_zone"]
    obh_b, obh_t = sig["ob_htf_zone"]
    direction = sig["direction"]
    tf_minutes = 15 if sig["fvg_tf"] == "15m" else 20
    forward = df_1m[df_1m.index >= sig["signal_time"] + pd.Timedelta(minutes=tf_minutes)]
    if forward.empty:
        return None
    entry_mid = (fvg_b + fvg_t) / 2
    if direction == "LONG":
        risk_mid = entry_mid - obh_b
        tp_const = entry_mid + risk_mid
    else:
        risk_mid = obh_t - entry_mid
        tp_const = entry_mid - risk_mid
    return {
        "direction": direction,
        "fvg_b": float(fvg_b), "fvg_t": float(fvg_t),
        "obh_b": float(obh_b), "obh_t": float(obh_t),
        "tp_const": float(tp_const),
        "highs": forward["high"].values.astype(np.float64),
        "lows": forward["low"].values.astype(np.float64),
    }


def simulate(s: dict, entry: float, sl: float, tp: float) -> str:
    """Симуляция с проверкой no_entry: если TP достигнут ДО entry — отмена.

    Outcomes:
      - 'no_entry'   : цена дошла до TP, не коснувшись entry. Trade отменён.
      - 'not_filled' : entry не достигнут вообще (и TP тоже не).
      - 'win' / 'loss' / 'open' : нормальная симуляция после fill.
    """
    highs, lows = s["highs"], s["lows"]
    n = len(highs)
    if s["direction"] == "LONG":
        entry_idxs = np.where(lows <= entry)[0]
        tp_pre_idxs = np.where(highs >= tp)[0]
    else:
        entry_idxs = np.where(highs >= entry)[0]
        tp_pre_idxs = np.where(lows <= tp)[0]

    entry_idx = int(entry_idxs[0]) if entry_idxs.size else n + 1
    tp_pre_idx = int(tp_pre_idxs[0]) if tp_pre_idxs.size else n + 1

    # Если TP хитнулся СТРОГО раньше entry — no_entry (тот же бар = entry first)
    if tp_pre_idx < entry_idx:
        return "no_entry"
    if entry_idx >= n:
        return "not_filled"

    # Активирован — стандартная симуляция SL/TP с этого момента
    post_l = lows[entry_idx:]
    post_h = highs[entry_idx:]
    if s["direction"] == "LONG":
        sl_mask = post_l <= sl; tp_mask = post_h >= tp
    else:
        sl_mask = post_h >= sl; tp_mask = post_l <= tp
    sl_first = int(np.argmax(sl_mask)) if sl_mask.any() else -1
    tp_first = int(np.argmax(tp_mask)) if tp_mask.any() else -1
    if sl_first == -1 and tp_first == -1: return "open"
    if sl_first == -1: return "win"
    if tp_first == -1: return "loss"
    return "win" if tp_first < sl_first else "loss"


def main() -> None:
    print(f"[INFO] Stage 1 на SWEPT deduped, {SYMBOL}, окно {DAYS_BACK}d")
    print()

    print("[INFO] загрузка")
    df_1d = load_df(SYMBOL, "1d")
    df_4h = load_df(SYMBOL, "4h")
    df_1h = load_df(SYMBOL, "1h")
    df_12h = compose_from_base(df_1h, "12h")
    df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_15m = load_df(SYMBOL, "15m")
    df_1m = load_df(SYMBOL, "1m")
    df_20m = compose_from_base(df_1m, "20m")
    today = pd.Timestamp.now(tz="UTC").normalize()
    cutoff = today - pd.Timedelta(days=DAYS_BACK)
    df_1d_f = df_1d[df_1d.index >= cutoff]

    print("[INFO] детект signals (raw)")
    raw = detect_strategy_1_1_1_signals(
        df_1d_f, df_12h, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m, verbose=False,
    )
    print(f"  raw paths: {len(raw)}")

    # Group by dedup key + check swept per path
    groups = defaultdict(list)
    for s in raw:
        key = (s["signal_time"], s["direction"], round(float(s["entry"]), 2))
        sw = check_swept_for_path(s, df_1h, df_2h)
        if sw is None:
            continue
        groups[key].append({"sig": s, "swept": sw})

    # Group is SWEPT if ANY path is swept
    # Pick ONE representative per group: prefer a SWEPT path
    swept_groups = []
    notswept_groups = []
    for key, paths in groups.items():
        any_swept = any(p["swept"] for p in paths)
        if any_swept:
            rep = next(p["sig"] for p in paths if p["swept"])
            swept_groups.append(rep)
        else:
            notswept_groups.append(paths[0]["sig"])
    print(f"  deduped groups: {len(groups)}")
    print(f"  SWEPT groups: {len(swept_groups)}")
    print(f"  NOT-SWEPT groups: {len(notswept_groups)}")

    # Precompute on swept only
    cache = [c for c in (precompute_signal(s, df_1m) for s in swept_groups) if c is not None]
    print(f"  cache (SWEPT only): {len(cache)}")

    # Stage 1: vary entry, SL=ob_htf edge, TP=TP_const
    print()
    print("=" * 100)
    print("ЭТАП 1 (SWEPT only): SL=ob_htf edge, TP=TP_const, entry varies")
    print("=" * 100)
    rows = []
    for ep in ENTRY_GRID:
        wins = losses = nf = skipped = opens = no_entry = 0
        pnl_r = 0.0; rr_sum = 0.0; n_with_rr = 0
        for s in cache:
            fw = s["fvg_t"] - s["fvg_b"]
            if s["direction"] == "LONG":
                entry = s["fvg_b"] + ep * fw
                sl = s["obh_b"]
            else:
                entry = s["fvg_t"] - ep * fw
                sl = s["obh_t"]
            tp = s["tp_const"]
            if s["direction"] == "LONG":
                if sl >= entry or tp <= entry:
                    skipped += 1; continue
                risk = entry - sl
                rr = (tp - entry) / risk
            else:
                if sl <= entry or tp >= entry:
                    skipped += 1; continue
                risk = sl - entry
                rr = (entry - tp) / risk
            outcome = simulate(s, entry, sl, tp)
            if outcome == "win":
                wins += 1; pnl_r += rr; rr_sum += rr; n_with_rr += 1
            elif outcome == "loss":
                losses += 1; pnl_r -= 1.0; rr_sum += rr; n_with_rr += 1
            elif outcome == "open":
                opens += 1
            elif outcome == "no_entry":
                no_entry += 1
            else:
                nf += 1
        closed = wins + losses
        rows.append({
            "entry_pct": round(ep, 2),
            "wins": wins, "losses": losses, "no_entry": no_entry,
            "nf": nf, "opens": opens, "skipped": skipped,
            "wr": round(wins / closed * 100, 1) if closed else 0,
            "pnl_r": round(pnl_r, 2),
            "avg_rr": round(rr_sum / n_with_rr, 3) if n_with_rr else 0,
        })
    df = pd.DataFrame(rows).sort_values("pnl_r", ascending=False)
    print(df.to_string(index=False))

    best = df.iloc[0]
    print()
    print(f"  >>> Best entry_pct = {best['entry_pct']}")
    print(f"      wins={best['wins']} losses={best['losses']} WR={best['wr']}% "
          f"PnL={best['pnl_r']}R avg_RR={best['avg_rr']}")

    # Сравним с дефолтом entry=0.5
    default = df[df["entry_pct"] == 0.5].iloc[0]
    print(f"  Default (entry=0.5): wins={default['wins']} losses={default['losses']} "
          f"WR={default['wr']}% PnL={default['pnl_r']}R avg_RR={default['avg_rr']}")

    out = Path("signals/optimize_1_1_1_swept_stage1.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f"\nGrid saved: {out}")


if __name__ == "__main__":
    main()
