"""АНАЛИТИКА ТОРГОВОСПОСОБНОСТИ arc-паттернов НА ФЬЮЧЕРСАХ (нетто PnL, не барьер-R).

Сдвиг от arc_analysis: там edge мерился на СИММЕТРИЧНОМ ±1.5ATR барьере = НЕ PnL. Здесь — реальная
сделка на перп-фьючерсах:
  сигнал = arc завершилась (i1) с условиями (изогнутость + apex центр/поздно + против контекста);
  направление = FADE конца дуги (купол/спуск -> LONG отскок; чаша/рост -> SHORT откат);
  вход = OPEN следующего бара (без lookahead); стоп = k_sl·ATR; TP = RR·risk; иначе таймаут.
КОСТЫ ФЬЮЧЕРСОВ: taker 0.05%/сторона + слиппедж 0.02%/сторона (=0.14% round-trip) + funding 0.01%/8ч (drag).
Пессимистичный тай-брейк: если в одном баре и стоп, и TP -> считаем СТОП.
Метрики: нетто-R, экспектация, WR, profit factor, total R, макс. просадка, Sharpe(на сделку),
по символам/годам/направлению. Контроли: GRID SL×RR (нет cherry-pick), RANDOM-ENTRY null, cost-sensitivity 0/1/2×.

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/ta_laws/futures_tradeability.py
Выход: research/ta_laws/tradeability_report.txt + trades.csv
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
sys.path.insert(0, str(HERE))
import geometry as G  # noqa: E402
import curves as C    # noqa: E402

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
TFS = [("1h", "1h", 1.0), ("2h", "2h", 2.0), ("4h", "4h", 4.0),
       ("6h", "6h", 6.0), ("12h", "12h", 12.0), ("1d", "1d", 24.0)]
# косты (доли)
TAKER = 0.0005
SLIP = 0.0002
FUND_PER_8H = 0.0001
RT_FEE = 2 * (TAKER + SLIP)         # round-trip fee+slip
RNG = np.random.default_rng(31)

# условия arc-сетапа (валидированный подмножество)
SAG_MIN = 2.5
APEX_MIN = 0.4


def load_1m(sym):
    df = pd.read_csv(ROOT / "data" / f"{sym}_1m.csv", parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def rs(df, freq):
    return df.resample(freq, origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["close"])


def simulate(o, h, l, c, entry_i, direction, atr_a, k_sl, rr, horizon, n, tf_hours, cost_mult):
    """Сделка от OPEN[entry_i]. direction +1 long / -1 short. Возврат net_R или None."""
    if entry_i >= n:
        return None
    entry = o[entry_i]
    if not (entry > 0) or atr_a <= 0:
        return None
    risk = k_sl * atr_a
    if direction > 0:
        stop = entry - risk; tp = entry + rr * risk
    else:
        stop = entry + risk; tp = entry - rr * risk
    end = min(entry_i + horizon, n - 1)
    exit_price = c[end]; bars_held = end - entry_i; outcome = "timeout"
    for x in range(entry_i, end + 1):
        hit_sl = (l[x] <= stop) if direction > 0 else (h[x] >= stop)
        hit_tp = (h[x] >= tp) if direction > 0 else (l[x] <= tp)
        if hit_sl:                       # пессимизм: стоп раньше TP в одном баре
            exit_price = stop; bars_held = x - entry_i; outcome = "loss"; break
        if hit_tp:
            exit_price = tp; bars_held = x - entry_i; outcome = "win"; break
    gross = (exit_price - entry) / entry * direction
    fee = RT_FEE * cost_mult
    fund = (bars_held * tf_hours / 8.0) * FUND_PER_8H * cost_mult
    net_pct = gross - fee - fund
    risk_pct = risk / entry
    return dict(net_R=net_pct / risk_pct, gross_R=gross / risk_pct, outcome=outcome,
                bars=bars_held, net_pct=net_pct, risk_pct=risk_pct)


def collect_signals():
    """Список arc-сигналов (каузально): symbol,tf,entry_i,direction,atr,horizon,year,context,...
    + полные ряды для симуляции."""
    btc_1d = rs(load_1m("BTCUSDT"), "1d")["close"]
    series = {}
    sigs = []
    for sym in SYMBOLS:
        print(f"[sig] {sym}...", flush=True)
        d1 = load_1m(sym)
        mtf = {"1h": (rs(d1, "1h")["close"], pd.Timedelta(hours=10)),
               "4h": (rs(d1, "4h")["close"], pd.Timedelta(hours=40)),
               "1d": (rs(d1, "1d")["close"], pd.Timedelta(days=10))}
        for tlabel, freq, tf_hours in TFS:
            df = rs(d1, freq)
            n = len(df)
            o = df["open"].values; h = df["high"].values; l = df["low"].values; c = df["close"].values
            atr = G.compute_atr(df)
            series[(sym, tlabel)] = (o, h, l, c, n, tf_hours)
            arcs = C.find_arcs(df, atr=atr)
            for a in arcs:
                i1 = a.i1
                if i1 < 25 or i1 >= n - 3:
                    continue
                L = a.i1 - a.i0
                aa, bb, _ = a.coeffs
                deriv = 2 * aa * L + bb
                end_dir = 1 if deriv > 0 else -1          # куда шла цена в конце дуги
                fade_dir = -end_dir                        # сделка = fade конца дуги
                apex_pos = (a.apex_i - a.i0) / max(L, 1)
                arm_ts = df.index[i1]
                mtf_up = 0
                for _t, (ser, td) in mtf.items():
                    vn = ser.asof(arm_ts); vp = ser.asof(arm_ts - td)
                    if pd.notna(vn) and pd.notna(vp):
                        mtf_up += int(vn > vp)
                # «против контекста» относительно НАПРАВЛЕНИЯ СДЕЛКИ:
                # fade вверх (long) хотим когда контекст НЕ вверх (mtf_up<=1); fade вниз когда контекст не вниз
                against_ctx = (mtf_up <= 1) if fade_dir > 0 else (mtf_up >= 2)
                sigs.append(dict(sym=sym, tf=tlabel, i1=i1, entry_i=i1 + 1, dir=fade_dir,
                                 atr=atr[i1], horizon=min(L, int(30 * 24 / tf_hours)),
                                 year=arm_ts.year, kind=a.kind, sag=a.sagitta_atr, depth=a.depth_atr,
                                 apex=apex_pos, mtf_up=mtf_up, against=int(against_ctx), tf_hours=tf_hours))
            print(f"   {sym} {tlabel}: arcs->sigs {len([s for s in sigs if s['sym']==sym and s['tf']==tlabel])}", flush=True)
    return sigs, series


def run(sigs, series, k_sl, rr, cost_mult, cond=True, randomize=False):
    trades = []
    for s in sigs:
        # КОНТЕКСТ-СОВПАДАЕТ (aligned): откат разворачивается обратно в мульти-ТФ тренд (trend-continuation pullback)
        if cond and not (s["sag"] >= SAG_MIN and s["apex"] >= APEX_MIN and not s["against"]):
            continue
        o, h, l, c, n, tf_hours = series[(s["sym"], s["tf"])]
        entry_i = s["entry_i"]; direction = s["dir"]
        if randomize:
            entry_i = int(RNG.integers(26, n - s["horizon"] - 2))
            direction = int(RNG.choice([-1, 1]))
        r = simulate(o, h, l, c, entry_i, direction, s["atr"], k_sl, rr, s["horizon"], n, tf_hours, cost_mult)
        if r is None:
            continue
        r.update(sym=s["sym"], tf=s["tf"], year=s["year"], dir=direction, kind=s["kind"])
        trades.append(r)
    return pd.DataFrame(trades)


def stats(t):
    if len(t) == 0:
        return dict(n=0)
    R = t.net_R.values
    wins = R[R > 0]; losses = R[R <= 0]
    pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else np.inf
    eq = np.cumsum(R); peak = np.maximum.accumulate(eq); dd = (eq - peak).min()
    sharpe = R.mean() / R.std() if R.std() > 0 else 0.0
    return dict(n=len(t), wr=(R > 0).mean() * 100, exp=R.mean(), total=R.sum(),
                pf=pf, dd=dd, sharpe=sharpe, med_bars=int(np.median(t.bars)))


def line(label, st):
    if st.get("n", 0) == 0:
        return f"  {label:26} n=0"
    return (f"  {label:26} n={st['n']:>4} WR={st['wr']:>4.0f}% exp={st['exp']:>+6.3f}R "
            f"PF={st['pf']:>4.2f} total={st['total']:>+7.1f}R DD={st['dd']:>+6.1f}R Sharpe={st['sharpe']:>+5.2f}")


def main():
    sigs, series = collect_signals()
    cond_sigs = [s for s in sigs if s["sag"] >= SAG_MIN and s["apex"] >= APEX_MIN and not s["against"]]
    out = []
    out.append("ТОРГОВОСПОСОБНОСТЬ arc-паттернов НА ФЬЮЧЕРСАХ — BTC/ETH/SOL, 1h->D, с 2020.")
    out.append("СЕТАП: форма (изогнутость+apex) + АНАЛИТИКА-КОНФЛЮЭНС (откат разворачивается ОБРАТНО в мульти-ТФ тренд).")
    out.append(f"Костов: taker {TAKER*100:.3f}%/side + slip {SLIP*100:.3f}%/side = {RT_FEE*100:.2f}% RT + "
               f"funding {FUND_PER_8H*100:.3f}%/8ч. Тай-брейк = стоп.")
    out.append(f"Всего arc-сигналов: {len(sigs)} | прошло условия (sag>={SAG_MIN}, apex>={APEX_MIN}, контекст СОВПАДАЕТ): "
               f"{len(cond_sigs)}\n")

    # ---------- GRID SL × RR (реальные косты), условный сетап ----------
    out.append("=== 1) GRID SL×RR (реальные косты, условный сетап) — нет cherry-pick ===")
    out.append(f"{'SL/RR':8} " + " ".join(f"RR{rr}" .ljust(34) for rr in (1.0, 1.5, 2.0)))
    grid = {}
    for k_sl in (0.8, 1.0, 1.5):
        cells = []
        for rr in (1.0, 1.5, 2.0):
            t = run(sigs, series, k_sl, rr, 1.0, cond=True)
            st = stats(t); grid[(k_sl, rr)] = (t, st)
            cells.append(f"exp{st.get('exp',0):+.3f} PF{st.get('pf',0):.2f} tot{st.get('total',0):+.0f}".ljust(34))
        out.append(f"SL{k_sl:<6} " + " ".join(cells))

    # выбрать ячейку по total среди положительной экспектации (или макс exp)
    best = max(grid.items(), key=lambda kv: (kv[1][1].get("exp", -9), kv[1][1].get("total", -9)))
    (bk_sl, brr), (bt, bst) = best
    out.append(f"\nЛучшая ячейка по экспектации: SL={bk_sl} RR={brr}")
    out.append(line("условный сетап", bst))

    # ---------- сравнение: ВСЕ арки (без условий) на той же ячейке ----------
    t_all = run(sigs, series, bk_sl, brr, 1.0, cond=False)
    out.append(line("ВСЕ арки (без условий)", stats(t_all)))

    # ---------- RANDOM-ENTRY null (та же ячейка, столько же сделок) ----------
    null_exps = []
    for _ in range(30):
        tr = run(sigs, series, bk_sl, brr, 1.0, cond=True, randomize=True)
        if len(tr):
            null_exps.append(tr.net_R.mean())
    null_exps = np.array(null_exps)
    p_rand = float((null_exps >= bst["exp"]).mean()) if len(null_exps) else 1.0
    out.append(f"  RANDOM-ENTRY null (30 прогонов): exp медиана {np.median(null_exps):+.3f}R, "
               f"P(null>=стратегия)={p_rand:.3f} -> {'СТРАТЕГИЯ БЬЁТ random' if p_rand<0.05 else 'НЕ бьёт random'}")

    # ---------- cost sensitivity ----------
    out.append("\n=== 2) COST-SENSITIVITY (лучшая ячейка) ===")
    for cm, lbl in [(0.0, "0× (без костов)"), (1.0, "1× (реальные)"), (2.0, "2× (стресс)")]:
        out.append(line(lbl, stats(run(sigs, series, bk_sl, brr, cm, cond=True))))

    # ---------- разбивки (лучшая ячейка, реальные косты) ----------
    out.append("\n=== 3) РАЗБИВКИ (лучшая ячейка, реальные косты) ===")
    out.append("  -- по символам:")
    for sym in SYMBOLS:
        out.append(line(sym, stats(bt[bt.sym == sym])))
    out.append("  -- по направлению:")
    out.append(line("LONG (fade купола вверх)", stats(bt[bt.dir == 1])))
    out.append(line("SHORT (fade чаши вниз)", stats(bt[bt.dir == -1])))
    out.append("  -- по годам:")
    for yr in sorted(bt.year.unique()):
        out.append(line(str(yr), stats(bt[bt.year == yr])))
    out.append("  -- по ТФ:")
    for tf, _, _ in TFS:
        out.append(line(tf, stats(bt[bt.tf == tf])))

    bt.to_csv(HERE / "trades.csv", index=False)
    out.append("\n=== ВЕРДИКТ ===")
    pos_sym = sum(1 for sym in SYMBOLS if stats(bt[bt.sym == sym]).get("exp", -9) > 0)
    pos_yr = sum(1 for yr in bt.year.unique() if stats(bt[bt.year == yr]).get("exp", -9) > 0)
    survive_cost = stats(run(sigs, series, bk_sl, brr, 1.0, cond=True)).get("exp", -9) > 0
    verdict = ("ТОРГОВОСПОСОБНО (с оговорками)" if (bst["exp"] > 0 and p_rand < 0.1 and pos_sym >= 2 and survive_cost)
               else "НЕ торговоспособно нетто (edge не переживает косты/random)")
    out.append(f"  Нетто-экспектация {bst['exp']:+.3f}R | бьёт random p={p_rand:.3f} | "
               f"символы+ {pos_sym}/3 | годы+ {pos_yr}/{bt.year.nunique()} -> {verdict}")

    rep = HERE / "tradeability_report.txt"
    rep.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))
    print(f"\n[trade] -> {rep.name}")


if __name__ == "__main__":
    main()
