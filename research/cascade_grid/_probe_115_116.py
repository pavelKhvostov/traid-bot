"""Smoke: проверить, что фиксы g_115/g_116 дают сигналы на BTC без KeyError."""
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
import decorrelation as D  # noqa: E402
import live_skeleton_top3 as LS  # noqa: E402

d1 = LS.load_1m("BTCUSDT")
tfs = {tl: LS.rs(d1, fr) for tl, fr in
       [("1d", "1d"), ("12h", "12h"), ("4h", "4h"), ("6h", "6h"),
        ("1h", "1h"), ("2h", "2h"), ("15m", "15min"), ("20m", "20min")]}
s5 = D.g_115(tfs)
s6 = D.g_116(tfs)
print(f"1.1.5 BTC signals: {len(s5)}  sample={s5[0] if s5 else None}")
print(f"1.1.6 BTC signals: {len(s6)}  sample={s6[0] if s6 else None}")
