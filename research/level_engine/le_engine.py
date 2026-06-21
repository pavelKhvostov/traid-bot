"""le_engine — оркестрация: build levels -> replay interactions -> belief -> снапшот.

ПРИЧИННОСТЬ по построению (lookahead-register #1): snapshot() СНАЧАЛА усекает вход до
df1h[index<=T] и работает только с ним -> любой срез детектора/скана физически не достаёт
строк > T. Поэтому snapshot(full_df, T) ИДЕНТИЧЕН snapshot(df<=T, T) — это адверс-тест
future-mutation (test_le_engine).

snapshot(symbol_df1h, T) -> dict со списком уровней: center/полоса/side/сила1-10/аргументы/
state/конфлюэнс. predicts_hold=False, пока валидация (le_validate) не подтвердит предиктивность.
@@JSON@@ — в схеме etap_263 (переиспользуем путь отрисовки TradingView без изменений).
"""
from __future__ import annotations
import sys, json
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import le_zones as LZ
import le_cluster as LC
import le_interact as LI
import le_belief as LB


def _load_flow(symbol="BTCUSDT"):
    """1h order-flow (volume, signed delta) для описательного absorption-фактора."""
    p = Path(__file__).resolve().parents[1] / "elements_study" / "data" / f"{symbol}_1h_flow.csv"
    if not p.exists():
        return None
    try:
        f = pd.read_csv(p, usecols=["open_time", "volume", "delta"])
        f["open_time"] = pd.to_datetime(f["open_time"], utc=True)
        return f.set_index("open_time").sort_index()
    except Exception:
        return None


def _atr1d_asof(df1h, T):
    d1 = df1h[df1h.index <= T].resample("1D").agg({"high": "max", "low": "min", "close": "last"}).dropna()
    if len(d1) < 15:
        return float("nan")
    pc = d1["close"].shift(1)
    tr = pd.concat([d1.high - d1.low, (d1.high - pc).abs(), (d1.low - pc).abs()], axis=1).max(axis=1)
    return float(tr.rolling(14).mean().iloc[-1])


def snapshot(df1h: pd.DataFrame, T: pd.Timestamp, price: float | None = None,
             window_usd: float = 15000.0, tfs: list[str] | None = None,
             with_propagation: bool = True, symbol: str = "BTCUSDT") -> dict:
    """Причинный снапшот уровней силы на момент T."""
    if df1h.index.tz is None:
        df1h = df1h.tz_localize("UTC")
    if T.tz is None:
        T = T.tz_localize("UTC")
    base = df1h[df1h.index <= T]                       # ХАРД-усечение (анти-lookahead)
    if len(base) < 50:
        return dict(symbol=None, ref_time=str(T), price=None, levels=[], predicts_hold=False)
    if price is None:
        price = float(base["close"].iloc[-1])
    atr1d = _atr1d_asof(base, T)
    atr_d = LI.daily_atr(base)
    daily_hl = base.resample("1D").agg({"high": "max", "low": "min"}).dropna()
    flow = _load_flow(symbol)
    if flow is not None:
        flow = flow[flow.index <= T]                 # причинно: поток только <=T
    raws = LZ.build_raw_zones(base, T, price=price, window_usd=window_usd, tfs=tfs, atr_d=atr_d)
    levels = LC.cluster(raws, price, atr1d)
    # interactions per level (на base<=T -> все t_resolved<=T)
    inter_map = {}
    for L in levels:
        t0 = min(pd.Timestamp(m.form_time) for m in L.members)
        inter_map[L.lid] = LI.replay_interactions(L.bottom, L.top, t0, base, atr_d)
    _kw = dict(df1h=base, atr_d=atr_d, price=price, daily_hl=daily_hl, flow=flow)
    # pass-1 belief (без graft) -> состояния
    bel = {}
    for L in levels:
        bel[L.lid] = LB.belief(L.members, inter_map[L.lid], T, level=L, **_kw)
    # pass-2: graft break-propagation (сосед пробит) + финальная сила
    out_levels = []
    by_lid = {L.lid: L for L in levels}
    for L in levels:
        nb = False
        if with_propagation:
            for nlid in (L.up_neighbor, L.down_neighbor):
                if nlid and bel.get(nlid) and bel[nlid]["state"] == "broken":
                    nb = True; break
        b = LB.belief(L.members, inter_map[L.lid], T, neighbor_broken=nb, level=L, **_kw)
        if b is None:
            continue
        s10, raw, conf = LB.strength10(b)
        out_levels.append(dict(
            lid=L.lid, center=round(L.center, 1), bottom=round(L.bottom, 1), top=round(L.top, 1),
            side=L.side, strength=s10, strength_raw=round(raw, 3), confidence=round(conf, 1),
            state=b["state"], dist_pct=round((L.center / price - 1) * 100, 2),
            n_zones=L.n_zones, tfs=sorted(L.tfs), kinds=sorted(L.kinds),
            rejects=b["rejects"], breaks=b["breaks"], flips=b["flips"],
            has_magnet=b["has_magnet"], has_liquidity=b["has_liquidity"],
            args=LB.explain(L, b)))
    out_levels.sort(key=lambda d: -d["center"])
    return dict(symbol=symbol, ref_time=str(T), price=round(price, 1),
                window_usd=window_usd, predicts_hold=False, n_levels=len(out_levels),
                levels=out_levels)


def main():
    import argparse
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from data_manager import load_df
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol", nargs="?", default="BTCUSDT")
    ap.add_argument("--at", default=None, help="ISO time (default: last bar)")
    ap.add_argument("--top", type=int, default=12)
    a = ap.parse_args()
    df = load_df(a.symbol, "1h")
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    T = pd.Timestamp(a.at, tz="UTC") if a.at else df.index[-1]
    snap = snapshot(df, T)
    print(f"{a.symbol} price {snap['price']:,.0f} @ {snap['ref_time'][:16]} · {snap['n_levels']} levels "
          f"(predicts_hold={snap['predicts_hold']})")
    ranked = sorted(snap["levels"], key=lambda d: (-d["strength"], -d["confidence"]))[:a.top]
    for L in ranked:
        print(f"\n[{L['strength']}/10] {L['center']:,.0f} [{L['bottom']:,.0f}-{L['top']:,.0f}] "
              f"{L['side']} ({L['dist_pct']:+.1f}%) state={L['state']} R/B/F={L['rejects']}/{L['breaks']}/{L['flips']}")
        for arg in L["args"]:
            print("   ", arg)
    print("\n@@JSON@@" + json.dumps(snap))


if __name__ == "__main__":
    main()
