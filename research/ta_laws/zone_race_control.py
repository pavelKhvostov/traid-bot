"""КОНТРОЛЬ: «гонка зон» — это закон рынка или просто gambler's ruin (геометрия)?

Возражение: «ближайшая первой» может быть чистой теоремой о первом достижении (driftless), а не свойством
зон Вадима. Тест:
  1) GAMBLER'S RUIN калибровка: предсказание driftless P(up-first)=d_down/(d_up+d_down). Если actual≈формула →
     дрейфа нет, всё решает геометрия расстояний.
  2) ЗОНЫ vs СЛУЧАЙНЫЕ УРОВНИ: на тех же якорях ставим случайные up/down уровни (расст. ~ как у зон) и меряем
     ту же first-passage точность «ближайший первым». Если зоны ≈ случайные → зоны для гонки НЕ важны (касание
     = геометрия; смысл зоны — в реакции ПОСЛЕ, не в гонке).
  3) Симметрия: up-first ≈ 50%? (тогда направления нет — снимает «рынок всегда рос/падал»).
Каузально, BTC/ETH/SOL.
Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/ta_laws/zone_race_control.py
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
from research.smc_adapter import precompute_zone_events, snapshot_from_events, ZTYPES_FAST  # noqa: E402

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
ZONE_TFS = ("12h", "1d")
HORIZON = 60
MAXDIST = 6.0
RNG = np.random.default_rng(17)


def load_1m(s):
    df = pd.read_csv(ROOT / "data" / f"{s}_1m.csv", parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def rs(df, f):
    return df.resample(f, origin="epoch", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["close"])


def first_passage(H, L, i, up_lvl, dn_lvl):
    for x in range(i + 1, i + 1 + HORIZON):
        uh = H[x] >= up_lvl; dh = L[x] <= dn_lvl
        if uh and dh:
            return 1 if (H[x] - up_lvl) >= (dn_lvl - L[x]) else 0  # грубо: кто дальше пробил
        if uh:
            return 1
        if dh:
            return 0
    return None


def main():
    rows = []
    for sym in SYMBOLS:
        print(f"[{sym}]...", flush=True)
        d1 = load_1m(sym); h1 = rs(d1, "1h"); n = len(h1)
        C = h1["close"].values; H = h1["high"].values; L = h1["low"].values
        ev, resampled = precompute_zone_events(d1, tfs=ZONE_TFS, types=ZTYPES_FAST)
        for i in range(60, n - HORIZON - 1, 12):
            ts = h1.index[i]; price = float(C[i])
            zs = snapshot_from_events(ev, resampled, d1, ts)
            ups = [z for z in zs if z.lo > price and (z.lo - price) / price * 100 <= MAXDIST]
            dns = [z for z in zs if z.hi < price and (price - z.hi) / price * 100 <= MAXDIST]
            if not ups or not dns:
                continue
            zu = min(ups, key=lambda z: z.lo); zd = max(dns, key=lambda z: z.hi)
            d_up = (zu.lo - price) / price; d_dn = (price - zd.hi) / price
            yv = first_passage(H, L, i, zu.lo, zd.hi)
            if yv is None:
                continue
            # СЛУЧАЙНЫЕ уровни на расстояниях ~ как у зон (перетасуем сами зон-дистанции этого же якоря ±)
            ru = RNG.uniform(0.3, MAXDIST) / 100; rd = RNG.uniform(0.3, MAXDIST) / 100
            yr = first_passage(H, L, i, price * (1 + ru), price * (1 - rd))
            rows.append({"sym": sym, "yv": yv, "d_up": d_up, "d_dn": d_dn,
                         "p_gr": d_dn / (d_up + d_dn),               # gambler's ruin predicted P(up-first)
                         "near_up_v": int(d_up < d_dn),
                         "yr": (np.nan if yr is None else yr), "near_up_r": int(ru < rd)})
    df = pd.DataFrame(rows)
    out = ["КОНТРОЛЬ ГОНКИ ЗОН: закон рынка или gambler's ruin? — BTC/ETH/SOL, каузально.\n"]
    out.append(f"Якорей: {len(df)}")

    out.append("\n=== 3) СИММЕТРИЯ (снимает 'рынок всегда рос/падал') ===")
    out.append(f"  up-first (зоны): {df.yv.mean()*100:.1f}%  -> {'симметрично, направления НЕТ' if abs(df.yv.mean()-0.5)<0.04 else 'есть перекос'}")

    out.append("\n=== 1) GAMBLER'S RUIN калибровка: actual up-first vs driftless формула d_dn/(d_up+d_dn) ===")
    out.append(f"{'предсказ. P(up) бакет':24} {'n':>6} {'формула':>9} {'факт':>8}")
    qs = np.quantile(df.p_gr, [0.2, 0.4, 0.6, 0.8])
    edges = [0] + list(qs) + [1.0]
    for k in range(len(edges) - 1):
        m = (df.p_gr > edges[k]) & (df.p_gr <= edges[k + 1])
        if m.sum() < 30:
            continue
        out.append(f"  ({edges[k]:.2f},{edges[k+1]:.2f}]{'':9} {m.sum():>6} {df.p_gr[m].mean()*100:>8.1f}% {df.yv[m].mean()*100:>7.1f}%")
    mae = (df.yv - df.p_gr).abs().mean()
    out.append(f"  Калибровка (|факт−формула| средн.): {mae:.3f} -> "
               f"{'ДРИФТА НЕТ, чистая геометрия (gambler ruin)' if mae < 0.06 else 'есть отклонение от driftless'}")

    out.append("\n=== 2) ЗОНЫ ВАДИМА vs СЛУЧАЙНЫЕ УРОВНИ (точность 'ближайший первым') ===")
    accv = (df.near_up_v == df.yv).mean()
    dr = df.dropna(subset=["yr"])
    accr = (dr.near_up_r == dr.yr).mean()
    out.append(f"  зоны Вадима:      {accv*100:.1f}%  (n={len(df)})")
    out.append(f"  случайные уровни: {accr*100:.1f}%  (n={len(dr)})")
    out.append(f"  разница: {(accv-accr)*100:+.1f} п.п. -> "
               f"{'ЗОНЫ лучше случайных (есть смысл в гонке)' if accv > accr + 0.02 else 'ЗОНЫ ≈ СЛУЧАЙНЫЕ → гонка = геометрия, зоны для first-passage НЕ важны'}")

    out.append("\n=== ВЫВОД ===")
    out.append("  Если калибровка ~diagonal И зоны≈случайные → 'ближайшая первой' = теорема (gambler's ruin),")
    out.append("  а не закон рынка. Ценность зон — в РЕАКЦИИ ПОСЛЕ касания, не в гонке к касанию.")
    rep = HERE / "zone_race_control_report.txt"
    rep.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))
    print(f"\n[control] -> {rep.name}")


if __name__ == "__main__":
    main()
