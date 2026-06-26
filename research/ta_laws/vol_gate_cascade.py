"""ВОЛА-ГЕЙТ для каскадов 1.1.x — улучшает ли режим волатильности нетто-R живых стратегий?

Гипотеза (после находки магнитуды): магнитуда (размер хода) предсказуема = вола-кластеризация. Для RR>1
каскадов экспансия может помогать (есть кому добежать до TP), тишина — вредить (чоп, не доходит). Проверяем
ЧЕСТНО на РЕАЛЬНЫХ сделках live-скелета (scan_strict из live_skeleton_top3): каждой сделке проставляем
вола-режим на момент arm (atr-перцентиль ПОСЛЕДНЕЙ ЗАКРЫТОЙ 12h-свечи = каузально) и сравниваем R по режимам.

Стены: фикс-терцили (без тюнинга порога), pooled + cross-asset консистентность, раскол по символам/годам,
честный вывод «гейт помогает / нейтрален / вредит». RR=2.0 (как в скелете).

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/ta_laws/vol_gate_cascade.py
Выход: research/ta_laws/vol_gate_cascade_report.txt
"""
from __future__ import annotations
import sys
from pathlib import Path
from collections import defaultdict
import numpy as np
import pandas as pd
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "research" / "cascade_grid"))
import geometry as G  # noqa: E402
from live_skeleton_top3 import load_1m, rs, scan_strict, MAX_HOLD_MIN  # noqa: E402

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
RR = 2.0
CONFIGS = [("1.1.2", "OB", "OB", "OB"),
           ("1.1.1", "OB", "FVG", "OB"),
           ("cand2-FVGtop", "FVG", "OB", "OB")]
Q_LO, Q_HI = 0.40, 0.60     # фикс-границы режима (atr-перцентиль)


def sim_trades(signals, df_1m, rr):
    """Возвращает закрытые сделки: список (arm, dir, win)."""
    lo = df_1m["low"].to_numpy(); hi = df_1m["high"].to_numpy(); idx = df_1m.index
    out = []
    for (d, entry, slv, risk, arm) in signals:
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
        out.append((arm, d, tf_ < sf))
    return out


def regime_lookup(df_12h):
    """atr-перцентиль (rolling 200) по 12h; возвращает (close_times_ns, pctile[])."""
    atr = G.compute_atr(df_12h)
    atr_pct = atr / df_12h["close"].values * 100
    pctile = pd.Series(atr_pct).rolling(200, min_periods=30).apply(
        lambda s: (s.iloc[-1] >= s).mean(), raw=False).values
    ct = (df_12h.index + pd.Timedelta(hours=12)).values.astype("datetime64[ns]").astype(np.int64)
    return ct, pctile


