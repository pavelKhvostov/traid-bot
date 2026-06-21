"""_audit_variance — эмпирический аудит дисперсии 8 факторов le_belief v2.

Цель: выяснить, какие факторы РЕАЛЬНО дифференцируют уровни, а какие — мёртвый
груз/баг (near-zero std). Строим снапшот через тот же конвейер, что и le_engine
(zones -> cluster -> interactions -> belief), но читаем СЫРЫЕ значения факторов
A,C,V,O,W,L,Q,K,B,fresh_gate из dict-а belief() для каждого уровня.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for p in (HERE, ROOT, ROOT / "research" / "daily_engine"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import etap_225_dual_dashboard as D          # noqa: E402
import le_zones as LZ                          # noqa: E402
import le_cluster as LC                        # noqa: E402
import le_interact as LI                       # noqa: E402
import le_belief as LB                         # noqa: E402

# те же факторы и веса, что в core (для контекста вклада)
FACTORS = ["A", "C", "V", "O", "W", "L", "Q", "K", "B", "fresh_gate"]
WEIGHTS = {"A": 2.4, "C": 2.4, "V": 1.0, "O": 0.8, "W": 1.0, "L": 1.0,
           "Q": 1.4, "K": -2.0, "B": 0.0, "fresh_gate": 0.0}


def build_beliefs(symbol="BTCUSDT", days=900):
    df = D.fetch(symbol, days)
    if df.index.tz is None:
        df = df.tz_localize("UTC")
    T = df.index[-1]
    price = float(df["close"].iloc[-1])

    # тот же конвейер, что snapshot()
    d1 = df.resample("1D").agg({"high": "max", "low": "min", "close": "last"}).dropna()
    pc = d1["close"].shift(1)
    tr = pd.concat([d1.high - d1.low, (d1.high - pc).abs(), (d1.low - pc).abs()], axis=1).max(axis=1)
    atr1d = float(tr.rolling(14).mean().iloc[-1])
    atr_d = LI.daily_atr(df)
    daily_hl = df.resample("1D").agg({"high": "max", "low": "min"}).dropna()

    raws = LZ.build_raw_zones(df, T, price=price, atr_d=atr_d)
    levels = LC.cluster(raws, price, atr1d)

    kw = dict(df1h=df, atr_d=atr_d, price=price, daily_hl=daily_hl)
    beliefs = []
    for L in levels:
        t0 = min(pd.Timestamp(m.form_time) for m in L.members)
        ints = LI.replay_interactions(L.bottom, L.top, t0, df, atr_d)
        b = LB.belief(L.members, ints, T, level=L, **kw)
        if b is not None:
            b["_lid"] = L.lid
            b["_center"] = L.center
            b["_width"] = L.top - L.bottom
            b["_n_zones"] = L.n_zones
            beliefs.append(b)
    return beliefs, price, atr1d, T


def summarize(beliefs):
    n = len(beliefs)
    print(f"\n{'='*78}")
    print(f"AUDIT: {n} levels | factor variance (raw belief() outputs)")
    print(f"{'='*78}")
    header = f"{'fac':<11}{'wt':>6}{'min':>9}{'max':>9}{'mean':>9}{'std':>9}{'distinct':>9}"
    print(header)
    print("-" * 78)
    stats = {}
    for f in FACTORS:
        vals = np.array([float(b[f]) for b in beliefs], dtype=float)
        rounded = np.round(vals, 2)
        distinct = len(set(rounded.tolist()))
        s = dict(min=float(vals.min()), max=float(vals.max()),
                 mean=float(vals.mean()), std=float(vals.std()),
                 distinct=distinct, vals=vals)
        stats[f] = s
        print(f"{f:<11}{WEIGHTS[f]:>6.1f}{s['min']:>9.3f}{s['max']:>9.3f}"
              f"{s['mean']:>9.3f}{s['std']:>9.3f}{distinct:>9d}")
    print("-" * 78)

    # strength range
    s10 = np.array([b["s10"] for b in beliefs])
    raw01 = np.array([b["raw01"] for b in beliefs])
    print(f"strength s10 : min {s10.min()} max {s10.max()} distinct {len(set(s10.tolist()))}")
    print(f"raw01        : min {raw01.min():.3f} max {raw01.max():.3f} std {raw01.std():.3f}")

    # touches / disp distribution (root-cause evidence)
    touches = np.array([b["touches"] for b in beliefs])
    disp = np.array([b["disp_sigma"] for b in beliefs])
    print(f"\ntouches      : min {touches.min()} max {touches.max()} "
          f"mean {touches.mean():.1f} | levels with >=3 touches: {(touches>=3).sum()}/{len(touches)}")
    print(f"disp_sigma   : min {disp.min():.3f} max {disp.max():.3f} mean {disp.mean():.3f}")

    # contribution to core (variance that actually moves strength)
    print(f"\n{'CONTRIBUTION to core (weighted) — std of weighted term':<60}")
    print("-" * 78)
    contrib = {}
    for f in FACTORS:
        if WEIGHTS[f] == 0.0:
            continue
        vals = stats[f]["vals"]
        if f in ("L", "Q"):                       # gated factors
            fg = stats["fresh_gate"]["vals"]
            term = WEIGHTS[f] * vals * fg
        else:
            term = WEIGHTS[f] * vals
        contrib[f] = float(np.std(term))
        print(f"{f:<11} weighted-term std = {np.std(term):>7.3f}  "
              f"(range {term.min():.2f}..{term.max():.2f})")
    print("-" * 78)
    order = sorted(contrib.items(), key=lambda kv: -kv[1])
    print("ranked by differentiation power (weighted std):")
    for f, c in order:
        tag = "DEAD" if c < 0.05 else ("WEAK" if c < 0.15 else "DIFFERENTIATES")
        print(f"   {f:<6} {c:>7.3f}  -> {tag}")
    return stats


def evidence_dump(beliefs, stats):
    """Печатает доказательства под конкретные гипотезы root-cause."""
    print(f"\n{'='*78}\nROOT-CAUSE EVIDENCE\n{'='*78}")

    # (a) O — разбор слагаемых на нескольких уровнях
    print("\n[O] location — раскладка по уровням (aligned, dist_val term, rnd term):")
    print("   O = clip(0.5*aligned + 0.3*clip(dist_val/3) + 0.2*max(0,rnd))")
    print("   (значения aligned/dist/rnd напрямую недоступны из belief — печатаем итог O)")
    Ovals = stats["O"]["vals"]
    print(f"   O distinct={stats['O']['distinct']}, all values: {sorted(set(np.round(Ovals,3).tolist()))}")

    # (b) W — ширина в σ
    print("\n[W] width — отношение ширины уровня к σ (wr) и сам W:")
    atrish = None
    rows = []
    for b in beliefs[:50]:
        rows.append((b["_lid"], b["_width"], b["W"]))
    widths = np.array([b["_width"] for b in beliefs])
    print(f"   level width (USD): min {widths.min():.1f} max {widths.max():.1f} "
          f"std {widths.std():.1f} distinct {len(set(np.round(widths,1).tolist()))}")
    print(f"   W distinct={stats['W']['distinct']}, values: {sorted(set(np.round(stats['W']['vals'],2).tolist()))}")

    # (c) C — HTF dominance; смотрим max_tf_w
    mtw = np.array([b["max_tf_w"] for b in beliefs])
    print("\n[C] HTF dominance — max_tf_w per level:")
    print(f"   max_tf_w: min {mtw.min():.1f} max {mtw.max():.1f} distinct {len(set(mtw.tolist()))}")
    print(f"   C distinct={stats['C']['distinct']}, "
          f"levels with C>=0.9: {(stats['C']['vals']>=0.9).sum()}/{len(beliefs)}")

    # (d) B / fresh_gate saturation
    tch = np.array([b["touches"] for b in beliefs])
    fg = stats["fresh_gate"]["vals"]
    print("\n[B] freshness gate saturation:")
    print(f"   touches>=5: {(tch>=5).sum()}/{len(tch)} | fresh_gate==0.40 (floored): "
          f"{(np.round(fg,2)==0.40).sum()}/{len(fg)}")
    print(f"   fresh_gate distinct={stats['fresh_gate']['distinct']}, "
          f"range {fg.min():.3f}..{fg.max():.3f}")

    # (e) A — origin disp distribution
    A = stats["A"]["vals"]
    disp = np.array([b["disp_sigma"] for b in beliefs])
    print("\n[A] origin displacement:")
    print(f"   disp_sigma: min {disp.min():.2f} max {disp.max():.2f} std {disp.std():.2f}")
    print(f"   A distinct={stats['A']['distinct']}, range {A.min():.2f}..{A.max():.2f}")


if __name__ == "__main__":
    sym = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT"
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 900
    beliefs, price, atr1d, T = build_beliefs(sym, days)
    print(f"{sym} price {price:,.0f} @ {str(T)[:16]} | atr1d {atr1d:,.0f} | {len(beliefs)} levels")
    stats = summarize(beliefs)
    evidence_dump(beliefs, stats)
