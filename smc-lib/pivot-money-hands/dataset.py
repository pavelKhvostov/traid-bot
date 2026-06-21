"""
Labelled dataset для исследования: на каждом 1h баре снять multi-TF
MoneyHands snapshot + forward-looking labels (будет ли pivot в 12h/24h).

Output: CSV / DataFrame, одна строка на каждый 1h bar в выбранном диапазоне.

Оптимизация: MoneyHands считаем ОДИН раз на полном диапазоне для каждого TF,
затем для каждого 1h ts берём состояние последнего закрытого бара того TF.
Это амортизирует тяжёлый расчёт wavetrend/MF SMA60.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import pandas as pd

SMC_LIB = Path(os.environ.get("SMCLIB_ROOT", str(Path.home() / "smc-lib")))
sys.path.insert(0, str(SMC_LIB))
sys.path.insert(0, str(SMC_LIB / "prediction-algo"))

from indicators.money_hands_asvk import money_hands  # noqa: E402
from resample import resample_many  # noqa: E402

from multi_tf_mh import MH_FIELDS, PIVOT_TFS  # noqa: E402
from pivots import find_1h_pivots  # noqa: E402

# из prediction-algo:
from data import load_btc_1m  # noqa: E402


def _precompute_mh_per_tf(
    df_1m: pd.DataFrame,
    tfs: tuple[str, ...],
    end_ts: pd.Timestamp,
) -> dict[str, pd.DataFrame]:
    """
    Один раз: для каждого TF посчитать MoneyHands по всем барам.
    Возвращает: tf → DataFrame с колонками [bw2, color, mf, rsi_mod, stc_rsi_mod] индекс = bar open_ts.
    """
    out: dict[str, pd.DataFrame] = {}
    resampled = resample_many(df_1m, list(tfs), end_ts)
    for tf, df_tf in resampled.items():
        if df_tf.empty:
            out[tf] = df_tf.iloc[0:0]
            continue
        bars = list(zip(
            df_tf["open"].astype(float),
            df_tf["high"].astype(float),
            df_tf["low"].astype(float),
            df_tf["close"].astype(float),
            df_tf["volume"].astype(float),
        ))
        res = money_hands(bars)
        mh_df = pd.DataFrame({
            "bw2": res["bw2"],
            "color": res["color"],
            "mf": res["mf"],
            "rsi_mod": res["rsi_mod"],
            "stc_rsi_mod": res["stc_rsi_mod"],
        }, index=df_tf.index)
        out[tf] = mh_df
    return out


def _mh_state_at_ts(mh_df: pd.DataFrame, tf: str, ts: pd.Timestamp) -> dict:
    """Получить состояние MH для TF на момент ts (= последний бар чьё закрытие ≤ ts)."""
    tf_td_map = {"3d": pd.Timedelta("72h"), "1d": pd.Timedelta("24h"), "12h": pd.Timedelta("12h"),
                 "8h": pd.Timedelta("8h"), "4h": pd.Timedelta("4h"), "2h": pd.Timedelta("2h"),
                 "1h": pd.Timedelta("1h")}
    tf_td = tf_td_map.get(tf, pd.Timedelta(tf))
    # ищем последний bar где open + tf_td ≤ ts
    mask = (mh_df.index + tf_td) <= ts
    if not mask.any():
        return {f"mh_{tf}_{fld}": None for fld in MH_FIELDS}
    last_idx = mh_df.index[mask][-1]
    row = mh_df.loc[last_idx]
    return {f"mh_{tf}_{fld}": row[fld] for fld in MH_FIELDS}


def build_pivot_dataset(
    df_1m: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    tfs: tuple[str, ...] = PIVOT_TFS,
    horizon_hours: tuple[int, ...] = (12, 24),
    pivot_n: int = 2,
    min_hold_bars: int = 0,
    min_reversal_pct: float = 0.0,
    verbose: bool = True,
) -> pd.DataFrame:
    """
    Сбор labelled датасета.

    Каждая строка = один 1h bar в [start, end]:
      - все MH features на 7 TF (35 фич)
      - is_current_pivot (FH/FL = 'short'/'long' или 'none')
      - forward-looking labels: pivot_in_12h_long, pivot_in_12h_short, pivot_in_24h_long, pivot_in_24h_short
    """
    t0 = time.time()

    # 1. Precompute MH per TF на полном диапазоне
    if verbose:
        print(f"[1/3] Precompute MoneyHands per TF (7 TFs)...")
    mh_per_tf = _precompute_mh_per_tf(df_1m, tfs, end + pd.Timedelta(hours=2))
    if verbose:
        print(f"  done in {time.time()-t0:.1f}s")

    # 2. Найти все pivots (для current_pivot маркера и forward-looking labels)
    if verbose:
        print(f"[2/3] Detect pivots...")
    t1 = time.time()
    pivots = find_1h_pivots(
        df_1m, start - pd.Timedelta(days=2), end + pd.Timedelta(days=2),
        n=pivot_n, min_hold_bars=min_hold_bars, min_reversal_pct=min_reversal_pct,
    )
    pivot_by_ts: dict[pd.Timestamp, list] = {}
    for p in pivots:
        pivot_by_ts.setdefault(p.center_ts, []).append(p)
    if verbose:
        print(f"  {len(pivots)} pivots in {time.time()-t1:.1f}s")

    # 3. Собираем строки по каждому 1h bar в [start, end]
    if verbose:
        print(f"[3/3] Build rows...")
    t2 = time.time()
    df_1h = mh_per_tf["1h"]
    bars_in_range = df_1h.loc[(df_1h.index >= start) & (df_1h.index <= end)]

    records: list[dict] = []
    for ts, _ in bars_in_range.iterrows():
        # Сначала собираем все MH-фичи
        row = {"bar_ts": ts}
        for tf in tfs:
            row.update(_mh_state_at_ts(mh_per_tf[tf], tf, ts + pd.Timedelta(hours=1)))
            # +1h т.к. для 1h bar мы используем СОБСТВЕННОЕ закрытие как cut-off

        # is_current_pivot
        current_piv_dirs = [p.direction for p in pivot_by_ts.get(ts, [])]
        row["is_current_pivot"] = (
            "both" if {"long", "short"}.issubset(current_piv_dirs)
            else ("long" if "long" in current_piv_dirs
                  else ("short" if "short" in current_piv_dirs else "none"))
        )

        # forward-looking labels на каждом горизонте
        for H in horizon_hours:
            horizon_end = ts + pd.Timedelta(hours=H)
            had_long = False
            had_short = False
            for p in pivots:
                if p.center_ts <= ts:
                    continue
                if p.center_ts > horizon_end:
                    continue
                if p.direction == "long":
                    had_long = True
                else:
                    had_short = True
                if had_long and had_short:
                    break
            row[f"pivot_in_{H}h_long"] = had_long
            row[f"pivot_in_{H}h_short"] = had_short

        records.append(row)

    if verbose:
        print(f"  {len(records)} rows in {time.time()-t2:.1f}s")

    return pd.DataFrame(records)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--pivot-n", type=int, default=2)
    p.add_argument("--min-hold", type=int, default=0)
    p.add_argument("--min-reversal-pct", type=float, default=0.0)
    args = p.parse_args()

    start = pd.Timestamp(args.start, tz="UTC")
    end = pd.Timestamp(args.end, tz="UTC")

    # Грузим 1m с большим lookback (для 3d MH нужно ~75 баров = 225 дней)
    df = load_btc_1m(start=start - pd.Timedelta(days=250), end=end + pd.Timedelta(days=2))
    print(f"Loaded {len(df)} 1m bars")

    ds = build_pivot_dataset(
        df, start=start, end=end,
        pivot_n=args.pivot_n,
        min_hold_bars=args.min_hold,
        min_reversal_pct=args.min_reversal_pct,
    )
    print(f"Dataset: {ds.shape[0]} rows × {ds.shape[1]} cols")
    ds.to_csv(args.out, index=False)
    print(f"Saved: {args.out}")

    # Summary
    print(f"\nLabels summary:")
    for col in [c for c in ds.columns if c.startswith("pivot_in_")]:
        n = int(ds[col].sum())
        print(f"  {col}: {n}/{len(ds)} ({100*n/len(ds):.1f}%)")
    print(f"\nis_current_pivot distribution:")
    print(ds["is_current_pivot"].value_counts())


if __name__ == "__main__":
    main()
