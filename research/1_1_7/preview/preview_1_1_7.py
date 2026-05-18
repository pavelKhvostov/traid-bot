"""Preview Strategy 1.1.7 — последние 10 сигналов на BTCUSDT (3y data).

Печатает все ключевые времена в UTC+3 для визуальной сверки на TV.
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

import pandas as pd

from data_manager import compose_from_base, load_df
from strategies.strategy_1_1_7 import detect_strategy_1_1_7_signals


def msk(ts) -> str:
    if ts is None or ts == "":
        return ""
    return (pd.Timestamp(ts) + pd.Timedelta(hours=3)).strftime("%Y-%m-%d %H:%M")


def main():
    print("[INFO] загрузка данных")
    df_4h = load_df("BTCUSDT", "4h")
    df_1h = load_df("BTCUSDT", "1h")
    df_15m = load_df("BTCUSDT", "15m")
    df_2h = compose_from_base(df_1h, "2h")
    df_20m = compose_from_base(df_15m, "20m") if df_15m is not None else None
    print(f"  4h={len(df_4h)} 1h={len(df_1h)} 2h={len(df_2h)} "
          f"15m={len(df_15m)} 20m={len(df_20m) if df_20m is not None else 0}")

    # 3y cutoff
    today = pd.Timestamp.utcnow().normalize()
    if today.tz is None:
        today = today.tz_localize("UTC")
    cutoff = today - pd.Timedelta(days=1095)
    df_4h_f = df_4h[df_4h.index >= cutoff]

    print(f"  4h after cutoff ({cutoff.date()}): {len(df_4h_f)}")
    print()

    sigs = detect_strategy_1_1_7_signals(
        df_4h=df_4h_f, df_1h=df_1h, df_2h=df_2h,
        df_15m=df_15m, df_20m=df_20m,
        verbose=True,
    )
    print(f"\n  raw signals (no dedup): {len(sigs)}")

    if not sigs:
        return

    sigs.sort(key=lambda s: s["signal_time"], reverse=True)
    print()
    print("=" * 90)
    print(f"Последние {min(10, len(sigs))} сигналов (UTC+3 = Москва):")
    print("=" * 90)
    for s in sigs[:10]:
        poi = s["poi_zone"]
        ob = s["ob_zone"]
        fvg = s["fvg_zone"]
        print(
            f"\n  {s['direction']}  signal_time(fvg.c2)={msk(s['signal_time'])}  "
            f"ob_tf={s['ob_tf']}  fvg_tf={s['fvg_tf']}"
        )
        print(f"    fractal_4h: {msk(s['fractal_time'])}  price={s['fractal_price']:.2f}")
        print(f"    sweep_4h:   open={msk(s['sweep_time'])}  close={msk(s['sweep_close_time'])}")
        print(f"    POI zone:   [{poi[0]:.2f}, {poi[1]:.2f}]")
        inval = s.get("invalidation_time")
        print(f"    invalidation: {msk(inval) if inval else 'none'}")
        print(f"    OB:         cur={msk(s['ob_cur_time'])}  zone=[{ob[0]:.2f}, {ob[1]:.2f}]")
        print(f"    FVG:        c2={msk(s['fvg_c2_time'])}  zone=[{fvg[0]:.2f}, {fvg[1]:.2f}]")
        print(f"    Entry={s['entry']:.2f}  SL={s['sl']:.2f}  TP={s['tp']:.2f}  "
              f"risk={s['risk']:.2f}")


if __name__ == "__main__":
    main()
