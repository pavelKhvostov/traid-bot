"""Полный грид каскадов — ночной перебор пространства 1.1.x-скелета с анти-оверфит гейтами.

Скелет: L1 top(1d,12h) -> L2 macro(4h,6h) -> L3 htf(1h,2h)[+swept] -> L4 entry(15m/20m или same-tf FVG).
Оси грида:
  top_kind   in {OB, FVG}
  macro_kind in {OB, FVG, iFVG, RDRB}
  htf_kind   in {OB, RDRB}
  entry_mode in {deep (15m+20m), sametf (FVG на htf-TF)}
  swept      in {False, True}     (htf-зона сняла ликвидность за prior-K экстремум)
= 2*4*2*2*2 = 64 структурных конфига.

Унифицированная геометрия (как семейство 1.1.x, чтобы конфиги были сравнимы):
  entry = mid(L4 entry-FVG); SL = внутрь top-зоны на OB_SL_DEPTH; risk=|entry-SL|; TP = entry +/- RR*risk.
RR ФИКСИРОВАН = 2.0 для гейтинга (без RR-cherry-pick; 1.5/2.5 — справочно).

Гейты (победитель обязан пройти ВСЕ — мульти-тестинг отсекается совместностью):
  1. min_n: >= 60 закрытых на BTC и >= 40 на ETH/SOL
  2. cross-asset: ΣR>0 на >= 2 из 3 символов
  3. two-sided: на BTC LONG ΣR>0 И SHORT ΣR>0 (убивает bull-drift)
  4. year-stability: на BTC >= 5/N плюсовых лет
  5. OOS-split: на BTC ΣR>0 в ОБЕИХ половинах (2020-2023 / 2024-2026)
Финалистам (прошли 1-5) считается permutation-null (random-time entry, 500 сэмплов) -> p.

Запуск sanity:  set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/cascade_grid/grid.py sanity
Запуск полный:  ... research/cascade_grid/grid.py
Выход: research/cascade_grid/grid_results.csv (инкрементально) + grid_report.txt (финал).
"""
from __future__ import annotations

import sys
import time
import traceback
from itertools import product
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
sys.path.insert(0, str(ROOT / "research" / "elements_study"))

from strategies.strategy_1_1_1 import OB_SL_DEPTH, detect_ob_pair, detect_fvg  # noqa: E402
from strategies.strategy_rdrb import detect_rdrb  # noqa: E402
import etap_93_inverse_fvg as e93  # noqa: E402

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
RR_GATE = 2.0
RR_REPORT = [1.5, 2.5]
MAX_HOLD_MIN = 30 * 24 * 60
SWEPT_K = 8
PER_TOP_CAP = 3
HTF_MAX_DAYS = {24: 12, 12: 7}
NULL_SAMPLES = 300
NULL_HORIZON = 14 * 24 * 60
RNG = np.random.default_rng(7)

TOP_TFS = [("1d", "1d", 24), ("12h", "12h", 12)]
MACRO_TFS = [("4h", "4h", 4), ("6h", "6h", 6)]
HTF_TFS = [("1h", "1h", 60), ("2h", "2h", 120)]
ENTRY_TFS = [("15m", "15min", 15), ("20m", "20min", 20)]


# ----------------------------------------------------------------------------- data
def load_1m(sym):
    df = pd.read_csv(ROOT / "data" / f"{sym}_1m.csv",
                     parse_dates=["open_time"], index_col="open_time")
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.sort_index()


