"""etap_253 — ICT-анализ FVG-формаций на 12h/1d/2d/3d: что было ПОСЛЕ.

Фокус: «двойной FVG» (два ПОСЛЕДОВАТЕЛЬНЫХ FVG одного направления = displacement-leg,
как сейчас вырисовывается на D). Эмпирика forward-исхода vs одиночный FVG vs база.

Канон FVG (c1-c2-c3, подтверждается на close c3, БЕЗ лукахеда):
  bull: c1.high < c3.low  → зона [c1.high, c3.low]
  bear: c1.low  > c3.high → зона [c3.high, c1.low]
Double = на баре i подтверждён FVG, И на i-1 подтверждён FVG того же направления.

Forward-метрики (N баров вперёд на том же ТФ):
  dir_next  — close[i+1] в сторону FVG? (тест стены «направление=монетка»)
  cont_N    — close[i+N] вышел за close[i] в сторону FVG? (продолжение)
  fill_N    — цена вернулась В зону FVG за N баров? (митигация, ICT: FVG тянет назад)
  fwd_rng   — диапазон N баров / трейлинг-медиана (расширение хода)
Сравнение: double vs single vs ВСЕ бары (база). Плюс per-year устойчивость направления.

Запуск: venv/Scripts/python.exe research/daily_engine/etap_253_ict_fvg_formations.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from data_manager import compose_from_base, load_df

SYMS = ["BTCUSDT", "ETHUSDT"]
NFWD = 5            # баров вперёд для cont/fill/range


def tfs(sym):
    h1 = load_df(sym, "1h"); d1 = load_df(sym, "1d")
    for d in (h1, d1):
        if d.index.tz is None: d.index = d.index.tz_localize("UTC")
    return {
        "12h": compose_from_base(h1, "12h"),
        "1d": d1,
        "2d": compose_from_base(d1, "2d"),
        "3d": compose_from_base(d1, "3d"),
    }


def find_fvg(df):
    """Список FVG: (i_c3, dir, lo, hi). i_c3 — индекс бара подтверждения (c3)."""
    H, L = df["high"].values, df["low"].values
    out = []
    for i in range(2, len(df)):
        if H[i-2] < L[i]:        # bull
            out.append((i, +1, H[i-2], L[i]))
        elif L[i-2] > H[i]:      # bear
            out.append((i, -1, H[i], L[i-2]))
    return out


def analyse(sym, tf, df):
    if len(df) < 60:
        return None
    o, h, l, c = (df[x].values for x in ["open", "high", "low", "close"])
    fvgs = find_fvg(df)
    by_i = {i: (d, lo, hi) for i, d, lo, hi in fvgs}
    rng = (h - l)
    med_rng = pd.Series(rng).rolling(20).median().shift(1).values

    rows = []
    for i, d, lo, hi in fvgs:
        if i + NFWD >= len(df) or i < 21:
            continue
        is_double = (i-1) in by_i and by_i[i-1][0] == d
        # forward
        dir_next = int(np.sign(c[i+1] - c[i]) == d)
        cont = int((c[i+NFWD] - c[i]) * d > 0)
        # fill: цена входит в зону FVG за NFWD баров (low<=hi и high>=lo)
        fill = int(any(l[j] <= hi and h[j] >= lo for j in range(i+1, i+1+NFWD)))
        fwd = (np.max(h[i+1:i+1+NFWD]) - np.min(l[i+1:i+1+NFWD]))
        fwd_ratio = fwd / med_rng[i] if med_rng[i] and med_rng[i] > 0 else np.nan
        rows.append(dict(t=df.index[i], year=df.index[i].year, dir=d, double=is_double,
                         dir_next=dir_next, cont=cont, fill=fill, fwd_ratio=fwd_ratio))
    r = pd.DataFrame(rows)
    if len(r) < 20:
        return None
    # база — все бары (next-bar up-rate)
    base_dir = (np.sign(np.diff(c)) > 0).mean()
    def agg(g):
        return dict(n=len(g), dir_next=g.dir_next.mean(), cont=g.cont.mean(),
                    fill=g.fill.mean(), fwd=g.fwd_ratio.median())
    res = {"single": agg(r[~r.double]), "double": agg(r[r.double]), "base_up": base_dir}
    # направление double по годам (устойчивость)
    yr = r[r.double].groupby("year").dir_next.agg(["mean", "size"])
    res["double_yr"] = [(int(y), round(m, 2), int(n)) for y, (m, n) in yr.iterrows() if n >= 3]
    return res


def current_state(sym):
    """Есть ли сейчас (на последних ЗАКРЫТЫХ дневных) double-FVG-D и формируется ли новый сегодня."""
    d1 = load_df(sym, "1d")
    if d1.index.tz is None: d1.index = d1.index.tz_localize("UTC")
    fvgs = find_fvg(d1)
    last = fvgs[-3:] if fvgs else []
    info = []
    for i, dr, lo, hi in last:
        age = len(d1) - 1 - i
        info.append(f"{d1.index[i].date()} {'bull' if dr>0 else 'bear'} [{lo:,.0f}–{hi:,.0f}] (age {age} баров)")
    return info


def main():
    for sym in SYMS:
        print("\n" + "#" * 78)
        print(f"# {sym} — ICT FVG-формации")
        print("#" * 78)
        T = tfs(sym)
        for tf, df in T.items():
            r = analyse(sym, tf, df)
            if r is None:
                print(f"\n[{tf}] мало данных"); continue
            s, d = r["single"], r["double"]
            print(f"\n[{tf}] (база next-bar up={r['base_up']:.0%})")
            print(f"  одиночный FVG: n={s['n']:>3}  dir_next={s['dir_next']:.0%}  cont{NFWD}={s['cont']:.0%}  fill{NFWD}={s['fill']:.0%}  fwd_range×={s['fwd']:.2f}")
            print(f"  ДВОЙНОЙ  FVG:  n={d['n']:>3}  dir_next={d['dir_next']:.0%}  cont{NFWD}={d['cont']:.0%}  fill{NFWD}={d['fill']:.0%}  fwd_range×={d['fwd']:.2f}")
            if r["double_yr"]:
                print(f"  double dir_next по годам: {r['double_yr']}")
        print(f"\n  ПОСЛЕДНИЕ дневные FVG ({sym}):")
        for x in current_state(sym):
            print(f"    {x}")


if __name__ == "__main__":
    main()
