"""Финальная стратегия 12h-фрактал-предсказания с maxV ТОЧНО как Pine
ASVK ViC (LTF=8m, origin=epoch).

Pine code: /Users/vadim/Downloads/vic.txt (восстановлено 2026-05-21).

Логика:
  tfC = 43200s (12h chart)
  rs = auto ? tfC/mlt = 432s
  rs = max(60, rs) = 432  (non-premium)
  res = timeframe.from_seconds(min(43200, 432)) = "8" (8 минут)

  request.security_lower_tf(symbol, "8", [bull_vol, bear_vol, ..., close])
  → массив 8m bars внутри 12h bar

  bV.max(), sV.max(): найти максимум среди bullish/bearish volumes
  side = bVmax > sVmax ? bull : bear
  maxV = close of bar with max volume on chosen side

Проверено: 6/6 свечей 2026-05-14..17 с расхождением ≤6 USD от индикатора.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

CACHE_1M = ROOT / "data" / "BTCUSDT_1m_vic_vadim.csv"
LTF_MINUTES = 8  # Pine resolution: from_seconds(432) → "8"

HTF_LIST: list[tuple[str, str]] = [("12h", "12h"), ("1d", "1D"), ("2d", "2D"), ("3d", "3D"), ("W", "7D")]
WEEKLY_ANCHOR = pd.Timestamp("1970-01-05", tz="UTC")


def load_1m() -> pd.DataFrame:
    df = pd.read_csv(CACHE_1M, parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def compose_htf(df_base: pd.DataFrame, freq: str) -> pd.DataFrame:
    origin = WEEKLY_ANCHOR if freq == "7D" else "epoch"
    return df_base.resample(freq, origin=origin, label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna(subset=["close"])


def calculate_maxv_pine(df_1m: pd.DataFrame, bar_open: pd.Timestamp) -> float | None:
    """Точная реплика Pine ASVK ViC maxV: 8m bars (epoch-aligned), max
    among bull/bear by volume, выбираем сторону с большим max."""
    end = bar_open + pd.Timedelta(hours=12)
    mask = (df_1m.index >= bar_open) & (df_1m.index < end)
    sub = df_1m.loc[mask]
    if sub.empty: return None
    # resample 1m → 8m с origin=epoch (Pine 8m-сетка)
    s = sub.resample(f"{LTF_MINUTES}min", origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna(subset=["close"])
    if s.empty: return None
    bull = s[s["close"] > s["open"]]
    bear = s[s["close"] < s["open"]]
    mb = bull["volume"].max() if not bull.empty else 0
    mr = bear["volume"].max() if not bear.empty else 0
    if mb == 0 and mr == 0: return None
    if mb > mr:
        return float(bull.loc[bull["volume"].idxmax(), "close"])
    return float(bear.loc[bear["volume"].idxmax(), "close"])


# === C1 helpers (повтор) ===

def find_ob_zones(df_tf, tf_label):
    out = []
    o = df_tf["open"].to_numpy(); h = df_tf["high"].to_numpy()
    l = df_tf["low"].to_numpy(); c = df_tf["close"].to_numpy()
    idx = df_tf.index
    tf_dur = (idx[1] - idx[0]) if len(idx) > 1 else pd.Timedelta("12h")
    for k in range(len(df_tf) - 1):
        if c[k] < o[k] and c[k+1] > o[k+1] and c[k+1] > o[k]:
            zb, zt = float(min(l[k], l[k+1])), float(o[k])
            if zt > zb:
                out.append({"dir":"LONG","zone_bottom":zb,"zone_top":zt,"ready_time":idx[k+1]+tf_dur})
        if c[k] > o[k] and c[k+1] < o[k+1] and c[k+1] < o[k]:
            zb, zt = float(o[k]), float(max(h[k], h[k+1]))
            if zt > zb:
                out.append({"dir":"SHORT","zone_bottom":zb,"zone_top":zt,"ready_time":idx[k+1]+tf_dur})
    return out


def find_fractals(df_tf, tf_label):
    out = []
    h = df_tf["high"].to_numpy(); l = df_tf["low"].to_numpy()
    idx = df_tf.index
    tf_dur = (idx[1] - idx[0]) if len(idx) > 1 else pd.Timedelta("12h")
    for i in range(2, len(df_tf) - 2):
        if h[i] > h[i-2] and h[i] > h[i-1] and h[i] > h[i+1] and h[i] > h[i+2]:
            out.append({"kind":"FH","level":float(h[i]),"ready_time":idx[i+2]+tf_dur})
        if l[i] < l[i-2] and l[i] < l[i-1] and l[i] < l[i+1] and l[i] < l[i+2]:
            out.append({"kind":"FL","level":float(l[i]),"ready_time":idx[i+2]+tf_dur})
    return out


def zone_sweep_flags(df_12h, zones, direction):
    n = len(df_12h); flag = np.zeros(n, dtype=bool); idx = df_12h.index
    h = df_12h["high"].to_numpy(); l = df_12h["low"].to_numpy(); c = df_12h["close"].to_numpy()
    for z in zones:
        if z["dir"] != direction: continue
        rt = pd.Timestamp(z["ready_time"])
        if rt.tz is None: rt = rt.tz_localize("UTC")
        sp = int(idx.searchsorted(rt, side="left"))
        if sp >= n: continue
        level = z["zone_top"] if direction == "SHORT" else z["zone_bottom"]
        for i in range(sp, n):
            if direction == "SHORT":
                if h[i] > level and c[i] < level: flag[i] = True; break
                if c[i] > level: break
            else:
                if l[i] < level and c[i] > level: flag[i] = True; break
                if c[i] < level: break
    return flag


def fractal_sweep_flags(df_12h, fractals, kind):
    n = len(df_12h); flag = np.zeros(n, dtype=bool); idx = df_12h.index
    h = df_12h["high"].to_numpy(); l = df_12h["low"].to_numpy(); c = df_12h["close"].to_numpy()
    for f in fractals:
        if f["kind"] != kind: continue
        rt = pd.Timestamp(f["ready_time"])
        if rt.tz is None: rt = rt.tz_localize("UTC")
        sp = int(idx.searchsorted(rt, side="left"))
        if sp >= n: continue
        lvl = f["level"]
        for i in range(sp, n):
            if kind == "FH":
                if h[i] > lvl and c[i] < lvl: flag[i] = True; break
                if c[i] > lvl: break
            else:
                if l[i] < lvl and c[i] > lvl: flag[i] = True; break
                if c[i] < lvl: break
    return flag


def main() -> None:
    df_1m = load_1m()
    print(f"1m BTC: {len(df_1m):,} баров")

    htf_dfs = {tf: compose_htf(df_1m, freq) for tf, freq in HTF_LIST}
    df_12h = htf_dfs["12h"]

    print(f"Считаем maxV Pine-style (LTF=8m, epoch-aligned)...", flush=True)
    df_1m_naive = df_1m.copy(); df_1m_naive.index.name = None
    maxv = np.array([calculate_maxv_pine(df_1m_naive, t) or np.nan for t in df_12h.index])
    print(f"maxV: рассчитан для {(~np.isnan(maxv)).sum()} из {len(maxv)} 12h-свечей")

    h = df_12h["high"].to_numpy(); l = df_12h["low"].to_numpy(); c = df_12h["close"].to_numpy()
    sw_short = np.zeros(len(df_12h), dtype=bool); sw_long = np.zeros(len(df_12h), dtype=bool)
    for i in range(1, len(df_12h)):
        if np.isnan(maxv[i-1]): continue
        if h[i] > maxv[i-1] and c[i] < maxv[i-1]: sw_short[i] = True
        if l[i] < maxv[i-1] and c[i] > maxv[i-1]: sw_long[i] = True
    print(f"sweep_maxV SHORT={sw_short.sum()}, LONG={sw_long.sum()}")

    # C1
    all_ob, all_fract = [], []
    for tf, df_tf in htf_dfs.items():
        all_ob += find_ob_zones(df_tf, tf)
        all_fract += find_fractals(df_tf, tf)
    c1_fh = fractal_sweep_flags(df_12h, all_fract, "FH")
    c1_fl = fractal_sweep_flags(df_12h, all_fract, "FL")
    c1_obs = zone_sweep_flags(df_12h, all_ob, "SHORT")
    c1_obl = zone_sweep_flags(df_12h, all_ob, "LONG")

    # target
    n_bars = len(df_12h); valid = np.arange(2, n_bars - 2)
    hh = ((h[valid]>h[valid-2])&(h[valid]>h[valid-1])&(h[valid]>h[valid+1])&(h[valid]>h[valid+2]))
    ll = ((l[valid]<l[valid-2])&(l[valid]<l[valid-1])&(l[valid]<l[valid+1])&(l[valid]<l[valid+2]))
    n_total = len(valid); base_hh = hh.mean(); base_ll = ll.mean()
    print(f"\nbaseline P(HH)={base_hh*100:.2f}%  P(LL)={base_ll*100:.2f}%  (n={n_total})\n")

    def report(label, target, cond, base):
        n_c = int(cond.sum()); n_tc = int((target & cond).sum())
        prec = n_tc / n_c if n_c else float("nan")
        lift = prec / base if base else float("nan")
        cov = n_c / n_total
        rec = n_tc / int(target.sum()) if target.any() else float("nan")
        print(f"  {label:<52} n={n_c:3d}  hits={n_tc:3d}  prec={prec*100:6.2f}%  "
              f"lift=×{lift:.2f}  cov={cov*100:5.2f}%  rec={rec*100:5.2f}%")

    print("=== Per-component ∩ maxV[i] (LTF=8m Pine) ===")
    report("HH | sweep_FH ∩ maxV[i]",   hh, (c1_fh & sw_short)[valid], base_hh)
    report("HH | OB_sweep ∩ maxV[i]",   hh, (c1_obs & sw_short)[valid], base_hh)
    report("LL | sweep_FL ∩ maxV[i]",   ll, (c1_fl & sw_long)[valid], base_ll)
    report("LL | OB_sweep ∩ maxV[i]",   ll, (c1_obl & sw_long)[valid], base_ll)

    print("\n=== Core: (sweep_FH ∪ OB_sweep) ∩ maxV[i] ===")
    hh_core = (c1_fh | c1_obs) & sw_short
    ll_core = (c1_fl | c1_obl) & sw_long
    report("HH Core", hh, hh_core[valid], base_hh)
    report("LL Core", ll, ll_core[valid], base_ll)

    print("\n=== Sniper: sweep_FH ∩ OB_sweep ∩ maxV[i] ===")
    report("HH Sniper", hh, (c1_fh & c1_obs & sw_short)[valid], base_hh)
    report("LL Sniper", ll, (c1_fl & c1_obl & sw_long)[valid], base_ll)

    # сверка: контрольная свеча 2026-03-17 03:00 UTC+3
    print("\n=== Контрольная свеча 2026-03-17 03:00 UTC+3 (UTC: 00:00) ===")
    target_t = pd.Timestamp('2026-03-17 00:00', tz='UTC')
    pos = int(df_12h.index.searchsorted(target_t))
    if df_12h.index[pos] == target_t:
        i = pos
        print(f"  high={h[i]:.2f}  close={c[i]:.2f}  maxV(prev, 8m)={maxv[i-1]:.2f}")
        print(f"  sweep_maxV SHORT={sw_short[i]}  sweep_FH={c1_fh[i]}  OB_sweep_S={c1_obs[i]}")


if __name__ == "__main__":
    main()
