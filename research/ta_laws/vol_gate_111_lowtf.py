"""ТОНКИЙ вола-гейт: даёт ли НИЗКИЙ ТФ (1h-режим на момент входа) более резкую сортировку 1.1.1, чем 12h?

12h-режим грубый (весь 12h-блок). Тоньше = atr-перцентиль на 1h в момент ФАКТИЧЕСКОГО входа (fill). Сравниваем
сепарацию exp-vs-quiet ptt для: 12h@signal (baseline) vs 1h-168 (нед.) @fill vs 1h-48 (2дн) @fill. Cross-asset.
Реальный 1.1.1 (канон-детектор, entry0.80/sl0.35/RR=2.2, dedup), BTC+ETH+SOL.

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/ta_laws/vol_gate_111_lowtf.py
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
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "research" / "ta_laws"))
import geometry as G  # noqa: E402
from data_manager import load_df, compose_from_base  # noqa: E402
from strategies.strategy_1_1_1 import detect_strategy_1_1_1_signals  # noqa: E402

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
DAYS_BACK = 2400
RR = 2.2
MAX_HOLD_MIN = 30 * 24 * 60
Q_LO, Q_HI = 0.40, 0.60


def dedup(sigs):
    seen, out = set(), []
    for s in sorted(sigs, key=lambda x: x["signal_time"]):
        k = (s["signal_time"], s["direction"], round(float(s["entry"]), 6))
        if k in seen:
            continue
        seen.add(k); out.append(s)
    return out


def sim_vec(sigs, df_1m, rr):
    """limit-fill + SL/TP; -> (signal_time, fill_time, dir, win)."""
    lo = df_1m["low"].to_numpy(); hi = df_1m["high"].to_numpy(); idx = df_1m.index
    out = []
    for s in sigs:
        d = s["direction"]; entry = float(s["entry"]); slv = float(s["sl"]); risk = float(s["risk"])
        if risk <= 0:
            continue
        tfm = 15 if s["fvg_tf"] == "15m" else 20
        arm = s["signal_time"] + pd.Timedelta(minutes=tfm)
        sp = int(idx.searchsorted(arm, side="left"))
        if sp >= len(lo):
            continue
        end = min(sp + MAX_HOLD_MIN, len(lo))
        fh = np.where(lo[sp:end] <= entry)[0] if d == "LONG" else np.where(hi[sp:end] >= entry)[0]
        if not fh.size:
            continue
        f = sp + int(fh[0]); plo, phi = lo[f:end], hi[f:end]
        tp = entry + rr * risk if d == "LONG" else entry - rr * risk
        slm, tpm = (plo <= slv, phi >= tp) if d == "LONG" else (phi >= slv, plo <= tp)
        sf = int(np.argmax(slm)) if slm.any() else 10**9
        tf_ = int(np.argmax(tpm)) if tpm.any() else 10**9
        if sf == 10**9 and tf_ == 10**9:
            continue
        out.append((s["signal_time"], idx[f], d, tf_ < sf))
    return out


def regime_series(df, tf_hours, win):
    atr = G.compute_atr(df[["high", "low", "close"]])
    atr_pct = atr / df["close"].values * 100
    pctile = pd.Series(atr_pct).rolling(win, min_periods=max(20, win // 4)).apply(
        lambda s: (s.iloc[-1] >= s).mean(), raw=False).values
    ct = (df.index + pd.Timedelta(hours=tf_hours)).values.astype("datetime64[ns]").astype(np.int64)
    return ct, pctile


def lookup(ct, pct, t):
    a = np.datetime64(pd.Timestamp(t).to_datetime64(), "ns").astype(np.int64)
    pos = int(np.searchsorted(ct, a, side="right")) - 1
    return pct[pos] if 0 <= pos < len(pct) and np.isfinite(pct[pos]) else np.nan


def main():
    today = pd.Timestamp.utcnow().normalize()
    if today.tz is None:
        today = today.tz_localize("UTC")
    cutoff = today - pd.Timedelta(days=DAYS_BACK)
    # per-trade: win + три режима (12h@signal, 1h168@fill, 1h48@fill) + sym
    data = {"12h": [], "1h168": [], "1h48": []}
    wins = []; syms = []
    persym = {s: {"12h": [], "1h168": [], "1h48": [], "win": []} for s in SYMBOLS}
    for sym in SYMBOLS:
        print(f"[{sym}] detect+sim...", flush=True)
        d1d = load_df(sym, "1d"); d12 = load_df(sym, "12h"); d4 = load_df(sym, "4h")
        d1h = load_df(sym, "1h"); d6 = compose_from_base(d1h, "6h"); d2 = compose_from_base(d1h, "2h")
        d15 = load_df(sym, "15m"); d1m = load_df(sym, "1m"); d20 = compose_from_base(d1m, "20m")
        sigs = dedup(detect_strategy_1_1_1_signals(d1d[d1d.index >= cutoff], d12[d12.index >= cutoff],
                                                   d4, d6, d1h, d2, d15, d20, verbose=False))
        tt = sim_vec(sigs, d1m, RR)
        ct12, p12 = regime_series(d12, 12, 200)
        ct1h_a, p1h_a = regime_series(d1h, 1, 168)
        ct1h_b, p1h_b = regime_series(d1h, 1, 48)
        for (st, ft, d, win) in tt:
            r12 = lookup(ct12, p12, st); ra = lookup(ct1h_a, p1h_a, ft); rb = lookup(ct1h_b, p1h_b, ft)
            if not (np.isfinite(r12) and np.isfinite(ra) and np.isfinite(rb)):
                continue
            data["12h"].append(r12); data["1h168"].append(ra); data["1h48"].append(rb)
            wins.append(1 if win else 0); syms.append(sym)
            persym[sym]["12h"].append(r12); persym[sym]["1h168"].append(ra)
            persym[sym]["1h48"].append(rb); persym[sym]["win"].append(1 if win else 0)
        print(f"  closed+режим={len(wins)} (накопл.)", flush=True)

    win = np.array(wins); n = len(win)
    allptt = (win.sum() * RR - (n - win.sum())) / n
    out = []; A = out.append
    A(f"ТОНКИЙ вола-гейт 1.1.1: 12h(грубо) vs 1h-режим(тонко) @вход. RR={RR}, {n} сделок BTC+ETH+SOL.")
    A(f"Все сделки ptt {allptt:+.3f}. Терцили режима {Q_LO}/{Q_HI}.\n")

    def report(key, label):
        reg = np.array(data[key])
        me = reg >= Q_HI; mq = reg <= Q_LO
        pe = (win[me].sum() * RR - (me.sum() - win[me].sum())) / me.sum() if me.sum() else np.nan
        pq = (win[mq].sum() * RR - (mq.sum() - win[mq].sum())) / mq.sum() if mq.sum() else np.nan
        spread = pe - pq
        cons = 0
        detail = []
        for s in SYMBOLS:
            r = np.array(persym[s][key]); w = np.array(persym[s]["win"])
            if len(r) < 20:
                detail.append(f"{s[:3]}:мало"); continue
            e = r >= Q_HI; q = r <= Q_LO
            ppe = (w[e].sum() * RR - (e.sum() - w[e].sum())) / e.sum() if e.sum() else np.nan
            ppq = (w[q].sum() * RR - (q.sum() - w[q].sum())) / q.sum() if q.sum() else np.nan
            cons += int(np.isfinite(ppe) and np.isfinite(ppq) and ppe > ppq)
            detail.append(f"{s[:3]}:{ppe:+.2f}/{ppq:+.2f}")
        A(f"  {label:18} эксп {pe:+.3f} | тихо {pq:+.3f} | СПРЕД {spread:+.3f} | cross {cons}/3 | "
          f"n(э/т)={int(me.sum())}/{int(mq.sum())}  [{' '.join(detail)}]")
        return spread, cons

    A("=== СЕПАРАЦИЯ exp-vs-quiet (чем больше СПРЕД и cross, тем тоньше инструмент) ===")
    s12, c12 = report("12h", "12h @signal (груб)")
    sa, ca = report("1h168", "1h-нед @fill")
    sb, cb = report("1h48", "1h-2дн @fill")

    A("\n=== ВЕРДИКТ ===")
    best = max([("12h", s12, c12), ("1h-нед", sa, ca), ("1h-2дн", sb, cb)], key=lambda x: x[1])
    A(f"  Лучшая сепарация: {best[0]} (спред {best[1]:+.3f}).")
    if best[0] != "12h" and best[1] > s12 + 0.03 and best[2] >= 2:
        A(f"  -> НИЗКИЙ ТФ ТОНЬШЕ: 1h-режим на входе сортирует 1.1.1 резче 12h (спред {best[1]:+.3f} vs {s12:+.3f}).")
    else:
        A(f"  -> низкий ТФ НЕ резче 12h (спред {best[1]:+.3f} vs 12h {s12:+.3f}); тоньше по таймингу, но не по сортировке.")
    A("  Напоминание: магнитуда на любом ТФ = размер, не направление; standalone на 1h убьют косты.")
    A("  Ценность тонкого режима = ТАЙМИНГ/сайзинг входа каскада, не отдельная сделка.")

    rep = Path(__file__).resolve().parent / "vol_gate_111_lowtf_report.txt"
    rep.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out)); print(f"\n[ok] -> {rep.name}")


if __name__ == "__main__":
    main()