def main():
    rep = []
    A = rep.append
    A("ВОЛА-ГЕЙТ для каскадов 1.1.x — нетто-R по режиму волатильности (RR=%.1f, фикс-терцили %.2f/%.2f)" % (RR, Q_LO, Q_HI))
    A("Реальные сделки live-скелета; режим = atr-перцентиль последней закрытой 12h-свечи на arm (каузально).\n")

    PC = {}
    for sym in SYMBOLS:
        print(f"load {sym}...", flush=True)
        d1 = load_1m(sym)
        tfs = {tl: rs(d1, fr) for tl, fr in
               [("1d", "1d"), ("12h", "12h"), ("4h", "4h"), ("6h", "6h"),
                ("1h", "1h"), ("2h", "2h"), ("15m", "15min"), ("20m", "20min")]}
        ct, pct = regime_lookup(tfs["12h"])
        PC[sym] = {"df_1m": d1, "tfs": tfs, "ct": ct, "pct": pct}

    def regime_of(sym, arm):
        ct, pct = PC[sym]["ct"], PC[sym]["pct"]
        a = np.datetime64(pd.Timestamp(arm).to_datetime64(), "ns").astype(np.int64)
        pos = int(np.searchsorted(ct, a, side="right")) - 1
        return pct[pos] if 0 <= pos < len(pct) and np.isfinite(pct[pos]) else np.nan

    for name, tk, mk, hk in CONFIGS:
        print(f"scan {name}...", flush=True)
        trades = []
        per_sym = {}
        for sym in SYMBOLS:
            sigs = scan_strict(PC[sym]["tfs"], tk, mk, hk)
            tt = sim_trades(sigs, PC[sym]["df_1m"], RR)
            rows = [(regime_of(sym, arm), 1 if win else 0) for (arm, d, win) in tt]
            rows = [(r, w) for (r, w) in rows if np.isfinite(r)]
            per_sym[sym] = rows
            trades += rows
        if not trades:
            A(f"=== {name}: нет сделок ==="); continue
        reg = np.array([r for r, _ in trades]); win = np.array([w for _, w in trades])

        def bucket(mask, lbl):
            n = int(mask.sum())
            if n == 0:
                return f"  {lbl:24} n=   0"
            w = int(win[mask].sum()); l = n - w
            sumR = w * RR - l; wr = w / n * 100; ptt = sumR / n
            return f"  {lbl:24} n={n:4d}  WR={wr:5.1f}%  ptt={ptt:+.3f}  sumR={sumR:+6.1f}"

        A(f"=== {name} ({tk}/{mk}/{hk}) — pooled BTC+ETH+SOL, {len(trades)} закрытых ===")
        A(bucket(np.ones(len(reg), bool), "ВСЕ (без гейта)"))
        A(bucket(reg <= Q_LO, f"ТИХО (pctile<={Q_LO})"))
        A(bucket((reg > Q_LO) & (reg < Q_HI), "средняя"))
        A(bucket(reg >= Q_HI, f"ЭКСПАНСИЯ (pctile>={Q_HI})"))
        # эффект гейта «пропустить тихо»
        keep = reg > Q_LO
        nk = int(keep.sum()); wk = int(win[keep].sum()); lk = nk - wk
        allR = int(win.sum()) * RR - (len(win) - int(win.sum()))
        gateR = wk * RR - lk
        A(f"  -> ГЕЙТ 'пропустить тихо': сделок {len(trades)}->{nk}, sumR {allR:+.1f}->{gateR:+.1f}, "
          f"ptt {allR/len(trades):+.3f}->{(gateR/nk if nk else 0):+.3f}")
        # cross-asset консистентность (ptt экспансия vs тихо по символам)
        A("  cross-asset (ptt экспансия / тихо):")
        consist = 0
        for sym in SYMBOLS:
            rr_ = np.array([r for r, _ in per_sym[sym]]); ww = np.array([w for _, w in per_sym[sym]])
            if len(rr_) < 20:
                A(f"    {sym}: мало ({len(rr_)})"); continue
            me = rr_ >= Q_HI; mq = rr_ <= Q_LO
            pe = (ww[me].sum() * RR - (me.sum() - ww[me].sum())) / me.sum() if me.sum() else np.nan
            pq = (ww[mq].sum() * RR - (mq.sum() - ww[mq].sum())) / mq.sum() if mq.sum() else np.nan
            consist += int(np.isfinite(pe) and np.isfinite(pq) and pe > pq)
            A(f"    {sym}: эксп {pe:+.3f} / тихо {pq:+.3f}  (n_эксп={int(me.sum())}, n_тихо={int(mq.sum())})")
        # вердикт по конфигу
        pe_all = (win[reg >= Q_HI].sum() * RR - ((reg >= Q_HI).sum() - win[reg >= Q_HI].sum())) / max(1, (reg >= Q_HI).sum())
        pq_all = (win[reg <= Q_LO].sum() * RR - ((reg <= Q_LO).sum() - win[reg <= Q_LO].sum())) / max(1, (reg <= Q_LO).sum())
        helps = (pe_all > allR / len(trades) + 0.05) and (consist >= 2)
        A(f"  ВЕРДИКТ {name}: эксп-ptt {pe_all:+.3f} vs все {allR/len(trades):+.3f} vs тихо {pq_all:+.3f}; "
          f"cross-asset {consist}/3 -> {'ГЕЙТ ПОМОГАЕТ' if helps else 'нейтрально/непоследовательно'}\n")

    out = HERE / "vol_gate_cascade_report.txt"
    out.write_text("\n".join(rep), encoding="utf-8")
    print("\n".join(rep))
    print(f"\n[ok] -> {out.name}")


if __name__ == "__main__":
    main()
