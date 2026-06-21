"""Labeler v2 — разметка архетипов на 1h->D с 2020 + bias-free метрики + null.

Для каждого архетипа (arm = conf последнего пивота, без lookahead):
  - tradeable measured-move (пробой по СПРОЕЦИРОВАННЫМ линиям -> TP/стоп)
  - bias-free signed forward-return (+ = по импульсу)
  - triple-barrier (±1.5 ATR от arm, горизонт ~импульса): что первым — continuation или against.
    tb_fade_R = +1 если against первым (mean-revert), -1 если continuation первым (геометро-независимая сделка)
Контекст: режим (трейлинг BTC 30d), HTF-тренд (1d символа), ТФ, год.
+ NULL: случайные бары той же дирекшн-смеси/горизонта (baseline для fwd и fade).

Выход: research/ta_laws/law_records.csv.
Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/ta_laws/labeler.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import geometry as G  # noqa: E402

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
TFS = [("1h", "1h", 60), ("2h", "2h", 120), ("4h", "4h", 240),
       ("6h", "6h", 360), ("12h", "12h", 720), ("1d", "1d", 1440)]
TB_ATR = 1.5
N_NULL = 500
RNG = np.random.default_rng(7)


def load_1m(sym):
    df = pd.read_csv(ROOT / "data" / f"{sym}_1m.csv", parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def rs(df, freq):
    return df.resample(freq, origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["close"])


def regime_at(btc_1d, ts):
    a = btc_1d.asof(ts); b = btc_1d.asof(ts - pd.Timedelta(days=30))
    if pd.notna(a) and pd.notna(b) and b > 0:
        return 1 if a > b else -1
    return 0


def triple_barrier(c, h, l, arm_idx, hz, base, atr_a, d):
    """Первый барьер ±TB_ATR*ATR. Возврат (tb, fade_R): against первым -> fade +1; cont первым -> -1."""
    if atr_a <= 0:
        return "none", 0.0
    bar_up = base + TB_ATR * atr_a
    bar_dn = base - TB_ATR * atr_a
    up_hit = dn_hit = None
    for x in range(arm_idx + 1, hz + 1):
        if up_hit is None and h[x] >= bar_up:
            up_hit = x
        if dn_hit is None and l[x] <= bar_dn:
            dn_hit = x
        if up_hit is not None and dn_hit is not None:
            break
    cont_hit, agn_hit = (dn_hit, up_hit) if d == "DOWN" else (up_hit, dn_hit)
    ci = cont_hit if cont_hit is not None else 10**9
    ai = agn_hit if agn_hit is not None else 10**9
    if ci == 10**9 and ai == 10**9:
        return "none", 0.0
    if ci <= ai:
        return "cont", -1.0
    return "against", +1.0


def sim(a, df_tf, atr, tf_min):
    p = a.correction.pivots[-1]
    arm_idx = p.conf_i
    n = len(df_tf)
    if arm_idx < 1 or arm_idx >= n - 1:
        return None
    up, loL = a.correction.upper, a.correction.lower
    if up[2] == up[0] or loL[2] == loL[0]:
        return None
    su = (up[3] - up[1]) / (up[2] - up[0]); iu = up[1] - su * up[0]
    slq = (loL[3] - loL[1]) / (loL[2] - loL[0]); il = loL[1] - slq * loL[0]
    window = min(max(a.impulse.bars * 3, 30), 30 * 24 * 60 // tf_min)
    end = min(arm_idx + window, n - 1)
    d = a.continuation_dir; tp = a.measured_move_tp
    c = df_tf["close"].values; h = df_tf["high"].values; l = df_tf["low"].values
    base = c[arm_idx]
    H = min(a.impulse.bars, window)
    j = min(arm_idx + H, n - 1)
    fwd = (c[j] - base) / base if base > 0 else 0.0
    fwd_signed = (-fwd if d == "DOWN" else fwd)
    tb, tb_fade_R = triple_barrier(c, h, l, arm_idx, j, base, atr[arm_idx], d)
    res = dict(arm=df_tf.index[arm_idx], fwd_signed=fwd_signed, rr=0.0, R=None,
               reached_mm=0, reversed=0, outcome="timeout", tb=tb, tb_fade_R=tb_fade_R)

    cont_bar = rev_bar = None
    for x in range(arm_idx + 1, end + 1):
        ul = su * x + iu; ll = slq * x + il
        if d == "DOWN":
            if c[x] < ll:
                cont_bar = x; break
            if c[x] > ul:
                rev_bar = x; break
        else:
            if c[x] > ul:
                cont_bar = x; break
            if c[x] < ll:
                rev_bar = x; break
    if rev_bar is not None:
        res.update(outcome="reversed", reversed=1); return res
    if cont_bar is None:
        return res
    x = cont_bar; entry = c[x]
    stop = (su * x + iu) if d == "DOWN" else (slq * x + il)
    risk = (stop - entry) if d == "DOWN" else (entry - stop)
    if risk <= 0:
        res.update(outcome="badrisk"); return res
    rr = abs(tp - entry) / risk; res["rr"] = rr
    for y in range(x + 1, end + 1):
        if d == "DOWN":
            if h[y] >= stop:
                res.update(outcome="loss", R=-1.0); return res
            if l[y] <= tp:
                res.update(outcome="win", R=rr, reached_mm=1); return res
        else:
            if l[y] <= stop:
                res.update(outcome="loss", R=-1.0); return res
            if h[y] >= tp:
                res.update(outcome="win", R=rr, reached_mm=1); return res
    res.update(outcome="open"); return res


def main():
    print("[labeler v2] 1h->D с 2020, BTC daily для режима...", flush=True)
    btc_1d = rs(load_1m("BTCUSDT"), "1d")["close"]
    rows = []
    for sym in SYMBOLS:
        print(f"[labeler] {sym}...", flush=True)
        d1 = load_1m(sym)
        sym_1d = rs(d1, "1d")["close"]
        # мульти-ТФ тренд (для mtf_align): close-серии 1h/4h/1d
        mtf = {"1h": (rs(d1, "1h")["close"], pd.Timedelta(hours=10)),
               "4h": (rs(d1, "4h")["close"], pd.Timedelta(hours=40)),
               "1d": (rs(d1, "1d")["close"], pd.Timedelta(days=10))}
        for tlabel, freq, tf_min in TFS:
            df_tf = rs(d1, freq)
            n = len(df_tf)
            c = df_tf["close"].values; h = df_tf["high"].values; l = df_tf["low"].values
            vol = df_tf["volume"].values
            atr = G.compute_atr(df_tf)
            atr_roll = pd.Series(atr).rolling(100, min_periods=20).mean().values
            piv_all = G.zigzag(df_tf)
            arts = G.find_archetypes(df_tf)
            Hs, ds = [], []
            for a in arts:
                r = sim(a, df_tf, atr, tf_min)
                if r is None:
                    continue
                arm = r["arm"]; cc = a.correction
                ai = a.correction.pivots[-1].conf_i  # arm bar index
                cn = sym_1d.asof(arm); cp = sym_1d.asof(arm - pd.Timedelta(days=10))
                htf_dir = "UP" if (pd.notna(cn) and pd.notna(cp) and cn > cp) else "DOWN"
                Hs.append(a.impulse.bars); ds.append(a.continuation_dir)
                # --- глубокие факторы ---
                ci0 = a.correction.pivots[0].i
                imp_vol = vol[a.impulse.i0:a.impulse.i1 + 1].mean() if a.impulse.i1 > a.impulse.i0 else np.nan
                corr_vol = vol[ci0:ai + 1].mean() if ai > ci0 else np.nan
                vol_contr = corr_vol / imp_vol if (imp_vol and imp_vol > 0) else np.nan
                arm_vol_z = vol[ai] / vol[max(0, ai - 50):ai].mean() if ai > 5 and vol[max(0, ai - 50):ai].mean() > 0 else np.nan
                atr_pct = atr[ai] / atr_roll[ai] if (ai < len(atr_roll) and atr_roll[ai] > 0) else np.nan
                run_before = abs(c[a.impulse.i0] - c[max(0, a.impulse.i0 - 20)]) / atr[a.impulse.i0] if atr[a.impulse.i0] > 0 else np.nan
                lo_w = l[max(0, ai - 50):ai + 1]; hi_w = h[max(0, ai - 50):ai + 1]
                rng = hi_w.max() - lo_w.min()
                range_pos = (c[ai] - lo_w.min()) / rng if rng > 0 else np.nan
                mtf_align = 0
                for _tf, (ser, td) in mtf.items():
                    vn = ser.asof(arm); vp = ser.asof(arm - td)
                    if pd.notna(vn) and pd.notna(vp):
                        tr = "UP" if vn > vp else "DOWN"
                        mtf_align += int(tr == a.impulse.direction)
                rows.append({
                    "is_null": 0, "symbol": sym, "tf": tlabel, "arm": arm.isoformat(),
                    "dir": a.continuation_dir, "kind": cc.kind, "against": int(cc.against_impulse),
                    "depth_pct": round(cc.depth_pct, 1), "imp_atr_mag": round(a.impulse.atr_mag, 2),
                    "imp_bars": a.impulse.bars, "corr_bars": cc.bars, "converging": int(cc.converging),
                    "rr": round(r["rr"], 2), "outcome": r["outcome"], "R": r["R"],
                    "reached_mm": r["reached_mm"], "reversed": r["reversed"],
                    "fwd_signed": round(r["fwd_signed"], 5), "tb": r["tb"], "tb_fade_R": r["tb_fade_R"],
                    "htf_aligned": int(htf_dir == a.impulse.direction),
                    "regime": regime_at(btc_1d, arm), "year": arm.year,
                    # глубокие факторы:
                    "vol_contr": round(vol_contr, 3) if pd.notna(vol_contr) else "",
                    "arm_vol_z": round(arm_vol_z, 3) if pd.notna(arm_vol_z) else "",
                    "atr_pct": round(atr_pct, 3) if pd.notna(atr_pct) else "",
                    "run_before": round(run_before, 2) if pd.notna(run_before) else "",
                    "range_pos": round(range_pos, 3) if pd.notna(range_pos) else "",
                    "corr_piv": len(a.correction.pivots), "imp_eff": round(a.impulse.efficiency, 3),
                    "mtf_align": mtf_align, "hour": arm.hour, "dow": arm.dayofweek,
                })
            if Hs and n > 60:
                for _ in range(N_NULL):
                    Hn = max(2, min(int(RNG.choice(Hs)), n // 4))
                    if n - Hn - 1 <= 25:
                        continue
                    b = int(RNG.integers(25, n - Hn - 1)); dd = str(RNG.choice(ds))
                    base = c[b]
                    if base <= 0:
                        continue
                    fwd = (c[b + Hn] - base) / base
                    fs = -fwd if dd == "DOWN" else fwd
                    tb, tbf = triple_barrier(c, h, l, b, b + Hn, base, atr[b], dd)
                    armb = df_tf.index[b]
                    rows.append({
                        "is_null": 1, "symbol": sym, "tf": tlabel, "arm": armb.isoformat(),
                        "dir": dd, "kind": "NULL", "against": 0, "depth_pct": 0.0, "imp_atr_mag": 0.0,
                        "imp_bars": Hn, "corr_bars": 0, "converging": 0, "rr": 0.0, "outcome": "null",
                        "R": None, "reached_mm": 0, "reversed": 0, "fwd_signed": round(fs, 5),
                        "tb": tb, "tb_fade_R": tbf, "htf_aligned": 0,
                        "regime": regime_at(btc_1d, armb), "year": armb.year,
                    })
                # PIVOT-NULL (is_null=2): generic swing-continuation на случайных пивотах.
                # «against»=направление последней ноги (пивот->conf) = продолжение свинга.
                vp = [pp for pp in piv_all if 0 <= pp.conf_i < n - 2]
                if vp:
                    idxs = RNG.choice(len(vp), size=min(N_NULL, len(vp)), replace=False)
                    for si in idxs:
                        pp = vp[int(si)]; ci = pp.conf_i
                        Hn = max(2, min(int(RNG.choice(Hs)), n - ci - 2))
                        if n - ci - 2 <= 2:
                            continue
                        recent_up = c[ci] > pp.price
                        pseudo_d = "DOWN" if recent_up else "UP"   # against=recent leg=continue swing
                        tb, tbf = triple_barrier(c, h, l, ci, ci + Hn, c[ci], atr[ci], pseudo_d)
                        armp = df_tf.index[ci]
                        rows.append({
                            "is_null": 2, "symbol": sym, "tf": tlabel, "arm": armp.isoformat(),
                            "dir": ("UP" if recent_up else "DOWN"), "kind": "PIVOTNULL", "against": 0,
                            "depth_pct": 0.0, "imp_atr_mag": 0.0, "imp_bars": Hn, "corr_bars": 0,
                            "converging": 0, "rr": 0.0, "outcome": "pivnull", "R": None, "reached_mm": 0,
                            "reversed": 0, "fwd_signed": 0.0, "tb": tb, "tb_fade_R": tbf,
                            "htf_aligned": 0, "regime": regime_at(btc_1d, armp), "year": armp.year,
                        })
            print(f"   {sym} {tlabel}: arts {len(arts)}", flush=True)

    df = pd.DataFrame(rows)
    out = HERE / "law_records.csv"
    df.to_csv(out, index=False)
    arche = df[df.is_null == 0]; null = df[df.is_null == 1]
    print(f"\n[labeler] архетипов {len(arche)}, null {len(null)} -> {out.name}")
    print(f"  fwd_signed: arche {arche.fwd_signed.mean():+.4f}  null {null.fwd_signed.mean():+.4f}")
    dec = arche[arche.tb != "none"]
    print(f"  triple-barrier fade: arche expR {dec.tb_fade_R.mean():+.3f} (n={len(dec)})  "
          f"null {null[null.tb!='none'].tb_fade_R.mean():+.3f}")


if __name__ == "__main__":
    main()
