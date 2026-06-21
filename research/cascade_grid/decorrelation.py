"""Декорреляция корзины цепочек — какие РАЗНЫЕ (не дубли) для фьючерсного счёта.

Цель (по задаче юзера): не ранжировать +EV конфиги, а выбрать набор цепочек, торгующих
РАЗНОЕ — чтобы каждая открытая позиция была независимой ставкой, а не копией.

Корзина: live 1.1.1, 1.1.2, 1.1.6, 1.1.5, 3.2 + новые A(i-RDRB+FVG), cand2(FVG-якорь), cand1(htf-RDRB).
На каждом символе (BTC/ETH/SOL):
  - сигналы цепочки → дедуп до 1 события на (символ,напр,день) [= 1 позиция/сетап/день]
  - симуляция RR=2.0 на 1m → R по месяцам
Метрики:
  1. ОВЕРЛАП (Jaccard событий (символ,напр,день)) — высокий = дубли
  2. КОРРЕЛЯЦИЯ месячных R — риск-метрик счёта (низкая = диверсификация)
  3. Жадный отбор декоррелированной корзины + инкрементальный УНИКАЛЬНЫЙ edge каждой

Запуск: set PYTHONIOENCODING=utf-8
        venv/Scripts/python.exe research/cascade_grid/decorrelation.py
Выход: research/cascade_grid/decorrelation_report.txt
"""
from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from strategies.strategy_1_1_1 import detect_strategy_1_1_1_signals, OB_SL_DEPTH  # noqa: E402
from strategies.strategy_1_1_2 import detect_strategy_1_1_2_signals  # noqa: E402
from strategies.strategy_1_1_6 import detect_strategy_1_1_6_signals  # noqa: E402
from strategies.strategy_1_1_5 import detect_strategy_1_1_5_signals  # noqa: E402
from strategies.strategy_3_2 import detect_strategy_3_2_signals  # noqa: E402
from strategies.strategy_i_rdrb_fvg import detect_all_i_rdrb_fvg  # noqa: E402
import live_skeleton_top3 as LS  # noqa: E402

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
RR = 2.0
MAX_HOLD_MIN = 30 * 24 * 60
CORR_MAX, OV_MAX = 0.50, 0.35


def rec(direction, t, entry, sl, risk):
    return {"direction": direction, "t": pd.Timestamp(t), "entry": float(entry),
            "sl": float(sl), "risk": float(risk)}


def g_111(tfs):
    s = detect_strategy_1_1_1_signals(tfs["1d"], tfs["12h"], tfs["4h"], tfs["6h"],
                                      tfs["1h"], tfs["2h"], tfs["15m"], tfs["20m"])
    return [rec(x["direction"], x["signal_time"], x["entry"], x["sl"], x["risk"]) for x in s]


def g_112(tfs):
    s = detect_strategy_1_1_2_signals(tfs["1d"], tfs["12h"], tfs["4h"], tfs["6h"],
                                      tfs["1h"], tfs["2h"], tfs["15m"], tfs["20m"])
    return [rec(x["direction"], x["signal_time"], x["entry"], x["sl"], x["risk"]) for x in s]


def g_116(tfs):
    # 1.1.6 даёт entry/sl, но НЕ risk -> вычисляем.
    s = detect_strategy_1_1_6_signals(tfs["1d"], tfs["12h"], tfs["4h"], tfs["6h"],
                                      tfs["1h"], tfs["2h"])
    return [rec(x["direction"], x["signal_time"], x["entry"], x["sl"], abs(x["entry"] - x["sl"]))
            for x in s]


def g_115(tfs):
    # 1.1.5 возвращает только зоны (entry/SL — TBD). Выводим как семейство:
    # entry = mid(fvg_entry_zone), SL = внутрь macro_ob_zone на OB_SL_DEPTH.
    s = detect_strategy_1_1_5_signals(tfs["1d"], tfs["4h"], tfs["6h"], tfs["1h"],
                                      tfs["2h"], tfs["15m"], tfs["20m"])
    out = []
    for x in s:
        fb, ft = x["fvg_entry_zone"]
        mb, mt = x["macro_ob_zone"]
        entry = (fb + ft) / 2.0
        depth = mt - mb
        sl = mb + depth * OB_SL_DEPTH if x["direction"] == "LONG" else mt - depth * OB_SL_DEPTH
        risk = abs(entry - sl)
        if risk <= 0 or (x["direction"] == "LONG" and sl >= entry) or \
           (x["direction"] == "SHORT" and sl <= entry):
            continue
        out.append(rec(x["direction"], x["signal_time"], entry, sl, risk))
    return out


