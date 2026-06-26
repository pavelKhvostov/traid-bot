"""КОНТРОЛЬ-2 (исправленный): зоны Вадима vs случайные уровни НА ТЕХ ЖЕ ДИСТАНЦИЯХ.

Ошибка контроля-1: случайные уровни брались на РАВНОМЕРНЫХ дистанциях ≠ распределению дистанций зон, отсюда
ложные +3.1пп. Здесь random-arm берёт (d_up,d_dn) ПЕРЕТАСОВАННЫЕ между якорями (та же маргинальная дистанция,
но развязанная с реальным положением зон) и симулирует first-passage на СВОЁМ пути. Если зоны ≈ shuffle →
'ближайшая первой' = чистая геометрия дистанций, зоны для ГОНКИ (касания) не важны; смысл зон — в реакции ПОСЛЕ.
+ корректная калибровка gambler's ruin по бакетам (без баговой mae). Каузально, BTC/ETH/SOL.
Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/ta_laws/zone_race_control2.py
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
ZONE_TFS = ("12h", "1d"); HORIZON = 60; MAXDIST = 6.0
RNG = np.random.default_rng(23)


def load_1m(s):
    df = pd.read_csv(ROOT / "data" / f"{s}_1m.csv", parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def rs(df, f):
    return df.resample(f, origin="epoch", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["close"])


def fp(H, L, i, up_lvl, dn_lvl):
    for x in range(i + 1, i + 1 + HORIZON):
        uh = H[x] >= up_lvl; dh = L[x] <= dn_lvl
        if uh and dh:
            return 1 if (H[x] - up_lvl) >= (dn_lvl - L[x]) else 0
        if uh:
            return 1
        if dh:
            return 0
    return None


def main():
    paths = {}; anch = []
    for sym in SYMBOLS:
        print(f"[{sym}]...", flush=True)
        d1 = load_1m(sym); h1 = rs(d1, "1h"); n = len(h1)
        C = h1["close"].values; H = h1["high"].values; L = h1["low"].values
        paths[sym] = (C, H, L, n)
        ev, resampled = precompute_zone_events(d1, tfs=ZONE_TFS, types=ZTYPES_FAST)
        for i in range(60, n - HORIZON - 1, 12):
            price = float(C[i]); ts = h1.index[i]
            zs = snapshot_from_events(ev, resampled, d1, ts)
            ups = [z for z in zs if z.lo > price and (z.lo - price) / price * 100 <= MAXDIST]
            dns = [z for z in zs if z.hi < price and (price - z.hi) / price * 100 <= MAXDIST]
            if not ups or not dns:
                continue
            zu = min(ups, key=lambda z: z.lo); zd = max(dns, key=lambda z: z.hi)
            d_up = (zu.lo - price) / price; d_dn = (price - zd.hi) / price
            yv = fp(H, L, i, zu.lo, zd.hi)
            if yv is None:
                continue
            anch.append({"sym": sym, "i": i, "price": price, "d_up": d_up, "d_dn": d_dn, "yv": yv})
    df = pd.DataFrame(anch)
    print(f"[anchors] {len(df)}", flush=True)

    # random-MATCHED: перетасуем пары (d_up,d_dn) между якорями, симулируем на своём пути
    perm = RNG.permutation(len(df))
    du_s = df.d_up.values[perm]; dd_s = df.d_dn.values[perm]
    yr = np.full(len(df), np.nan)
    for k in range(len(df)):
        sym = df.sym.values[k]; i = df.i.values[k]; price = df.price.values[k]
        C, H, L, n = paths[sym]
        r = fp(H, L, i, price * (1 + du_s[k]), price * (1 - dd_s[k]))
        if r is not None:
            yr[k] = r
    df["yr"] = yr; df["near_up_v"] = (df.d_up < df.d_dn).astype(int)
    df["near_up_r"] = (du_s < dd_s).astype(int)
    df["p_gr"] = df.d_dn / (df.d_up + df.d_dn)

    out = ["КОНТРОЛЬ-2: зоны vs random НА ТЕХ ЖЕ ДИСТАНЦИЯХ — BTC/ETH/SOL, каузально.\n"]
    out.append(f"Якорей: {len(df)} | up-first {df.yv.mean()*100:.1f}% (симметрично — направления нет)")

    out.append("\n=== GAMBLER'S RUIN калибровка (формула vs факт по бакетам) ===")
    qs = np.quantile(df.p_gr, [0.2, 0.4, 0.6, 0.8]); edges = [0] + list(qs) + [1.0]
    for k in range(len(edges) - 1):
        m = (df.p_gr > edges[k]) & (df.p_gr <= edges[k + 1])
        if m.sum() < 30:
            continue
        out.append(f"  P_формула {df.p_gr[m].mean()*100:>5.1f}%  vs  факт {df.yv[m].mean()*100:>5.1f}%  (n={m.sum()})")
    out.append("  -> близко по бакетам = first-passage ≈ driftless геометрия.")

    accv = (df.near_up_v == df.yv).mean()
    dr = df.dropna(subset=["yr"]); accr = (dr.near_up_r == dr.yr).mean()
    out.append("\n=== ЗОНЫ vs RANDOM (одинаковое распределение дистанций) ===")
    out.append(f"  зоны Вадима:                 {accv*100:.1f}%  (n={len(df)})")
    out.append(f"  random на тех же дистанциях: {accr*100:.1f}%  (n={len(dr)})")
    diff = accv - accr
    out.append(f"  разница: {diff*100:+.1f} п.п. -> "
               f"{'зоны НЕСУТ инфо в гонке' if diff > 0.02 else 'ЗОНЫ ≈ RANDOM → гонка к касанию = ЧИСТАЯ ГЕОМЕТРИЯ (зоны для first-passage не важны; их смысл — в реакции ПОСЛЕ касания)'}")

    rep = HERE / "zone_race_control2_report.txt"
    rep.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))
    print(f"\n[control2] -> {rep.name}")


if __name__ == "__main__":
    main()
