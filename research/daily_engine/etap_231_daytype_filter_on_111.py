"""etap_231 — НАЛОЖЕНИЕ day-type фильтра (etap_217) на реальные сделки 1.1.1.

Вопрос: помогает ли «тип дня» отсеять худшие входы 1.1.1?
Метод (без подглядывания):
  - day-type движок обучен на BTC 1h < 2023-01-01 (FEATS = IB-структура).
  - Сделки 1.1.1 = signals/analyze_1_1_1_swept_BTCUSDT_RR2.2.csv (все 2023+, OOS).
  - Для каждой сделки берём 1h-бары ТОГО дня ТОЛЬКО до часа сигнала
    (open_time <= signal_time) → daytype_nowcast → состояние на момент входа.
  - Фильтр: LONG в TREND_DOWN-день / SHORT в TREND_UP-день = конфликт → отбрасываем.
  - Сравниваем WR и сумму R (RR=2.2) baseline vs отфильтровано.

Запуск: venv/Scripts/python.exe research/daily_engine/etap_231_daytype_filter_on_111.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import etap_217_daytype_layer as L

ROOT = HERE.parent.parent
H1 = ROOT / "data" / "BTCUSDT_1h_orderflow.csv"
SIG = ROOT / "signals" / "analyze_1_1_1_swept_BTCUSDT_RR2.2.csv"
RR = 2.2


def stats(df, label):
    W = int((df.outcome == "win").sum()); Lo = int((df.outcome == "loss").sum())
    n = W + Lo; wr = W / n * 100 if n else 0.0; pnl = W * RR - Lo
    exp = pnl / n if n else 0.0
    print(f"  {label:<22} n={n:>3}  W={W:>2} L={Lo:>2}  WR={wr:>5.1f}%  PnL={pnl:>+7.1f}R  ожид/сделку={exp:>+5.2f}R")
    return dict(n=n, W=W, L=Lo, wr=wr, pnl=pnl, exp=exp)


def main():
    # 1h данные
    h1 = pd.read_csv(H1, index_col=0, parse_dates=True)
    if h1.index.tz is None: h1.index = h1.index.tz_localize("UTC")

    # обучаем движок типа дня на < 2023 (как в etap_217)
    R = L.build(h1).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    M = L.fit_per_hour(R[R.day < L.CUTOFF])
    print(f"Движок «тип дня» обучен на BTC 1h < {L.CUTOFF.date()} ({R[R.day < L.CUTOFF].day.nunique()} дней).")

    # сделки 1.1.1
    sig = pd.read_csv(SIG)
    sig["signal_time"] = pd.to_datetime(sig["signal_time"], utc=True)
    closed = sig[sig.outcome.isin(["win", "loss"])].copy().reset_index(drop=True)
    print(f"Сделок 1.1.1 (закрытых): {len(closed)}  | период {closed.signal_time.min().date()}…{closed.signal_time.max().date()}\n")

    states, calls, ks = [], [], []
    for _, s in closed.iterrows():
        t = s["signal_time"]; day = t.normalize()
        # бары дня ТОЛЬКО до часа сигнала включительно (без подглядывания в будущее)
        bars = h1[(h1.index.normalize() == day) & (h1.index <= t)]
        if len(bars) < L.IB + 2:        # день ещё не сформировал IB → фильтр молчит
            states.append("FORMING"); calls.append("HOLD"); ks.append(len(bars)); continue
        dec, _ = L.daytype_nowcast(bars, M)
        k, st, p, sm, mode, call = dec[-1]
        states.append(st); calls.append(call); ks.append(k)
    closed["dt_state"] = states; closed["dt_call"] = calls; closed["dt_k"] = ks

    # КОНФЛИКТ (мягкий фильтр по типу дня): LONG в падающий / SHORT в растущий день
    def conflict_state(r):
        if r.direction == "LONG" and r.dt_state == "TREND_DOWN": return True
        if r.direction == "SHORT" and r.dt_state == "TREND_UP": return True
        return False
    # ЖЁСТКИЙ фильтр по сглаженному call (направление движка против сделки)
    def conflict_call(r):
        if r.direction == "LONG" and r.dt_call == "SHORT": return True
        if r.direction == "SHORT" and r.dt_call == "LONG": return True
        return False

    closed["conf_state"] = closed.apply(conflict_state, axis=1)
    closed["conf_call"] = closed.apply(conflict_call, axis=1)

    print("="*78)
    print(f"РЕЗУЛЬТАТ: day-type фильтр на сделках 1.1.1 (BTC, RR={RR})")
    print("="*78)
    base = stats(closed, "БАЗА (все сделки)")
    f1 = stats(closed[~closed.conf_state], "− конфликт по типу дня")
    f2 = stats(closed[~closed.conf_call], "− конфликт по call (жёстко)")

    print("\n■ Что отсеяли (конфликт по типу дня):")
    drop = closed[closed.conf_state]
    dW = int((drop.outcome == "win").sum()); dL = int((drop.outcome == "loss").sum())
    print(f"   отброшено {len(drop)} сделок: {dW}W / {dL}L  "
          f"(их WR={dW/max(dW+dL,1)*100:.0f}% — чем ниже, тем лучше что убрали)")

    print("\n■ Согласие vs конфликт (по типу дня) — WR в каждой корзине:")
    for lab, mask in [("СОГЛАСИЕ (день за нас)", ~closed.conf_state),
                      ("КОНФЛИКТ (день против)", closed.conf_state)]:
        g = closed[mask]; w = int((g.outcome == "win").sum()); l = int((g.outcome == "loss").sum())
        print(f"   {lab:<26} n={w+l:>3}  WR={w/max(w+l,1)*100:>5.1f}%  PnL={w*RR-l:>+6.1f}R")

    print("\n■ Распределение сделок по типу дня входа:")
    for st, g in closed.groupby("dt_state"):
        w = int((g.outcome == "win").sum()); l = int((g.outcome == "loss").sum())
        print(f"   {st:<11} n={w+l:>3}  WR={w/max(w+l,1)*100:>5.1f}%")

    out = HERE / "output" / "etap_231_daytype_filter_on_111.csv"
    out.parent.mkdir(exist_ok=True)
    closed.to_csv(out, index=False)
    print(f"\nSaved: {out}")
    # вывод-резюме
    print("\n" + "─"*78)
    print(f"ИТОГ: ожид/сделку  база {base['exp']:+.2f}R → фильтр(тип дня) {f1['exp']:+.2f}R "
          f"→ фильтр(call) {f2['exp']:+.2f}R")


if __name__ == "__main__":
    main()