def g_32(tfs):
    s = detect_strategy_3_2_signals(tfs["4h"], tfs["1h"])
    return [rec(x["direction"], x["signal_time"], x["entry"], x["sl"], x["risk"]) for x in s]


def g_A(tfs):
    return [rec(s.direction, s.c5_time + pd.Timedelta(hours=1), s.entry, s.sl, s.risk)
            for s in detect_all_i_rdrb_fvg(tfs["1h"])]


def g_cand2(tfs):
    return [rec(d, arm, e, sl, r) for (d, e, sl, r, arm) in LS.scan_strict(tfs, "FVG", "OB", "OB")]


def g_cand1(tfs):
    return [rec(d, arm, e, sl, r) for (d, e, sl, r, arm) in LS.scan_strict(tfs, "OB", "OB", "RDRB")]


CHAINS = {
    "1.1.1": g_111, "1.1.2": g_112, "1.1.6": g_116, "1.1.5": g_115, "3.2": g_32,
    "A-iRDRB": g_A, "cand2-FVGtop": g_cand2, "cand1-htfRDRB": g_cand1,
}


def dedup_daily(records, symbol):
    """1 событие на (символ,напр,день): первый по времени."""
    by_key = {}
    for r in sorted(records, key=lambda x: x["t"]):
        key = (symbol, r["direction"], r["t"].date())
        if key not in by_key:
            r2 = dict(r); r2["key"] = key
            by_key[key] = r2
    return list(by_key.values())


def sim_one(r, idx_u, lo, hi):
    sp = int(np.searchsorted(idx_u, int(r["t"].timestamp()), side="left"))
    if sp >= len(lo):
        return None
    end = min(sp + MAX_HOLD_MIN, len(lo))
    d, entry, slv, risk = r["direction"], r["entry"], r["sl"], r["risk"]
    fh = np.where(lo[sp:end] <= entry)[0] if d == "LONG" else np.where(hi[sp:end] >= entry)[0]
    if not fh.size:
        return None
    f = sp + int(fh[0]); plo, phi = lo[f:end], hi[f:end]
    tp = entry + RR * risk if d == "LONG" else entry - RR * risk
    slm, tpm = (plo <= slv, phi >= tp) if d == "LONG" else (phi >= slv, plo <= tp)
    sf = int(np.argmax(slm)) if slm.any() else 10**9
    tf_ = int(np.argmax(tpm)) if tpm.any() else 10**9
    if sf == 10**9 and tf_ == 10**9:
        return None
    return RR if tf_ < sf else -1.0


def jaccard(a, b):
    return len(a & b) / len(a | b) if (a or b) else 0.0


