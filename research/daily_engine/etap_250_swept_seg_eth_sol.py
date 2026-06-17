"""etap_250 — перенос сегментации/грейда 1.1.1 SWEPT на ETH и SOL.

Вопрос: переносятся ли надёжно-слабые/сильные классы (etap_249, BTC) на ETH/SOL,
и работает ли композитный net-грейд (net≥0 → выше WR)? Если да — грейд можно
включить и для них; если нет — остаётся BTC-only (как ячейки 1.1.1).

Терцили risk_pct — ПО КАЖДОЙ монете (ширина стопа разная). day-type модель
обучена на BTC<2023 и переносится (валидировано). Fixed RR=2.2.

Запуск: venv/Scripts/python.exe research/daily_engine/etap_250_swept_seg_eth_sol.py
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
from etap_249_swept_segmentation import session, eff_ratio

RR = 2.2
OUT = HERE / "output"


def collect(sym, M):
    df_1d = load_df(sym, "1d"); df_4h = load_df(sym, "4h"); df_1h = load_df(sym, "1h")
    df_12h = compose_from_base(df_1h, "12h"); df_6h = compose_from_base(df_1h, "6h"); df_2h = compose_from_base(df_1h, "2h")
    df_15m = load_df(sym, "15m"); df_1m = load_df(sym, "1m"); df_20m = compose_from_base(df_1m, "20m")
    for d in (df_1h, df_1m):
        if d.index.tz is None: d.index = d.index.tz_localize("UTC")
    signals = detect_signals_111(df_1d, df_12h, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m)
    swept = [s for s in signals if check_swept(s, df_1h, df_2h)]
    seen, dedup = set(), []
    for s in swept:
        k = (pd.Timestamp(s["signal_time"]).isoformat(), s["direction"], tuple(s["fvg_zone"]))
        if k not in seen:
            seen.add(k); dedup.append(s)
    sl_, ss_ = build_score_series(df_1h)
    daily = df_1h.resample("1D").agg({"open": "first", "high": "max", "low": "min"})
    dmed = ((daily.high - daily.low) / daily.open).rolling(20).median().shift(1)
    rows = []
    for s in dedup:
        res = simulate_floating(s, df_1m, df_1h, sl_, ss_, R_cap=RR, threshold=-1e9, confirm=10**6, max_hold_days=3650)
        if res is None or res.outcome not in ("win", "loss", "flat"):
            continue
        t = pd.Timestamp(s["signal_time"]); t = t.tz_localize("UTC") if t.tz is None else t
        day = t.normalize(); es = build_entry_sl(s) or (np.nan, np.nan)
        entry, sl = es; risk_pct = abs(entry - sl) / entry * 100 if entry else np.nan
        bars = df_1h[(df_1h.index.normalize() == day) & (df_1h.index <= t)]
        state = "FORMING"
        if len(bars) >= L.IB + 2:
            dec, _ = L.daytype_nowcast(bars, M); state = dec[-1][1]
        m = df_1m[(df_1m.index.normalize() == day) & (df_1m.index <= t)]["close"].values
        eff = eff_ratio(m) if len(m) >= 60 else np.nan
        rng_sf = (bars["high"].max() - bars["low"].min()) / bars["open"].iloc[0] if len(bars) else np.nan
        exp = dmed.reindex([day]).iloc[0] if day in dmed.index else np.nan
        gauge = rng_sf / exp if (exp and exp > 0) else np.nan
        rows.append(dict(signal_time=t, year=t.year, win=int(res.outcome == "win"),
                         direction=s["direction"], fvg_tf=s.get("fvg_tf"), risk_pct=risk_pct,
                         state=state, hour=t.hour, session=session(t.hour), eff=eff, gauge=gauge))
    return pd.DataFrame(rows)


def analyse(sym, d):
    n = len(d); w = d.win.sum(); be = 1 / (1 + RR) * 100
    print(f"\n{'='*78}\n{sym}: {n} сделок, база WR {w/n*100:.1f}%  PnL {w*RR-(n-w):+.0f}R  "
          f"(безубыток {be:.0f}%, {d.signal_time.min().date()}…{d.signal_time.max().date()})\n{'='*78}")
    p33, p67 = np.quantile(d.risk_pct, 0.33), np.quantile(d.risk_pct, 0.67)
    def wr(g): return f"n={len(g):>3} WR={g.win.mean()*100:>5.1f}%" if len(g) else "n=0"
    print("  Слабые классы (BTC: широкий SL/вдогонку/20m/London-NY/ротация):")
    print(f"    широкий SL (≥p67):  {wr(d[d.risk_pct>=p67])}")
    print(f"    вдогонку gauge≥1:   {wr(d[d.gauge>=1.0])}")
    print(f"    20m entry:          {wr(d[d.fvg_tf=='20m'])}")
    print(f"    London/NY:          {wr(d[d.session.isin(['London (7-13)','NY (13-21)'])])}")
    print(f"    ротация-день:       {wr(d[d.state=='ROTATION'])}")
    print("  Сильные классы:")
    print(f"    узкий SL (≤p33):    {wr(d[d.risk_pct<=p33])}")
    print(f"    Asia-сессия:        {wr(d[d.hour<7])}")
    ct = d[(((d.direction=='SHORT')&(d.state=='TREND_UP'))|((d.direction=='LONG')&(d.state=='TREND_DOWN')))]
    print(f"    counter-trend:      {wr(ct)}")
    # net-грейд (per-symbol терцили)
    weak = ((d.risk_pct>=p67).astype(int)+(d.gauge>=1.0).astype(int)+(d.fvg_tf=='20m').astype(int)
            +d.session.isin(['London (7-13)','NY (13-21)']).astype(int)+(d.state=='ROTATION').astype(int))
    ctm = (((d.direction=='SHORT')&(d.state=='TREND_UP'))|((d.direction=='LONG')&(d.state=='TREND_DOWN'))).astype(int)
    strong = (d.risk_pct<=p33).astype(int)+(d.hour<7).astype(int)+ctm
    d = d.assign(net=strong-weak); good=d[d.net>=0]; bad=d[d.net<0]
    print(f"  ГРЕЙД net≥0: {wr(good)} exp={(good.win.sum()*RR-(len(good)-good.win.sum()))/max(len(good),1):+.2f}R | "
          f"net<0: {wr(bad)} exp={(bad.win.sum()*RR-(len(bad)-bad.win.sum()))/max(len(bad),1):+.2f}R")
    print("  net≥0 vs net<0 по годам:")
    stab=[]
    for y,g in d.groupby('year'):
        gg=g[g.net>=0]; bb=g[g.net<0]
        if len(gg)>=4 and len(bb)>=4:
            diff=gg.win.mean()-bb.win.mean(); stab.append(diff>0)
            print(f"    {y}: net≥0 {gg.win.mean()*100:>5.1f}% (n={len(gg):>2}) vs net<0 {bb.win.mean()*100:>5.1f}% (n={len(bb):>2})")
    if stab: print(f"  → грейд работает в {sum(stab)}/{len(stab)} лет")
    return d


def main():
    bt = load_df("BTCUSDT", "1h")
    if bt.index.tz is None: bt.index = bt.index.tz_localize("UTC")
    M = L.fit_per_hour(L.build(bt).replace([np.inf,-np.inf],np.nan).fillna(0.0).query("day < @L.CUTOFF"))
    for sym in ["ETHUSDT", "SOLUSDT"]:
        print(f"\n[collect] {sym}...")
        d = collect(sym, M)
        if len(d) < 30:
            print(f"  {sym}: мало сделок ({len(d)})"); continue
        d = analyse(sym, d)
        d.to_csv(OUT / f"etap_250_seg_{sym}.csv", index=False)


if __name__ == "__main__":
    main()
