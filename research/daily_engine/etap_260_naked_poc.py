"""etap_260 - BLOCK 2: Naked POC reaction (незакрытый объёмный POC как зона реакции).

Гипотеза: POC прошлой недели, к которому цена ещё НЕ возвращалась (virgin/naked) =
магнит + зона реакции. На ПЕРВОМ касании играем РЕАКЦИЮ (fade):
  - POC сверху (цена под ним) -> сопротивление -> SHORT на касании, SL выше
  - POC снизу -> поддержка -> LONG, SL ниже
SL = sl_atr * дневной ATR% (волатильностно-нормированный, не произвольный %), fixed RR=2.2.

Недельный POC через signal_context.volume_profile (1h-бары недели). Naked-трекинг:
POC активен пока цена его не коснулась; первое касание = сделка, потом снят.
Судим общим zone_harness. ЧЕСТНАЯ рамка та же: год-стаб, R/просадка, BTC->ETH/SOL.

Запуск: set PYTHONIOENCODING=utf-8
        venv/Scripts/python.exe research/daily_engine/etap_260_naked_poc.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(ROOT))
from data_manager import load_df
from signal_context import volume_profile
import zone_harness as ZH

RR = 2.2


def gen_naked_poc(df1h, sl_atr=1.0, atr_win=14, period="W-MON",
                  min_risk=0.003, max_risk=0.06):
    if df1h.index.tz is None: df1h.index = df1h.index.tz_localize("UTC")
    # дневной ATR% для размера стопа (true range)
    d = df1h.resample("1D").agg({"high": "max", "low": "min", "close": "last"}).dropna()
    pc = d["close"].shift(1)
    tr = pd.concat([(d.high - d.low), (d.high - pc).abs(), (d.low - pc).abs()], axis=1).max(axis=1)
    atr_pct = (tr.rolling(atr_win).mean() / d["close"]).shift(1)   # as-of предыдущего дня
    # POC по периодам
    pocs = []
    for t, g in df1h.resample(period, label="left", closed="left"):
        if len(g) < 20:
            continue
        vp = volume_profile(g)
        if not vp:
            continue
        ft = g.index[-1]; price = float(g["close"].iloc[-1])
        pocs.append((ft, float(vp[0]), price))
    pocs.sort()
    # трекинг naked + первое касание
    H = df1h["high"].values; Lo = df1h["low"].values; idx = df1h.index
    active = []   # (ft, poc, side)
    pi = 0; sig = []
    for k in range(len(df1h)):
        t = idx[k]
        while pi < len(pocs) and pocs[pi][0] <= t:
            ft, poc, price = pocs[pi]
            side = "SHORT" if price < poc else "LONG"   # poc сверху->fade short при касании снизу
            active.append((ft, poc, side)); pi += 1
        if not active:
            continue
        still = []
        for (ft, poc, side) in active:
            if ft >= t:
                still.append((ft, poc, side)); continue
            if Lo[k] <= poc <= H[k]:      # первое касание -> сделка, снимаем
                day = t.normalize()
                ap = atr_pct.reindex([day]).iloc[0] if day in atr_pct.index else np.nan
                if ap and ap > 0:
                    risk = poc * ap * sl_atr
                    rp = risk / poc
                    if min_risk <= rp <= max_risk:
                        sl = poc + risk if side == "SHORT" else poc - risk
                        # time=t-1 чтобы активация лимита прошла на баре касания k (без lookahead:
                        # уровень poc известен заранее из прошлой недели)
                        sig.append(dict(time=idx[k - 1] if k > 0 else t,
                                        direction=side, entry=poc, sl=float(sl)))
                # снят в любом случае (коснулись)
            else:
                still.append((ft, poc, side))
        active = still
    return sig


def run_symbol(sym, period="W-MON"):
    df1h = load_df(sym, "1h")
    if df1h.empty:
        print(f"{sym}: нет данных"); return None
    if df1h.index.tz is None: df1h.index = df1h.index.tz_localize("UTC")
    sigs = gen_naked_poc(df1h, period=period)
    book = ZH.simulate(sigs, df1h, rr=RR)
    return ZH.report(book, rr=RR, title=f"{sym} NAKED POC fade ({period}) | сигналов {len(sigs)}")


def main():
    for period, lab in (("W-MON", "недельный"), ("1D", "дневной")):
        print("\n" + "#" * 76)
        print(f"#  POC-период = {lab}")
        print("#" * 76)
        for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
            run_symbol(sym, period=period)


if __name__ == "__main__":
    main()
