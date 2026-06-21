"""Законы фигур ТА: КУДА раскроется (направление) + ДОКУДА дойдёт (цель) + от каких факторов.

На BTC/ETH/SOL, 1h->D, с 2020. Для каждой фигуры (figures.find_figures), каузально (arm=comp_conf_i):
  1) НАПРАВЛЕНИЕ: triple-barrier ±1.5 ATR, signed by expected_dir -> P(учебная сторона первой) + null.
  2) ЦЕЛЬ: после пробоя неклайна — MFE в «высотах фигуры» (measured-move multiple) до возврата/горизонта.
  3) ФАКТОРЫ цели: HTF-выравнивание, режим, высота фигуры (ATR), импульс пробоя, ТФ.

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/ta_laws/figure_analysis.py
Выход: research/ta_laws/figures_report.txt
"""
from __future__ import annotations

import sys
from collections import defaultdict
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
import figures as F  # noqa: E402

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
    return (1 if a > b else -1) if (pd.notna(a) and pd.notna(b) and b > 0) else 0


def dir_barrier(c, h, l, arm, hz, atr_a, expdir):
    """+1 если expected_dir барьер (1.5ATR) первым, -1 если против, 0 если ни один."""
    if atr_a <= 0:
        return 0
    base = c[arm]; up = base + TB_ATR * atr_a; dn = base - TB_ATR * atr_a
    uh = dh = None
    for x in range(arm + 1, hz + 1):
        if uh is None and h[x] >= up:
            uh = x
        if dh is None and l[x] <= dn:
            dh = x
        if uh is not None and dh is not None:
            break
    exp_hit, opp_hit = (uh, dh) if expdir == "UP" else (dh, uh)
    ei = exp_hit if exp_hit is not None else 10**9
    oi = opp_hit if opp_hit is not None else 10**9
    if ei == 10**9 and oi == 10**9:
        return 0
    return 1 if ei <= oi else -1


def extent(c, h, l, arm, hz, neck, expdir, height):
    """После пробоя неклайна — MFE в высотах фигуры до возврата за неклайн/горизонта."""
    bo = None
    for x in range(arm + 1, hz + 1):
        if (expdir == "UP" and c[x] > neck) or (expdir == "DOWN" and c[x] < neck):
            bo = x; break
    if bo is None or height <= 0:
        return None
    ext = 0.0; mom = 0.0
    for y in range(bo, hz + 1):
        if expdir == "UP":
            ext = max(ext, h[y] - neck)
            if c[y] < neck:
                break
        else:
            ext = max(ext, neck - l[y])
            if c[y] > neck:
                break
    return ext / height, bo


