"""etap_249 — РАССЛЕДОВАНИЕ 1.1.1 SWEPT: сегментация сделок по признакам → WR групп.

Сделки: detect_signals_111 + check_swept (BTC, полная история), ДЕДУП по
(signal_time, direction, fvg_zone) — pitfall: run_symbol_backtest не дедуплицирует.
Исход: fixed RR=2.2 (чистый бинарный win/loss = «винрейт»; approved-версия live).

Признаки группировки (на момент входа, без подглядывания):
  СТРУКТУРНЫЕ (из сигнала): direction, top_tf(1d/12h), fvg_macro_tf(4h/6h),
    ob_htf_tf(1h/2h), fvg_tf(15m/20m), risk_pct (ширина SL, терцили).
  АНАЛИТИКА (модуль v2): day_type-состояние (etap_217), confluence
    (counter-trend/continuation/rotation), сессия (Asia/London/NY), утренний
    eff_ratio (рваный/гладкий день, etap_245), gauge (сколько хода пройдено к входу).

Выводим ~15 групп (≤20): WR + n + PnL(R, RR2.2) + флаг робастности (n≥20 и
WR-стабилен по годам). Малые n и нестабильность помечаем явно.

Запуск: venv/Scripts/python.exe research/daily_engine/etap_249_swept_segmentation.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(ROOT))
from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_1_floating import detect_signals_111, check_swept, build_entry_sl, simulate_floating, build_score_series
import etap_217_daytype_layer as L

RR = 2.2
OUT = HERE / "output"


def session(h):
    if h < 7: return "Asia (0-7)"
    if h < 13: return "London (7-13)"
    if h < 21: return "NY (13-21)"
    return "Late (21-24)"


def eff_ratio(arr):
    r = np.diff(np.log(arr))
    path = np.sum(np.abs(r))
    return float(abs(np.sum(r)) / path) if path > 0 else np.nan


def main():
    print("[load] BTC данные...")
    df_1d = load_df("BTCUSDT", "1d"); df_4h = load_df("BTCUSDT", "4h"); df_1h = load_df("BTCUSDT", "1h")
    df_12h = compose_from_base(df_1h, "12h"); df_6h = compose_from_base(df_1h, "6h"); df_2h = compose_from_base(df_1h, "2h")
    df_15m = load_df("BTCUSDT", "15m"); df_1m = load_df("BTCUSDT", "1m"); df_20m = compose_from_base(df_1m, "20m")
    for d in (df_1h, df_1m):
        if d.index.tz is None: d.index = d.index.tz_localize("UTC")

    print("[detect] 1.1.1 + SWEPT...")
    signals = detect_signals_111(df_1d, df_12h, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m)
    swept = [s for s in signals if check_swept(s, df_1h, df_2h)]
    seen, dedup = set(), []
    for s in swept:
        k = (pd.Timestamp(s["signal_time"]).isoformat(), s["direction"], tuple(s["fvg_zone"]))
        if k in seen: continue
        seen.add(k); dedup.append(s)
    print(f"  raw {len(signals)} → SWEPT {len(swept)} → дедуп {len(dedup)}")

    # day-type модель (train <2023) + score для симулятора
    R = L.build(df_1h).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    M = L.fit_per_hour(R[R.day < L.CUTOFF])
    score_long, score_short = build_score_series(df_1h)

    # дневная медиана диапазона для gauge
    daily = df_1h.resample("1D").agg({"open": "first", "high": "max", "low": "min"})
    dmed = ((daily.high - daily.low) / daily.open).rolling(20).median().shift(1)

    rows = []
    for s in dedup:
        res = simulate_floating(s, df_1m, df_1h, score_long, score_short,
                                R_cap=RR, threshold=-1e9, confirm=10**6, max_hold_days=3650)
        if res is None or res.outcome not in ("win", "loss", "flat"):
            continue
        t = pd.Timestamp(s["signal_time"]);  t = t.tz_localize("UTC") if t.tz is None else t
        day = t.normalize()
        entry, sl = build_entry_sl(s) or (np.nan, np.nan)
        risk_pct = abs(entry - sl) / entry * 100 if entry else np.nan
        # day-type на момент входа (бары дня до часа входа)
        bars = df_1h[(df_1h.index.normalize() == day) & (df_1h.index <= t)]
        state = "FORMING"
        if len(bars) >= L.IB + 2:
            dec, _ = L.daytype_nowcast(bars, M); state = dec[-1][1]
        # eff_ratio дня до входа (1m)
        m = df_1m[(df_1m.index.normalize() == day) & (df_1m.index <= t)]["close"].values
        eff = eff_ratio(m) if len(m) >= 60 else np.nan
        # gauge: пройдено дн.хода к входу
        rng_so_far = (bars["high"].max() - bars["low"].min()) / bars["open"].iloc[0] if len(bars) else np.nan
        exp = dmed.reindex([day]).iloc[0] if day in dmed.index else np.nan
        gauge = rng_so_far / exp if (exp and exp > 0) else np.nan
        rows.append(dict(
            signal_time=t, year=t.year, win=int(res.outcome == "win"), R=res.R,
            direction=s["direction"], top_tf=s.get("top_tf"), macro_tf=s.get("fvg_macro_tf"),
            htf_tf=s.get("ob_htf_tf"), fvg_tf=s.get("fvg_tf"), risk_pct=risk_pct,
            state=state, hour=t.hour, session=session(t.hour), eff=eff, gauge=gauge))
    d = pd.DataFrame(rows)
    closed = d[d.win.isin([0, 1])].copy()
    n0 = len(closed); wr0 = closed.win.mean() * 100; pnl0 = closed.win.sum() * RR - (n0 - closed.win.sum())
    print(f"\n  закрытых (RR=2.2): {n0}  | базовый WR {wr0:.1f}%  PnL {pnl0:+.0f}R  "
          f"({closed.signal_time.min().date()}…{closed.signal_time.max().date()})")

    # confluence-категория
    closed["confluence"] = np.where(
        ((closed.direction == "SHORT") & (closed.state == "TREND_UP")) |
        ((closed.direction == "LONG") & (closed.state == "TREND_DOWN")), "counter-trend (в зону)",
        np.where(((closed.direction == "LONG") & (closed.state == "TREND_UP")) |
                 ((closed.direction == "SHORT") & (closed.state == "TREND_DOWN")), "continuation (по тренду)",
                 np.where(closed.state == "ROTATION", "rotation", "forming")))
    # терцили
    closed["risk_grp"] = pd.qcut(closed.risk_pct.rank(method="first"), 3, labels=["узкий SL", "средний SL", "широкий SL"])
    closed["eff_grp"] = np.where(closed.eff <= 0.024, "рваный день", np.where(closed.eff >= 0.062, "гладкий день", "средний"))
    closed["gauge_grp"] = np.where(closed.gauge <= 0.5, "рано (ход<0.5)", np.where(closed.gauge >= 1.0, "поздно (ход≥1.0)", "середина"))

    def yr_stable(g):
        yw = g.groupby("year").win.mean()
        yw = yw[g.groupby("year").size() >= 5]
        return "" if len(yw) < 2 else ("стаб" if (yw > 0.5).mean() >= 0.6 or (yw < 0.5).mean() >= 0.6 else "НЕСТАБ")

    print("\n" + "=" * 84)
    print(f"СЕГМЕНТАЦИЯ 1.1.1 SWEPT — WR групп (база {wr0:.1f}%, n={n0}, BTC fixed RR=2.2)")
    print("=" * 84)
    groups = []
    for dim, col in [("Направление", "direction"), ("Тип дня (модуль)", "state"),
                     ("Confluence (модуль)", "confluence"), ("Сессия входа", "session"),
                     ("Ширина SL", "risk_grp"), ("Top-TF", "top_tf"),
                     ("Entry-FVG TF", "fvg_tf"), ("Рваность дня (eff)", "eff_grp"),
                     ("Пройдено хода (gauge)", "gauge_grp")]:
        for val, g in closed.groupby(col, observed=True):
            n = len(g); w = g.win.sum()
            if n < 8: continue
            groups.append(dict(dim=dim, grp=str(val), n=n, wr=w / n * 100,
                               pnl=w * RR - (n - w), stab=yr_stable(g)))
    gdf = pd.DataFrame(groups)
    # печать по измерениям
    for dim in gdf.dim.unique():
        print(f"\n■ {dim}:")
        for _, r in gdf[gdf.dim == dim].sort_values("wr", ascending=False).iterrows():
            flag = "★" if (r.n >= 20 and r.wr >= 55 and r.stab == "стаб") else ("⚠" if r.stab == "НЕСТАБ" else "")
            print(f"   {r.grp:<26} n={int(r.n):>3}  WR={r.wr:>5.1f}%  PnL={r.pnl:>+6.1f}R  {r.stab:<6}{flag}")

    # топ/дно ячеек (n>=15)
    print("\n■ ТОП-3 и ДНО-3 группы (n≥15, по WR):")
    big = gdf[gdf.n >= 15].sort_values("wr", ascending=False)
    for _, r in pd.concat([big.head(3), big.tail(3)]).iterrows():
        print(f"   {r.dim:<22} {r.grp:<26} n={int(r.n):>3} WR={r.wr:>5.1f}% {r.stab}")

    closed.to_csv(OUT / "etap_249_swept_segmented.csv", index=False)
    print(f"\nSaved: {OUT/'etap_249_swept_segmented.csv'}")


if __name__ == "__main__":
    main()
