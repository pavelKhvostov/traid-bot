"""H18 — Inverse 3.2: если 3.2-сетап есть, но в окне [touch-6h, signal_time]
дивергенция ПРОТИВОПОЛОЖНОГО типа (для LONG-сетапа — bear/h_bear; для SHORT —
bull/h_bull) — переворачиваем направление и считаем outcome.

Гипотеза: rejection с противоположной дивергенцией = distribution → пробой.
Inverse-сделка может оказаться лучше «классической».

Re-симуляция:
  - direction inversed
  - entry = тот же mid FVG-1h (зеркально работает как лимит сверху/снизу)
  - sl: для перевёрнутого LONG (бывший SHORT) — high(c0_1h_at_signal),
        для перевёрнутого SHORT (бывший LONG) — low(c0_1h)
        НО эти данные из исходного CSV. Они были SL для OPPOSITE direction.
        Чтобы получить корректный SL для inverse-сделки, мне нужен low/high
        той же c0_1h, но другого знака — что в CSV не записано.

  Решение: SL для inverse = противоположная граница FVG-1h
        (зеркальное отражение SL-логики «за c0»):
        Bull-FVG-1h: SL_long = low(c0). Inversed (SHORT) SL = top FVG-1h
                     (FVG-1h sits ABOVE c0 для bull-fvg, top FVG = high боковой
                     зоны c2). Это аппроксимация — НЕ полностью эквивалентна
                     "high(c0_1h)". Но даёт начальное приближение.

  Активация для inverse: цена ДОЛЖНА коснуться entry с противоположной стороны.
  Для исходного LONG entry активировался при low ≤ entry (цена сверху).
  Для inverse-SHORT — high ≥ entry (цена снизу).
  → нужна повторная активация с 1m данных.
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    if _ROOT.parent == _ROOT:
        raise RuntimeError("repo root not found")
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

from pathlib import Path

import pandas as pd

from data_manager import load_df

ENRICHED_CSV = Path("signals/strategy_3_2_3y_RR1_with_asvk_part1.csv")
SYMBOL_1H = "BTCUSDT"
OUT_CSV = Path("signals/strategy_3_2_inverse_h18.csv")
SYMBOL = "BTCUSDT"
RR = 1.0


def parse_utc3(s):
    if pd.isna(s) or s == "":
        return None
    return pd.Timestamp(s, tz="UTC") - pd.Timedelta(hours=3)


def simulate_inverse(sig: pd.Series, df_1m: pd.DataFrame, df_1h: pd.DataFrame, rr: float):
    """Симуляция inverse-сделки.

    Inverse direction. Entry такой же (mid FVG-1h). SL — за дальней
    границей всей тройки FVG-1h (high всей тройки для inverse-SHORT,
    low всей тройки для inverse-LONG) — симметрично оригинальному
    SL=low(c0_1h)/high(c0_1h), но в противоположную сторону.
    """
    direction_orig = sig["direction"]
    direction_inv = "SHORT" if direction_orig == "LONG" else "LONG"
    entry = float(sig["entry"])

    c0_time = parse_utc3(sig["fvg_1h_c0_time"])
    c2_time = parse_utc3(sig["fvg_1h_c2_time"])
    if c0_time is None or c2_time is None:
        return "skip", None, None, None
    triple = df_1h[(df_1h.index >= c0_time) & (df_1h.index <= c2_time)]
    if len(triple) < 3:
        return "skip", None, None, None
    triple_high = float(triple["high"].max())
    triple_low = float(triple["low"].min())

    if direction_inv == "LONG":
        sl = triple_low
        risk = abs(entry - sl)
        tp = entry + risk * rr
    else:
        sl = triple_high
        risk = abs(entry - sl)
        tp = entry - risk * rr
    if risk <= 0:
        return "skip", None, None, None

    signal_time = parse_utc3(sig["signal_time"])
    fill_scan_start = signal_time + pd.Timedelta(minutes=60)
    forward = df_1m[df_1m.index >= fill_scan_start]

    activation_time = None
    for ts, c in forward.iterrows():
        h, l = float(c["high"]), float(c["low"])
        if direction_inv == "LONG":
            if l <= entry:
                activation_time = ts
                break
        else:
            if h >= entry:
                activation_time = ts
                break

    if activation_time is None:
        return "not_filled", None, None, None

    sim = df_1m[df_1m.index >= activation_time]
    for ts, c in sim.iterrows():
        h, l = float(c["high"]), float(c["low"])
        if direction_inv == "LONG":
            if l <= sl:
                return "loss", entry, sl, "sl"
            if h >= tp:
                return "win", entry, tp, "tp"
        else:
            if h >= sl:
                return "loss", entry, sl, "sl"
            if l <= tp:
                return "win", entry, tp, "tp"
    return "open", None, None, None


def main():
    print(f"[INFO] загрузка enriched CSV: {ENRICHED_CSV}")
    enriched = pd.read_csv(ENRICHED_CSV)
    print(f"  rows: {len(enriched)}")

    print(f"[INFO] загрузка {SYMBOL} 1m")
    df_1m = load_df(SYMBOL, "1m")
    print(f"  bars: {len(df_1m)}")
    print(f"[INFO] загрузка {SYMBOL_1H} 1h (для SL inverse)")
    df_1h = load_df(SYMBOL_1H, "1h")
    print(f"  bars: {len(df_1h)}")

    long_mask = enriched["direction"] == "LONG"
    short_mask = enriched["direction"] == "SHORT"
    # Сегменты:
    # opposite_div = есть div противоположного типа в окне
    long_opposite_div = long_mask & (
        (enriched["bear_div_in_window"] == True)
        | (enriched["h_bear_div_in_window"] == True)
    )
    short_opposite_div = short_mask & (
        (enriched["bull_div_in_window"] == True)
        | (enriched["h_bull_div_in_window"] == True)
    )
    has_opposite = long_opposite_div | short_opposite_div
    print(f"[INFO] сделок с opposite-div: {int(has_opposite.sum())}")

    print("[INFO] сравнение: классический outcome vs inverse outcome для тех же сделок")
    inv_outcomes = []
    for _, sig in enriched.iterrows():
        out, _e, _ex, _ht = simulate_inverse(sig, df_1m, df_1h, RR)
        inv_outcomes.append(out)
    enriched["inverse_outcome"] = inv_outcomes
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    enriched.to_csv(OUT_CSV, index=False)
    print(f"[OK] saved: {OUT_CSV}")

    def report(label: str, mask):
        sub = enriched[mask]
        n = len(sub)
        if n == 0:
            print(f"  {label:<45s}  n=0")
            return
        cl = sub[sub["outcome"].isin(["win", "loss"])]
        cl_inv = sub[sub["inverse_outcome"].isin(["win", "loss"])]
        if len(cl) > 0:
            w = int((cl["outcome"] == "win").sum())
            l = len(cl) - w
            wr = w / len(cl) * 100
            pnl = w * RR - l
            rt = pnl / len(cl)
            line_orig = f"WR={wr:5.1f}% PnL={pnl:+5.1f}R R/tr={rt:+.3f}"
        else:
            line_orig = "WR=- PnL=- R/tr=-"
        if len(cl_inv) > 0:
            wi = int((cl_inv["inverse_outcome"] == "win").sum())
            li = len(cl_inv) - wi
            wri = wi / len(cl_inv) * 100
            pnli = wi * RR - li
            rti = pnli / len(cl_inv)
            line_inv = f"WR={wri:5.1f}% PnL={pnli:+5.1f}R R/tr={rti:+.3f}"
        else:
            line_inv = "WR=- PnL=- R/tr=-"
        print(f"  {label:<45s}  n={n:<3d}  ORIG: {line_orig}  |  INV: {line_inv}")

    print()
    print("=" * 110)
    print("СРАВНЕНИЕ ORIG vs INVERSE по сегментам (на одних и тех же сделках)")
    print("=" * 110)

    report("ALL signals", pd.Series(True, index=enriched.index))
    report("opposite-div segment (H18 candidate)", has_opposite)
    report("aligned-div (H1, для контроля)",
           (long_mask & (enriched["bull_div_in_window"] | enriched["h_bull_div_in_window"]))
           | (short_mask & (enriched["bear_div_in_window"] | enriched["h_bear_div_in_window"])))
    report("no-div segment", ~(has_opposite | (long_mask & (enriched["bull_div_in_window"] | enriched["h_bull_div_in_window"])) | (short_mask & (enriched["bear_div_in_window"] | enriched["h_bear_div_in_window"]))))
    report("LONG opposite-div", long_opposite_div)
    report("SHORT opposite-div", short_opposite_div)


if __name__ == "__main__":
    main()
