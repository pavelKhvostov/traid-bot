"""Этап C: OOS validation на ETH и SOL.

Применяем найденную best config:
  - entry=0.5 mid FVG
  - sl=asym (LONG=0.35 inside, SHORT=0.65 inside)
  - RR=2.5
  - filters: TAM + poi_normal + ob_med

Если edge универсальный (~R/tr ≥ 0.5 на ETH/SOL) — production кандидат.
Если нет — BTC-specific.
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
from etap_35_strategy_111_forensic import (
    asvk_adjusted_rsi, asvk_dynamic_levels, money_flow_ha,
    money_hands_bw2,
)
from strategies.strategy_1_1_7 import detect_strategy_1_1_7_signals


def session_label(hour):
    if hour < 7: return "Asia"
    if hour < 12: return "London"
    if hour < 17: return "NY"
    return "off"


def asvk_zone_at(ema3, above, below, ts):
    idx = ema3.index.searchsorted(ts, side="right") - 1
    if idx < 1:
        return "na"
    # safe lookup (idx-1).
    e = ema3.iloc[idx - 1]
    a = above.iloc[idx - 1]
    b = below.iloc[idx - 1]
    if pd.isna(e) or pd.isna(a) or pd.isna(b):
        return "na"
    if e > a: return "red"
    if e > 50 + (a - 50) * 0.5: return "yellow_OB"
    if e < b: return "green"
    if e < 50 - (50 - b) * 0.5: return "yellow_OS"
    return "neutral"


def mh_color_at(bw2, sma14, ts):
    idx = bw2.index.searchsorted(ts, side="right") - 1
    if idx < 1:
        return "na"
    v = bw2.iloc[idx - 1]
    s = sma14.iloc[idx - 1]
    if pd.isna(v) or pd.isna(s):
        return "na"
    if v > 0:
        return "green" if v >= s else "grey_from_green"
    if v < 0:
        return "red" if v <= s else "grey_from_red"
    return "neutral"


def main():
    print("[INFO] OOS validation: ETH, SOL")
    print("Config: entry=0.5, sl=asym, RR=2.5, filters=TAM+poi_normal+ob_med\n")

    for symbol in ["ETHUSDT", "SOLUSDT"]:
        print("=" * 72)
        print(f"  SYMBOL = {symbol}")
        print("=" * 72)

        try:
            df_4h = load_df(symbol, "4h")
            df_1h = load_df(symbol, "1h")
            df_15m = load_df(symbol, "15m")
            df_1m = load_df(symbol, "1m")
        except Exception as e:
            print(f"  [SKIP] no data: {e}")
            continue

        df_2h = compose_from_base(df_1h, "2h")
        df_20m = compose_from_base(df_15m, "20m")
        df_1d = load_df(symbol, "1d")
        df_12h = compose_from_base(df_1h, "12h")

        # cutoff 2310 days (6.3y)
        today = pd.Timestamp.utcnow().normalize()
        if today.tz is None:
            today = today.tz_localize("UTC")
        cutoff = today - pd.Timedelta(days=2310)
        df_4h_f = df_4h[df_4h.index >= cutoff]
        print(f"  data: 4h={len(df_4h_f)} 1h={len(df_1h)} 15m={len(df_15m)} 1m={len(df_1m)}")
        print(f"  range: {df_4h.index[0]} .. {df_4h.index[-1]}")

        print("  detecting signals...")
        sigs = detect_strategy_1_1_7_signals(
            df_4h=df_4h_f, df_1h=df_1h, df_2h=df_2h,
            df_15m=df_15m, df_20m=df_20m, verbose=False,
        )
        print(f"  raw signals: {len(sigs)}")
        if not sigs:
            continue

        # Pre-compute indicators
        ema3_4h = asvk_adjusted_rsi(df_4h["close"])
        a_4h, b_4h = asvk_dynamic_levels(ema3_4h, 200)
        bw2_4h, sma14_4h = money_hands_bw2(df_4h)

        ts_arr = df_1m.index.values
        h_arr = df_1m["high"].to_numpy(dtype=float)
        l_arr = df_1m["low"].to_numpy(dtype=float)
        rr = 2.5

        def simulate(direction, entry, sl, tp, start_time, timeout_days=14):
            st = start_time.tz_localize(None) if start_time.tz else start_time
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
                return ("loss", -1.0) if si <= ti else ("win", (tp-entry)/risk)
            else:
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
                return ("loss", -1.0) if si <= ti else ("win", (entry-tp)/risk)

        rows = []
        for s in sigs:
            ts = s["fvg_c2_time"]
            if not isinstance(ts, pd.Timestamp):
                ts = pd.Timestamp(ts)
            if ts.tz is None:
                ts = ts.tz_localize("UTC")

            # Features
            asvk_4h_v = asvk_zone_at(ema3_4h, a_4h, b_4h, ts)
            mh_4h = mh_color_at(bw2_4h, sma14_4h, ts)
            hour = ts.hour
            weekday = ts.day_name()
            session = session_label(hour)

            # Filter TAM
            tam_ok = (weekday != "Sunday"
                       and session != "London"
                       and asvk_4h_v != "red"
                       and mh_4h not in ["green", "grey_from_green"])

            # Structural
            fb, ft = s["fvg_zone"]
            ob_b, ob_t = s["ob_zone"]
            poi_b, poi_t = s["poi_zone"]
            poi_h_pct = (poi_t - poi_b) / poi_b * 100
            ob_d_pct = (ob_t - ob_b) / ob_b * 100
            poi_ok = 0.5 <= poi_h_pct < 1.5
            ob_ok = 0.5 <= ob_d_pct < 1.5

            d = s["direction"]
            if d == "LONG":
                entry = fb + 0.5 * (ft - fb)
                sl = ob_b + 0.35 * (fb - ob_b)
                if sl >= entry: continue
                tp = entry + rr * (entry - sl)
            else:
                entry = ft - 0.5 * (ft - fb)
                sl = ob_t - 0.65 * (ob_t - ft)
                if sl <= entry: continue
                tp = entry - rr * (sl - entry)

            out, r = simulate(d, entry, sl, tp, ts)
            rows.append({
                "ts": ts, "direction": d, "out": out, "R": r,
                "TAM": tam_ok, "poi_ok": poi_ok, "ob_ok": ob_ok,
            })

        if not rows:
            print("  [WARN] нет setups после фильтра")
            continue

        sdf = pd.DataFrame(rows)
        print(f"  total simulated: {len(sdf)}")

        # Apply filter combinations
        for combo_name, mask in [
            ("baseline (all)", pd.Series(True, index=sdf.index)),
            ("TAM", sdf["TAM"]),
            ("TAM+poi_normal", sdf["TAM"] & sdf["poi_ok"]),
            ("TAM+ob_med", sdf["TAM"] & sdf["ob_ok"]),
            ("TAM+poi+ob_med", sdf["TAM"] & sdf["poi_ok"] & sdf["ob_ok"]),
        ]:
            sub = sdf[mask]
            cl = sub[sub["out"].isin(["win", "loss"])]
            n = len(sub)
            n_cl = len(cl)
            wr = (cl["out"] == "win").sum() / n_cl * 100 if n_cl else 0
            total = sub["R"].sum()
            r_tr = total / n_cl if n_cl else 0
            print(f"    {combo_name:<22} n={n:<4} n_cl={n_cl:<4} "
                  f"WR={wr:<5.1f}% total={total:+7.1f} R/tr={r_tr:+7.3f}")


if __name__ == "__main__":
    main()
