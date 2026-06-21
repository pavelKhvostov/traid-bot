"""B3C2 — Williams n=2 fractal sweep + retest (close back).

Snap классической HTF фрактальной ликвидности:
   1. На HTF (W ∪ 3D ∪ D) находим Williams n=2 фракталы (strict causal: i-2 точка экстремума,
      по 2 бара слева/справа подтверждают)
   2. Для каждого 12h pivot i проверяем:
      LONG  (pivot=low):  low[i]  < latest FL_HTF (unmitigated до i)
                          AND close[i] > FL_HTF level  ← откат (close back above)
      SHORT (pivot=high): high[i] > latest FH_HTF (unmitigated до i)
                          AND close[i] < FH_HTF level  ← откат (close back below)

Causal: ✅
   HTF fractals computed на закрытых HTF барах ≤ i-2 (Williams confirmation требует 2 бара ПОСЛЕ pivot)
   sweep/close check на bar i (current)
   "Unmitigated" = с момента confirmation никакой бар не пробил FH вверх (или FL вниз)

Mitigation для fractal level (TF-relative):
   - FL уровень "съеден" если low any subsequent bar < FL_level (kept lowest active)
   - FH уровень "съеден" если high any subsequent bar > FH_level (kept highest active)
"""
from __future__ import annotations
import numpy as np
from _lib import load_12h, load_htf_bars, load_baseline, match_pivots, report, save_fires, TF_HTF


HTF_LIST = ["W", "3D", "D"]


def find_williams_fractals(bars_htf, tf_ms):
    """Williams n=2 на closed HTF bars.
    Returns dict: 'fh' = list of (confirm_ts, level), 'fl' = same.
    confirm_ts = время когда фрактал стал confirmed (центр + 2 бара ПОСЛЕ закрыты).
    Strict causal: фрактал [i-2..i] доступен после close бара i.
    """
    fh, fl = [], []
    for i in range(2, len(bars_htf) - 2):
        c = bars_htf[i]
        # FH: high[i] > high[i-1], high[i-2], high[i+1], high[i+2]
        if (c[2] > bars_htf[i-1][2] and c[2] > bars_htf[i-2][2]
                and c[2] > bars_htf[i+1][2] and c[2] > bars_htf[i+2][2]):
            confirm_ts = bars_htf[i+2][0] + tf_ms  # close of bar i+2
            fh.append((confirm_ts, c[2]))
        if (c[3] < bars_htf[i-1][3] and c[3] < bars_htf[i-2][3]
                and c[3] < bars_htf[i+1][3] and c[3] < bars_htf[i+2][3]):
            confirm_ts = bars_htf[i+2][0] + tf_ms
            fl.append((confirm_ts, c[3]))
    return {"fh": fh, "fl": fl}


def latest_unmitigated(fractals, ts_now, bars_htf_lookup_h, bars_htf_lookup_l, ts_htf, tf_ms, kind):
    """Find latest fractal level (confirmed ≤ ts_now) that is still UN-mitigated.

    kind = 'fl': level is FL, mitigated if any subsequent bar low < level (deeper FL invalidates)
    kind = 'fh': level is FH, mitigated if any subsequent bar high > level
    Returns level or None.
    """
    candidates = [f for f in fractals if f[0] <= ts_now]
    if not candidates: return None
    # Walk backwards (latest first), return first un-mitigated
    candidates.sort(key=lambda x: x[0], reverse=True)
    for confirm_ts, level in candidates:
        # HONEST mitigation: only HTF bars FULLY CLOSED at ts_now count
        # bar fully closed: ts_open + tf_ms <= ts_now ⟺ ts_open <= ts_now - tf_ms
        cutoff = ts_now - tf_ms
        i_s = int(np.searchsorted(ts_htf, confirm_ts, side="left"))
        i_e = int(np.searchsorted(ts_htf, cutoff, side="right"))
        if i_e <= i_s:
            return level
        if kind == "fl":
            mit = (bars_htf_lookup_l[i_s:i_e] < level).any()
        else:
            mit = (bars_htf_lookup_h[i_s:i_e] > level).any()
        if not mit:
            return level
    return None


def main():
    bars = load_12h()
    n12 = bars["n"]; t12 = bars["t"]; h12 = bars["h"]; l12 = bars["l"]; c12 = bars["c"]

    # Build HTF fractals
    fractals_per_tf = {}
    htf_arrays = {}  # for mitigation lookup
    for tf in HTF_LIST:
        tf_ms = TF_HTF[tf]
        bars_htf = load_htf_bars(tf)
        fr = find_williams_fractals(bars_htf, tf_ms)
        fractals_per_tf[tf] = fr
        htf_arrays[tf] = {
            "ts": np.array([b[0] for b in bars_htf], dtype=np.int64),
            "h": np.array([b[2] for b in bars_htf]),
            "l": np.array([b[3] for b in bars_htf]),
            "tf_ms": tf_ms,
        }
        print(f"  HTF {tf}: bars={len(bars_htf)}, FH={len(fr['fh'])}, FL={len(fr['fl'])}")

    fires = set()
    for i in range(2, n12):
        ts_i = int(t12[i])  # open of 12h bar i
        # Pivot directions to evaluate at this bar
        # zone_dir = 'long' (FL pivot, expect FL sweep + close above)
        # zone_dir = 'short' (FH pivot, expect FH sweep + close below)

        # LONG: low sweeps FL on any HTF, close above
        for tf in HTF_LIST:
            a = htf_arrays[tf]
            level = latest_unmitigated(
                fractals_per_tf[tf]["fl"], ts_i,
                a["h"], a["l"], a["ts"], a["tf_ms"], kind="fl")
            if level is None: continue
            if l12[i] < level and c12[i] > level:
                fires.add((i, "long"))
                break

        # SHORT: high sweeps FH on any HTF, close below
        for tf in HTF_LIST:
            a = htf_arrays[tf]
            level = latest_unmitigated(
                fractals_per_tf[tf]["fh"], ts_i,
                a["h"], a["l"], a["ts"], a["tf_ms"], kind="fh")
            if level is None: continue
            if h12[i] > level and c12[i] < level:
                fires.add((i, "short"))
                break

    pmap = match_pivots(bars, load_baseline())
    report("B3C2", "Williams sweep+retest (W∪3D∪D)", fires, pmap)
    save_fires("B3C2", fires, bars)


if __name__ == "__main__":
    main()
