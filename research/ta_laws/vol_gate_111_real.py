"""ВАЛИДАЦИЯ вола-гейта на НАСТОЯЩЕМ 1.1.1 (реальный детектор + entry/sl/risk, RR=2.2, dedup).

Скелет-тест дал: вола-гейт улучшает 1.1.1 (эксп-ptt > тихо, cross-asset 3/3). Здесь проверяем на канон-детекторе
detect_strategy_1_1_1_signals (реальные entry=0.80/sl=0.35sym/risk из стратегии), RR=2.2, dedup как в бэктесте,
BTC+ETH+SOL, полный горизонт. Сим векторизован (limit-fill + SL/TP по 1m), вход = c2.close+tf (как в каноне).

Режим = atr-перцентиль (rolling 200) ПОСЛЕДНЕЙ ЗАКРЫТОЙ 12h-свечи на signal_time (каузально), фикс-терцили 0.40/0.60.
Решение по per-trade expectancy (ptt) + cross-asset.

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/ta_laws/vol_gate_111_real.py
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


def sim_vec(sigs, df_1m, rr):
    """Векторный сим: limit-fill от c2.close+tf, затем SL/TP по 1m. -> список (signal_time, dir, win)."""
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
        out.append((s["signal_time"], d, tf_ < sf))
    return out


def dedup(sigs):
    seen, out = set(), []
    for s in sorted(sigs, key=lambda x: x["signal_time"]):
        k = (s["signal_time"], s["direction"], round(float(s["entry"]), 6))
        if k in seen:
            continue
        seen.add(k); out.append(s)
    return out


def regime_lookup(df_12h):
    atr = G.compute_atr(df_12h[["high", "low", "close"]])
    atr_pct = atr / df_12h["close"].values * 100
    pctile = pd.Series(atr_pct).rolling(200, min_periods=30).apply(lambda s: (s.iloc[-1] >= s).mean(), raw=False).values
    ct = (df_12h.index + pd.Timedelta(hours=12)).values.astype("datetime64[ns]").astype(np.int64)
    return ct, pctile


def main():
    today = pd.Timestamp.utcnow().normalize()
    if today.tz is None:
        today = today.tz_localize("UTC")
    cutoff = today - pd.Timedelta(days=DAYS_BACK)
    rows = []
    per_sym = {}
    for sym in SYMBOLS:
        print(f"[{sym}] load+detect...", flush=True)
        d1d = load_df(sym, "1d"); d12 = load_df(sym, "12h"); d4 = load_df(sym, "4h")
        d1h = load_df(sym, "1h"); d6 = compose_from_base(d1h, "6h"); d2 = compose_from_base(d1h, "2h")
        d15 = load_df(sym, "15m"); d1m = load_df(sym, "1m"); d20 = compose_from_base(d1m, "20m")
        sigs = detect_strategy_1_1_1_signals(d1d[d1d.index >= cutoff], d12[d12.index >= cutoff],
                                             d4, d6, d1h, d2, d15, d20, verbose=False)
        sigs = dedup(sigs)
        tt = sim_vec(sigs, d1m, RR)
        ct, pct = regime_lookup(d12)
        rr_rows = []
        for (st, d, win) in tt:
            a = np.datetime64(pd.Timestamp(st).to_datetime64(), "ns").astype(np.int64)
            pos = int(np.searchsorted(ct, a, side="right")) - 1
            reg = pct[pos] if 0 <= pos < len(pct) and np.isfinite(pct[pos]) else np.nan
            if np.isfinite(reg):
                rr_rows.append((reg, 1 if win else 0, pd.Timestamp(st).year))
        per_sym[sym] = rr_rows; rows += [(sym, *r) for r in rr_rows]
        print(f"  signals={len(sigs)} closed={len(tt)} c режимом={len(rr_rows)}", flush=True)

    reg = np.array([r[1] for r in rows]); win = np.array([r[2] for r in rows]); yr = np.array([r[3] for r in rows])
    out = []; A = out.append
    A(f"ВАЛИДАЦИЯ ВОЛА-ГЕЙТА на НАСТОЯЩЕМ 1.1.1 (канон-детектор, entry0.80/sl0.35, RR={RR}, dedup; BTC+ETH+SOL)")
    A(f"Закрытых сделок с режимом: {len(rows)}. Геом-нуль не применим — критерий ptt по режиму + cross-asset.\n")

    def bucket(mask, lbl):
        n = int(mask.sum())
        if n == 0:
            return f"  {lbl:26} n=   0"
        w = int(win[mask].sum()); l = n - w
        return f"  {lbl:26} n={n:4d}  WR={w/n*100:5.1f}%  ptt={(w*RR-l)/n:+.3f}  sumR={w*RR-l:+6.1f}"

    allptt = (win.sum() * RR - (len(win) - win.sum())) / len(win)
    A("=== 1.1.1 по вола-режиму (pooled BTC+ETH+SOL) ===")
    A(bucket(np.ones(len(reg), bool), "ВСЕ (без гейта)"))
    A(bucket(reg <= Q_LO, f"ТИХО (pctile<={Q_LO})"))
    A(bucket((reg > Q_LO) & (reg < Q_HI), "средняя"))
    A(bucket(reg >= Q_HI, f"ЭКСПАНСИЯ (pctile>={Q_HI})"))
    keep = reg > Q_LO
    nk = int(keep.sum()); gateR = int(win[keep].sum()) * RR - (nk - int(win[keep].sum()))
    A(f"  -> ГЕЙТ 'пропустить тихо': {len(rows)}->{nk} сделок, sumR {win.sum()*RR-(len(win)-win.sum()):+.1f}->{gateR:+.1f}, "
      f"ptt {allptt:+.3f}->{gateR/nk if nk else 0:+.3f}")

    A("\n=== cross-asset (ptt экспансия / тихо) ===")
    consist = 0
    for sym in SYMBOLS:
        rs = np.array([r[0] for r in per_sym[sym]]); ws = np.array([r[1] for r in per_sym[sym]])
        if len(rs) < 20:
            A(f"  {sym}: мало ({len(rs)})"); continue
        me = rs >= Q_HI; mq = rs <= Q_LO
        pe = (ws[me].sum() * RR - (me.sum() - ws[me].sum())) / me.sum() if me.sum() else np.nan
        pq = (ws[mq].sum() * RR - (mq.sum() - ws[mq].sum())) / mq.sum() if mq.sum() else np.nan
        consist += int(np.isfinite(pe) and np.isfinite(pq) and pe > pq)
        A(f"  {sym}: эксп {pe:+.3f} / тихо {pq:+.3f}  (n_эксп={int(me.sum())}, n_тихо={int(mq.sum())})")

    A("\n=== эксп-ptt по годам (стабильность) ===")
    gy = 0; ty = 0
    for Y in sorted(set(yr[reg >= Q_HI])):
        mm = (reg >= Q_HI) & (yr == Y)
        if mm.sum() > 10:
            p = (win[mm].sum() * RR - (mm.sum() - win[mm].sum())) / mm.sum(); ty += 1; gy += p > 0
            A(f"  {Y}: эксп-ptt {p:+.3f} (n={int(mm.sum())})")

    pe_all = (win[reg >= Q_HI].sum() * RR - ((reg >= Q_HI).sum() - win[reg >= Q_HI].sum())) / max(1, (reg >= Q_HI).sum())
    pq_all = (win[reg <= Q_LO].sum() * RR - ((reg <= Q_LO).sum() - win[reg <= Q_LO].sum())) / max(1, (reg <= Q_LO).sum())
    helps = (pe_all > allptt + 0.05) and (consist >= 2)
    A("\n=== ВЕРДИКТ ===")
    A(f"  эксп-ptt {pe_all:+.3f} vs все {allptt:+.3f} vs тихо {pq_all:+.3f}; cross-asset {consist}/3; эксп-годы+ {gy}/{ty}")
    A(f"  -> {'ВОЛА-ГЕЙТ ПОДТВЕРЖДЁН на реальном 1.1.1 (эксп >> тихо, cross-asset держится)' if helps else 'на реальном 1.1.1 НЕ подтверждается так чисто, как на скелете'}")

    rep = Path(__file__).resolve().parent / "vol_gate_111_real_report.txt"
    rep.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out)); print(f"\n[ok] -> {rep.name}")


if __name__ == "__main__":
    main()
