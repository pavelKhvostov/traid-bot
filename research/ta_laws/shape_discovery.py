"""ОТКРЫТИЕ ПАТТЕРНОВ ИЗ ДАННЫХ (а не из учебника).

Идея: нарезать историю окнами фикс. длины, нормировать форму (z-score + ресэмпл к D точкам),
кластеризовать формы (KMeans) -> каждый кластер = повторяющийся «архетип формы», который рынок
рисует сам. Затем для каждого кластера измерить ИСХОД после окна (triple-barrier ±1.5ATR: вверх/вниз
первым, симметрично) + NULL (случайные окна) + cross-asset знак + год-стабильность.
Кластеры, чей исход бьёт null И согласован 3/3 по символам -> ВЫВЕДЕННЫЕ паттерны (часть совпадёт
с учебником, часть — новые). Печатает каталог + рисует центроиды (формы) с их прогностикой.

BTC/ETH/SOL, TFs 1h/4h/1d, с 2020. Каузально: arm = конец окна, исход строго в будущем.
Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/ta_laws/shape_discovery.py
Выход: research/ta_laws/shapes_report.txt + discovered_shapes.png + shape_records.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
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
TFS = [("1h", "1h", 60), ("4h", "4h", 240), ("1d", "1d", 1440)]
W = 24          # длина окна (баров)
D = 20          # точек в нормированной форме
STEP = 12       # шаг окна (50% перекрытие)
TB_ATR = 1.5
K = 16          # число кластеров-архетипов
N_NULL = 4000
RNG = np.random.default_rng(29)


def load_1m(sym):
    df = pd.read_csv(ROOT / "data" / f"{sym}_1m.csv", parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def rs(df, freq):
    return df.resample(freq, origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["close"])


def shape_vec(seg):
    """z-score + ресэмпл к D точкам -> форма (инвариант к уровню/масштабу)."""
    s = (seg - seg.mean())
    sd = s.std()
    if sd <= 0:
        return None
    s = s / sd
    xp = np.linspace(0, 1, len(s))
    xq = np.linspace(0, 1, D)
    return np.interp(xq, xp, s)


def future_R(c, h, l, arm, hz, atr_a):
    """+1 если верхний барьер 1.5ATR первым, -1 если нижний, 0 если ни один (симметрично)."""
    if atr_a <= 0:
        return 0.0
    base = c[arm]; up = base + TB_ATR * atr_a; dn = base - TB_ATR * atr_a
    for x in range(arm + 1, hz + 1):
        u = h[x] >= up; d = l[x] <= dn
        if u and d:
            return 1.0 if (h[x] - base) <= (base - l[x]) else -1.0  # грубо: ближе верх -> вверх
        if u:
            return 1.0
        if d:
            return -1.0
    return 0.0


def main():
    btc_1d = rs(load_1m("BTCUSDT"), "1d")["close"]

    def regime(ts):
        a = btc_1d.asof(ts); b = btc_1d.asof(ts - pd.Timedelta(days=30))
        return (1 if a > b else -1) if (pd.notna(a) and pd.notna(b) and b > 0) else 0

    vecs, meta, null_R = [], [], []
    for sym in SYMBOLS:
        print(f"[shape] {sym}...", flush=True)
        d1 = load_1m(sym)
        for tlabel, freq, tf_min in TFS:
            df = rs(d1, freq)
            n = len(df)
            c = df["close"].values; h = df["high"].values; l = df["low"].values
            atr = G.compute_atr(df)
            cap = 30 * 24 * 60 // tf_min
            for i0 in range(0, n - W - W - 1, STEP):
                ie = i0 + W - 1
                if ie < 20:
                    continue
                v = shape_vec(c[i0:ie + 1])
                if v is None:
                    continue
                hz = min(ie + W, n - 1)
                fr = future_R(c, h, l, ie, hz, atr[ie])
                vecs.append(v)
                meta.append((sym, tlabel, df.index[ie].year, regime(df.index[ie]), fr))
            # null: случайные окна того же горизонта
            for _ in range(N_NULL // (len(SYMBOLS) * len(TFS))):
                if n - W - 5 <= 25:
                    continue
                b = int(RNG.integers(25, n - W - 1))
                null_R.append(future_R(c, h, l, b, min(b + W, n - 1), atr[b]))

    X = np.array(vecs)
    M = pd.DataFrame(meta, columns=["symbol", "tf", "year", "regime", "fr"])
    nv = np.array([x for x in null_R], float)
    print(f"[shape] окон {len(X)}, null {len(nv)}; кластеризую K={K}...", flush=True)

    from sklearn.cluster import KMeans
    km = KMeans(n_clusters=K, n_init=6, random_state=0)
    lab = km.fit_predict(X)
    M["cl"] = lab

    def boot_p_two(mean, k, iters=4000):
        if len(nv) < 5 or k < 3:
            return 1.0
        m = nv[RNG.integers(0, len(nv), size=(iters, k))].mean(axis=1)
        base = nv.mean()
        return float((np.abs(m - base) >= abs(mean - base)).mean())

    base_null = nv.mean()
    rows = []
    for cl in range(K):
        s = M[M.cl == cl]
        if len(s) < 50:
            continue
        m = s.fr.mean()
        p = boot_p_two(m, len(s))
        persym = s.groupby("symbol").fr.mean()
        sym_sign = int((np.sign(persym - base_null) == np.sign(m - base_null)).sum())
        yrs = s.groupby("year").fr.mean()
        yr_sign = int((np.sign(yrs - base_null) == np.sign(m - base_null)).sum())
        rows.append(dict(cl=cl, n=len(s), fr=m, edge=m - base_null, p=p,
                         symp=sym_sign, yrp=yr_sign, yrtot=yrs.size,
                         centroid=km.cluster_centers_[cl]))
    rows.sort(key=lambda r: abs(r["edge"]), reverse=True)

    M.drop(columns=[]).to_csv(HERE / "shape_records.csv", index=False)

    out = []
    out.append("ОТКРЫТИЕ ПАТТЕРНОВ ИЗ ДАННЫХ — BTC/ETH/SOL, TFs 1h/4h/1d, с 2020.")
    out.append(f"Окон: {len(X)} | null fr (база/дрейф) = {base_null:+.3f} | K={K}, окно {W} баров, форма {D} точек.")
    out.append("fr = +1 если вверх первым к 1.5ATR, -1 вниз. edge = fr кластера − null. "
               "Паттерн = |edge|>0.06 И p<0.05 И sym 3/3.\n")
    out.append(f"{'кл':>3} {'n':>5} {'fr':>7} {'edge':>7} {'p':>6} {'sym':>4} {'год+':>6}  вердикт")
    laws = []
    for r in rows:
        law = abs(r["edge"]) > 0.06 and r["p"] < 0.05 and r["symp"] == 3
        tag = ("<< ПАТТЕРН " + ("BULL" if r["edge"] > 0 else "BEAR")) if law else ""
        out.append(f"{r['cl']:>3} {r['n']:>5} {r['fr']:>+7.3f} {r['edge']:>+7.3f} {r['p']:>6.3f} "
                   f"{r['symp']:>3}/3 {r['yrp']:>3}/{r['yrtot']}  {tag}")
        if law:
            laws.append(r)

    def describe(cen):
        q = D // 4
        start_sl = cen[q] - cen[0]
        end_sl = cen[-1] - cen[-q - 1]
        overall = cen[-1] - cen[0]
        imax = int(np.argmax(cen)); imin = int(np.argmin(cen))
        pmax, pmin = imax / (D - 1), imin / (D - 1)
        # закругление на конце: общий рост, но конец заваливается (или наоборот)
        if overall > 0.4 and end_sl < -0.1:
            return "рост с ЗАКРУГЛЕНИЕМ на верху (rolling top / истощение)"
        if overall < -0.4 and end_sl > 0.1:
            return "падение с РАЗВОРОТОМ вверх в конце (базирование/пружина)"
        if pmin > 0.55 and end_sl > 0.3:
            return "провал + резкий РЫВОК вверх в конце (J-launch / higher-low)"
        if pmax > 0.55 and end_sl < -0.3:
            return "взлёт + резкий слом вниз в конце (blow-off / выброс)"
        if cen[D // 2] < cen[0] - 0.3 and cen[D // 2] < cen[-1] - 0.3:
            return "U-образная (чаша/дно)"
        if cen[D // 2] > cen[0] + 0.3 and cen[D // 2] > cen[-1] + 0.3:
            return "∩-образная (купол)"
        return ("устойчивый рост" if overall > 0.5 else "устойчивое падение" if overall < -0.5 else "боковик/сложная")

    out.append(f"\nНайдено робастных паттернов-форм: {len(laws)}")
    for r in laws:
        cen = r["centroid"]
        out.append(f"  кл {r['cl']}: {describe(cen)} -> "
                   f"{'ВВЕРХ' if r['edge']>0 else 'ВНИЗ'} (edge {r['edge']:+.3f}, p={r['p']:.3f}, n={r['n']})")
    # описать и пограничные (3/3, p<0.15) как кандидаты
    cand = [r for r in rows if r["symp"] == 3 and 0.05 <= r["p"] < 0.15 and abs(r["edge"]) > 0.04
            and r not in laws]
    if cand:
        out.append("  Кандидаты (3/3, p<0.15):")
        for r in cand:
            out.append(f"    кл {r['cl']}: {describe(r['centroid'])} -> "
                       f"{'ВВЕРХ' if r['edge']>0 else 'ВНИЗ'} (edge {r['edge']:+.3f}, p={r['p']:.3f}, n={r['n']})")

    # график центроидов
    cols = 4; rows_n = (K + cols - 1) // cols
    fig, axs = plt.subplots(rows_n, cols, figsize=(16, 3 * rows_n))
    by_cl = {r["cl"]: r for r in rows}
    for cl in range(K):
        ax = axs[cl // cols][cl % cols]
        if cl in by_cl:
            r = by_cl[cl]
            law = abs(r["edge"]) > 0.06 and r["p"] < 0.05 and r["symp"] == 3
            col = ("#1a9850" if r["edge"] > 0 else "#d73027") if law else "#888"
            ax.plot(r["centroid"], color=col, lw=2.4)
            ax.set_title(f"кл{cl} n={r['n']} edge={r['edge']:+.3f}\np={r['p']:.3f} sym{r['symp']}/3"
                         + ("  ПАТТЕРН" if law else ""), fontsize=8,
                         color=(col if law else "#444"))
        ax.axhline(0, color="#ccc", lw=0.6); ax.set_xticks([]); ax.set_yticks([])
    fig.suptitle(f"Выведенные из данных формы (центроиды) — зелёный=BULL, красный=BEAR паттерн (n окон {len(X)})",
                 fontsize=13)
    fig.tight_layout()
    fig.savefig(HERE / "discovered_shapes.png", dpi=120)
    out.append(f"\n[график] discovered_shapes.png")

    rep = HERE / "shapes_report.txt"
    rep.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))
    print(f"\n[shape] -> {rep.name}")


if __name__ == "__main__":
    main()
