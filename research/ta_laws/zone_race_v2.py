"""ГОНКА ЗОН v2 — бьёт ли МОМЕНТУМ/СКОРОСТЬ дистанцию в задаче «какая зона первой».

v1 показал: first-passage ≈ дистанция (73%), зона-сила не добавляет. Гипотеза v2: дистанцию может побить
только краткосрочный ДРЕЙФ (моментум/скорость подхода) — и видно это ТОЛЬКО в НЕОДНОЗНАЧНОМ режиме
(зоны почти равноудалены, |dist_ratio| мал, baseline≈50%). Там и проверяем.

Фичи (каузально): dist_ratio (геометрия) + velocity_3/6/12 (signed ret/ATR) + accel + range_pos + str/mtf.
Тот же самоисправляющийся онлайн-предиктор (OnlineLaw из zone_race_module). КЛЮЧ: стратификация по |dist_ratio|
— точность в равноудалённом режиме vs 50%. Метрика без AUC.

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/ta_laws/zone_race_v2.py
Выход: research/ta_laws/zone_race_v2_report.txt
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
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(HERE))
import geometry as G  # noqa: E402
from research.smc_adapter import (precompute_zone_events, snapshot_from_events, ROLE, TF_W, ZTYPES_FAST)  # noqa: E402
from zone_race_module import OnlineLaw  # noqa: E402

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
ZONE_TFS = ("12h", "1d")
HORIZON = 60
MAXDIST = 6.0
FEATS = ["dist_ratio", "vel3", "vel6", "vel12", "accel", "range_pos", "str_diff", "mtf_up"]


def load_1m(s):
    df = pd.read_csv(ROOT / "data" / f"{s}_1m.csv", parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def rs(df, f):
    return df.resample(f, origin="epoch", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["close"])


def zstr(z):
    mat = 1.0 if 2 <= z.age_bars <= 40 else (0.7 if z.age_bars <= 120 else 0.4)
    rw = {"block": 1.0, "liquidity": 0.7, "inefficiency": 0.6}[ROLE.get(z.type, "block")]
    return TF_W.get(z.tf, 1.0) * mat * rw


def build(sym):
    d1 = load_1m(sym); h1 = rs(d1, "1h"); n = len(h1)
    C = h1["close"].values; H = h1["high"].values; L = h1["low"].values
    atr = G.compute_atr(h1)
    mtf = {"1h": (h1["close"], pd.Timedelta(hours=10)), "4h": (rs(d1, "4h")["close"], pd.Timedelta(hours=40)),
           "1d": (rs(d1, "1d")["close"], pd.Timedelta(days=10))}
    ev, resampled = precompute_zone_events(d1, tfs=ZONE_TFS, types=ZTYPES_FAST)
    out = []
    for i in range(60, n - HORIZON - 1, 12):
        ts = h1.index[i]; price = float(C[i]); a_pct = atr[i] / price * 100
        if a_pct <= 0:
            continue
        zs = snapshot_from_events(ev, resampled, d1, ts)
        ups = [z for z in zs if z.lo > price and (z.lo - price) / price * 100 <= MAXDIST]
        dns = [z for z in zs if z.hi < price and (price - z.hi) / price * 100 <= MAXDIST]
        if not ups or not dns:
            continue
        zu = min(ups, key=lambda z: z.lo); zd = max(dns, key=lambda z: z.hi)
        d_up = (zu.lo - price) / price * 100; d_dn = (price - zd.hi) / price * 100
        first = None
        for x in range(i + 1, i + 1 + HORIZON):
            uh = H[x] >= zu.lo; dh = L[x] <= zd.hi
            if uh and dh:
                first = 1 if (H[x] - price) <= (price - L[x]) else 0; break
            if uh:
                first = 1; break
            if dh:
                first = 0; break
        if first is None:
            continue
        # моментум/скорость (signed ret в ATR-долях), каузально
        v3 = (C[i] - C[i - 3]) / C[i - 3] * 100 / a_pct
        v6 = (C[i] - C[i - 6]) / C[i - 6] * 100 / a_pct
        v12 = (C[i] - C[i - 12]) / C[i - 12] * 100 / a_pct
        lo50 = L[max(0, i - 50):i + 1].min(); hi50 = H[max(0, i - 50):i + 1].max()
        rpos = (price - lo50) / (hi50 - lo50) if hi50 > lo50 else 0.5
        mtf_up = sum(int(s.asof(ts) > s.asof(ts - td)) for s, td in mtf.values())
        out.append({"sym": sym, "ts": ts, "y": first,
                    "dist_ratio": (d_dn - d_up) / (d_dn + d_up + 1e-9),
                    "vel3": v3, "vel6": v6, "vel12": v12, "accel": v3 - v12,
                    "range_pos": rpos, "str_diff": zstr(zu) - zstr(zd), "mtf_up": float(mtf_up)})
    return out


def main():
    alls = []
    for s in SYMBOLS:
        print(f"[{s}] build...", flush=True); alls += build(s)
    df = pd.DataFrame(alls).sort_values("ts").reset_index(drop=True)
    print(f"[samples] {len(df)} up-first {df.y.mean()*100:.0f}%", flush=True)
    X = df[FEATS].values; y = df.y.values.astype(int)
    base = (df.dist_ratio.values > 0).astype(int)
    law = OnlineLaw(FEATS)
    preds = np.zeros(len(df), int)
    for i in range(len(df)):
        pr, _ = law.step(X[i], y[i], {"i": i, "sym": df.sym.values[i],
                                      "ts": df.ts.values[i].astype('datetime64[s]').item()})
        preds[i] = pr
    warm = 200
    m = np.arange(len(df)) >= warm
    acc = (preds[m] == y[m]).mean(); bacc = (base[m] == y[m]).mean()

    out = ["ГОНКА ЗОН v2 — бьёт ли моментум дистанцию? (first-passage, само-исправление, БЕЗ AUC)"]
    out.append(f"Якорей {len(df)}, up-first {df.y.mean()*100:.0f}%, фичи: дистанция + скорость/моментум.\n")
    out.append("=== ОБЩАЯ ТОЧНОСТЬ ===")
    out.append(f"  baseline (ближайшая первой): {bacc*100:.1f}%")
    out.append(f"  нейро v2 (+моментум):        {acc*100:.1f}%  (лифт {(acc-bacc)*100:+.1f} п.п.)")

    # КЛЮЧ: стратификация по |dist_ratio| — где геометрия НЕ решает
    out.append("\n=== СТРАТИФИКАЦИЯ по |dist_ratio| (где дистанция теряет силу) ===")
    out.append(f"{'режим |dist_ratio|':24} {'n':>6} {'baseline':>9} {'нейро v2':>9} {'лифт пп':>8}")
    adr = np.abs(df.dist_ratio.values)
    qs = np.quantile(adr[m], [0.33, 0.66])
    bins = [("равноудал. (низ трети)", adr <= qs[0]),
            ("средн.", (adr > qs[0]) & (adr <= qs[1])),
            ("явная ближе (верх трети)", adr > qs[1])]
    ambiguous_lift = None
    for name, msk in bins:
        mm = msk & m
        if mm.sum() < 30:
            continue
        b = (base[mm] == y[mm]).mean(); a = (preds[mm] == y[mm]).mean()
        out.append(f"{name:24} {mm.sum():>6} {b*100:>8.1f}% {a*100:>8.1f}% {(a-b)*100:>+7.1f}")
        if "равноудал" in name:
            ambiguous_lift = (a, b, mm)

    # в равноудалённом режиме: какая фича коррелирует с исходом (именуем закон)
    out.append("\n=== В РАВНОУДАЛЁННОМ РЕЖИМЕ: что предсказывает (корреляция фичи с up-first) ===")
    if ambiguous_lift:
        _, _, amask = ambiguous_lift
        sub = df[amask]
        for f in FEATS:
            c = np.corrcoef(sub[f].values, sub.y.values)[0, 1]
            out.append(f"  {f:12} corr={c:+.3f}")

    out.append("\n=== ВЫВЕДЕННЫЕ ВЕСА (что модуль понял) ===")
    for j in np.argsort(-np.abs(law.w)):
        out.append(f"  {FEATS[j]:12} w={law.w[j]:+.3f}")

    out.append("\n=== САМО-КОРРЕКЦИИ (первые) ===")
    out += ["  " + l for l in law.log[:5]]

    out.append("\n=== ВЕРДИКТ ===")
    if ambiguous_lift:
        a, b, _ = ambiguous_lift
        real = a > 0.55 and a > b + 0.02
        out.append(f"  Равноудалённый режим: нейро {a*100:.1f}% vs baseline {b*100:.1f}% -> "
                   f"{'МОМЕНТУМ БЬЁТ геометрию (есть сигнал сверх дистанции!)' if real else 'момент НЕ бьёт ~50% — сигнала сверх дистанции нет'}")
    out.append("  Общий вывод: дистанция доминирует везде; решающая проверка — равноудалённый режим выше.")

    rep = HERE / "zone_race_v2_report.txt"
    rep.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))
    print(f"\n[v2] -> {rep.name}")


if __name__ == "__main__":
    main()
