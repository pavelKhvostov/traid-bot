"""etap_132: A2 (Wicked OB-D + 4-stage 1.1.1 no-SWEPT) cross-symbol на ETH/SOL.

etap_131 strict-dedup показал что A2 — лучший вариант на BTC: +36R / WR 50.7% / 1 bad year.
F12-overlay (EMA pro OR LONG): +30R / WR 52.9% / 1 bad year / 51 closed.

V2+F12 baseline на BTC = +42R / 138 closed. На ETH +4R, SOL +5R — BTC-only.
Гипотеза: A2 с дополнительным макро-уровнем может стать более универсальной.

Прогон: BTC + ETH (cutoff 2020-05-15, 5.96y) + SOL (cutoff 2020-08-11, 5.72y).
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
import importlib.util as _ilu
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists(): _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path: _sys.path.insert(0, str(_ROOT))

from collections import defaultdict
import numpy as np
import pandas as pd

from data_manager import compose_from_base, load_df

_E121 = _Path(__file__).parent / "etap_121_wicked_fractal_ob.py"
_E131 = _Path(__file__).parent / "etap_131_wicked_4stage_strict_dedup.py"
_spec = _ilu.spec_from_file_location("etap121_core", _E121)
_e121 = _ilu.module_from_spec(_spec); _sys.modules["etap121_core"] = _e121
_spec.loader.exec_module(_e121)
_spec = _ilu.spec_from_file_location("etap131_core", _E131)
_e131 = _ilu.module_from_spec(_spec); _sys.modules["etap131_core"] = _e131
_spec.loader.exec_module(_e131)
collect_wicked_fractal_obs = _e121.collect_wicked_fractal_obs
first_setup_per_ob = _e131.first_setup_per_ob
summarize = _e131.summarize

SYMBOLS = [
    ("BTCUSDT", "2020-01-01"),
    ("ETHUSDT", "2020-05-15"),
    ("SOLUSDT", "2020-08-11"),
]


def run_symbol(symbol, start_date):
    print(f"\n{'#'*72}\n# {symbol}  (cutoff {start_date})\n{'#'*72}")
    df_1d = load_df(symbol, "1d"); df_1h = load_df(symbol, "1h"); df_1m = load_df(symbol, "1m")
    if len(df_1d) == 0 or len(df_1h) == 0 or len(df_1m) == 0:
        print(f"  NO DATA for {symbol}"); return
    df_12h = compose_from_base(df_1h, "12h")
    df_4h = compose_from_base(df_1h, "4h"); df_6h = compose_from_base(df_1h, "6h")
    df_2h = compose_from_base(df_1h, "2h")
    df_15m = compose_from_base(df_1m, "15m"); df_20m = compose_from_base(df_1m, "20m")
    cutoff = pd.Timestamp(start_date, tz="UTC")
    df_1d = df_1d[df_1d.index >= cutoff].copy()
    df_1h = df_1h[df_1h.index >= cutoff].copy()
    df_12h = df_12h[df_12h.index >= cutoff].copy()
    df_4h = df_4h[df_4h.index >= cutoff].copy()
    df_6h = df_6h[df_6h.index >= cutoff].copy()
    df_2h = df_2h[df_2h.index >= cutoff].copy()
    df_15m = df_15m[df_15m.index >= cutoff].copy()
    df_20m = df_20m[df_20m.index >= cutoff].copy()
    df_1m = df_1m[df_1m.index >= cutoff]
    df_2h["ema200"] = df_2h["close"].ewm(span=200, adjust=False).mean()

    wf_1d = collect_wicked_fractal_obs(df_1d, 24)
    wf_12h = collect_wicked_fractal_obs(df_12h, 12)
    all_ob_d = [(ob, df_1d) for ob in wf_1d] + [(ob, df_12h) for ob in wf_12h]
    print(f"  wicked+fractal OB: 1d={len(wf_1d)} 12h={len(wf_12h)} total={len(all_ob_d)}")
    print()

    # A2: 1.1.1 no-SWEPT (FVG macro, e=0.80, RR=2.0)
    setups = []
    for ob, df_l1 in all_ob_d:
        s = first_setup_per_ob(ob, df_l1, df_4h, df_6h, df_1h, df_2h, df_15m, df_20m,
                               macro_kind="FVG", swept_required=False,
                               entry_pct=0.80, sl_pct=0.35)
        if s is not None: setups.append(s)

    print("  STRICT (1 setup per ob_d):")
    print("  " + "-"*100)
    summarize(f"A2 baseline ({symbol})", setups, df_1m, df_2h, rr=2.0, apply_f12=False)
    summarize(f"A2 + F12   ({symbol})", setups, df_1m, df_2h, rr=2.0, apply_f12=True)


def main():
    print("etap_132: A2 (Wicked OB-D 4-stage 1.1.1 no-SWEPT) cross-symbol ETH/SOL")
    print("BTC ref (etap_131): A2+F12 = +30R / WR 52.9% / 1 bad / 51 closed / R/tr +0.59")
    for sym, start in SYMBOLS:
        run_symbol(sym, start)


if __name__ == "__main__":
    main()
