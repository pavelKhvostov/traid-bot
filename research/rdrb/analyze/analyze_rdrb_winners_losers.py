"""Анализ — что общего у WIN vs LOSS RDRB сигналов.

Считаем 15+ структурных и контекстных features для каждого сигнала,
сравниваем распределение между winners и losers, ищем фичи с самой большой
сепарацией и потенциальным фильтром.

Параметры trade'а: entry=0.95, sl=0.35, RR=2.2 (best из grid).
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

import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_rdrb import detect_strategy_rdrb_signals

DAYS_BACK = 1095
SYMBOL = "BTCUSDT"
RR = 2.2
ENTRY_PCT = 0.95
SL_PCT = 0.35


def simulate_one(sig: dict, df_1m: pd.DataFrame) -> tuple[str, float, float, float]:
    """Возвращает (outcome, entry, sl, tp)."""
    direction = sig["direction"]
    fvg_b, fvg_t = sig["fvg_zone"]
    obh_b, obh_t = sig["ob_htf_zone"]
    rdrb_b, rdrb_t = sig["rdrb_zone"]
    if direction == "LONG":
        entry = fvg_b + ENTRY_PCT * (fvg_t - fvg_b)
        sl = obh_b + SL_PCT * (rdrb_b - obh_b)
        if sl >= entry:
            return "skipped", 0, 0, 0
        risk = entry - sl
        tp = entry + risk * RR
    else:
        entry = fvg_t - ENTRY_PCT * (fvg_t - fvg_b)
        sl = obh_t + SL_PCT * (rdrb_t - obh_t)
        if sl <= entry:
            return "skipped", 0, 0, 0
        risk = sl - entry
        tp = entry - risk * RR

    tf_minutes = 15 if sig["fvg_tf"] == "15m" else 20
    fill_scan_start = sig["signal_time"] + pd.Timedelta(minutes=tf_minutes)
    forward = df_1m[df_1m.index >= fill_scan_start]
    activation = None
    for ts, c in forward.iterrows():
        h, l = float(c["high"]), float(c["low"])
        if direction == "LONG":
            if l <= entry: activation = ts; break
        else:
            if h >= entry: activation = ts; break
    if activation is None:
        return "not_filled", entry, sl, tp
    sim = df_1m[df_1m.index >= activation]
    for ts, c in sim.iterrows():
        h, l = float(c["high"]), float(c["low"])
        if direction == "LONG":
            if l <= sl: return "loss", entry, sl, tp
            if h >= tp: return "win", entry, sl, tp
        else:
            if h >= sl: return "loss", entry, sl, tp
            if l <= tp: return "win", entry, sl, tp
    return "open", entry, sl, tp


def daily_momentum(df: pd.DataFrame, ts: pd.Timestamp, lookback: int) -> int:
    if df.empty:
        return 0
    day = ts.normalize()
    prev = day - pd.Timedelta(days=lookback)
    n = df[df.index <= day]; p = df[df.index <= prev]
    if n.empty or p.empty: return 0
    delta = float(n["close"].iloc[-1]) - float(p["close"].iloc[-1])
    return 1 if delta > 0 else (-1 if delta < 0 else 0)


def extract_features(s: dict, outcome: str, entry: float, sl: float,
                     df_top_1d: pd.DataFrame, df_top_12h: pd.DataFrame,
                     df_btc_1d: pd.DataFrame,
                     df_tot: pd.DataFrame, df_usd: pd.DataFrame) -> dict:
    direction = s["direction"]
    fvg_b, fvg_t = s["fvg_zone"]
    obh_b, obh_t = s["ob_htf_zone"]
    rdrb_b, rdrb_t = s["rdrb_zone"]
    sig_t = pd.Timestamp(s["signal_time"])
    if sig_t.tz is None:
        sig_t = sig_t.tz_localize("UTC")
    trigger_t = pd.Timestamp(s["rdrb_trigger_time"])
    if trigger_t.tz is None:
        trigger_t = trigger_t.tz_localize("UTC")

    # Trigger candle OHLC (для wick / body)
    df_top = df_top_1d if s["rdrb_tf"] == "1d" else df_top_12h
    if trigger_t in df_top.index:
        row = df_top.loc[trigger_t]
        c_o = float(row["open"]); c_h = float(row["high"])
        c_l = float(row["low"]); c_c = float(row["close"])
        c_range = c_h - c_l
        if direction == "LONG":
            wick = (min(c_o, c_c) - c_l) / c_range if c_range else 0
        else:
            wick = (c_h - max(c_o, c_c)) / c_range if c_range else 0
        body_pct = abs(c_c - c_o) / c_range if c_range else 0
    else:
        wick = body_pct = 0

    # Размеры зон в %
    rdrb_w_pct = (rdrb_t - rdrb_b) / entry * 100 if entry else 0
    obh_w_pct = (obh_t - obh_b) / entry * 100 if entry else 0
    fvg_w_pct = (fvg_t - fvg_b) / entry * 100 if entry else 0
    risk_pct = abs(entry - sl) / entry * 100 if entry else 0

    # Position of OB-htf inside RDRB zone
    # Для LONG: ob_htf_top близко к rdrb_top = "top of zone" (good for LONG?)
    # Для SHORT: ob_htf_bottom близко к rdrb_bottom
    rdrb_w = rdrb_t - rdrb_b
    if direction == "LONG":
        ob_pos = (obh_t - rdrb_b) / rdrb_w if rdrb_w else 0   # 1 = at top of RDRB, 0 = at bottom
    else:
        ob_pos = (rdrb_t - obh_b) / rdrb_w if rdrb_w else 0   # 1 = at bottom of RDRB

    # Position of FVG inside OB-htf
    obh_w = obh_t - obh_b
    if direction == "LONG":
        fvg_pos = (fvg_t - obh_b) / obh_w if obh_w else 0  # 1 = top of OB
    else:
        fvg_pos = (obh_t - fvg_b) / obh_w if obh_w else 0

    # Time features
    hour_utc = sig_t.hour
    dow = sig_t.dayofweek  # 0=Mon

    # Daily momentum
    sign = 1 if direction == "LONG" else -1
    mom_btc_1d = daily_momentum(df_btc_1d, sig_t, 1)
    mom_btc_3d = daily_momentum(df_btc_1d, sig_t, 3)
    mom_btc_7d = daily_momentum(df_btc_1d, sig_t, 7)
    mom_tot_1d = daily_momentum(df_tot, sig_t, 1)
    mom_usd_1d = daily_momentum(df_usd, sig_t, 1)

    return {
        "outcome": outcome,
        "direction": direction,
        "rdrb_tf": s["rdrb_tf"],
        "ob_htf_tf": s["ob_htf_tf"],
        "fvg_tf": s["fvg_tf"],
        "wick_ratio": round(wick, 3),
        "body_pct": round(body_pct, 3),
        "rdrb_w_pct": round(rdrb_w_pct, 3),
        "obh_w_pct": round(obh_w_pct, 3),
        "fvg_w_pct": round(fvg_w_pct, 4),
        "risk_pct": round(risk_pct, 3),
        "ob_pos": round(ob_pos, 3),
        "fvg_pos": round(fvg_pos, 3),
        "hour_utc": hour_utc,
        "dow": dow,
        "btc_mom_1d": mom_btc_1d * sign,   # +1 = follow, -1 = counter
        "btc_mom_3d": mom_btc_3d * sign,
        "btc_mom_7d": mom_btc_7d * sign,
        "tot_mom_1d": mom_tot_1d * sign,   # +1 = sync
        "usd_mom_1d_mirror": mom_usd_1d * (-sign),  # +1 = mirror match
    }


def compare_feature(rows: list[dict], feature: str, fmt: str = "{:.3f}") -> str:
    wins = [r[feature] for r in rows if r["outcome"] == "win"]
    losses = [r[feature] for r in rows if r["outcome"] == "loss"]
    if not wins or not losses:
        return ""
    w_mean = sum(wins) / len(wins)
    l_mean = sum(losses) / len(losses)
    diff = w_mean - l_mean
    return f"  {feature:<22} win_mean={fmt.format(w_mean):<8} loss_mean={fmt.format(l_mean):<8} diff={fmt.format(diff)}"


def discrete_split(rows: list[dict], feature: str) -> str:
    """Для категориальных features — WR по каждой категории."""
    cats = {}
    for r in rows:
        v = r[feature]
        cats.setdefault(v, []).append(r["outcome"])
    out = [f"  {feature}:"]
    for v, outcomes in sorted(cats.items(), key=lambda x: str(x[0])):
        wins = sum(1 for o in outcomes if o == "win")
        losses = sum(1 for o in outcomes if o == "loss")
        n = wins + losses
        wr = wins / n * 100 if n else 0
        pnl = wins * RR - losses
        out.append(f"    {str(v):<10} n={n:3d} W={wins:3d} L={losses:3d} WR={wr:5.1f}% PnL={pnl:+5.1f}R")
    return "\n".join(out)


def threshold_split(rows: list[dict], feature: str, thresholds: list[float]) -> str:
    """Для непрерывных features — WR по бакетам."""
    out = [f"  {feature} buckets:"]
    closed = [r for r in rows if r["outcome"] in ("win", "loss")]
    if not closed:
        return out[0]
    bins = [-float("inf"), *thresholds, float("inf")]
    for lo, hi in zip(bins, bins[1:]):
        sub = [r for r in closed if lo <= r[feature] < hi]
        if not sub:
            continue
        wins = sum(1 for r in sub if r["outcome"] == "win")
        losses = sum(1 for r in sub if r["outcome"] == "loss")
        n = wins + losses
        wr = wins / n * 100 if n else 0
        pnl = wins * RR - losses
        rng = f"<{hi}" if lo == -float("inf") else (f">={lo}" if hi == float("inf") else f"[{lo},{hi})")
        out.append(f"    {rng:<14} n={n:3d} W={wins:3d} L={losses:3d} WR={wr:5.1f}% PnL={pnl:+5.1f}R")
    return "\n".join(out)


def main() -> None:
    print(f"[INFO] Анализ winners vs losers RDRB, RR={RR}, entry={ENTRY_PCT}, sl={SL_PCT}")
    print()

    print("[INFO] загрузка")
    df_btc_1d = load_df(SYMBOL, "1d")
    df_1h = load_df(SYMBOL, "1h")
    df_12h = compose_from_base(df_1h, "12h")
    df_2h = compose_from_base(df_1h, "2h")
    df_15m = load_df(SYMBOL, "15m")
    df_1m = load_df(SYMBOL, "1m")
    df_20m = compose_from_base(df_1m, "20m")
    df_tot = load_df("TOTALES", "1d")
    df_usd = load_df("USDT_D", "1d")
    today = pd.Timestamp.now(tz="UTC").normalize()
    cutoff = today - pd.Timedelta(days=DAYS_BACK)
    df_1d_f = df_btc_1d[df_btc_1d.index >= cutoff - pd.Timedelta(days=5)]
    df_12h_f = df_12h[df_12h.index >= cutoff - pd.Timedelta(days=5)]
    df_1h_f = df_1h[df_1h.index >= cutoff - pd.Timedelta(days=2)]
    df_2h_f = df_2h[df_2h.index >= cutoff - pd.Timedelta(days=2)]
    df_15m_f = df_15m[df_15m.index >= cutoff - pd.Timedelta(days=2)]
    df_20m_f = df_20m[df_20m.index >= cutoff - pd.Timedelta(days=2)]

    print("[INFO] детект + симуляция + features")
    signals = detect_strategy_rdrb_signals(
        df_1d_f, df_12h_f, df_1h_f, df_2h_f, df_15m_f, df_20m_f, verbose=False,
    )
    rows = []
    for s in signals:
        outcome, entry, sl, tp = simulate_one(s, df_1m)
        if outcome == "skipped":
            continue
        feat = extract_features(s, outcome, entry, sl, df_btc_1d, df_12h,
                                df_btc_1d, df_tot, df_usd)
        rows.append(feat)
    closed = [r for r in rows if r["outcome"] in ("win", "loss")]
    print(f"  total simulated: {len(rows)}, closed: {len(closed)}")
    wins = [r for r in closed if r["outcome"] == "win"]
    losses = [r for r in closed if r["outcome"] == "loss"]
    print(f"  wins: {len(wins)}, losses: {len(losses)}")

    print()
    print("=" * 90)
    print("MEAN comparison (win vs loss):")
    print("=" * 90)
    for feat in ["wick_ratio", "body_pct", "rdrb_w_pct", "obh_w_pct",
                 "fvg_w_pct", "risk_pct", "ob_pos", "fvg_pos"]:
        print(compare_feature(closed, feat))

    print()
    print("=" * 90)
    print("CATEGORICAL features:")
    print("=" * 90)
    print(discrete_split(closed, "direction"))
    print(discrete_split(closed, "rdrb_tf"))
    print(discrete_split(closed, "ob_htf_tf"))
    print(discrete_split(closed, "fvg_tf"))
    print(discrete_split(closed, "btc_mom_1d"))
    print(discrete_split(closed, "btc_mom_3d"))
    print(discrete_split(closed, "btc_mom_7d"))
    print(discrete_split(closed, "tot_mom_1d"))
    print(discrete_split(closed, "usd_mom_1d_mirror"))
    print(discrete_split(closed, "dow"))

    print()
    print("=" * 90)
    print("HOUR-of-day buckets:")
    print("=" * 90)
    print(threshold_split(closed, "hour_utc", [4, 8, 12, 16, 20]))

    print()
    print("=" * 90)
    print("THRESHOLD splits для continuous features:")
    print("=" * 90)
    print(threshold_split(closed, "wick_ratio", [0.2, 0.4, 0.6]))
    print(threshold_split(closed, "rdrb_w_pct", [0.5, 1.0, 2.0]))
    print(threshold_split(closed, "obh_w_pct", [0.3, 0.6, 1.0]))
    print(threshold_split(closed, "risk_pct", [0.5, 1.0, 2.0]))
    print(threshold_split(closed, "ob_pos", [0.25, 0.50, 0.75]))
    print(threshold_split(closed, "fvg_pos", [0.25, 0.50, 0.75]))


if __name__ == "__main__":
    main()