def main():
    t0 = time.time()
    print("[decorr] generate signals per chain x symbol...", flush=True)
    events = {c: set() for c in CHAINS}        # set of (symbol,dir,date)
    trades = {c: [] for c in CHAINS}           # list of {key, month, R}

    for sym in SYMBOLS:
        d1 = LS.load_1m(sym)
        tfs = {tl: LS.rs(d1, fr) for tl, fr in
               [("1d", "1d"), ("12h", "12h"), ("4h", "4h"), ("6h", "6h"),
                ("1h", "1h"), ("2h", "2h"), ("15m", "15min"), ("20m", "20min")]}
        idx_u = (d1.index.view("int64") // 1_000_000_000).astype(np.int64)
        lo = d1["low"].to_numpy(); hi = d1["high"].to_numpy()
        for cname, gen in CHAINS.items():
            try:
                raw = gen(tfs)
            except Exception as ex:
                print(f"   {sym} {cname} ERROR: {ex}", flush=True); traceback.print_exc(); continue
            dd = dedup_daily(raw, sym)
            closed = 0
            for r in dd:
                events[cname].add(r["key"])
                R = sim_one(r, idx_u, lo, hi)
                if R is not None:
                    trades[cname].append({"key": r["key"], "month": r["t"].to_period("M"), "R": R})
                    closed += 1
            print(f"   {sym:8} {cname:14} events={len(dd):4} closed={closed:4}", flush=True)

    names = list(CHAINS)
    summ = {}
    for c in names:
        sR = sum(x["R"] for x in trades[c]); n = len(trades[c])
        summ[c] = {"events": len(events[c]), "closed": n, "sumR": sR,
                   "ptt": sR / n if n else 0.0}

    # monthly R matrix -> correlation
    allmonths = sorted({x["month"] for c in names for x in trades[c]})
    mat = pd.DataFrame(0.0, index=[str(m) for m in allmonths], columns=names)
    for c in names:
        for x in trades[c]:
            mat.loc[str(x["month"]), c] += x["R"]
    corr = mat.corr().fillna(0.0)

    # overlap (Jaccard) matrix
    ov = pd.DataFrame(0.0, index=names, columns=names)
    for a in names:
        for b in names:
            ov.loc[a, b] = jaccard(events[a], events[b])

    # greedy decorrelated basket (по ΣR, добавляем если corr<=CORR_MAX и overlap<=OV_MAX)
    order = sorted(names, key=lambda c: summ[c]["sumR"], reverse=True)
    basket, basket_events, log = [], set(), []
    for c in order:
        uniqR = sum(x["R"] for x in trades[c] if x["key"] not in basket_events)
        if not basket:
            basket.append(c); basket_events |= events[c]
            log.append(f"  {c:14} SEED  ΣR={summ[c]['sumR']:+.1f}")
            continue
        mc = max(abs(corr.loc[c, b]) for b in basket)
        mo = max(ov.loc[c, b] for b in basket)
        decorr_ok = mc <= CORR_MAX and mo <= OV_MAX
        if decorr_ok and uniqR > 0:
            basket.append(c); basket_events |= events[c]
            log.append(f"  {c:14} ADD   maxcorr={mc:.2f} maxov={mo:.2f} uniqR={uniqR:+.1f}")
        elif not decorr_ok:
            who_c = max(basket, key=lambda b: abs(corr.loc[c, b]))
            who_o = max(basket, key=lambda b: ov.loc[c, b])
            log.append(f"  {c:14} SKIP-dup  maxcorr={mc:.2f}(~{who_c}) maxov={mo:.2f}(~{who_o})")
        else:
            log.append(f"  {c:14} SKIP-noEdge  декоррелирован, но уникальный edge uniqR={uniqR:+.1f} (база-геометрия)")

    rep = HERE / "decorrelation_report.txt"
    with rep.open("w", encoding="utf-8") as f:
        f.write(f"ДЕКОРРЕЛЯЦИЯ КОРЗИНЫ — {time.time()-t0:.0f}s; RR={RR}; дедуп 1/(символ,напр,день)\n")
        f.write("Вопрос: какие цепочки торгуют РАЗНОЕ (не дубли) для независимых фьюч-позиций.\n\n")
        f.write("=== Per-chain (BTC+ETH+SOL суммарно) ===\n")
        f.write(f"{'chain':14} {'events':>7} {'closed':>7} {'sumR':>8} {'ptt':>7}\n")
        for c in order:
            s = summ[c]
            f.write(f"{c:14} {s['events']:>7} {s['closed']:>7} {s['sumR']:>+8.1f} {s['ptt']:>+7.3f}\n")
        f.write("\n=== ОВЕРЛАП (Jaccard событий; >0.35 = дубли) ===\n")
        f.write(f"{'':12}" + "".join(f"{c[:9]:>10}" for c in names) + "\n")
        for a in names:
            f.write(f"{a:12}" + "".join(f"{ov.loc[a, b]:>10.2f}" for b in names) + "\n")
        f.write("\n=== КОРРЕЛЯЦИЯ месячных R (>0.5 = коррелированы) ===\n")
        f.write(f"{'':12}" + "".join(f"{c[:9]:>10}" for c in names) + "\n")
        for a in names:
            f.write(f"{a:12}" + "".join(f"{corr.loc[a, b]:>10.2f}" for b in names) + "\n")
        f.write(f"\n=== ЖАДНАЯ ДЕКОРРЕЛИРОВАННАЯ КОРЗИНА (corr<={CORR_MAX}, overlap<={OV_MAX}) ===\n")
        for line in log:
            f.write(line + "\n")
        f.write(f"\n  ИТОГ КОРЗИНА ({len(basket)}): {basket}\n")
        bvec = mat[basket].sum(axis=1)
        best = max(names, key=lambda c: summ[c]["sumR"])
        svec = mat[best]
        bsh = bvec.mean() / bvec.std() if bvec.std() else 0
        ssh = svec.mean() / svec.std() if svec.std() else 0
        f.write(f"\n  Корзина combined: ΣR/мес mean={bvec.mean():+.2f} std={bvec.std():.2f} Sharpe~{bsh:.2f}\n")
        f.write(f"  Лучшая одиночка {best}: mean={svec.mean():+.2f} std={svec.std():.2f} Sharpe~{ssh:.2f}\n")
        f.write(f"  -> диверсификация {'УЛУЧШАЕТ' if bsh > ssh else 'НЕ улучшает'} Sharpe-like\n")
    print(f"[decorr] DONE {time.time()-t0:.0f}s; basket={basket}", flush=True)


if __name__ == "__main__":
    main()
