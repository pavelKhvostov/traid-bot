"""Этап 57: CSV позиций для стратегии 1.1.4 STRICT-L1 + do_match aligned.

Параметры:
  - 4-уровневый каскад FVG-1d/12h -> OB-4h/6h -> OB-1h/2h -> FVG-15m
  - STRICT: L4 в L1 zone проверяется явно
  - Filter: do_match aligned (LONG в discount, SHORT в premium от Daily Open)
  - entry=0.7 FVG, sl=0.35L/0.65S, min_sl=1%
  - RR=1.8

Output:
  - etap57_114_dom_positions_full.csv  (35 колонок, английские заголовки)
  - etap57_114_dom_positions_human.csv (16 колонок, русские заголовки)
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
from pathlib import Path
import time
import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_1 import detect_ob_pair, detect_fvg

SYMBOL = "BTCUSDT"
START_DATE = "2020-01-01"
ENTRY_PCT = 0.70
USER_SL_LONG = 0.35
USER_SL_SHORT = 0.65
RR = 1.8
MIN_SL_PCT = 1.0

LIFE_DAYS = {"1d": 14, "12h": 7, "6h": 4, "4h": 3,
              "2h": 1.5, "1h": 1, "15m": 0.5}
TF_HOURS = {"1d": 24, "12h": 12, "6h": 6, "4h": 4,
             "2h": 2, "1h": 1, "15m": 0.25}

OUT_DIR = Path("research/elements_study/output")
OUT_FULL = OUT_DIR / "etap57_114_dom_positions_full.csv"
OUT_HUMAN = OUT_DIR / "etap57_114_dom_positions_human.csv"


def compute_atr(df, period=14):
    high = df["high"]; low = df["low"]; pc = df["close"].shift(1)
    tr = pd.concat([(high-low),(high-pc).abs(),(low-pc).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def collect_obs(df, atr, tf):
    out = []
    for idx in range(2, len(df) - 1):
        ob = detect_ob_pair(df, idx)
        if ob is None: continue
        a = float(atr.iloc[idx])
        if pd.isna(a) or a <= 0: continue
        out.append({"tf": tf, "direction": ob.direction,
                     "bottom": ob.bottom, "top": ob.top, "atr": a,
                     "time": ob.cur_time, "idx": idx,
                     "prev_time": ob.prev_time})
    return out


def collect_fvgs(df, atr, tf):
    out = []
    for idx in range(2, len(df) - 1):
        f = detect_fvg(df, idx)
        if f is None: continue
        a = float(atr.iloc[idx])
        if pd.isna(a) or a <= 0: continue
        out.append({"tf": tf, "direction": f.direction,
                     "bottom": f.bottom, "top": f.top, "atr": a,
                     "time": f.c2_time, "idx": idx,
                     "c0_time": f.c0_time})
    return out


def zones_overlap(b1, t1, b2, t2):
    return not (t1 < b2 or t2 < b1)


def detect_114_strict(fvgs_top, obs_macro, obs_mid, fvgs_entry,
                       top_tf, macro_tf, mid_tf, entry_tf):
    setups = []
    top_td = pd.Timedelta(hours=TF_HOURS[top_tf])
    macro_td = pd.Timedelta(hours=TF_HOURS[macro_tf])
    mid_td = pd.Timedelta(hours=TF_HOURS[mid_tf])
    top_life = pd.Timedelta(days=LIFE_DAYS[top_tf])
    macro_life = pd.Timedelta(days=LIFE_DAYS[macro_tf])
    mid_life = pd.Timedelta(days=LIFE_DAYS[mid_tf])

    obs_macro_sorted = sorted(obs_macro, key=lambda x: x["time"])
    obs_mid_sorted = sorted(obs_mid, key=lambda x: x["time"])
    fvgs_entry_sorted = sorted(fvgs_entry, key=lambda x: x["time"])
    obs_macro_times = np.array([np.datetime64(z["time"].tz_localize(None) if z["time"].tz else z["time"])
                                  for z in obs_macro_sorted])
    obs_mid_times = np.array([np.datetime64(z["time"].tz_localize(None) if z["time"].tz else z["time"])
                                for z in obs_mid_sorted])
    fvgs_entry_times = np.array([np.datetime64(z["time"].tz_localize(None) if z["time"].tz else z["time"])
                                   for z in fvgs_entry_sorted])

    for fvg_top in fvgs_top:
        l1_confirm = fvg_top["time"] + top_td
        l1_end = fvg_top["time"] + top_life
        if l1_end <= l1_confirm: continue
        i0 = np.searchsorted(obs_macro_times, np.datetime64(
            l1_confirm.tz_localize(None) if l1_confirm.tz else l1_confirm), side="right")
        i1 = np.searchsorted(obs_macro_times, np.datetime64(
            l1_end.tz_localize(None) if l1_end.tz else l1_end), side="right")
        for mi in range(i0, i1):
            ob_macro = obs_macro_sorted[mi]
            if ob_macro["direction"] != fvg_top["direction"]: continue
            if not zones_overlap(ob_macro["bottom"], ob_macro["top"],
                                  fvg_top["bottom"], fvg_top["top"]): continue
            l2_confirm = ob_macro["time"] + macro_td
            l2_end = ob_macro["time"] + macro_life
            if l2_end <= l2_confirm: continue
            j0 = np.searchsorted(obs_mid_times, np.datetime64(
                l2_confirm.tz_localize(None) if l2_confirm.tz else l2_confirm), side="right")
            j1 = np.searchsorted(obs_mid_times, np.datetime64(
                l2_end.tz_localize(None) if l2_end.tz else l2_end), side="right")
            ob_mid_found = None
            for oj in range(j0, j1):
                ob_mid = obs_mid_sorted[oj]
                if ob_mid["direction"] != fvg_top["direction"]: continue
                if not zones_overlap(ob_mid["bottom"], ob_mid["top"],
                                      fvg_top["bottom"], fvg_top["top"]): continue
                if not zones_overlap(ob_mid["bottom"], ob_mid["top"],
                                      ob_macro["bottom"], ob_macro["top"]): continue
                ob_mid_found = ob_mid; break
            if ob_mid_found is None: continue

            l3_confirm = ob_mid_found["time"] + mid_td
            l3_end = ob_mid_found["time"] + mid_life
            if l3_end <= l3_confirm: continue
            k0 = np.searchsorted(fvgs_entry_times, np.datetime64(
                l3_confirm.tz_localize(None) if l3_confirm.tz else l3_confirm), side="right")
            k1 = np.searchsorted(fvgs_entry_times, np.datetime64(
                l3_end.tz_localize(None) if l3_end.tz else l3_end), side="right")
            fvg_entry_found = None
            for ek in range(k0, k1):
                f_entry = fvgs_entry_sorted[ek]
                if f_entry["direction"] != fvg_top["direction"]: continue
                if not zones_overlap(f_entry["bottom"], f_entry["top"],
                                      ob_mid_found["bottom"], ob_mid_found["top"]): continue
                if not zones_overlap(f_entry["bottom"], f_entry["top"],
                                      fvg_top["bottom"], fvg_top["top"]): continue
                fvg_entry_found = f_entry; break
            if fvg_entry_found is None: continue

            setups.append({
                "anchor_kind": "FVG", "anchor_tf": top_tf,
                "anchor_time": fvg_top["time"],
                "anchor_bot": fvg_top["bottom"], "anchor_top": fvg_top["top"],
                "macro_tf": macro_tf,
                "macro_time": ob_macro["time"],
                "macro_bot": ob_macro["bottom"], "macro_top": ob_macro["top"],
                "mid_tf": mid_tf,
                "mid_time": ob_mid_found["time"],
                "mid_bot": ob_mid_found["bottom"], "mid_top": ob_mid_found["top"],
                "trigger_time": fvg_entry_found["time"],
                "fvg_b": fvg_entry_found["bottom"],
                "fvg_t": fvg_entry_found["top"],
                "obh_b": ob_mid_found["bottom"],
                "obh_t": ob_mid_found["top"],
                "tf_minutes": 15,
                "year": fvg_entry_found["time"].year,
                "direction": fvg_entry_found["direction"],
                "signal_time": fvg_entry_found["time"],
            })
            break
    return setups


def build_orders(s):
    direction = s["direction"]
    fb, ft = s["fvg_b"], s["fvg_t"]
    obb, obt = s["obh_b"], s["obh_t"]
    fw = ft - fb
    if direction == "LONG":
        entry = fb + ENTRY_PCT * fw
        sl_lo = obb; sl_hi = fb
        sl = sl_lo + USER_SL_LONG * (sl_hi - sl_lo)
        if MIN_SL_PCT > 0:
            sl = min(sl, entry - entry * MIN_SL_PCT / 100)
        if sl >= entry: return None
    else:
        entry = ft - ENTRY_PCT * fw
        sl_hi = obt; sl_lo = ft
        sl = sl_hi - USER_SL_SHORT * (sl_hi - sl_lo)
        if MIN_SL_PCT > 0:
            sl = max(sl, entry + entry * MIN_SL_PCT / 100)
        if sl <= entry: return None
    return entry, sl


def simulate_safe(s, entry, sl, tp, df_1m, max_hold_days=7):
    """Returns: outcome, R, fill_ts, close_ts."""
    direction = s["direction"]
    risk = abs(entry - sl)
    if risk <= 0: return ("invalid", 0.0, None, None)
    tf_min = s["tf_minutes"]
    entry_window_start = s["signal_time"] + pd.Timedelta(minutes=tf_min)
    end_time = entry_window_start + pd.Timedelta(days=max_hold_days)
    et64 = np.datetime64(entry_window_start.tz_localize(None) if entry_window_start.tz else entry_window_start)
    ee64 = np.datetime64(end_time.tz_localize(None) if end_time.tz else end_time)

    i0 = np.searchsorted(df_1m.index.values, et64)
    i1 = np.searchsorted(df_1m.index.values, ee64)
    if i1 <= i0: return ("no_data", 0.0, None, None)
    h = df_1m["high"].values[i0:i1].astype(np.float64)
    l = df_1m["low"].values[i0:i1].astype(np.float64)

    if direction == "LONG":
        ent_idxs = np.where(l <= entry)[0]
        tp_pre_idxs = np.where(h >= tp)[0]
    else:
        ent_idxs = np.where(h >= entry)[0]
        tp_pre_idxs = np.where(l <= tp)[0]
    ent_idx = int(ent_idxs[0]) if ent_idxs.size else len(h) + 1
    tp_pre = int(tp_pre_idxs[0]) if tp_pre_idxs.size else len(h) + 1

    if tp_pre < ent_idx:
        return ("no_entry", 0.0, None, None)
    if ent_idx >= len(h):
        return ("not_filled", 0.0, None, None)

    fill_ts = pd.Timestamp(df_1m.index.values[i0 + ent_idx]).tz_localize("UTC")

    post_h = h[ent_idx:]; post_l = l[ent_idx:]
    if direction == "LONG":
        sl_m = post_l <= sl; tp_m = post_h >= tp
    else:
        sl_m = post_h >= sl; tp_m = post_l <= tp
    sl_first = int(np.argmax(sl_m)) if sl_m.any() else -1
    tp_first = int(np.argmax(tp_m)) if tp_m.any() else -1
    if sl_first == -1 and tp_first == -1:
        return ("open", 0.0, fill_ts, None)
    if sl_first == -1:
        close_ts = pd.Timestamp(df_1m.index.values[i0 + ent_idx + tp_first]).tz_localize("UTC")
        return ("win", abs(tp - entry) / risk, fill_ts, close_ts)
    if tp_first == -1:
        close_ts = pd.Timestamp(df_1m.index.values[i0 + ent_idx + sl_first]).tz_localize("UTC")
        return ("loss", -1.0, fill_ts, close_ts)
    if tp_first < sl_first:
        close_ts = pd.Timestamp(df_1m.index.values[i0 + ent_idx + tp_first]).tz_localize("UTC")
        return ("win", abs(tp - entry) / risk, fill_ts, close_ts)
    close_ts = pd.Timestamp(df_1m.index.values[i0 + ent_idx + sl_first]).tz_localize("UTC")
    return ("loss", -1.0, fill_ts, close_ts)


OUTCOME_RU = {
    "win":        "PROFIT (TP hit)",
    "loss":       "LOSS (SL hit)",
    "open":       "STILL OPEN",
    "not_filled": "no entry (limit not filled)",
    "no_entry":   "skipped (TP hit before entry)",
    "no_data":    "no data",
    "invalid":    "invalid setup",
}

OUTCOME_RU2 = {
    "win":        "ПРИБЫЛЬ (TP)",
    "loss":       "УБЫТОК (SL)",
    "open":       "осталась открытой",
    "not_filled": "лимит не заполнился",
    "no_entry":   "пропуск (TP до entry)",
    "no_data":    "нет данных",
    "invalid":    "невалидный сетап",
}


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
    df_15m = compose_from_base(df_1m, "15m")  # composed (avoid 2022 native gap)

    cutoff = pd.Timestamp(START_DATE, tz="UTC")
    df_1d = df_1d[df_1d.index >= cutoff].copy()
    df_4h = df_4h[df_4h.index >= cutoff].copy()
    df_1h = df_1h[df_1h.index >= cutoff].copy()
    df_12h = df_12h[df_12h.index >= cutoff].copy()
    df_6h = df_6h[df_6h.index >= cutoff].copy()
    df_2h = df_2h[df_2h.index >= cutoff].copy()
    df_15m = df_15m[df_15m.index >= cutoff].copy()
    df_1m = df_1m[df_1m.index >= cutoff]

    for tf, df in [("1d", df_1d), ("12h", df_12h), ("6h", df_6h),
                    ("4h", df_4h), ("2h", df_2h), ("1h", df_1h),
                    ("15m", df_15m)]:
        df["atr14"] = compute_atr(df, 14)
    print(f"  years: {(df_1d.index[-1] - df_1d.index[0]).days/365:.2f}")

    print("[INFO] collect zones")
    fvgs_1d = collect_fvgs(df_1d, df_1d["atr14"], "1d")
    fvgs_12h = collect_fvgs(df_12h, df_12h["atr14"], "12h")
    obs_4h = collect_obs(df_4h, df_4h["atr14"], "4h")
    obs_6h = collect_obs(df_6h, df_6h["atr14"], "6h")
    obs_1h = collect_obs(df_1h, df_1h["atr14"], "1h")
    obs_2h = collect_obs(df_2h, df_2h["atr14"], "2h")
    fvgs_15m = collect_fvgs(df_15m, df_15m["atr14"], "15m")

    print("[INFO] STRICT-L1 detect 1.1.4 cascades")
    all_setups = []
    for top_tf, top_zones in [("1d", fvgs_1d), ("12h", fvgs_12h)]:
        for macro_tf, macro_zones in [("4h", obs_4h), ("6h", obs_6h)]:
            for mid_tf, mid_zones in [("1h", obs_1h), ("2h", obs_2h)]:
                chains = detect_114_strict(top_zones, macro_zones, mid_zones,
                                            fvgs_15m, top_tf, macro_tf, mid_tf, "15m")
                all_setups.extend(chains)
    seen = set(); unique = []
    for s in all_setups:
        key = (s["signal_time"], s["direction"], round(s["fvg_b"], 2), round(s["fvg_t"], 2))
        if key in seen: continue
        seen.add(key); unique.append(s)
    print(f"  total chains: {len(all_setups)}, deduped: {len(unique)}")

    print("[INFO] simulate + filter by do_match aligned")
    rows = []
    skipped_dom = 0
    for s in unique:
        tup = build_orders(s)
        if tup is None: continue
        entry, sl = tup

        # do_match check
        ts = s["signal_time"]
        idx_d = df_1d.index.searchsorted(ts, side="right") - 1
        if idx_d < 0:
            do = None
        else:
            do = float(df_1d["open"].iloc[idx_d])
        if do is None or pd.isna(do):
            skipped_dom += 1
            continue
        if s["direction"] == "LONG":
            do_aligned = entry < do
            do_pos = "discount" if do_aligned else ("premium" if entry > do else "mid")
        else:
            do_aligned = entry > do
            do_pos = "premium" if do_aligned else ("discount" if entry < do else "mid")
        if not do_aligned:
            skipped_dom += 1
            continue

        # Simulate
        risk = abs(entry - sl)
        tp = entry + RR * risk if s["direction"] == "LONG" else entry - RR * risk
        start_time = s["signal_time"] + pd.Timedelta(minutes=15)
        outcome, R, fill_ts, close_ts = simulate_safe(s, entry, sl, tp, df_1m)

        risk_pct = risk / entry * 100
        target_pct = RR * risk_pct
        if outcome == "win":
            actual_R = R; actual_pnl_pct = target_pct; exit_price = tp
        elif outcome == "loss":
            actual_R = -1.0; actual_pnl_pct = -risk_pct; exit_price = sl
        else:
            actual_R = 0.0; actual_pnl_pct = 0.0; exit_price = None

        hold_h = ((close_ts - start_time).total_seconds() / 3600
                    if close_ts is not None else None)
        time_to_fill_h = ((fill_ts - start_time).total_seconds() / 3600
                           if fill_ts is not None else None)

        rows.append({
            "trade_id": len(rows) + 1,
            "year": s["year"],
            "month": s["signal_time"].month,
            "direction": s["direction"],
            # Times
            "anchor_time_utc": s["anchor_time"].strftime("%Y-%m-%d %H:%M"),
            "macro_time_utc": s["macro_time"].strftime("%Y-%m-%d %H:%M"),
            "mid_time_utc": s["mid_time"].strftime("%Y-%m-%d %H:%M"),
            "trigger_time_utc": s["trigger_time"].strftime("%Y-%m-%d %H:%M"),
            "entry_window_start_utc": start_time.strftime("%Y-%m-%d %H:%M"),
            "fill_time_utc": fill_ts.strftime("%Y-%m-%d %H:%M") if fill_ts is not None else "",
            "exit_time_utc": close_ts.strftime("%Y-%m-%d %H:%M") if close_ts is not None else "",
            # Cascade meta
            "anchor_tf": s["anchor_tf"],
            "macro_tf": s["macro_tf"],
            "mid_tf": s["mid_tf"],
            # Zones
            "anchor_fvg_bot": round(s["anchor_bot"], 2),
            "anchor_fvg_top": round(s["anchor_top"], 2),
            "anchor_fvg_height_pct": round((s["anchor_top"] - s["anchor_bot"]) / s["anchor_bot"] * 100, 2),
            "macro_ob_bot": round(s["macro_bot"], 2),
            "macro_ob_top": round(s["macro_top"], 2),
            "mid_ob_bot": round(s["mid_bot"], 2),
            "mid_ob_top": round(s["mid_top"], 2),
            "fvg_15m_bot": round(s["fvg_b"], 2),
            "fvg_15m_top": round(s["fvg_t"], 2),
            "fvg_15m_height_pct": round((s["fvg_t"] - s["fvg_b"]) / s["fvg_b"] * 100, 3),
            # Daily Open + ICT positioning
            "daily_open": round(do, 2),
            "do_pos": do_pos,
            # Orders
            "entry_price": round(entry, 2),
            "sl_price": round(sl, 2),
            "tp_price": round(tp, 2),
            "risk_pct": round(risk_pct, 3),
            "target_pct": round(target_pct, 3),
            "rr_target": RR,
            # Result
            "outcome_code": outcome,
            "outcome_en": OUTCOME_RU.get(outcome, outcome),
            "result_R": round(actual_R, 3),
            "result_pnl_pct": round(actual_pnl_pct, 3),
            "exit_price": round(exit_price, 2) if exit_price is not None else "",
            "time_to_fill_hours": round(time_to_fill_h, 1) if time_to_fill_h is not None else "",
            "hold_hours": round(hold_h, 1) if hold_h is not None else "",
            "hold_days": round(hold_h / 24, 2) if hold_h is not None else "",
        })

    df_full = pd.DataFrame(rows)

    # cumulative R / pnl
    cum = 0.0; cum_p = 0.0
    cum_R_list = []; cum_p_list = []
    for _, row in df_full.iterrows():
        if row["outcome_code"] in ("win", "loss"):
            cum += row["result_R"]
            cum_p += row["result_pnl_pct"]
        cum_R_list.append(round(cum, 2))
        cum_p_list.append(round(cum_p, 2))
    df_full["cumulative_R"] = cum_R_list
    df_full["cumulative_pnl_pct"] = cum_p_list

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df_full.to_csv(OUT_FULL, index=False, encoding="utf-8-sig")
    print(f"\n[OK] full CSV: {OUT_FULL}")
    print(f"     {len(df_full)} positions, {len(df_full.columns)} columns")

    # Human version (Russian)
    cols_human = [
        ("trade_id", "№"),
        ("anchor_time_utc", "Якорь FVG-1d/12h (время)"),
        ("anchor_tf", "ТФ якоря"),
        ("trigger_time_utc", "Триггер FVG-15m (время)"),
        ("direction", "Направление"),
        ("entry_price", "Вход"),
        ("sl_price", "Стоп"),
        ("tp_price", "Цель"),
        ("daily_open", "Daily Open"),
        ("do_pos", "Где entry"),
        ("risk_pct", "Риск %"),
        ("outcome_code", "Результат (код)"),
        ("result_R", "R"),
        ("result_pnl_pct", "Прибыль %"),
        ("hold_hours", "Удержание ч"),
        ("cumulative_R", "Накопит. R"),
    ]
    df_human = df_full[[c for c, _ in cols_human]].copy()
    # Локализуем outcome
    df_human["outcome_code"] = df_full["outcome_code"].map(OUTCOME_RU2).fillna(df_full["outcome_code"])
    # Локализуем direction
    df_human["direction"] = df_full["direction"].map({"LONG": "ЛОНГ", "SHORT": "ШОРТ"})
    df_human["do_pos"] = df_full["do_pos"].map({"discount": "ниже DO (discount)",
                                                   "premium": "выше DO (premium)",
                                                   "mid": "на DO"})
    df_human.columns = [name for _, name in cols_human]
    df_human.to_csv(OUT_HUMAN, index=False, encoding="utf-8-sig")
    print(f"\n[OK] human CSV: {OUT_HUMAN}")
    print(f"     {len(df_human)} positions, {len(df_human.columns)} columns")

    # Summary
    print("\n" + "=" * 70)
    print("СВОДКА")
    print("=" * 70)
    closed = df_full[df_full["outcome_code"].isin(["win", "loss"])]
    print(f"  Найдено сетапов 1.1.4 STRICT (всего): {len(unique) - skipped_dom + len(df_full)}")
    print(f"  Отрезано do_match counter:           {skipped_dom}")
    print(f"  Прошло do_match aligned:             {len(df_full)}")
    print(f"  Закрытых сделок:                     {len(closed)}")
    print(f"     прибыльных:                       {(closed['outcome_code'] == 'win').sum()}")
    print(f"     убыточных:                        {(closed['outcome_code'] == 'loss').sum()}")
    n_no_entry = (df_full["outcome_code"] == "no_entry").sum()
    n_no_fill = (df_full["outcome_code"] == "not_filled").sum()
    n_open = (df_full["outcome_code"] == "open").sum()
    print(f"     no_entry (TP до entry):           {n_no_entry}")
    print(f"     not_filled (limit не сработал):   {n_no_fill}")
    print(f"     осталось открытых:                {n_open}")
    if len(closed) > 0:
        wr = (closed["outcome_code"] == "win").mean() * 100
        total_R = closed["result_R"].sum()
        years = (df_1d.index[-1] - df_1d.index[0]).days / 365
        print(f"\n  WinRate:           {wr:.1f}%")
        print(f"  Суммарный R:       {total_R:+.1f}")
        print(f"  В % (риск 1%):     {total_R*1:+.0f}% за {years:.2f} лет")
        print(f"  Среднее удержание: {closed['hold_hours'].astype(float).mean():.1f}ч")

    print("\n[TIME] {:.1f}s".format(time.time() - t0))


if __name__ == "__main__":
    main()