def rs(df_1m, freq):
    out = df_1m.resample(freq, origin="epoch", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna(subset=["close"])
    return out


def u(ts):
    return int(pd.Timestamp(ts).timestamp())


def overlap(b1, t1, b2, t2):
    return not (t1 < b2 or t2 < b1)


# ----------------------------------------------------------------------------- zones
# zone tuple: (dir, b, t, prev_u, cur_u)   htf adds swept -> (dir,b,t,prev_u,cur_u,swept)
def zones_ob(df):
    out = []
    idx = df.index
    for i in range(1, len(df)):
        z = detect_ob_pair(df, i)
        if z is not None:
            out.append((z.direction, z.bottom, z.top, u(idx[i - 1]), u(idx[i])))
    return out


def zones_fvg(df):
    out = []
    for i in range(2, len(df)):
        z = detect_fvg(df, i)
        if z is not None:
            out.append((z.direction, z.bottom, z.top, u(z.c0_time), u(z.c2_time)))
    return out


def zones_rdrb(df):
    out = []
    idx = df.index
    for i in range(2, len(df)):
        z = detect_rdrb(df, i, "V1")
        if z is not None:
            out.append((z.direction, z.bottom, z.top, u(idx[i - 2]), u(idx[i])))
    return out


def zones_ifvg(df):
    out = []
    res = e93.find_inverse_fvgs(df.reset_index().rename(columns={"open_time": "time"}).set_index("time"))
    for A, B, _touch in res:
        out.append((B.direction, B.bottom, B.top, u(B.c0_time), u(B.c2_time)))
    return out


def zones_htf_swept(df, kind):
    """htf зоны (OB|RDRB) + флаг swept: формация сняла ликвидность за prior-K экстремум."""
    lows = df["low"].values
    highs = df["high"].values
    idx = df.index
    out = []
    if kind == "OB":
        rng = range(1, len(df))
        det = lambda i: detect_ob_pair(df, i)
        form_lo = lambda i: min(lows[i - 1], lows[i])
        form_hi = lambda i: max(highs[i - 1], highs[i])
        back0 = lambda i: i - 1
    else:  # RDRB
        rng = range(2, len(df))
        det = lambda i: detect_rdrb(df, i, "V1")
        form_lo = lambda i: min(lows[i - 2], lows[i - 1], lows[i])
        form_hi = lambda i: max(highs[i - 2], highs[i - 1], highs[i])
        back0 = lambda i: i - 2
    for i in rng:
        z = det(i)
        if z is None:
            continue
        b0 = back0(i)
        lo_w = b0 - SWEPT_K
        if lo_w < 0:
            swept = False
        elif z.direction == "LONG":
            swept = form_lo(i) < float(lows[lo_w:b0].min()) if b0 > lo_w else False
        else:
            swept = form_hi(i) > float(highs[lo_w:b0].max()) if b0 > lo_w else False
        prev_u = u(idx[i - 1]) if kind == "OB" else u(idx[i - 2])
        out.append((z.direction, z.bottom, z.top, prev_u, u(idx[i]), bool(swept)))
    return out


def collect_zones(df, kind):
    return {"OB": zones_ob, "FVG": zones_fvg, "RDRB": zones_rdrb, "iFVG": zones_ifvg}[kind](df)


# ----------------------------------------------------------------------------- precompute
def build_precomp(sym):
    df_1m = load_1m(sym)
    tf = {}
    for label, freq, _ in TOP_TFS + MACRO_TFS + HTF_TFS + ENTRY_TFS:
        tf[label] = rs(df_1m, freq)
    pc = {"df_1m": df_1m,
          "idx1_u": (df_1m.index.view("int64") // 1_000_000_000).astype(np.int64),
          "lo1": df_1m["low"].to_numpy(), "hi1": df_1m["high"].to_numpy(),
          "cl1": df_1m["close"].to_numpy()}
    # top zones OB/FVG on 1d,12h
    for tl, _, _ in TOP_TFS:
        for k in ("OB", "FVG"):
            pc[("top", tl, k)] = collect_zones(tf[tl], k)
    # macro zones all kinds on 4h,6h
    for tl, _, _ in MACRO_TFS:
        for k in ("OB", "FVG", "iFVG", "RDRB"):
            pc[("macro", tl, k)] = collect_zones(tf[tl], k)
    # htf zones OB/RDRB on 1h,2h (with swept)
    for tl, _, _ in HTF_TFS:
        for k in ("OB", "RDRB"):
            pc[("htf", tl, k)] = zones_htf_swept(tf[tl], k)
    # entry FVG on 15m,20m AND on htf-TFs (same-tf entry)
    for tl, freq, _ in ENTRY_TFS:
        pc[("entry", tl)] = zones_fvg(tf[tl])
    for tl, _, _ in HTF_TFS:
        pc[("entrysame", tl)] = zones_fvg(tf[tl])
    pc["tf_index_u"] = {tl: (tf[tl].index.view("int64") // 1_000_000_000).astype(np.int64)
                        for tl, _, _ in TOP_TFS + MACRO_TFS + HTF_TFS + ENTRY_TFS}
    return pc


# ----------------------------------------------------------------------------- cascade
def scan_cascade(pc, cfg):
    top_kind, macro_kind, htf_kind, entry_mode, swept = cfg
    signals = []
    for top_l, _, top_h in TOP_TFS:
        tops = pc[("top", top_l, top_kind)]
        htf_window_s = HTF_MAX_DAYS[top_h] * 86400
        for (td, tb, tt, tprev, tcur) in tops:
            win_start, win_end = tprev, tcur + top_h * 3600
            for macro_l, _, macro_h in MACRO_TFS:
                macros = pc[("macro", macro_l, macro_kind)]
                got = 0
                for (md, mb, mt, mprev, mcur) in macros:
                    if md != td or not (win_start <= mcur < win_end):
                        continue
                    if not overlap(mb, mt, tb, tt):
                        continue
                    zb, zt = max(tb, mb), min(tt, mt)
                    hsearch = tcur + top_h * 3600
                    for htf_l, _, htf_min in HTF_TFS:
                        htfs = pc[("htf", htf_l, htf_kind)]
                        for hz in htfs:
                            hd, hb, ht, hprev, hcur, hsw = hz
                            if hd != td or hcur < hsearch or hcur > hsearch + htf_window_s:
                                continue
                            if swept and not hsw:
                                continue
                            if not (overlap(hb, ht, zb, zt) and overlap(hb, ht, mb, mt)):
                                continue
                            # entry
                            if entry_mode == "deep":
                                e_lists = [(pc[("entry", el)], etf) for el, _, etf in ENTRY_TFS]
                            else:
                                e_lists = [(pc[("entrysame", htf_l)], htf_min)]
                            best_e = None
                            for elist, etf in e_lists:
                                for (ed, eb, et, eprev, ecur) in elist:
                                    if ed != td:
                                        continue
                                    if ecur < hprev or ecur > hcur + (htf_min - etf) * 60:
                                        continue
                                    if not overlap(eb, et, hb, ht):
                                        continue
                                    arm = ecur + etf * 60
                                    if best_e is None or arm < best_e[0]:
                                        best_e = (arm, eb, et)
                                    break  # earliest per list
                            if best_e is None:
                                continue
                            arm, eb, et = best_e
                            entry = (eb + et) / 2.0
                            depth = tt - tb
                            sl = tb + depth * OB_SL_DEPTH if td == "LONG" else tt - depth * OB_SL_DEPTH
                            risk = abs(entry - sl)
                            if risk <= 0 or (td == "LONG" and sl >= entry) or (td == "SHORT" and sl <= entry):
                                continue
                            signals.append((td, float(entry), float(sl), float(risk), int(arm)))
                            got += 1
                            break  # first htf
                        if got >= PER_TOP_CAP:
                            break
                    if got >= PER_TOP_CAP:
                        break
    # dedup by (arm, dir, entry)
    seen, out = set(), []
    for s in sorted(signals, key=lambda x: x[4]):
        k = (s[4], s[0], round(s[1], 1))
        if k in seen:
            continue
        seen.add(k); out.append(s)
    return out


# ----------------------------------------------------------------------------- sim
def sim(signals, pc, rr):
    idx1_u, lo1, hi1 = pc["idx1_u"], pc["lo1"], pc["hi1"]
    ow = ol = nf = op = 0
    yr = {}
    side = {"LONG": [0, 0], "SHORT": [0, 0]}  # [w,l]
    halves = [[0, 0], [0, 0]]  # [<2024][>=2024] -> [w,l]
    for (d, entry, slv, risk, arm) in signals:
        sp = int(np.searchsorted(idx1_u, arm, side="left"))
        if sp >= len(lo1):
            continue
        end = min(sp + MAX_HOLD_MIN, len(lo1))
        if d == "LONG":
            fh = np.where(lo1[sp:end] <= entry)[0]
        else:
            fh = np.where(hi1[sp:end] >= entry)[0]
        if not fh.size:
            nf += 1; continue
        f = sp + int(fh[0])
        plo, phi = lo1[f:end], hi1[f:end]
        tp = entry + rr * risk if d == "LONG" else entry - rr * risk
        if d == "LONG":
            slm, tpm = plo <= slv, phi >= tp
        else:
            slm, tpm = phi >= slv, plo <= tp
        sf = int(np.argmax(slm)) if slm.any() else 10**9
        tf_ = int(np.argmax(tpm)) if tpm.any() else 10**9
        if sf == 10**9 and tf_ == 10**9:
            op += 1; continue
        win = tf_ < sf
        y = pd.Timestamp(arm, unit="s", tz="UTC").year
        if y not in yr:
            yr[y] = [0, 0]
        half = 0 if y < 2024 else 1
        if win:
            ow += 1; yr[y][0] += 1; side[d][0] += 1; halves[half][0] += 1
        else:
            ol += 1; yr[y][1] += 1; side[d][1] += 1; halves[half][1] += 1
    closed = ow + ol
    sumR = ow * rr - ol
    year_R = {y: w * rr - l for y, (w, l) in yr.items()}
    return {"n": len(signals), "closed": closed, "w": ow, "l": ol, "nf": nf, "open": op,
            "wr": ow / closed * 100 if closed else 0.0, "sumR": sumR,
            "L_R": side["LONG"][0] * rr - side["LONG"][1],
            "S_R": side["SHORT"][0] * rr - side["SHORT"][1],
            "year_R": year_R,
            "h1_R": halves[0][0] * rr - halves[0][1],
            "h2_R": halves[1][0] * rr - halves[1][1]}


def perm_null(signals, pc, rr, n_samples=NULL_SAMPLES):
    """random-time entry null: те же N ставок (dir, risk%) на случайных барах -> p(ΣR/сд>=real)."""
    if not signals:
        return 1.0
    cl1, lo1, hi1 = pc["cl1"], pc["lo1"], pc["hi1"]
    N1 = len(cl1)
    real = sim(signals, pc, rr)
    if real["closed"] == 0:
        return 1.0
    real_rpt = real["sumR"] / real["closed"]
    # risk% per signal (relative to entry)
    specs = [(d, risk / entry) for (d, entry, slv, risk, arm) in signals]
    horizon = NULL_HORIZON
    null = np.empty(n_samples)
    for s in range(n_samples):
        w = l = 0
        starts = RNG.integers(0, N1 - horizon - 5, size=len(specs))
        for (d, rpct), st in zip(specs, starts):
            entry = cl1[st]
            risk = entry * rpct
            sl = entry - risk if d == "LONG" else entry + risk
            tp = entry + rr * risk if d == "LONG" else entry - rr * risk
            end = st + horizon
            plo, phi = lo1[st:end], hi1[st:end]
            if d == "LONG":
                slm, tpm = plo <= sl, phi >= tp
            else:
                slm, tpm = phi >= sl, plo <= tp
            sf = int(np.argmax(slm)) if slm.any() else 10**9
            tf_ = int(np.argmax(tpm)) if tpm.any() else 10**9
            if sf == 10**9 and tf_ == 10**9:
                continue
            if tf_ < sf:
                w += 1
            else:
                l += 1
        c = w + l
        null[s] = (w * rr - l) / c if c else -999
    return float((null >= real_rpt).mean())


# ----------------------------------------------------------------------------- gates
def gates(per_sym):
    btc = per_sym["BTCUSDT"]
    n_ok = (btc["closed"] >= 60
            and per_sym["ETHUSDT"]["closed"] >= 40
            and per_sym["SOLUSDT"]["closed"] >= 40)
    cross = sum(1 for s in SYMBOLS if per_sym[s]["sumR"] > 0) >= 2
    two_sided = btc["L_R"] > 0 and btc["S_R"] > 0
    yrs = btc["year_R"]
    pos_yrs = sum(1 for v in yrs.values() if v > 0)
    year_ok = pos_yrs >= 5 and len(yrs) >= 5
    oos = btc["h1_R"] > 0 and btc["h2_R"] > 0
    passed = n_ok and cross and two_sided and year_ok and oos
    return {"n_ok": n_ok, "cross": cross, "two_sided": two_sided,
            "year_ok": year_ok, "pos_yrs": pos_yrs, "n_yrs": len(yrs),
            "oos": oos, "PASS": passed}


# ----------------------------------------------------------------------------- run
CSV_COLS = ["cfg", "top", "macro", "htf", "entry", "swept",
            "btc_n", "btc_closed", "btc_wr", "btc_R", "btc_LR", "btc_SR",
            "btc_posyrs", "btc_nyrs", "btc_h1", "btc_h2",
            "eth_closed", "eth_R", "sol_closed", "sol_R",
            "cross", "two_sided", "year_ok", "oos", "PASS", "null_p",
            "btc_R_rr15", "btc_R_rr25"]


def cfg_name(cfg):
    top, macro, htf, entry, swept = cfg
    return f"top{top}-mac{macro}-htf{htf}-{entry}{'-SW' if swept else ''}"


def main():
    sanity = len(sys.argv) > 1 and sys.argv[1] == "sanity"
    t0 = time.time()
    print(f"[grid] start; sanity={sanity}", flush=True)

    print("[grid] precomputing zones per symbol (this is the slow part)...", flush=True)
    PC = {}
    for sym in SYMBOLS:
        ts = time.time()
        PC[sym] = build_precomp(sym)
        print(f"   {sym}: 1m={len(PC[sym]['lo1']):,}  "
              f"tops1d={len(PC[sym][('top','1d','OB')])}OB  "
              f"macro4h_iFVG={len(PC[sym][('macro','4h','iFVG')])}  "
              f"htf1h_RDRB={len(PC[sym][('htf','1h','RDRB')])}  ({time.time()-ts:.0f}s)", flush=True)

    if sanity:
        cfg = ("OB", "FVG", "OB", "deep", False)
        sigs = scan_cascade(PC["BTCUSDT"], cfg)
        m = sim(sigs, PC["BTCUSDT"], RR_GATE)
        print(f"\n[SANITY] {cfg_name(cfg)} BTC @RR2.0:")
        print(f"  signals={m['n']} closed={m['closed']} WR={m['wr']:.1f}% sumR={m['sumR']:+.1f} "
              f"L_R={m['L_R']:+.1f} S_R={m['S_R']:+.1f}")
        print(f"  year_R={ {k: round(v,1) for k,v in sorted(m['year_R'].items())} }")
        print(f"  half1(<2024)={m['h1_R']:+.1f} half2(>=2024)={m['h2_R']:+.1f}")
        print(f"  (ожидание: десятки положительных R, ~как C OB-htf baseline)")
        # second sanity: macro-RDRB (новая ячейка)
        cfg2 = ("OB", "RDRB", "OB", "deep", False)
        m2 = sim(scan_cascade(PC["BTCUSDT"], cfg2), PC["BTCUSDT"], RR_GATE)
        print(f"\n[SANITY] {cfg_name(cfg2)} BTC: closed={m2['closed']} sumR={m2['sumR']:+.1f}")
        print(f"[grid] sanity done in {time.time()-t0:.0f}s", flush=True)
        return

    configs = list(product(["OB", "FVG"], ["OB", "FVG", "iFVG", "RDRB"],
                           ["OB", "RDRB"], ["deep", "sametf"], [False, True]))
    print(f"\n[grid] {len(configs)} структурных конфигов x {len(SYMBOLS)} символов\n", flush=True)

    csv_path = HERE / "grid_results.csv"
    with csv_path.open("w", encoding="utf-8") as fcsv:
        fcsv.write(",".join(CSV_COLS) + "\n")
        rows = []
        for ci, cfg in enumerate(configs, 1):
            try:
                per_sym, per_rep = {}, {}
                for sym in SYMBOLS:
                    sigs = scan_cascade(PC[sym], cfg)
                    per_sym[sym] = sim(sigs, PC[sym], RR_GATE)
                    if sym == "BTCUSDT":
                        per_sym[sym]["_sigs"] = sigs
                        per_rep["rr15"] = sim(sigs, PC[sym], 1.5)["sumR"]
                        per_rep["rr25"] = sim(sigs, PC[sym], 2.5)["sumR"]
                g = gates(per_sym)
                null_p = ""
                if g["PASS"]:
                    null_p = f"{perm_null(per_sym['BTCUSDT']['_sigs'], PC['BTCUSDT'], RR_GATE):.3f}"
                b = per_sym["BTCUSDT"]
                row = [cfg_name(cfg), cfg[0], cfg[1], cfg[2], cfg[3], int(cfg[4]),
                       b["n"], b["closed"], round(b["wr"], 1), round(b["sumR"], 1),
                       round(b["L_R"], 1), round(b["S_R"], 1), g["pos_yrs"], g["n_yrs"],
                       round(b["h1_R"], 1), round(b["h2_R"], 1),
                       per_sym["ETHUSDT"]["closed"], round(per_sym["ETHUSDT"]["sumR"], 1),
                       per_sym["SOLUSDT"]["closed"], round(per_sym["SOLUSDT"]["sumR"], 1),
                       int(g["cross"]), int(g["two_sided"]), int(g["year_ok"]), int(g["oos"]),
                       int(g["PASS"]), null_p, round(per_rep["rr15"], 1), round(per_rep["rr25"], 1)]
                fcsv.write(",".join(str(x) for x in row) + "\n"); fcsv.flush()
                rows.append(row)
                flag = "  <<< PASS" + (f" null_p={null_p}" if null_p else "") if g["PASS"] else ""
                print(f"[{ci:2}/{len(configs)}] {cfg_name(cfg):28} BTC closed={b['closed']:4} "
                      f"R={b['sumR']:+7.1f} L/S={b['L_R']:+.0f}/{b['S_R']:+.0f} "
                      f"yrs={g['pos_yrs']}/{g['n_yrs']} oos={int(g['oos'])} "
                      f"ETH={per_sym['ETHUSDT']['sumR']:+.0f} SOL={per_sym['SOLUSDT']['sumR']:+.0f}{flag}",
                      flush=True)
            except Exception as ex:
                print(f"[{ci:2}/{len(configs)}] {cfg_name(cfg)} ERROR: {ex}", flush=True)
                traceback.print_exc()

    # финальный отчёт
    rep = HERE / "grid_report.txt"
    passers = [r for r in rows if r[CSV_COLS.index("PASS")] == 1]
    passers.sort(key=lambda r: r[CSV_COLS.index("btc_R")], reverse=True)
    allrows = sorted(rows, key=lambda r: r[CSV_COLS.index("btc_R")], reverse=True)
    with rep.open("w", encoding="utf-8") as f:
        f.write(f"CASCADE GRID — {len(configs)} конфигов, {time.time()-t0:.0f}s\n")
        f.write(f"Гейты: min_n + cross-asset(>=2/3) + two-sided(BTC) + year(>=5/N) + OOS(обе половины).\n")
        f.write(f"RR гейтинга=2.0 (фикс, без cherry-pick).\n\n")
        f.write(f"=== ПРОШЛИ ВСЕ ГЕЙТЫ: {len(passers)} ===\n")
        for r in passers:
            f.write(f"  {r[0]:30} BTC R={r[9]:+.1f} (L{r[10]:+.0f}/S{r[11]:+.0f}) "
                    f"yrs={r[12]}/{r[13]} OOS h1{r[14]:+.0f}/h2{r[15]:+.0f} "
                    f"ETH={r[17]:+.0f} SOL={r[19]:+.0f} null_p={r[25]}\n")
        f.write(f"\n=== ТОП-15 по BTC ΣR (все) ===\n")
        for r in allrows[:15]:
            f.write(f"  {r[0]:30} BTC R={r[9]:+.1f} closed={r[7]} "
                    f"cross={r[20]} two_sided={r[21]} oos={r[23]} PASS={r[24]}\n")
    print(f"\n[grid] DONE {time.time()-t0:.0f}s; passers={len(passers)}; "
          f"csv={csv_path.name} report={rep.name}", flush=True)


if __name__ == "__main__":
    main()
