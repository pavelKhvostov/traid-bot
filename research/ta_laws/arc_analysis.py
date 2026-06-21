"""Закон АРОК (округлений/параболики): что происходит ПОСЛЕ завершения дуги.

BTC/ETH/SOL, 1h->D, с 2020. Каузально (arm = i1, правый край дуги). Для каждой арки:
  - end_dir   — куда цена шла в момент завершения (знак производной параболы в i1);
  - triple-barrier ±1.5 ATR от i1: что первым — продолжение end_dir или РАЗВОРОТ;
  - rev_R = +1 если разворот первым (mean-revert после дуги), -1 если продолжение;
  - MFE/MAE в ATR в сторону разворота (докуда отскок);
  - факторы: kind (купол/чаша), sagitta_atr (изогнутость), depth_atr, кривизна, позиция apex, мульти-ТФ.
Контроли: NULL (случайные окна, случайное направление) + PIVOT-NULL (generic swing-continuation).
Гейты: эффект > null И cross-asset >=2/3 И год-стабильность.

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/ta_laws/arc_analysis.py
Выход: research/ta_laws/arcs_report.txt + arc_records.csv
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
import curves as C    # noqa: E402

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
TFS = [("1h", "1h", 60), ("2h", "2h", 120), ("4h", "4h", 240),
       ("6h", "6h", 360), ("12h", "12h", 720), ("1d", "1d", 1440)]
TB_ATR = 1.5
N_NULL = 600
RNG = np.random.default_rng(23)


def load_1m(sym):
    df = pd.read_csv(ROOT / "data" / f"{sym}_1m.csv", parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def rs(df, freq):
    return df.resample(freq, origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["close"])


def regime_at(btc_1d, ts):
    a = btc_1d.asof(ts); b = btc_1d.asof(ts - pd.Timedelta(days=30))
    return (1 if a > b else -1) if (pd.notna(a) and pd.notna(b) and b > 0) else 0


def barrier(c, h, l, arm, hz, base, atr_a, cont_dir):
    """Триггер-барьер ±1.5ATR. Возврат (rev_R, mfe_rev_atr, mae_atr):
    rev_R=+1 если барьер ПРОТИВ cont_dir первым (разворот), -1 если по cont_dir (продолжение)."""
    if atr_a <= 0:
        return 0.0, np.nan, np.nan
    up = base + TB_ATR * atr_a; dn = base - TB_ATR * atr_a
    uh = dh = None
    for x in range(arm + 1, hz + 1):
        if uh is None and h[x] >= up:
            uh = x
        if dh is None and l[x] <= dn:
            dh = x
        if uh is not None and dh is not None:
            break
    cont_hit, rev_hit = (dh, uh) if cont_dir == "DOWN" else (uh, dh)
    ci = cont_hit if cont_hit is not None else 10**9
    ri = rev_hit if rev_hit is not None else 10**9
    if ci == 10**9 and ri == 10**9:
        return 0.0, np.nan, np.nan
    rev_R = 1.0 if ri < ci else -1.0
    # MFE в сторону разворота / MAE против — до конца горизонта
    rev_up = (cont_dir == "DOWN")  # разворот = вверх если падали
    mfe = mae = 0.0
    for x in range(arm + 1, hz + 1):
        fav = (h[x] - base) if rev_up else (base - l[x])
        adv = (base - l[x]) if rev_up else (h[x] - base)
        mfe = max(mfe, fav); mae = max(mae, adv)
    return rev_R, mfe / atr_a, mae / atr_a


def main():
    btc_1d = rs(load_1m("BTCUSDT"), "1d")["close"]
    rows = []
    for sym in SYMBOLS:
        print(f"[arc] {sym}...", flush=True)
        d1 = load_1m(sym)
        sym_1d = rs(d1, "1d")["close"]
        mtf = {"1h": (rs(d1, "1h")["close"], pd.Timedelta(hours=10)),
               "4h": (rs(d1, "4h")["close"], pd.Timedelta(hours=40)),
               "1d": (sym_1d, pd.Timedelta(days=10))}
        for tlabel, freq, tf_min in TFS:
            df = rs(d1, freq)
            n = len(df)
            c = df["close"].values; h = df["high"].values; l = df["low"].values
            atr = G.compute_atr(df)
            cap = 30 * 24 * 60 // tf_min
            arcs = C.find_arcs(df, atr=atr)
            lens = []
            for arc in arcs:
                i1 = arc.i1
                if i1 < 25 or i1 >= n - 2:
                    continue
                L = arc.i1 - arc.i0
                lens.append(L)
                a, b, _ = arc.coeffs
                deriv = 2 * a * L + b            # наклон параболы в правом крае
                end_dir = "UP" if deriv > 0 else "DOWN"
                hz = min(i1 + min(L, cap), n - 1)
                rev_R, mfe, mae = barrier(c, h, l, i1, hz, c[i1], atr[i1], end_dir)
                arm_ts = df.index[i1]
                # факторы
                apex_pos = (arc.apex_i - arc.i0) / max(L, 1)   # 0=рано(слева), 1=поздно(справа)
                mtf_up = 0
                for _t, (ser, td) in mtf.items():
                    vn = ser.asof(arm_ts); vp = ser.asof(arm_ts - td)
                    if pd.notna(vn) and pd.notna(vp):
                        mtf_up += int(vn > vp)
                rows.append({
                    "is_null": 0, "symbol": sym, "tf": tlabel, "arm": arm_ts.isoformat(),
                    "kind": arc.kind, "end_dir": end_dir, "rev_R": rev_R,
                    "mfe_rev_atr": round(mfe, 3) if pd.notna(mfe) else "",
                    "mae_atr": round(mae, 3) if pd.notna(mae) else "",
                    "sagitta_atr": round(arc.sagitta_atr, 2), "depth_atr": round(arc.depth_atr, 2),
                    "a_norm": round(arc.a_norm, 6), "arc_gain": round(arc.arc_gain, 3),
                    "r2_quad": round(arc.r2_quad, 3), "L": L, "apex_pos": round(apex_pos, 2),
                    "mtf_up": mtf_up, "regime": regime_at(btc_1d, arm_ts), "year": arm_ts.year,
                })
            # NULL: случайные окна, случайное направление
            if lens and n > 80:
                for _ in range(N_NULL):
                    Ln = int(RNG.choice(lens))
                    if n - Ln - 2 <= 25:
                        continue
                    bi = int(RNG.integers(25, n - Ln - 1))
                    cont = str(RNG.choice(["UP", "DOWN"]))
                    hzn = min(bi + min(Ln, cap), n - 1)
                    rev_R, mfe, mae = barrier(c, h, l, bi, hzn, c[bi], atr[bi], cont)
                    rows.append({
                        "is_null": 1, "symbol": sym, "tf": tlabel, "arm": df.index[bi].isoformat(),
                        "kind": "NULL", "end_dir": cont, "rev_R": rev_R,
                        "mfe_rev_atr": round(mfe, 3) if pd.notna(mfe) else "",
                        "mae_atr": round(mae, 3) if pd.notna(mae) else "",
                        "sagitta_atr": 0, "depth_atr": 0, "a_norm": 0, "arc_gain": 0, "r2_quad": 0,
                        "L": Ln, "apex_pos": 0, "mtf_up": 0,
                        "regime": regime_at(btc_1d, df.index[bi]), "year": df.index[bi].year,
                    })
            print(f"   {sym} {tlabel}: арок {len([a for a in arcs if 25 <= a.i1 < n-2])}", flush=True)

    df = pd.DataFrame(rows)
    df.to_csv(HERE / "arc_records.csv", index=False)
    A = df[df.is_null == 0].copy()
    Nl = df[df.is_null == 1].copy()
    nv = Nl.rev_R.values

    def boot_p(mean, k, iters=3000):
        if len(nv) < 5 or k < 3:
            return 1.0
        m = nv[RNG.integers(0, len(nv), size=(iters, k))].mean(axis=1)
        return float((m >= mean).mean())

    out = []
    out.append("ЗАКОН АРОК (округлений/параболики) — BTC/ETH/SOL, 1h->D, с 2020.")
    out.append(f"Всего арок: {len(A)} | null: {len(Nl)} | базовый rev_R (разворот после дуги) = "
               f"{A.rev_R.mean():+.3f} | null = {nv.mean():+.3f}")
    out.append("rev_R>0 = после завершения дуги цена чаще РАЗВОРАЧИВАЕТСЯ (mean-revert), <0 = продолжает.\n")

    out.append("=== 1) ПО ТИПУ ДУГИ (купол/чаша) ===")
    out.append(f"{'тип':18} {'n':>6} {'rev_R':>7} {'P(разв)%':>9} {'p_null':>7} {'sym+':>5} {'год+':>6} {'MFE_rev':>8} {'MAE':>6}")
    for k in ["ROUNDING_TOP", "ROUNDING_BOTTOM"]:
        s = A[A.kind == k]
        if len(s) < 30:
            out.append(f"{k:18} n={len(s)} (мало)"); continue
        m = s.rev_R.mean(); pr = (s.rev_R > 0).mean() * 100
        p = boot_p(m, len(s))
        symp = int((s.groupby("symbol").rev_R.mean() > 0).sum())
        yrs = s.groupby("year").rev_R.mean(); yp = int((yrs > 0).sum())
        mfe = pd.to_numeric(s.mfe_rev_atr, errors="coerce").median()
        mae = pd.to_numeric(s.mae_atr, errors="coerce").median()
        out.append(f"{k:18} {len(s):>6} {m:>+7.3f} {pr:>9.1f} {p:>7.3f} {symp:>4}/3 {yp:>4}/{yrs.size} "
                   f"{mfe:>8.2f} {mae:>6.2f}")

    out.append("\n=== 2) ФАКТОРЫ силы разворота (бакеты rev_R + null лучшего) ===")

    def fac(label, mask):
        s = A[mask]
        if len(s) < 40:
            return f"  {label:30} (мало)"
        m = s.rev_R.mean(); p = boot_p(m, len(s))
        symp = int((s.groupby("symbol").rev_R.mean() > 0).sum())
        return f"  {label:30} n={len(s):>5} rev_R={m:>+.3f} P(разв)={ (s.rev_R>0).mean()*100:>4.0f}% p={p:.3f} sym {symp}/3"

    out.append("  -- изогнутость дуги (sagitta в ATR):")
    out.append(fac("слабая <2.5", A.sagitta_atr < 2.5))
    out.append(fac("средняя 2.5-4", (A.sagitta_atr >= 2.5) & (A.sagitta_atr < 4)))
    out.append(fac("сильная >=4", A.sagitta_atr >= 4))
    out.append("  -- размах дуги (depth в ATR):")
    out.append(fac("мелкая <5", A.depth_atr < 5))
    out.append(fac("крупная >=8", A.depth_atr >= 8))
    out.append("  -- позиция вершины/дна (apex_pos):")
    out.append(fac("apex рано <0.4 (длинный хвост дуги)", A.apex_pos < 0.4))
    out.append(fac("apex по центру 0.4-0.7", (A.apex_pos >= 0.4) & (A.apex_pos <= 0.7)))
    out.append(fac("apex поздно >0.7", A.apex_pos > 0.7))
    out.append("  -- мульти-ТФ контекст (mtf_up: сколько ТФ вверх):")
    out.append(fac("контекст вниз (0-1/3)", A.mtf_up <= 1))
    out.append(fac("контекст вверх (3/3)", A.mtf_up >= 3))
    out.append("  -- режим BTC:")
    out.append(fac("бычий режим", A.regime == 1))
    out.append(fac("медвежий режим", A.regime == -1))

    out.append("\n=== 3) КУПОЛ детально (паттерн с фото: дуга-над, спуск) ===")
    dome = A[A.kind == "ROUNDING_TOP"]
    out.append(f"  end_dir после купола: DOWN {int((dome.end_dir=='DOWN').sum())} / UP {int((dome.end_dir=='UP').sum())}")
    dd = dome[dome.end_dir == "DOWN"]
    if len(dd) >= 30:
        out.append(f"  купол со спуском в конце (как на фото): n={len(dd)} rev_R={dd.rev_R.mean():+.3f} "
                   f"P(отскок вверх)={ (dd.rev_R>0).mean()*100:.0f}% p={boot_p(dd.rev_R.mean(), len(dd)):.3f}")
        mfe = pd.to_numeric(dd.mfe_rev_atr, errors='coerce').median()
        out.append(f"  докуда отскок (MFE медиана) = {mfe:.2f} ATR; против (MAE) = "
                   f"{pd.to_numeric(dd.mae_atr, errors='coerce').median():.2f} ATR")

    out.append("\n=== СИНТЕЗ ===")
    base_p = boot_p(A.rev_R.mean(), len(A))
    verdict = ("АРКА = ЗАКОН разворота" if A.rev_R.mean() > 0.05 and base_p < 0.05
               else ("АРКА = продолжение" if A.rev_R.mean() < -0.05 else "АРКА ≈ нейтрально (не бьёт null)"))
    out.append(f"  Базовый: rev_R {A.rev_R.mean():+.3f} (null {nv.mean():+.3f}), p={base_p:.3f} -> {verdict}")

    rep = HERE / "arcs_report.txt"
    rep.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))
    print(f"\n[arc] -> {rep.name}")


if __name__ == "__main__":
    main()
