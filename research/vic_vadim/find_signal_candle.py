"""ViC Vadim — условие 1 (LONG):

Сигнальная D-свеча: внутри неё на одном из ТФ {1h, 2h, 90m} формируется
LONG OB или LONG FVG, чья зона содержит maxV(D) и не митигирована до close D.

  • OB-canon: zone = [min(prev.low, cur.low), prev.open], prev bear, cur bull, close > prev.open
  • FVG-canon: high(i-2) < low(i) → zone = [high(i-2), low(i)]
  • митигация: ни один бар того же ТФ ПОСЛЕ формирования зоны и ДО close D не входит в неё.

LTF=15m для maxV (VIC_LTF_MINUTES в config.py).
Все ТФ {1h, 2h, 90m} composeятся из 15m с origin=epoch.

Запуск: .venv/bin/python research/vic_vadim/find_signal_candle.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from vic_levels import calculate_vic_d

CACHE_15M = ROOT / "data" / "BTCUSDT_15m_vic_vadim.csv"
MTF_LIST: list[tuple[str, str]] = [("1h", "60min"), ("2h", "120min"), ("90m", "90min")]


def load_15m() -> pd.DataFrame:
    df = pd.read_csv(CACHE_15M, parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df


def compose(df_15m: pd.DataFrame, freq: str) -> pd.DataFrame:
    return df_15m.resample(freq, origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna(subset=["close"])


def aggregate_to_daily(df_15m: pd.DataFrame) -> pd.DataFrame:
    return df_15m.resample("1D", origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna(subset=["close"])


def detect_long_ob_in_window(
    bars: pd.DataFrame, maxv: float, window_start: pd.Timestamp, window_end: pd.Timestamp,
) -> list[dict]:
    """Найти все LONG OB, у которых пара (prev, cur) лежит в [window_start, window_end)
    и зона содержит maxV. Митигация считается на барах ПОСЛЕ cur и < window_end.
    Возвращает только немитигированные."""
    inside = bars[(bars.index >= window_start) & (bars.index < window_end)]
    if len(inside) < 2:
        return []
    out = []
    for k in range(len(inside) - 1):
        prev = inside.iloc[k]
        cur = inside.iloc[k + 1]
        # LONG OB: prev bearish, cur bullish, cur.close > prev.open
        if not (prev["close"] < prev["open"] and cur["close"] > cur["open"]):
            continue
        if not (cur["close"] > prev["open"]):
            continue
        zone_bottom = min(prev["low"], cur["low"])
        zone_top = prev["open"]
        if zone_top <= zone_bottom:
            continue
        if not (zone_bottom <= maxv <= zone_top):
            continue
        # митигация: бары после cur и до window_end
        after = inside.iloc[k + 2:]
        if len(after) > 0:
            touched = ((after["low"] <= zone_top) & (after["high"] >= zone_bottom)).any()
            if touched:
                continue
        out.append({
            "kind": "OB", "ob_time": prev.name, "cur_time": cur.name,
            "zone_bottom": zone_bottom, "zone_top": zone_top,
        })
    return out


def detect_long_fvg_in_window(
    bars: pd.DataFrame, maxv: float, window_start: pd.Timestamp, window_end: pd.Timestamp,
) -> list[dict]:
    """LONG FVG: high(i-2) < low(i) → zone = [high(i-2), low(i)].
    Тройка (i-2, i-1, i) лежит в [window_start, window_end). Митигация на барах после i."""
    inside = bars[(bars.index >= window_start) & (bars.index < window_end)]
    if len(inside) < 3:
        return []
    out = []
    for k in range(len(inside) - 2):
        c0 = inside.iloc[k]
        c2 = inside.iloc[k + 2]
        if not (c0["high"] < c2["low"]):
            continue
        zone_bottom = c0["high"]
        zone_top = c2["low"]
        if not (zone_bottom <= maxv <= zone_top):
            continue
        after = inside.iloc[k + 3:]
        if len(after) > 0:
            touched = ((after["low"] <= zone_top) & (after["high"] >= zone_bottom)).any()
            if touched:
                continue
        out.append({
            "kind": "FVG", "c0_time": c0.name, "c2_time": c2.name,
            "zone_bottom": zone_bottom, "zone_top": zone_top,
        })
    return out


def main() -> None:
    df_15m = load_15m()
    print(f"15m: {len(df_15m)} bars  {df_15m.index.min()} → {df_15m.index.max()}")

    # MTF композиция
    mtf_bars: dict[str, pd.DataFrame] = {tf: compose(df_15m, freq) for tf, freq in MTF_LIST}
    for tf, df_tf in mtf_bars.items():
        print(f"  composed {tf}: {len(df_tf)} bars")

    df_d = aggregate_to_daily(df_15m)
    print(f"D: {len(df_d)} bars")

    df_in = df_15m.copy()
    df_in.index.name = None
    # maxV per D (LTF=15m, наши 15m уже native → ltf_minutes=1 в функции = no-op resample)
    df_d["maxV"] = [calculate_vic_d(df_in, day, ltf_minutes=1) for day in df_d.index]
    df_d = df_d.dropna(subset=["maxV"])

    print(f"\nищем сигнальные D: внутри есть нем. LONG OB/FVG на 1h/2h/90m, "
          f"зона содержит maxV ({len(df_d)} D-свечей)")

    records: list[dict] = []
    for day, d_row in df_d.iterrows():
        d_start = day  # 00:00 UTC
        d_end = day + pd.Timedelta(days=1)
        m = d_row["maxV"]
        found: list[dict] = []
        for tf, _freq in MTF_LIST:
            bars = mtf_bars[tf]
            obs = detect_long_ob_in_window(bars, m, d_start, d_end)
            fvgs = detect_long_fvg_in_window(bars, m, d_start, d_end)
            for r in obs + fvgs:
                r["tf"] = tf
                found.append(r)
        if found:
            records.append({
                "day": day, "maxV": m,
                "open": d_row["open"], "high": d_row["high"],
                "low": d_row["low"], "close": d_row["close"],
                "n_zones": len(found), "zones": found,
            })

    print(f"\n=== Сигнальных D-свечей: {len(records)} из {len(df_d)} "
          f"({len(records)/len(df_d)*100:.1f}%) ===\n")

    # breakdown по типу/ТФ
    by_kind_tf: dict[tuple[str, str], int] = {}
    for rec in records:
        for z in rec["zones"]:
            key = (z["tf"], z["kind"])
            by_kind_tf[key] = by_kind_tf.get(key, 0) + 1
    if by_kind_tf:
        print("Распределение зон по (TF, kind):")
        for key, cnt in sorted(by_kind_tf.items()):
            print(f"  {key[0]:>3} {key[1]:>3}: {cnt}")

    show = min(3, len(records))
    print(f"\n=== Последние {show} сигнальных D-свечей ===\n")
    for idx, k in enumerate(range(len(records) - show, len(records)), 1):
        rec = records[k]
        d = rec["day"]
        print(f"#{idx}  {d.date()}: o={rec['open']:.2f} h={rec['high']:.2f} "
              f"l={rec['low']:.2f} c={rec['close']:.2f}  maxV={rec['maxV']:.2f}")
        for z in rec["zones"][:5]:  # max 5 зон на свечу для краткости
            ts = z.get("ob_time") or z.get("c0_time")
            t2 = z.get("cur_time") or z.get("c2_time")
            print(
                f"    {z['tf']:>3} {z['kind']:>3}: "
                f"zone=[{z['zone_bottom']:.2f}, {z['zone_top']:.2f}]  "
                f"({ts.strftime('%H:%M')} → {t2.strftime('%H:%M')})",
            )
        if len(rec["zones"]) > 5:
            print(f"    ... ещё {len(rec['zones']) - 5} зон")
        print()


if __name__ == "__main__":
    main()
