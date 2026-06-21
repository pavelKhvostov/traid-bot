"""Усиливает ли АНАЛИТИКА (контекст/режим) результативность ТА (форм)?

Меряем LIFT: edge голой формы (арки) -> + слой формы (изогнутость/apex) -> + слой АНАЛИТИКИ (контекст mtf,
режим). По arc_records.csv (rev_R = +1 разворот первым после дуги). Cross-asset 3/3 — критерий робастности.
Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/ta_laws/confluence_lift.py
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
A = pd.read_csv(HERE / "arc_records.csv")
A = A[A.is_null == 0].copy()
nv = pd.read_csv(HERE / "arc_records.csv")
nv = nv[nv.is_null == 1].rev_R.values
RNG = np.random.default_rng(7)


def boot_p(mean, k, iters=4000):
    if len(nv) < 5 or k < 3:
        return 1.0
    m = nv[RNG.integers(0, len(nv), size=(iters, k))].mean(axis=1)
    return float((m >= mean).mean())


# направление сделки = fade конца дуги; "против контекста" относительно сделки
A["fade_dir"] = np.where(A.end_dir == "DOWN", "UP", "DOWN")
A["against_ctx"] = np.where(A.fade_dir == "UP", A.mtf_up <= 1, A.mtf_up >= 2)
A["regime_with_fade"] = np.where(A.fade_dir == "UP", A.regime <= 0, A.regime >= 0)
shape_ok = (A.sagitta_atr >= 2.5) & (A.apex_pos >= 0.4)


def show(label, mask):
    s = A[mask]
    if len(s) < 20:
        print(f"  {label:46} n={len(s)} (мало)"); return None
    m = s.rev_R.mean(); pr = (s.rev_R > 0).mean() * 100
    symp = int((s.groupby('symbol').rev_R.mean() > 0).sum())
    p = boot_p(m, len(s))
    print(f"  {label:46} n={len(s):>5} rev_R={m:>+.3f} P(разв)={pr:>4.0f}% p={p:.3f} sym{symp}/3")
    return m


print("УСИЛИВАЕТ ЛИ АНАЛИТИКА (контекст/режим) РЕЗУЛЬТАТИВНОСТЬ ТА (форм)?")
print(f"База null rev_R = {nv.mean():+.3f}\n")

print("СЛОЙ ЗА СЛОЕМ (накопительно):")
b0 = show("0) голая арка (любая форма)", A.index == A.index)
b1 = show("1) + слой ФОРМЫ (изогнутость+apex)", shape_ok)
b2 = show("2) + слой АНАЛИТИКИ (против контекста mtf)", shape_ok & A.against_ctx)
b3 = show("3) + слой АНАЛИТИКИ (контекст + режим)", shape_ok & A.against_ctx & A.regime_with_fade)

print("\nИЗОЛЯЦИЯ ВКЛАДА АНАЛИТИКИ (на одной и той же форме):")
sf = A[shape_ok]
print(f"  форма + ПО контексту   : rev_R={sf[~sf.against_ctx].rev_R.mean():+.3f} (n={int((~sf.against_ctx).sum())})")
print(f"  форма + ПРОТИВ контекста: rev_R={sf[sf.against_ctx].rev_R.mean():+.3f} (n={int(sf.against_ctx.sum())})")

print("\nАНАЛИТИКА БЕЗ ФОРМЫ (контекст на ЛЮБОЙ арке) — несёт ли сама:")
show("контекст ПРОТИВ (любая форма)", A.against_ctx)
show("контекст ПО (любая форма)", ~A.against_ctx)

if b0 is not None and b2 is not None:
    print(f"\nLIFT: форма {b1-b0:+.3f} над голой; аналитика {b2-b1:+.3f} над формой; "
          f"итог стек {b2-b0:+.3f} над голой ({b2/max(b0,1e-9):.1f}× если b0>0).")