def main():
    btc_1d = rs(load_1m("BTCUSDT"), "1d")["close"]
    rows = []
    null_dir = []
    for sym in SYMBOLS:
        print(f"[fig] {sym}...", flush=True)
        d1 = load_1m(sym)
        sym_1d = rs(d1, "1d")["close"]
        for tlabel, freq, tf_min in TFS:
            df = rs(d1, freq)
            n = len(df)
            c = df["close"].values; h = df["high"].values; l = df["low"].values
            atr = G.compute_atr(df)
            cap = 30 * 24 * 60 // tf_min
            figs = F.find_figures(df)
            spans = []
            for f in figs:
                arm = f.comp_conf_i
                if arm < 1 or arm >= n - 2:
                    continue
                span = max(f.comp_i - f.pivots[0].i, 10)
                hz = min(arm + min(span * 2, cap), n - 1)
                spans.append(span)
                dR = dir_barrier(c, h, l, arm, hz, atr[arm], f.expected_dir)
                ex = extent(c, h, l, arm, hz, f.neckline, f.expected_dir, f.height)
                arm_ts = df.index[arm]
                cn = sym_1d.asof(arm_ts); cp = sym_1d.asof(arm_ts - pd.Timedelta(days=10))
                htf = "UP" if (pd.notna(cn) and pd.notna(cp) and cn > cp) else "DOWN"
                reg = regime_at(btc_1d, arm_ts)
                bar_mom = (h[arm] - l[arm]) / atr[arm] if atr[arm] > 0 else 0
                rows.append({
                    "symbol": sym, "tf": tlabel, "kind": f.kind, "expdir": f.expected_dir,
                    "dirR": dR, "mfe_h": (ex[0] if ex else np.nan), "confirmed": int(ex is not None),
                    "height_atr": f.height / atr[arm] if atr[arm] > 0 else np.nan,
                    "htf_align": int(htf == f.expected_dir), "regime_align": int(reg == (1 if f.expected_dir == "UP" else -1)),
                    "bar_mom": bar_mom, "year": arm_ts.year,
                })
            # null направления: случайные бары, случайное expected_dir
            if spans and n > 60:
                for _ in range(N_NULL):
                    sp = max(10, int(RNG.choice(spans)))
                    if n - sp * 2 - 5 <= 25:
                        continue
                    b = int(RNG.integers(25, n - sp * 2 - 5))
                    hz = min(b + sp * 2, n - 1)
                    ed = str(RNG.choice(["UP", "DOWN"]))
                    null_dir.append(dir_barrier(c, h, l, b, hz, atr[b], ed))

    df = pd.DataFrame(rows)
    nd = np.array([x for x in null_dir if x != 0], float)
    df.to_csv(HERE / "figures_records.csv", index=False)

    def boot_p(mean, n, iters=3000):
        if len(nd) < 5 or n < 3:
            return 1.0
        m = nd[RNG.integers(0, len(nd), size=(iters, n))].mean(axis=1)
        return float((m >= mean).mean())

    out = []
    out.append("ЗАКОНЫ ФИГУР ТА — BTC/ETH/SOL, 1h->D, с 2020. dir: triple-barrier signed by учебник.")
    out.append(f"Всего фигур: {len(df)} | null dir mean (decided) = {nd.mean():+.3f}\n")

    out.append("=== 1) КУДА РАСКРОЕТСЯ (направление: учебная сторона первой к 1.5ATR) ===")
    out.append(f"{'фигура':20} {'n':>5} {'P(учеб)%':>8} {'dirExpR':>8} {'p':>6} {'sym+':>5} "
               f"{'bull':>6} {'bear':>6}")
    dir_laws = []
    for k in sorted(df.kind.unique()):
        s = df[(df.kind == k) & (df.dirR != 0)]
        if len(s) < 20:
            out.append(f"{k:20} n={len(s):>4}  (мало)"); continue
        m = s.dirR.mean(); pexp = (s.dirR > 0).mean() * 100
        p = boot_p(m, len(s))
        persym = s.groupby("symbol").dirR.mean(); symp = int((persym > 0).sum())
        bull = df[(df.kind == k) & (df.dirR != 0) & (df.regime_align == 1)].dirR.mean()
        bear = df[(df.kind == k) & (df.dirR != 0) & (df.regime_align == 0)].dirR.mean()
        law = m > 0.05 and p < 0.05 and symp >= 2
        out.append(f"{k:20} {len(s):>5} {pexp:>8.1f} {m:>+8.3f} {p:>6.3f} {symp:>4}/3 "
                   f"{bull:>+6.2f} {bear:>+6.2f}{'  <<ЗАКОН' if law else ''}")
        if law:
            dir_laws.append(k)

    out.append("\n=== 2) ДОКУДА ДОЙДЁТ (MFE в высотах фигуры, при подтверждённом пробое) ===")
    out.append(f"{'фигура':20} {'n':>5} {'медиана':>8} {'>=0.5x':>7} {'>=1x':>6} {'>=1.5x':>7} {'>=2x':>6}")
    conf = df[df.confirmed == 1].dropna(subset=["mfe_h"])
    for k in sorted(conf.kind.unique()):
        s = conf[conf.kind == k]
        if len(s) < 15:
            continue
        out.append(f"{k:20} {len(s):>5} {s.mfe_h.median():>8.2f} {(s.mfe_h>=0.5).mean()*100:>6.0f}% "
                   f"{(s.mfe_h>=1).mean()*100:>5.0f}% {(s.mfe_h>=1.5).mean()*100:>6.0f}% {(s.mfe_h>=2).mean()*100:>5.0f}%")
    out.append(f"  ВСЕ фигуры: медиана MFE={conf.mfe_h.median():.2f}x высоты, "
               f">=1x: {(conf.mfe_h>=1).mean()*100:.0f}%, >=2x: {(conf.mfe_h>=2).mean()*100:.0f}%")

    out.append("\n=== 3) ОТ ЧЕГО ЗАВИСИТ ЦЕЛЬ (медиана MFE/высота по факторам) ===")

    def fac(label, mask):
        s = conf[mask]
        return f"  {label:34} n={len(s):>5}  медиана={s.mfe_h.median():.2f}x  >=1x={ (s.mfe_h>=1).mean()*100:>3.0f}%" if len(s) >= 20 else f"  {label:34} (мало)"

    out.append("  -- HTF-выравнивание фигуры:")
    out.append(fac("фигура ПО HTF-тренду", conf.htf_align == 1))
    out.append(fac("фигура ПРОТИВ HTF", conf.htf_align == 0))
    out.append("  -- режим рынка:")
    out.append(fac("фигура ПО режиму", conf.regime_align == 1))
    out.append(fac("фигура ПРОТИВ режима", conf.regime_align == 0))
    out.append("  -- высота фигуры (в ATR):")
    out.append(fac("маленькая <3 ATR", conf.height_atr < 3))
    out.append(fac("средняя 3-6 ATR", (conf.height_atr >= 3) & (conf.height_atr < 6)))
    out.append(fac("большая >=6 ATR", conf.height_atr >= 6))
    out.append("  -- импульс бара-пробоя (range/ATR):")
    out.append(fac("слабый <1.5", conf.bar_mom < 1.5))
    out.append(fac("сильный >=1.5", conf.bar_mom >= 1.5))
    out.append("  -- ТФ:")
    for tf in ["1h", "2h", "4h", "6h", "12h", "1d"]:
        out.append(fac(f"TF={tf}", conf.tf == tf))

    out.append("\n=== СИНТЕЗ ===")
    out.append(f"  Фигуры с законом НАПРАВЛЕНИЯ (учеб. сторона бьёт случай): {dir_laws if dir_laws else 'НЕТ'}")
    out.append(f"  Медиана хода ВСЕХ фигур = {conf.mfe_h.median():.2f}x высоты — это и есть реалистичный measured-move.")

    rep = HERE / "figures_report.txt"
    rep.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))
    print(f"\n[fig] -> {rep.name}")


if __name__ == "__main__":
    main()
