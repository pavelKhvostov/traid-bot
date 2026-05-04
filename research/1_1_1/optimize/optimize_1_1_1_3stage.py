"""3-этапная оптимизация Strategy 1.1.1.

Каждый сигнал имеет константу TP_const = цена TP при default-config
(entry=mid FVG, SL=ob_htf edge, RR=1):
  LONG  TP_const = entry_mid + (entry_mid - ob_htf.bottom)
  SHORT TP_const = entry_mid - (ob_htf.top - entry_mid)

Этап 1: SL=ob_htf edge (const), TP=TP_const, варьируем entry в FVG.
Этап 2: entry=лучший из этапа 1, TP=TP_const, варьируем SL внутри ob_htf zone.
Этап 3: entry/SL=лучшие, варьируем RR (TP = entry ± risk × RR).
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

from pathlib import Path

import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_1 import detect_strategy_1_1_1_signals

DAYS_BACK = 1095
SYMBOL = "BTCUSDT"
ENTRY_GRID = np.arange(0.0, 1.01, 0.05)   # 21 значение
SL_GRID = np.arange(0.0, 0.96, 0.05)      # 20 значений (исключая 1.0 — SL=top для LONG = выше entry)
RR_GRID = np.arange(0.5, 5.01, 0.25)      # 19 значений


def precompute_signal(sig: dict, df_1m: pd.DataFrame) -> dict | None:
    fvg_b, fvg_t = sig["fvg_zone"]
    obh_b, obh_t = sig["ob_htf_zone"]
    direction = sig["direction"]
    tf_minutes = 15 if sig["fvg_tf"] == "15m" else 20
    fill_scan_start = sig["signal_time"] + pd.Timedelta(minutes=tf_minutes)
    forward = df_1m[df_1m.index >= fill_scan_start]
    if forward.empty:
        return None
    # TP_const — TP при default (entry=mid FVG, SL=ob_htf edge, RR=1)
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
    highs, lows = s["highs"], s["lows"]
    if s["direction"] == "LONG":
        fill_mask = lows <= entry
        if not fill_mask.any():
            return "not_filled"
        fill_idx = int(np.argmax(fill_mask))
        post_l = lows[fill_idx:]; post_h = highs[fill_idx:]
        sl_mask = post_l <= sl; tp_mask = post_h >= tp
    else:
        fill_mask = highs >= entry
        if not fill_mask.any():
            return "not_filled"
        fill_idx = int(np.argmax(fill_mask))
        post_l = lows[fill_idx:]; post_h = highs[fill_idx:]
        sl_mask = post_h >= sl; tp_mask = post_l <= tp
    sl_first = int(np.argmax(sl_mask)) if sl_mask.any() else -1
    tp_first = int(np.argmax(tp_mask)) if tp_mask.any() else -1
    if sl_first == -1 and tp_first == -1: return "open"
    if sl_first == -1: return "win"
    if tp_first == -1: return "loss"
    return "win" if tp_first < sl_first else "loss"


def compute_entry(s: dict, entry_pct: float) -> float:
    fw = s["fvg_t"] - s["fvg_b"]
    if s["direction"] == "LONG":
        return s["fvg_b"] + entry_pct * fw
    return s["fvg_t"] - entry_pct * fw


def compute_sl_baseline(s: dict) -> float:
    """SL = ob_htf edge (baseline для этапа 1)."""
    return s["obh_b"] if s["direction"] == "LONG" else s["obh_t"]


def compute_sl_param(s: dict, sl_pct: float) -> float:
    """SL варьируется внутри ob_htf zone.
       LONG  sl_pct=0 → obh_b (широкий SL),  sl_pct=1 → obh_t (узкий, может быть выше entry)
       SHORT sl_pct=0 → obh_t (широкий),     sl_pct=1 → obh_b (узкий)
    """
    w = s["obh_t"] - s["obh_b"]
    if s["direction"] == "LONG":
        return s["obh_b"] + sl_pct * w
    return s["obh_t"] - sl_pct * w


def evaluate(cache: list[dict], entry_pct: float, sl_value_fn,
             tp_value_fn) -> dict:
    """Прогон всех сигналов с заданными функциями для SL и TP, считаем R-units.

    1R = текущий risk = |entry - SL|. Win = +rr (где rr = (tp-entry)/risk для LONG),
    Loss = -1.
    """
    wins = losses = nf = skipped = opens = 0
    pnl_r = 0.0
    rr_sum = 0.0; n_with_rr = 0
    for s in cache:
        entry = compute_entry(s, entry_pct)
        sl = sl_value_fn(s)
        tp = tp_value_fn(s, entry, sl)
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
            opens += 1; rr_sum += rr; n_with_rr += 1
        else:
            nf += 1
    closed = wins + losses
    return {
        "wins": wins, "losses": losses, "nf": nf, "skipped": skipped, "opens": opens,
        "wr": (wins / closed * 100) if closed else 0,
        "pnl_r": round(pnl_r, 2),
        "avg_rr": round(rr_sum / n_with_rr, 3) if n_with_rr else 0,
    }


def main() -> None:
    print(f"[INFO] 3-stage optimize Strategy 1.1.1, {SYMBOL}, окно {DAYS_BACK}d")
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
    print("[INFO] детект сигналов")
    sigs = detect_strategy_1_1_1_signals(
        df_1d_f, df_12h, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m, verbose=False,
    )
    cache = [c for c in (precompute_signal(s, df_1m) for s in sigs) if c is not None]
    print(f"  raw: {len(sigs)}, cached: {len(cache)}")

    n_total = len(cache)
    min_valid = int(n_total * 0.80)  # 80% сигналов должны быть валидны
    print(f"  Min valid (80% of {n_total}): {min_valid}")

    def pick_best(df, label):
        # Фильтруем конфиги где skipped > 20% (мало валидных сигналов)
        df["valid"] = df["wins"] + df["losses"] + df["nf"] + df["opens"]
        df = df[df["valid"] >= min_valid].copy()
        df = df.sort_values("pnl_r", ascending=False)
        if df.empty:
            print(f"  [WARN] {label}: ни одного конфига с >=80% валидных")
            return None, df
        return df.iloc[0], df

    # ---------- ЭТАП 1: vary entry, SL=ob_htf edge, TP=TP_const ----------
    print()
    print("=" * 100)
    print("ЭТАП 1: SL=ob_htf edge (baseline), TP=TP_const(default), entry varies")
    print("=" * 100)
    sl_fn1 = lambda s: compute_sl_baseline(s)
    tp_fn = lambda s, e, sl: s["tp_const"]
    rows1 = []
    for ep in ENTRY_GRID:
        r = evaluate(cache, ep, sl_fn1, tp_fn)
        rows1.append({"entry_pct": round(ep, 2), **r})
    df1 = pd.DataFrame(rows1)
    best, df1_filt = pick_best(df1, "stage 1")
    print(df1_filt.head(8).to_string(index=False))
    best_ep = best["entry_pct"]
    print(f"  >>> Best entry_pct = {best_ep}")

    # ---------- ЭТАП 2: entry=best, SL varies, TP=TP_const ----------
    print()
    print("=" * 100)
    print(f"ЭТАП 2: entry={best_ep} (из этапа 1), TP=TP_const, SL varies in ob_htf zone")
    print("=" * 100)
    rows2 = []
    for sp in SL_GRID:
        sl_fn = lambda s, _sp=sp: compute_sl_param(s, _sp)
        r = evaluate(cache, best_ep, sl_fn, tp_fn)
        rows2.append({"sl_pct": round(sp, 2), **r})
    df2 = pd.DataFrame(rows2)
    best, df2_filt = pick_best(df2, "stage 2")
    print(df2_filt.head(8).to_string(index=False))
    best_sp = best["sl_pct"]
    print(f"  >>> Best sl_pct = {best_sp}")

    # ---------- ЭТАП 3: entry=best, SL=best, TP varies (RR varies) ----------
    print()
    print("=" * 100)
    print(f"ЭТАП 3: entry={best_ep}, sl_pct={best_sp}, TP/RR varies")
    print("=" * 100)
    rows3 = []
    for rr in RR_GRID:
        sl_fn = lambda s, _sp=best_sp: compute_sl_param(s, _sp)
        def tp_fn_rr(s, e, sl, _rr=rr):
            risk = abs(e - sl)
            return e + risk * _rr if s["direction"] == "LONG" else e - risk * _rr
        r = evaluate(cache, best_ep, sl_fn, tp_fn_rr)
        rows3.append({"rr": round(rr, 2), **r})
    df3 = pd.DataFrame(rows3)
    best, df3_filt = pick_best(df3, "stage 3")
    print(df3_filt.head(10).to_string(index=False))
    best_rr = best["rr"]
    print(f"  >>> Best RR = {best_rr}")

    # ---------- Финальная сводка ----------
    print()
    print("=" * 100)
    print("ИТОГОВЫЙ ОПТИМАЛЬНЫЙ КОНФИГ:")
    print("=" * 100)
    final_sl = lambda s: compute_sl_param(s, best_sp)
    final_tp = lambda s, e, sl: e + abs(e - sl) * best_rr if s["direction"] == "LONG" else e - abs(e - sl) * best_rr
    final = evaluate(cache, best_ep, final_sl, final_tp)
    print(f"  entry_pct = {best_ep}")
    print(f"  sl_pct    = {best_sp}")
    print(f"  RR        = {best_rr}")
    print()
    print(f"  Total: wins={final['wins']} losses={final['losses']} not_filled={final['nf']}")
    print(f"  WR={final['wr']:.1f}%  PnL={final['pnl_r']:+.1f}R  avg_RR={final['avg_rr']}")

    # Сохраним полный grid для дальнейшего изучения
    out_dir = Path("signals")
    out_dir.mkdir(exist_ok=True)
    df1.to_csv(out_dir / "optimize_1_1_1_stage1_entry.csv", index=False)
    df2.to_csv(out_dir / "optimize_1_1_1_stage2_sl.csv", index=False)
    df3.to_csv(out_dir / "optimize_1_1_1_stage3_rr.csv", index=False)


if __name__ == "__main__":
    main()
