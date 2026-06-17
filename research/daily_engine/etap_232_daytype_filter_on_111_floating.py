"""etap_232 — day-type фильтр на 1.1.1 ФИНАЛЬНОЙ версии (Floating TP).

То же, что etap_231, но сделки берём из strategies.strategy_1_1_1_floating
(run_symbol_backtest) → реальные плавающие R, а не fixed RR=2.2.
Входы у floating и fixed идентичны (тот же детектор) — меняется только выход,
поэтому проверяем, держится ли вывод «counter-trend в зону» на правильных R.

day-type движок обучен на BTC 1h < 2023; оцениваем только сделки 2023+ (OOS).
Для каждой сделки day-type считается по барам дня ТОЛЬКО до часа сигнала.

Запуск: venv/Scripts/python.exe research/daily_engine/etap_232_daytype_filter_on_111_floating.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(ROOT))
import etap_217_daytype_layer as L
from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_1_floating import run_symbol_backtest

H1 = ROOT / "data" / "BTCUSDT_1h_orderflow.csv"
SYMBOL = "BTCUSDT"


def stats(rows, label):
    n = len(rows); W = sum(1 for r in rows if r["R"] > 0); Lo = n - W
    pnl = sum(r["R"] for r in rows); wr = W/n*100 if n else 0; exp = pnl/n if n else 0
    print(f"  {label:<26} n={n:>3}  W={W:>2} L={Lo:>2}  WR={wr:>5.1f}%  PnL={pnl:>+8.1f}R  ожид/сделку={exp:>+5.2f}R")
    return dict(n=n, pnl=pnl, exp=exp, wr=wr)


def wr_line(rows):
    n = len(rows); w = sum(1 for r in rows if r["R"] > 0)
    pnl = sum(r["R"] for r in rows)
    return f"n={n:>2} WR={w/max(n,1)*100:>5.1f}% PnL={pnl:>+7.1f}R"


def main():
    print("[INFO] загрузка BTC данных...")
    df_1d = load_df(SYMBOL, "1d"); df_12h = load_df(SYMBOL, "12h")
    df_4h = load_df(SYMBOL, "4h"); df_1h = load_df(SYMBOL, "1h")
    df_6h = compose_from_base(df_1h, "6h"); df_2h = compose_from_base(df_1h, "2h")
    df_15m = load_df(SYMBOL, "15m"); df_1m = load_df(SYMBOL, "1m")
    df_20m = compose_from_base(df_1m, "20m")

    print("[INFO] прогон 1.1.1 Floating TP (финальная версия)...")
    trades = run_symbol_backtest(SYMBOL, df_1d, df_12h, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m, df_1m)
    trades = [t for t in trades if t["outcome"] in ("win", "loss", "flat")]

    # day-type движок
    h1 = pd.read_csv(H1, index_col=0, parse_dates=True)
    if h1.index.tz is None: h1.index = h1.index.tz_localize("UTC")
    Rdf = L.build(h1).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    M = L.fit_per_hour(Rdf[Rdf.day < L.CUTOFF])

    # оставляем только OOS-сделки (signal_time >= 2023), классифицируем тип дня на момент входа
    rows = []
    for t in trades:
        st = pd.Timestamp(t["signal_time"])
        if st.tzinfo is None: st = st.tz_localize("UTC")
        if st < L.CUTOFF: continue
        day = st.normalize()
        bars = h1[(h1.index.normalize() == day) & (h1.index <= st)]
        if len(bars) < L.IB + 2:
            state = "FORMING"
        else:
            dec, _ = L.daytype_nowcast(bars, M); state = dec[-1][1]
        rows.append({"signal_time": st, "direction": t["direction"], "R": float(t["R"]),
                     "outcome": t["outcome"], "dt_state": state})

    print(f"\nСделок (OOS 2023+): {len(rows)}  | период "
          f"{min(r['signal_time'] for r in rows).date()}…{max(r['signal_time'] for r in rows).date()}")

    def conflict(r):  # «align with day» (то, что я сперва предлагал)
        return (r["direction"] == "LONG" and r["dt_state"] == "TREND_DOWN") or \
               (r["direction"] == "SHORT" and r["dt_state"] == "TREND_UP")

    print("\n" + "="*82)
    print("РЕЗУЛЬТАТ: day-type на 1.1.1 FLOATING TP (BTC, реальные R)")
    print("="*82)
    base = stats(rows, "БАЗА (все сделки)")
    stats([r for r in rows if not conflict(r)], "− убрать «конфликт с днём»")

    print("\n■ Согласие vs конфликт по типу дня:")
    print(f"   СОГЛАСИЕ (день за нас)   {wr_line([r for r in rows if not conflict(r)])}")
    print(f"   КОНФЛИКТ (день против)   {wr_line([r for r in rows if conflict(r)])}")

    print("\n■ Направление × тип дня:")
    for dr in ("LONG", "SHORT"):
        for stt in ("FORMING", "ROTATION", "TREND_UP", "TREND_DOWN"):
            sub = [r for r in rows if r["direction"] == dr and r["dt_state"] == stt]
            if sub: print(f"   {dr:<5} {stt:<11} {wr_line(sub)}")

    cont = [r for r in rows if (r["direction"]=="LONG" and r["dt_state"]=="TREND_UP") or
            (r["direction"]=="SHORT" and r["dt_state"]=="TREND_DOWN")]
    ct = [r for r in rows if (r["direction"]=="LONG" and r["dt_state"]=="TREND_DOWN") or
          (r["direction"]=="SHORT" and r["dt_state"]=="TREND_UP")]
    print("\n■ Тезис etap_231 на правильных R:")
    print(f"   CONTINUATION (LONG в UP / SHORT в DOWN) {wr_line(cont)}")
    print(f"   COUNTER-TREND в зону (LONG в DOWN / SHORT в UP) {wr_line(ct)}")
    longrot = [r for r in rows if r["direction"]=="LONG" and r["dt_state"]=="ROTATION"]
    print(f"   LONG в боковик (дыра из etap_231) {wr_line(longrot)}")

    out = HERE / "output" / "etap_232_daytype_filter_on_111_floating.csv"
    out.parent.mkdir(exist_ok=True)
    pd.DataFrame(rows).to_csv(out, index=False)
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
