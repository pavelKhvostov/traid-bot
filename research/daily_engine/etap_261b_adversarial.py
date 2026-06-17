"""etap_261b - ADVERSARIAL kill-suite for the vol-gate ORB claim (Block 3).

Reuses gen_orb / morning_eff / zone_harness from etap_261 WITHOUT editing them.
Adds: cost model, threshold sweep, walk-forward, permutation null, cost stress,
RR robustness, long/short split, lookahead audit.

All math on the SAME simulate() race (SL-first, stop entry). ASCII-only prints.
Run: set PYTHONIOENCODING=utf-8
     venv/Scripts/python.exe research/daily_engine/etap_261b_adversarial.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(ROOT))
from data_manager import load_df
import zone_harness as ZH
from etap_261_vol_gate_orb import gen_orb, morning_eff, IB_H

RR = 2.2
WAIT = 24
HOLD = 120
SYMS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


def load(sym):
    df1h = load_df(sym, "1h"); df15 = load_df(sym, "15m")
    if df1h.index.tz is None: df1h.index = df1h.index.tz_localize("UTC")
    if not df15.empty and df15.index.tz is None: df15.index = df15.index.tz_localize("UTC")
    return df1h, df15


def cost_R(sig):
    """round_trip handled by caller; returns risk_pct = |entry-sl|/entry per sig."""
    return abs(sig["entry"] - sig["sl"]) / sig["entry"]


def simulate_book(sigs, df1h, rr=RR):
    return ZH.simulate(sigs, df1h, rr=rr, wait_bars=WAIT, hold_bars=HOLD, entry_type="stop")


def attach_risk(book, sigs):
    """Map risk_pct onto closed book rows by time (gen_orb has one sig/day)."""
    rp = {pd.Timestamp(s["time"]): cost_R(s) for s in sigs}
    book = book.copy()
    book["risk_pct"] = book["time"].map(lambda t: rp.get(pd.Timestamp(t), np.nan))
    return book


def net_stats(book, sigs, rt_pct=0.10, rr=RR):
    """Closed-only gross & net R/trade after round-trip cost (rt_pct in PERCENT)."""
    b = attach_risk(book, sigs)
    closed = b[b.outcome.isin(["win", "loss"])].copy()
    n = len(closed)
    if n == 0:
        return dict(n=0, gross=np.nan, net=np.nan, wr=np.nan)
    gross = closed.R.mean()
    cost = (rt_pct / 100.0) / closed["risk_pct"]   # cost in R units per trade
    net = (closed.R - cost).mean()
    wr = closed.R.eq(rr).mean() * 100
    return dict(n=n, gross=float(gross), net=float(net), wr=float(wr),
                closed=closed, cost_mean=float(cost.mean()))


# ----------------------------------------------------------------------------
def attack0_repro():
    print("\n" + "#" * 78)
    print("# REPRO: baseline vs eff>=0.50, gross + NET@0.10% (claim check)")
    print("#" * 78)
    print(f"{'sym':<8}{'gate':<10}{'n':>5}{'WR%':>7}{'grossR':>9}{'netR':>9}")
    pooled = {}
    for sym in SYMS:
        df1h, df15 = load(sym)
        for lab, em in (("none", None), ("0.50", 0.50)):
            sigs = gen_orb(df1h, df15, eff_min=em)
            book = simulate_book(sigs, df1h)
            st = net_stats(book, sigs, rt_pct=0.10)
            print(f"{sym:<8}{lab:<10}{st['n']:>5}{st['wr']:>7.1f}{st['gross']:>+9.3f}{st['net']:>+9.3f}")
            if em == 0.50:
                pooled[sym] = st
    return pooled


def attack1_threshold_sweep():
    print("\n" + "#" * 78)
    print("# ATTACK 1: THRESHOLD SWEEP (gross R/trade vs eff_min) -- monotone or spike?")
    print("#" * 78)
    grid = [None, 0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]
    hdr = "thr".ljust(7) + "".join(f"{('%s' % ('none' if g is None else g)):>16}" for g in grid)
    for sym in SYMS:
        df1h, df15 = load(sym)
        rows_g = []; rows_n = []
        for g in grid:
            sigs = gen_orb(df1h, df15, eff_min=g)
            book = simulate_book(sigs, df1h)
            st = net_stats(book, sigs, rt_pct=0.10)
            rows_g.append((st["gross"], st["n"]))
        print(f"\n  {sym}  (gross R/trade [n]):")
        line = "  "
        for g, (gr, n) in zip(grid, rows_g):
            tag = "none" if g is None else f"{g:.1f}"
            line += f"{tag}={gr:+.3f}[{n}]  "
        print(line)


def attack2_walkforward():
    print("\n" + "#" * 78)
    print("# ATTACK 2: WALK-FORWARD -- best eff_min on 2020-2023, applied to 2024-2026")
    print("#" * 78)
    grid = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]
    split = pd.Timestamp("2024-01-01", tz="UTC")
    pooled_oos = []
    for sym in SYMS:
        df1h, df15 = load(sym)
        # choose best by IN-SAMPLE net R/trade (2020-2023)
        best = None
        for g in grid:
            sigs = gen_orb(df1h, df15, eff_min=g)
            book = simulate_book(sigs, df1h)
            b = attach_risk(book, sigs)
            ins = b[(b.outcome.isin(["win", "loss"])) & (pd.to_datetime(b.time) < split)]
            if len(ins) < 20:
                continue
            cost = (0.10 / 100.0) / ins["risk_pct"]
            net = (ins.R - cost).mean()
            if best is None or net > best[1]:
                best = (g, float(net), len(ins))
        if best is None:
            print(f"  {sym}: insufficient IS data"); continue
        g = best[0]
        sigs = gen_orb(df1h, df15, eff_min=g)
        book = simulate_book(sigs, df1h)
        b = attach_risk(book, sigs)
        oos = b[(b.outcome.isin(["win", "loss"])) & (pd.to_datetime(b.time) >= split)]
        n = len(oos)
        if n:
            cost = (0.10 / 100.0) / oos["risk_pct"]
            net = (oos.R - cost).mean(); gross = oos.R.mean()
            wr = oos.R.eq(RR).mean() * 100
            pooled_oos.append(oos.assign(cost=cost))
        else:
            net = gross = wr = np.nan
        print(f"  {sym}: best IS eff_min={g:.1f} (IS net {best[1]:+.3f}, n={best[2]}) "
              f"-> OOS net {net:+.3f} gross {gross:+.3f} WR {wr:.1f}% n={n}")
    if pooled_oos:
        allp = pd.concat(pooled_oos)
        net = (allp.R - allp.cost).mean()
        print(f"  POOLED OOS: net {net:+.3f} gross {allp.R.mean():+.3f} n={len(allp)}")


def attack3_permutation():
    print("\n" + "#" * 78)
    print("# ATTACK 3: PERMUTATION NULL (eff>=0.50 dayset fixed)")
    print("#   (a) randomize entry DIRECTION; (b) random same-N days from ALL days")
    print("#   pooled across BTC/ETH/SOL, 1000 shuffles, seed=42")
    print("#" * 78)
    rng = np.random.default_rng(42)
    N_SH = 1000

    # ---- build per-symbol gated & ungated outcome pools ----
    # For (a): we need to recompute outcome with a FLIPPED direction. Easiest: build
    # both LONG and SHORT outcome for each gated day, then random pick.
    # For (b): the ungated day-set with the same selection mechanism (first IB break,
    # native direction), drawn at random to match gated N.

    obs_gated_R = []           # observed gated R per closed trade (pooled)
    null_dir = np.zeros(N_SH)  # (a) sum of pooled R under random direction
    null_sel = np.zeros(N_SH)  # (b) mean pooled R from random ungated subset

    # collect per-symbol structures
    sym_data = {}
    for sym in SYMS:
        df1h, df15 = load(sym)
        # gated sigs (eff>=0.50)
        gated = gen_orb(df1h, df15, eff_min=0.50)
        # ALL-days sigs (no gate)
        alld = gen_orb(df1h, df15, eff_min=None)
        # simulate both with NATIVE direction
        bg = simulate_book(gated, df1h)
        ba = simulate_book(alld, df1h)
        bg_c = bg[bg.outcome.isin(["win", "loss"])].copy()
        ba_c = ba[ba.outcome.isin(["win", "loss"])].copy()
        # for direction-flip, build outcome under FORCED LONG and FORCED SHORT for gated days
        gated_long = [dict(s, direction="LONG", entry=max(s["entry"], s["sl"]),
                           sl=min(s["entry"], s["sl"])) for s in gated]
        gated_short = [dict(s, direction="SHORT", entry=min(s["entry"], s["sl"]),
                            sl=max(s["entry"], s["sl"])) for s in gated]
        # NOTE: for a clean direction coin we re-derive entry/sl from ib edges:
        # native gen_orb: LONG entry=ib_h sl=ib_l ; SHORT entry=ib_l sl=ib_h.
        # so ib_h=max(entry,sl), ib_l=min(entry,sl) regardless of native side. correct above.
        bl = simulate_book(gated_long, df1h)
        bs = simulate_book(gated_short, df1h)
        bl_c = bl[bl.outcome.isin(["win", "loss"])].set_index("time")
        bs_c = bs[bs.outcome.isin(["win", "loss"])].set_index("time")
        # align on common closed times (both sides filled)
        common = bl_c.index.intersection(bs_c.index)
        sym_data[sym] = dict(
            obs=bg_c.R.values,
            long_R=bl_c.loc[common, "R"].values,
            short_R=bs_c.loc[common, "R"].values,
            all_R=ba_c.R.values,
            n_gated=len(bg_c),
        )
        obs_gated_R.append(bg_c.R.values)

    obs_all = np.concatenate(obs_gated_R)
    obs_mean = obs_all.mean()

    # (a) direction coin: per symbol flip each gated day's side 50/50, pool
    for i in range(N_SH):
        acc = []
        for sym in SYMS:
            d = sym_data[sym]
            m = len(d["long_R"])
            if m == 0:
                continue
            pick = rng.integers(0, 2, m)  # 0=long,1=short
            r = np.where(pick == 0, d["long_R"], d["short_R"])
            acc.append(r)
        null_dir[i] = np.concatenate(acc).mean()

    # (b) random selection: per symbol draw n_gated random days from ALL days, pool
    for i in range(N_SH):
        acc = []
        for sym in SYMS:
            d = sym_data[sym]
            pool = d["all_R"]; k = min(d["n_gated"], len(pool))
            sel = rng.choice(pool, size=k, replace=False)
            acc.append(sel)
        null_sel[i] = np.concatenate(acc).mean()

    def pct_p(obs, null):
        # one-sided: P(null >= obs)
        return float((null >= obs).mean())

    print(f"  observed pooled gross R/trade (eff>=0.50) = {obs_mean:+.4f}  (n={len(obs_all)})")
    pa = pct_p(obs_mean, null_dir)
    pb = pct_p(obs_mean, null_sel)
    print(f"  (a) direction-coin null: mean {null_dir.mean():+.4f} sd {null_dir.std():.4f} "
          f"[{np.percentile(null_dir,2.5):+.4f},{np.percentile(null_dir,97.5):+.4f}]  p={pa:.3f}")
    print(f"  (b) random-day  null:    mean {null_sel.mean():+.4f} sd {null_sel.std():.4f} "
          f"[{np.percentile(null_sel,2.5):+.4f},{np.percentile(null_sel,97.5):+.4f}]  p={pb:.3f}")
    print(f"  -> selection edge {'SURVIVES' if pb < 0.05 else 'DIES'} vs random-day null (p={pb:.3f})")
    print(f"  -> direction edge {'SURVIVES' if pa < 0.05 else 'DIES'} vs coin null (p={pa:.3f})")


def attack4_cost_stress():
    print("\n" + "#" * 78)
    print("# ATTACK 4: COST STRESS (NET R/trade vs round-trip %, eff>=0.50)")
    print("#" * 78)
    costs = [0.05, 0.10, 0.15, 0.20]
    print(f"  {'sym':<8}" + "".join(f"{('%.2f%%' % c):>10}" for c in costs) + f"{'n':>6}")
    for sym in SYMS:
        df1h, df15 = load(sym)
        sigs = gen_orb(df1h, df15, eff_min=0.50)
        book = simulate_book(sigs, df1h)
        line = f"  {sym:<8}"
        n = 0
        for c in costs:
            st = net_stats(book, sigs, rt_pct=c)
            line += f"{st['net']:>+10.3f}"; n = st["n"]
        print(line + f"{n:>6}")


def attack5_rr_robust():
    print("\n" + "#" * 78)
    print("# ATTACK 5: RR ROBUSTNESS (NET@0.10% per RR, eff>=0.50)")
    print("#" * 78)
    rrs = [1.5, 2.0, 2.2, 2.5, 3.0]
    print(f"  {'sym':<8}" + "".join(f"{('RR%.1f' % r):>10}" for r in rrs) + f"{'n~':>6}")
    for sym in SYMS:
        df1h, df15 = load(sym)
        sigs = gen_orb(df1h, df15, eff_min=0.50)
        line = f"  {sym:<8}"
        n = 0
        for r in rrs:
            book = simulate_book(sigs, df1h, rr=r)
            st = net_stats(book, sigs, rt_pct=0.10, rr=r)
            line += f"{st['net']:>+10.3f}"; n = st["n"]
        print(line + f"{n:>6}")


def attack6_longshort():
    print("\n" + "#" * 78)
    print("# ATTACK 6: LONG vs SHORT split (NET@0.10%, eff>=0.50) + per-year sign")
    print("#" * 78)
    for sym in SYMS:
        df1h, df15 = load(sym)
        sigs = gen_orb(df1h, df15, eff_min=0.50)
        book = simulate_book(sigs, df1h)
        b = attach_risk(book, sigs)
        closed = b[b.outcome.isin(["win", "loss"])].copy()
        for side in ("LONG", "SHORT"):
            sub = closed[closed.direction == side]
            n = len(sub)
            if n == 0:
                print(f"  {sym} {side}: n=0"); continue
            cost = (0.10 / 100.0) / sub["risk_pct"]
            net = (sub.R - cost).mean(); gross = sub.R.mean()
            wr = sub.R.eq(RR).mean() * 100
            # per-year net sign
            ys = []
            for yr, gg in sub.groupby(pd.to_datetime(sub.time).dt.year):
                c = (0.10 / 100.0) / gg["risk_pct"]
                ys.append((yr, (gg.R - c).mean()))
            yr_str = " ".join(f"{y}:{v:+.2f}" for y, v in ys)
            print(f"  {sym} {side}: n={n} WR {wr:.1f}% gross {gross:+.3f} net {net:+.3f}")
            print(f"        per-yr net: {yr_str}")


def gen_orb_signfix(df1h, df15, eff_min=None):
    """Lookahead-audit variant: on double-break bars pick side by sign(close-ib_mid)
    of the breakout bar instead of larger intrabar excursion."""
    sig = []
    n_double = 0
    for day, g in df1h.groupby(df1h.index.normalize()):
        if len(g) < IB_H + 3:
            continue
        H = g["high"].values; Lo = g["low"].values; C = g["close"].values; idx = g.index
        ib_h = H[:IB_H].max(); ib_l = Lo[:IB_H].min()
        if ib_h <= ib_l:
            continue
        if eff_min is not None:
            e = morning_eff(df15, day)
            if not (e >= eff_min):
                continue
        ib_mid = 0.5 * (ib_h + ib_l)
        for k in range(IB_H, len(g)):
            up = H[k] > ib_h; dn = Lo[k] < ib_l
            if not (up or dn):
                continue
            if up and dn:
                n_double += 1
                direction = "LONG" if C[k] >= ib_mid else "SHORT"
            else:
                direction = "LONG" if up else "SHORT"
            entry = ib_h if direction == "LONG" else ib_l
            sl = ib_l if direction == "LONG" else ib_h
            sig.append(dict(time=idx[k - 1], direction=direction, entry=float(entry), sl=float(sl)))
            break
    return sig, n_double


def attack7_lookahead():
    print("\n" + "#" * 78)
    print("# ATTACK 7: LOOKAHEAD AUDIT")
    print("#   (a) double-break side pick: excursion (orig) vs sign(close-ib_mid)")
    print("#   (b) time=idx[k-1] + stop-entry leak check")
    print("#   (c) SL-first intrabar = conservative (noted in harness)")
    print("#" * 78)
    for sym in SYMS:
        df1h, df15 = load(sym)
        sigs_orig = gen_orb(df1h, df15, eff_min=0.50)
        sigs_fix, n_double = gen_orb_signfix(df1h, df15, eff_min=0.50)
        bo = simulate_book(sigs_orig, df1h); bf = simulate_book(sigs_fix, df1h)
        so = net_stats(bo, sigs_orig, rt_pct=0.10); sf = net_stats(bf, sigs_fix, rt_pct=0.10)
        # count how many native-direction sigs differ between the two
        do = {pd.Timestamp(s["time"]): s["direction"] for s in sigs_orig}
        diff = sum(1 for s in sigs_fix if do.get(pd.Timestamp(s["time"])) != s["direction"])
        print(f"  {sym}: gated n={so['n']} double-break days={n_double} dir-changed={diff}")
        print(f"        orig(excursion) net {so['net']:+.3f} gross {so['gross']:+.3f}  |  "
              f"signfix net {sf['net']:+.3f} gross {sf['gross']:+.3f}")
    print("  (b) gen_orb sets time=idx[k-1] (open of breakout bar's PRIOR bar); simulate()")
    print("      starts search STRICTLY AFTER time (searchsorted side=right) with stop entry")
    print("      (H>=entry/Lo<=entry). Entry level = IB edge known at end of hour IB_H, well")
    print("      before the breakout bar -> no future info in the level. The k-1 timestamp is")
    print("      CONSERVATIVE-NEUTRAL: it lets fill happen on the breakout bar itself, which is")
    print("      when the break is observed. No leak of the breakout bar's high/low into level.")
    print("  (c) SL-first when both hit same bar = pessimistic; not inflating edge.")


def main():
    attack0_repro()
    attack1_threshold_sweep()
    attack2_walkforward()
    attack3_permutation()
    attack4_cost_stress()
    attack5_rr_robust()
    attack6_longshort()
    attack7_lookahead()


if __name__ == "__main__":
    main()
