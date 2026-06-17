"""etap_240 — АУДИТ approved-цифр 1.1.1 Floating на ДЕДУПЛИЦИРОВАННЫХ сделках.

Контекст: адверсариальный ревью etap_239 нашёл, что run_symbol_backtest
(strategies/strategy_1_1_1_floating.py) не дедуплицирует сигналы каскада
(один entry-FVG приходит через ветки 1d/12h × 4h/6h × 1h/2h). Approved-цифры
(BTC 6.34y: floating +179.9R WR 52% medR +0.07 vs baseline RR2.2 +165.2R
WR 45% medR −1.00) построены этим пайплайном.

Вопросы:
  1) Сколько дублей? Во что сдуваются абсолютные R на дедупе?
  2) Выживает ли ОТНОСИТЕЛЬНЫЙ вывод «floating > fixed RR2.2» на дедупе?

Метод: один прогон детектора + SWEPT (как run_symbol_backtest), затем ДВЕ
симуляции на одних сигналах: floating (R_cap=4.5, thr=-0.25, confirm=2) и
baseline (R_cap=2.2, score-exit выключен, таймаут отключён = чистый RR2.2).
Дедуп-ключ: (signal_time, direction, fvg_zone) — канон fixed-бэктеста.
BTC only (у ETH 1m-истории нет полных 6 лет — отдельный вопрос).

Запуск: venv/Scripts/python.exe research/daily_engine/etap_240_floating_dedup_audit.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_1_floating import (
    FLOATING_TP_CONFIG, build_score_series, check_swept,
    detect_signals_111, simulate_floating,
)

SYMBOL = "BTCUSDT"


def stats(rows, label):
    closed = [r for r in rows if r["outcome"] in ("win", "loss", "flat")]
    n = len(closed)
    if n == 0:
        print(f"  {label}: пусто"); return {}
    W = sum(1 for r in closed if r["R"] > 0)
    pnl = sum(r["R"] for r in closed)
    med = float(np.median([r["R"] for r in closed]))
    print(f"  {label:<26} n={n:>4}  WR={W/n*100:>5.1f}%  ΣR={pnl:>+8.1f}  medR={med:>+5.2f}  R/tr={pnl/n:>+5.2f}")
    by_year = {}
    for r in closed:
        y = pd.Timestamp(r["signal_time"]).year
        by_year.setdefault(y, []).append(r["R"])
    line = "    по годам: " + "  ".join(f"{y}:{sum(v):+.0f}R" for y, v in sorted(by_year.items()))
    print(line)
    return {"n": n, "wr": W/n*100, "pnl": pnl, "med": med, "by_year": {y: sum(v) for y, v in by_year.items()}}


def main():
    print("[INFO] данные BTC (полный спан)...")
    df_1d = load_df(SYMBOL, "1d"); df_12h = load_df(SYMBOL, "12h")
    df_4h = load_df(SYMBOL, "4h"); df_1h = load_df(SYMBOL, "1h")
    df_6h = compose_from_base(df_1h, "6h"); df_2h = compose_from_base(df_1h, "2h")
    df_15m = load_df(SYMBOL, "15m"); df_1m = load_df(SYMBOL, "1m")
    df_20m = compose_from_base(df_1m, "20m")
    span_y = (df_1d.index.max() - df_1d.index.min()).days / 365.25
    print(f"  спан: {df_1d.index.min().date()} … {df_1d.index.max().date()} ({span_y:.2f}y)")

    print("[INFO] детект + SWEPT...")
    signals = detect_signals_111(df_1d, df_12h, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m)
    swept = [s for s in signals if check_swept(s, df_1h, df_2h)]
    print(f"  raw signals: {len(signals)}  после SWEPT: {len(swept)}")

    # дедуп-ключ: (signal_time, direction, fvg_zone)
    seen, dedup = set(), []
    for s in swept:
        key = (pd.Timestamp(s["signal_time"]).isoformat(), s["direction"], tuple(s["fvg_zone"]))
        if key in seen: continue
        seen.add(key); dedup.append(s)
    print(f"  дедуп: {len(dedup)}  (дублей: {len(swept) - len(dedup)})")

    score_long, score_short = build_score_series(df_1h)
    cfg = FLOATING_TP_CONFIG[SYMBOL]

    def run(sigs, **kw):
        out = []
        for s in sigs:
            r = simulate_floating(s, df_1m, df_1h, score_long, score_short, **kw)
            if r is None: continue
            out.append({"signal_time": s["signal_time"], "direction": s["direction"],
                        "outcome": r.outcome, "R": r.R, "exit_reason": r.exit_reason})
        return out

    print("\n[INFO] симуляция floating (raw и дедуп)...")
    fl_raw = run(swept, R_cap=cfg["R_cap"], threshold=cfg["threshold"], confirm=cfg["confirm"])
    fl_dd = run(dedup, R_cap=cfg["R_cap"], threshold=cfg["threshold"], confirm=cfg["confirm"])
    print("[INFO] симуляция baseline RR=2.2 (дедуп)...")
    bl_dd = run(dedup, R_cap=2.2, threshold=-1e9, confirm=10**6, max_hold_days=3650)

    print("\n" + "=" * 80)
    print(f"АУДИТ 1.1.1 FLOATING, {SYMBOL}, {span_y:.2f}y  (approved: float +179.9R WR52 medR+0.07 | base +165.2R WR45 medR−1.00)")
    print("=" * 80)
    a = stats(fl_raw, "FLOATING raw (как approved)")
    b = stats(fl_dd, "FLOATING дедуп")
    c = stats(bl_dd, "BASELINE RR2.2 дедуп")
    if a and b:
        print(f"\n  инфляция дублей: ΣR ×{a['pnl']/max(b['pnl'],1e-9):.2f}  n ×{a['n']/b['n']:.2f}")
    if b and c:
        boost = (b['pnl'] - c['pnl']) / abs(c['pnl']) * 100 if c['pnl'] else float('nan')
        print(f"  ОТНОСИТЕЛЬНЫЙ вывод на дедупе: floating {b['pnl']:+.1f}R vs baseline {c['pnl']:+.1f}R  → boost {boost:+.0f}%")
        years = sorted(set(b['by_year']) | set(c['by_year']))
        worse = [y for y in years if b['by_year'].get(y, 0) < c['by_year'].get(y, 0)]
        print(f"  годы, где floating ХУЖЕ baseline: {worse or 'нет'}")

    out = HERE / "output" / "etap_240_audit.csv"
    pd.DataFrame(fl_dd).assign(kind="float_dd").to_csv(out, index=False)
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
