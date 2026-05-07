"""Бэктест Strategy 1.1.5 на BTCUSDT — RAW зоны (без entry/SL/TP/outcome).

Воронка: 1d-фрактал → 4h/6h sweep+OB → 1h/2h OB + 15m/20m FVG.
Прогоняется два раза: k_after=3 и k_after=4 — это окно поиска макро-OB
после snipe-свечи (см. strategies/strategy_1_1_5.py docstring).

CSV содержит только сами зоны, времена и метаданные сигнала. Entry/SL/TP/RR
и win/loss-симуляция намеренно НЕ считаются — будут добавлены отдельно,
когда юзер зафиксирует формулу entry и SL.
"""
from __future__ import annotations


# --- repo-root injection ---
import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    if _ROOT.parent == _ROOT:
        raise RuntimeError("repo root not found")
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))
# --- end repo-root injection ---

from pathlib import Path

import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_5 import detect_strategy_1_1_5_signals

DAYS_BACK = 1095  # 3 года
SYMBOL = "BTCUSDT"
K_RUNS = [3, 4]


def to_utc3(ts) -> str:
    """UTC timestamp -> 'YYYY-MM-DD HH:MM' в UTC+3."""
    if ts is None or ts == "":
        return ""
    return (pd.Timestamp(ts) + pd.Timedelta(hours=3)).strftime("%Y-%m-%d %H:%M")


def signal_to_row(sig: dict) -> dict:
    """Развернуть сигнал детектора в плоский словарь для CSV."""
    return {
        "signal_time": to_utc3(sig["signal_time"]),
        "direction": sig["direction"],
        "fractal_type": sig["fractal_type"],
        "fractal_time": to_utc3(sig["fractal_time"]),
        "fractal_price": sig["fractal_price"],
        "fractal_confirm_time": to_utc3(sig["fractal_confirm_time"]),
        "sweep_tf": sig["sweep_tf"],
        "sweep_time": to_utc3(sig["sweep_time"]),
        "sweep_high": sig["sweep_high"],
        "sweep_low": sig["sweep_low"],
        "sweep_close": sig["sweep_close"],
        "macro_ob_tf": sig["macro_ob_tf"],
        "macro_ob_prev_time": to_utc3(sig["macro_ob_prev_time"]),
        "macro_ob_cur_time": to_utc3(sig["macro_ob_cur_time"]),
        "macro_ob_bottom": sig["macro_ob_zone"][0],
        "macro_ob_top": sig["macro_ob_zone"][1],
        "macro_ob_cur_is_sweep": sig["macro_ob_cur_is_sweep"],
        "k_after": sig["k_after"],
        "ob_htf_tf": sig["ob_htf_tf"],
        "ob_htf_prev_time": to_utc3(sig["ob_htf_prev_time"]),
        "ob_htf_cur_time": to_utc3(sig["ob_htf_cur_time"]),
        "ob_htf_bottom": sig["ob_htf_zone"][0],
        "ob_htf_top": sig["ob_htf_zone"][1],
        "fvg_entry_tf": sig["fvg_entry_tf"],
        "fvg_entry_c0_time": to_utc3(sig["fvg_entry_c0_time"]),
        "fvg_entry_c2_time": to_utc3(sig["fvg_entry_c2_time"]),
        "fvg_entry_bottom": sig["fvg_entry_zone"][0],
        "fvg_entry_top": sig["fvg_entry_zone"][1],
    }


def main():
    print(f"[INFO] Strategy 1.1.5 RAW backtest, {SYMBOL}, окно {DAYS_BACK}d, K={K_RUNS}")
    print()

    print("[INFO] загрузка данных")
    df_1d = load_df(SYMBOL, "1d")
    df_4h = load_df(SYMBOL, "4h")
    df_1h = load_df(SYMBOL, "1h")
    df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_15m = load_df(SYMBOL, "15m")
    df_1m = load_df(SYMBOL, "1m")
    df_20m = compose_from_base(df_1m, "20m")
    print(f"  1d={len(df_1d)} 4h={len(df_4h)} 6h={len(df_6h)} "
          f"1h={len(df_1h)} 2h={len(df_2h)} "
          f"15m={len(df_15m)} 20m={len(df_20m)}")

    today = pd.Timestamp.utcnow().normalize()
    if today.tz is None:
        today = today.tz_localize("UTC")
    cutoff = today - pd.Timedelta(days=DAYS_BACK)
    df_1d_cut = df_1d[df_1d.index >= cutoff]
    print(f"  after cutoff ({cutoff.date()}): 1d={len(df_1d_cut)}")
    print()

    for k in K_RUNS:
        print(f"[INFO] прогон детектора k_after={k}")
        signals = detect_strategy_1_1_5_signals(
            df_1d_cut, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m,
            k_after=k, verbose=True,
        )
        if not signals:
            print(f"  [WARN] k={k}: ни одного сигнала")
            continue

        rows = [signal_to_row(s) for s in signals]
        df = pd.DataFrame(rows)

        output_path = Path(f"signals/strategy_1_1_5_3y_K{k}.csv")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(output_path, index=False)
        print(f"  записано: {output_path} ({len(df)} строк)")

        # Cводка по разрезам
        df["year"] = pd.to_datetime(df["signal_time"]).dt.year
        print()
        print(f"  По годам (k={k}):")
        for y in sorted(df["year"].unique()):
            sub = df[df["year"] == y]
            print(f"    {y}: n={len(sub)}  L={int((sub['direction']=='LONG').sum())} "
                  f"S={int((sub['direction']=='SHORT').sum())}")
        print(f"  По sweep_tf: 4h={int((df['sweep_tf']=='4h').sum())} "
              f"6h={int((df['sweep_tf']=='6h').sum())}")
        print(f"  По ob_htf_tf: 1h={int((df['ob_htf_tf']=='1h').sum())} "
              f"2h={int((df['ob_htf_tf']=='2h').sum())}")
        print(f"  По fvg_entry_tf: 15m={int((df['fvg_entry_tf']=='15m').sum())} "
              f"20m={int((df['fvg_entry_tf']=='20m').sum())}")
        print(f"  macro_ob_cur_is_sweep=True: "
              f"{int(df['macro_ob_cur_is_sweep'].sum())}")
        print()


if __name__ == "__main__":
    main()
