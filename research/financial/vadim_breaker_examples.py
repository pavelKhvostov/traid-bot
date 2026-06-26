"""Вытащить КОНКРЕТНЫЕ примеры цепочки HTF-breaker(8h)+1d-CHoCH-гейт на BTC для отрисовки на TV.

Для каждого сетапа: зона breaker-флипа, дата активации, вход(лимит в зону), SL(ATR), TP(RR3), исход.
Печатает последние N сделок (разрешённых исходов) с ISO-датами и ценами.

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/financial/vadim_breaker_examples.py
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
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "smc-lib"))
from candle import Candle  # noqa: E402
from elements.ob.code import detect_ob  # noqa: E402
from elements.breaker_block.code import detect_breaker  # noqa: E402
from elements.choch_bos.code import scan_market_structure  # noqa: E402

SYM = "BTCUSDT"
ENTRY_TF, GATE_TF = "8h", "1d"
SL_MULT, RR = 0.5, 3.0
TF_HOURS = {"1h": 1, "2h": 2, "4h": 4, "6h": 6, "8h": 8, "12h": 12, "1d": 24}


def load_1m(s):
    df = pd.read_csv(ROOT / "data" / f"{s}_1m.csv", parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def rs(df, f):
    return df.resample(f, origin="epoch", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["close"])


def atr_tf(df, n=14):
    h, l, c = df.high.values, df.low.values, df.close.values
    pc = np.roll(c, 1); pc[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return pd.Series(tr).rolling(n, min_periods=3).mean().values


def cndl(df):
    o, h, lo, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    t = df.index.view("int64") // 1_000_000
    return [Candle(float(o[i]), float(h[i]), float(lo[i]), float(c[i]), int(t[i])) for i in range(len(df))]


def breaker_arms(dtf, atr, cnd):
    n = len(cnd); out = []
    for i in range(1, n - 1):
        ob = detect_ob(cnd[i - 1], cnd[i])
        if ob is None:
            continue
        br = detect_breaker(ob, cnd[i + 1:])
        if br is None:
            continue
        arm = i + 1 + br.activated_at_idx
        if arm >= n or not np.isfinite(atr[arm]) or atr[arm] <= 0:
            continue
        z_lo, z_hi = br.initial_zone
        if z_hi <= z_lo:
            continue
        # direction: bullish breaker -> ждём разворот вниз (SHORT, +1); bearish -> LONG (-1)
        out.append((-1 if br.direction == "bullish" else 1, z_lo, z_hi, float(atr[arm]), arm, dtf.index[arm]))
    return out


def struct_events(dtf, cnd, want):
    try:
        evs = scan_market_structure(cnd)
    except Exception:
        return []
    out = []
    for ev in evs:
        if want != "any" and ev.type != want:
            continue
        if ev.break_idx is None or ev.break_idx >= len(dtf):
            continue
        out.append((1 if ev.side == "bullish" else -1, dtf.index[ev.break_idx]))
    return out


def main():
    d1 = load_1m(SYM)
    edtf = rs(d1, ENTRY_TF); eatr = atr_tf(edtf); ecnd = cndl(edtf)
    gdtf = rs(d1, GATE_TF); gcnd = cndl(gdtf)
    arms = breaker_arms(edtf, eatr, ecnd)
    evs = struct_events(gdtf, gcnd, "CHoCH")
    Kdur = pd.Timedelta(hours=TF_HOURS[GATE_TF] * 10)
    gated = [a for a in arms if any(es == a[0] and (a[5] - Kdur) <= ets <= a[5] for (es, ets) in evs)]

    h = edtf.high.values; lo = edtf.low.values; c = edtf.close.values; n = len(c)
    idx = edtf.index
    trades = []
    for (d, z_lo, z_hi, a, arm, ats) in gated:
        e = 0.5 * (z_lo + z_hi)
        # вход: первая свеча после arm, коснувшаяся зоны (лимит в mid)
        f = None
        for j in range(arm + 1, min(arm + 81, n)):
            if lo[j] <= e <= h[j]:
                f = j; break
        if f is None or f + 1 >= n:
            continue
        # КОНВЕНЦИЯ ХАРНЕСА (signed=d*(c-e)): d==1 -> LONG, d==-1 -> SHORT (fade флипа)
        if d == 1:  # LONG
            sp = e - SL_MULT * a; tp = e + SL_MULT * a * RR
            end = min(f + 61, n)
            sh = np.nonzero(lo[f + 1:end] <= sp)[0]; th = np.nonzero(h[f + 1:end] >= tp)[0]
        else:       # SHORT
            sp = e + SL_MULT * a; tp = e - SL_MULT * a * RR
            end = min(f + 61, n)
            sh = np.nonzero(h[f + 1:end] >= sp)[0]; th = np.nonzero(lo[f + 1:end] <= tp)[0]
        si = sh[0] if sh.size else 10**9; ti = th[0] if th.size else 10**9
        if si == 10**9 and ti == 10**9:
            outc = "open"; exit_t = None; res_R = np.nan
        elif ti < si:
            outc = "WIN"; exit_t = idx[f + 1 + ti]; res_R = RR
        else:
            outc = "LOSS"; exit_t = idx[f + 1 + si]; res_R = -1.0
        trades.append(dict(dir="LONG" if d == 1 else "SHORT", z_lo=z_lo, z_hi=z_hi, entry=e,
                           sl=sp, tp=tp, atr=a, arm_t=ats, fill_t=idx[f], exit_t=exit_t,
                           outcome=outc, R=res_R))

    print(f"=== HTF-breaker(8h)+1d-CHoCH-гейт на {SYM}: {len(trades)} сетапов с заполнением ===\n")
    closed = [t for t in trades if t["outcome"] in ("WIN", "LOSS")]
    wins = sum(1 for t in closed if t["outcome"] == "WIN")
    print(f"закрыто {len(closed)}: WIN {wins} / LOSS {len(closed)-wins}  WR={wins/max(1,len(closed)):.1%}  "
          f"ΣR={sum(t['R'] for t in closed):+.1f}\n")
    print("ПОСЛЕДНИЕ 6 закрытых (для отрисовки):")
    for t in closed[-6:]:
        print(f"  {t['dir']:5} | вход {t['entry']:.0f} зона[{t['z_lo']:.0f}-{t['z_hi']:.0f}] "
              f"SL {t['sl']:.0f} TP {t['tp']:.0f} | заполн {t['fill_t']:%Y-%m-%d %H:%M} "
              f"вых {t['exit_t']:%Y-%m-%d %H:%M} -> {t['outcome']} ({t['R']:+.0f}R)")
    # сохранить полную таблицу
    pd.DataFrame(trades).to_csv(Path(__file__).resolve().parent / "breaker_examples_btc.csv", index=False)
    print(f"\n-> breaker_examples_btc.csv ({len(trades)} строк)")


if __name__ == "__main__":
    main()
