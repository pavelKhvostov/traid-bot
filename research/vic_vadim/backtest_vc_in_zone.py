"""Backtest VC (FVG-15m/20m в SWEPT OB-1h/2h) внутри зоны i-свечи 12h
для финальной выборки HH(Core) + LL(Core ∩ Hull-1h GREEN) по BTC+ETH+SOL.

Окно поиска VC после close(i) — 24h (2 фрейма 12h).
Entry/SL/TP — canon 1.1.1: entry=mid(FVG), SL=OB_bottom+0.15*depth, RR=2.2.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from strategies.strategy_1_1_1 import (
    OBZone, FVGZone,
    detect_ob_pair, detect_fvg, zones_overlap, find_first_fvg_in_range,
)

ENTRY_PCT = 0.80
SL_PCT = 0.35
TIME_STOP_BARS_12H = 10
from research.asvk_trend_line.plot_asvk_trend_line import hma  # для Hull-1h
from research.vic_vadim.optimize_mlt_sol import (
    compose_htf, find_ob_zones, find_fractals,
    zone_sweep_flags, fractal_sweep_flags, maxv_all_12h,
    HTF_LIST,
)

ASSETS = [
    ("BTCUSDT", ROOT / "data" / "BTCUSDT_1m_vic_vadim.csv"),
    ("ETHUSDT", ROOT / "data" / "ETHUSDT_1m_vic_vadim.csv"),
    ("SOLUSDT", ROOT / "data" / "SOLUSDT_1m_vic_vadim.csv"),
]
MLT = 45
LTF_MAXV = 16  # ceil(43200/45/60) = 16
HMA_LEN = 78
RR = 2.2
WINDOW_HOURS = 24


def load_1m(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def resample_tf(df_1m: pd.DataFrame, freq: str) -> pd.DataFrame:
    return df_1m.resample(freq, origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna(subset=["close"])


def hull_color_1h(df_1h: pd.DataFrame) -> pd.Series:
    """GREEN если close > HMA-78, RED иначе."""
    h = hma(df_1h["close"], HMA_LEN)
    return (df_1h["close"] > h).astype(int)  # 1=GREEN, 0=RED


def compute_core_signals(df_1m: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    """Считает Core HH/LL флаги (на 12h-индексе) с mlt=45 / LTF=16m.

    Возвращает (df_12h, hh_core_mask, ll_core_mask).
    """
    df_1m_naive = df_1m.copy()
    df_1m_naive.index.name = None
    htf_dfs = {tf: compose_htf(df_1m, freq) for tf, freq in HTF_LIST}
    df_12h = htf_dfs["12h"]

    all_ob, all_fract = [], []
    for tf, df_tf in htf_dfs.items():
        all_ob += find_ob_zones(df_tf)
        all_fract += find_fractals(df_tf)
    c1_fh = fractal_sweep_flags(df_12h, all_fract, "FH")
    c1_fl = fractal_sweep_flags(df_12h, all_fract, "FL")
    c1_obs = zone_sweep_flags(df_12h, all_ob, "SHORT")
    c1_obl = zone_sweep_flags(df_12h, all_ob, "LONG")

    maxv = maxv_all_12h(df_1m_naive, df_12h, LTF_MAXV)
    h12 = df_12h["high"].to_numpy(); l12 = df_12h["low"].to_numpy(); c12 = df_12h["close"].to_numpy()
    n = len(df_12h)
    sw_s = np.zeros(n, dtype=bool); sw_l = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if np.isnan(maxv[i-1]): continue
        if h12[i] > maxv[i-1] and c12[i] < maxv[i-1]: sw_s[i] = True
        if l12[i] < maxv[i-1] and c12[i] > maxv[i-1]: sw_l[i] = True

    hh_core = (c1_fh | c1_obs) & sw_s
    ll_core = (c1_fl | c1_obl) & sw_l
    return df_12h, hh_core, ll_core


def check_swept_ob(df_top: pd.DataFrame, prev_idx: int, cur_idx: int, direction: str) -> bool:
    """SWEPT для OB-htf: ликвидность n1/n2 свечей до prev пробита парой prev/cur."""
    if prev_idx < 2:
        return False
    c1_low = float(df_top.iloc[prev_idx]["low"])
    c2_low = float(df_top.iloc[cur_idx]["low"])
    c1_high = float(df_top.iloc[prev_idx]["high"])
    c2_high = float(df_top.iloc[cur_idx]["high"])
    n1_low = float(df_top.iloc[prev_idx - 1]["low"])
    n2_low = float(df_top.iloc[prev_idx - 2]["low"])
    n1_high = float(df_top.iloc[prev_idx - 1]["high"])
    n2_high = float(df_top.iloc[prev_idx - 2]["high"])
    if direction == "LONG":
        return min(c1_low, c2_low) < min(n1_low, n2_low)
    return max(c1_high, c2_high) > max(n1_high, n2_high)


def find_vc_for_i(
    i_close: pd.Timestamp, i_low: float, i_high: float, direction: str,
    df_1h: pd.DataFrame, df_2h: pd.DataFrame,
    df_15m: pd.DataFrame, df_20m: pd.DataFrame,
) -> dict | None:
    """Найти первый SWEPT OB-1h/2h с nested FVG-15m/20m в окне 24h."""
    search_start = i_close
    search_end = i_close + pd.Timedelta(hours=WINDOW_HOURS)

    candidates = []
    for tf_label, df_top, df_ltf, tf_min, htf_min in (
        ("1h", df_1h, df_15m, 15, 60),
        ("2h", df_2h, df_20m, 20, 120),
    ):
        # OB pairs (prev_idx, cur_idx) where cur_time в окне
        idx = df_top.index
        sp = int(idx.searchsorted(search_start, side="left"))
        ep = int(idx.searchsorted(search_end, side="right"))
        for k in range(max(sp, 1), min(ep, len(idx))):
            ob = detect_ob_pair(df_top, k)
            if ob is None or ob.direction != direction:
                continue
            if not zones_overlap(ob.bottom, ob.top, i_low, i_high):
                continue
            if not check_swept_ob(df_top, k - 1, k, direction):
                continue
            # nested FVG search
            fvg_end = ob.cur_time + pd.Timedelta(minutes=htf_min - tf_min)
            if fvg_end > search_end:
                fvg_end = search_end
            fvg = find_first_fvg_in_range(df_ltf, ob.prev_time, fvg_end, direction, ob.bottom, ob.top)
            if fvg is None:
                continue
            candidates.append({
                "ob_tf": tf_label, "ob": ob, "fvg_tf": f"{tf_min}m", "fvg": fvg, "tf_min": tf_min,
            })

    if not candidates:
        return None
    # earliest by fvg.c2_time
    candidates.sort(key=lambda c: c["fvg"].c2_time)
    return candidates[0]


def simulate(vc: dict, direction: str, df_1m: pd.DataFrame) -> dict:
    """vault-optimum: entry=0.80*FVG_width внутрь FVG, SL=0.35 от OB_edge к FVG_edge,
    no_entry logic (если TP до entry — отмена), таймстоп TIME_STOP_BARS_12H × 12h."""
    fvg = vc["fvg"]; ob = vc["ob"]
    fvg_b, fvg_t = fvg.bottom, fvg.top
    obh_b, obh_t = ob.bottom, ob.top
    fw = fvg_t - fvg_b
    if direction == "LONG":
        entry = fvg_b + ENTRY_PCT * fw
        sl = obh_b + SL_PCT * (fvg_b - obh_b)
        if sl >= entry:
            return {"outcome": "bad_risk"}
        risk = entry - sl
        tp = entry + RR * risk
    else:
        entry = fvg_t - ENTRY_PCT * fw
        sl = obh_t - SL_PCT * (obh_t - fvg_t)
        if sl <= entry:
            return {"outcome": "bad_risk"}
        risk = sl - entry
        tp = entry - RR * risk

    fill_start = fvg.c2_time + pd.Timedelta(minutes=vc["tf_min"])
    stop_time = fill_start + pd.Timedelta(hours=12 * TIME_STOP_BARS_12H)
    fwd = df_1m[(df_1m.index >= fill_start) & (df_1m.index <= stop_time)]
    if fwd.empty:
        return {"outcome": "no_data"}

    h_arr = fwd["high"].values; l_arr = fwd["low"].values
    n = len(fwd)
    base = {"entry": entry, "sl": sl, "tp": tp, "risk_pct": risk/entry*100}

    # no_entry: индекс первого касания TP и entry
    if direction == "LONG":
        entry_idxs = np.where(l_arr <= entry)[0]
        tp_idxs = np.where(h_arr >= tp)[0]
    else:
        entry_idxs = np.where(h_arr >= entry)[0]
        tp_idxs = np.where(l_arr <= tp)[0]
    entry_idx = int(entry_idxs[0]) if entry_idxs.size else n + 1
    tp_pre_idx = int(tp_idxs[0]) if tp_idxs.size else n + 1
    if tp_pre_idx < entry_idx:
        return {**base, "outcome": "no_entry"}
    if entry_idx >= n:
        return {**base, "outcome": "not_filled"}

    # SL/TP scan после fill, до stop_time
    post_l = l_arr[entry_idx:]; post_h = h_arr[entry_idx:]
    if direction == "LONG":
        sl_mask = post_l <= sl; tp_mask = post_h >= tp
    else:
        sl_mask = post_h >= sl; tp_mask = post_l <= tp
    sl_first = int(np.argmax(sl_mask)) if sl_mask.any() else -1
    tp_first = int(np.argmax(tp_mask)) if tp_mask.any() else -1
    if sl_first == -1 and tp_first == -1:
        return {**base, "outcome": "timeout", "r": 0.0}
    if sl_first == -1:
        return {**base, "outcome": "win", "r": RR}
    if tp_first == -1:
        return {**base, "outcome": "loss", "r": -1.0}
    if tp_first < sl_first:
        return {**base, "outcome": "win", "r": RR}
    return {**base, "outcome": "loss", "r": -1.0}


def process_asset(symbol: str, csv_path: Path) -> dict:
    print(f"\n=== {symbol} ===", flush=True)
    print("  load 1m...", flush=True)
    df_1m = load_1m(csv_path)

    print("  resample TFs...", flush=True)
    df_1h = resample_tf(df_1m, "1H")
    df_2h = resample_tf(df_1m, "2H")
    df_15m = resample_tf(df_1m, "15min")
    df_20m = resample_tf(df_1m, "20min")

    print("  compute Hull-1h color...", flush=True)
    hull_g = hull_color_1h(df_1h)  # 1=GREEN

    print("  compute Core 12h signals...", flush=True)
    df_12h, hh_core, ll_core = compute_core_signals(df_1m)

    # Hull C: для LL берём только те 12h-bars где Hull-1h GREEN на close_i
    print("  apply Hull C (LL only)...", flush=True)
    ll_filtered = np.zeros_like(ll_core)
    for i in range(len(df_12h)):
        if not ll_core[i]:
            continue
        close_i = df_12h.index[i] + pd.Timedelta(hours=12)
        h_idx = int(df_1h.index.searchsorted(close_i, side="right")) - 1
        if h_idx < 0 or h_idx >= len(df_1h):
            continue
        if hull_g.iloc[h_idx] == 1:
            ll_filtered[i] = True

    print(f"  Core HH n={int(hh_core.sum())}; Core LL n={int(ll_core.sum())} → LL Hull C n={int(ll_filtered.sum())}", flush=True)

    # Перечень i-свечей: HH (Core) → SHORT trade, LL (Hull C) → LONG trade
    signals_i = []
    h12 = df_12h["high"].to_numpy(); l12 = df_12h["low"].to_numpy()
    for i in range(len(df_12h)):
        if hh_core[i]:
            signals_i.append((i, "SHORT"))
        if ll_filtered[i]:
            signals_i.append((i, "LONG"))
    print(f"  total i-bars to backtest: {len(signals_i)}", flush=True)

    rows = []
    for k, (i, direction) in enumerate(signals_i):
        i_time = df_12h.index[i]
        i_close = i_time + pd.Timedelta(hours=12)
        i_low, i_high = float(l12[i]), float(h12[i])
        vc = find_vc_for_i(i_close, i_low, i_high, direction, df_1h, df_2h, df_15m, df_20m)
        row = {"symbol": symbol, "i_time": i_time, "direction": direction,
               "i_low": i_low, "i_high": i_high}
        if vc is None:
            row.update({"outcome": "no_vc", "ob_tf": "", "fvg_tf": ""})
        else:
            sim = simulate(vc, direction, df_1m)
            row.update({
                "ob_tf": vc["ob_tf"], "fvg_tf": vc["fvg_tf"],
                "ob_bottom": vc["ob"].bottom, "ob_top": vc["ob"].top,
                "fvg_bottom": vc["fvg"].bottom, "fvg_top": vc["fvg"].top,
                "fvg_c2_time": vc["fvg"].c2_time,
                **{k2: v2 for k2, v2 in sim.items()},
            })
        rows.append(row)
        if (k+1) % 50 == 0:
            print(f"    {k+1}/{len(signals_i)} processed", flush=True)

    df_res = pd.DataFrame(rows)
    out_path = ROOT / "signals" / f"vc_in_zone_{symbol}.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df_res.to_csv(out_path, index=False)
    print(f"  saved: {out_path}", flush=True)

    # Сводка
    total = len(df_res)
    no_vc = int((df_res["outcome"] == "no_vc").sum())
    no_entry = int((df_res["outcome"] == "no_entry").sum())
    nf = int((df_res["outcome"] == "not_filled").sum())
    to = int((df_res["outcome"] == "timeout").sum())
    win = int((df_res["outcome"] == "win").sum())
    loss = int((df_res["outcome"] == "loss").sum())
    closed = win + loss
    wr = win / closed * 100 if closed else 0
    sum_r = win * RR - loss * 1.0
    print(f"  TOTAL={total}  no_vc={no_vc}  no_entry={no_entry}  not_filled={nf}  timeout={to}  closed={closed}  WR={wr:.1f}%  ΣR={sum_r:+.2f}", flush=True)
    return {"symbol": symbol, "total": total, "no_vc": no_vc, "no_entry": no_entry, "nf": nf, "to": to,
            "win": win, "loss": loss, "wr": wr, "sum_r": sum_r}


def main():
    summaries = []
    for symbol, path in ASSETS:
        s = process_asset(symbol, path)
        summaries.append(s)
    print("\n=== TRIPLE SUMMARY ===")
    for s in summaries:
        print(f"  {s['symbol']}: total={s['total']}  no_vc={s['no_vc']}  no_entry={s['no_entry']}  not_filled={s['nf']}  "
              f"timeout={s['to']}  closed={s['win']+s['loss']}  WR={s['wr']:.1f}%  ΣR={s['sum_r']:+.2f}")
    t_total = sum(s["total"] for s in summaries)
    t_win = sum(s["win"] for s in summaries)
    t_loss = sum(s["loss"] for s in summaries)
    t_no_vc = sum(s["no_vc"] for s in summaries)
    t_ne = sum(s["no_entry"] for s in summaries)
    t_nf = sum(s["nf"] for s in summaries)
    t_to = sum(s["to"] for s in summaries)
    t_closed = t_win + t_loss
    t_wr = t_win / t_closed * 100 if t_closed else 0
    t_r = t_win * RR - t_loss
    print(f"  Σ:        total={t_total}  no_vc={t_no_vc}  no_entry={t_ne}  not_filled={t_nf}  timeout={t_to}  "
          f"closed={t_closed}  WR={t_wr:.1f}%  ΣR={t_r:+.2f}")


if __name__ == "__main__":
    main()
