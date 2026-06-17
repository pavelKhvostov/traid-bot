"""etap_253 — ATAKA 3 deep-dive: htf_tf=2h как доп-правило к BTC net-грейду.

Из etap_252: htf_tf=2h(+good) дал OOS spread +29.7pp (vs base +18.0), year-sign 6/6.
Проверяем ЧЕСТНО:
  1) htf_tf=2h как САМОСТОЯТЕЛЬНЫЙ маркер (WR 2h vs 1h, по годам + permutation).
  2) ортогонален ли он net-грейду (corr с net, conditional на net).
  3) мультитест: 17 кандидатов в etap_252 -> Bonferroni / FWER permutation
     (перемешиваем win, считаем max улучшение OOS-спреда по всем 17 правилам -> p).
  4) переносится ли 2h-преимущество на ETH/SOL (sanity, хотя цель = BTC).

ASCII-only print.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
HERE = Path(__file__).resolve().parent
CACHE = HERE / "output" / "etap_251_dataset.csv"
CUTOFF = pd.Timestamp("2024-01-01", tz="UTC")


def load(asset=None):
    d = pd.read_csv(CACHE, parse_dates=["signal_time"])
    if asset: d = d[d.asset == asset].copy()
    for c in ["risk_pct", "gauge", "p_green", "trend_hold", "eff", "hour", "dow", "year"]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    return d.dropna(subset=["win"]).reset_index(drop=True)


def base_net(g):
    p33, p67 = g.risk_pct.quantile(0.33), g.risk_pct.quantile(0.67)
    weak = ((g.risk_pct >= p67).astype(int) + (g.gauge >= 1.0).astype(int)
            + (g.fvg_tf == "20m").astype(int)
            + g.session.isin(["London (7-13)", "NY (13-21)"]).astype(int)
            + (g.state == "ROTATION").astype(int))
    ct = (((g.direction == "SHORT") & (g.state == "TREND_UP"))
          | ((g.direction == "LONG") & (g.state == "TREND_DOWN"))).astype(int)
    strong = (g.risk_pct <= p33).astype(int) + (g.hour < 7).astype(int) + ct
    return strong - weak


def main():
    d = load("BTCUSDT"); d["net"] = base_net(d)
    print(f"BTC n={len(d)} base WR {d.win.mean()*100:.1f}%")

    # ---- 1) htf_tf standalone: WR by tf, by year ----
    print("\n" + "="*70)
    print("1) htf_tf standalone (BTC)")
    print("="*70)
    for tf, g in d.groupby("htf_tf"):
        print(f"  htf={tf}: n={len(g):>3} WR={g.win.mean()*100:5.1f}%  "
              f"(train {g[g.signal_time<CUTOFF].win.mean()*100:.0f}% n={(g.signal_time<CUTOFF).sum()} / "
              f"OOS {g[g.signal_time>=CUTOFF].win.mean()*100:.0f}% n={(g.signal_time>=CUTOFF).sum()})")
    print("\n  WR 2h vs 1h by year:")
    for y, g in d.groupby("year"):
        h2 = g[g.htf_tf=="2h"]; h1 = g[g.htf_tf=="1h"]
        s = (h2.win.mean()-h1.win.mean())*100 if len(h2)>=3 and len(h1)>=3 else np.nan
        print(f"    {int(y)}: 2h WR {h2.win.mean()*100 if len(h2) else float('nan'):5.1f}% (n={len(h2):>2}) "
              f"1h WR {h1.win.mean()*100 if len(h1) else float('nan'):5.1f}% (n={len(h1):>2})  "
              f"diff {'na' if np.isnan(s) else f'{s:+.0f}pp'}")

    # share of 2h inside each net-grade group (is the signal redundant with net?)
    print("\n  share htf=2h by net group:  (если ~равны -> ортогонален net)")
    for grp, g in [("net>=0", d[d.net>=0]), ("net<0", d[d.net<0])]:
        print(f"    {grp}: P(htf=2h)={ (g.htf_tf=='2h').mean()*100:.0f}%  n={len(g)}  WR={g.win.mean()*100:.1f}%")

    # ---- 2) standalone OOS spread: 2h vs 1h (no net) ----
    oos = d[d.signal_time>=CUTOFF]
    h2o, h1o = oos[oos.htf_tf=="2h"], oos[oos.htf_tf=="1h"]
    print(f"\n  OOS standalone: 2h WR {h2o.win.mean()*100:.1f}% (n={len(h2o)}) vs 1h WR {h1o.win.mean()*100:.1f}% (n={len(h1o)}) "
          f"spread {(h2o.win.mean()-h1o.win.mean())*100:+.1f}pp")

    # ---- 3) conditional: 2h ON TOP of net (does it add WITHIN net>=0?) ----
    print("\n" + "="*70)
    print("2) htf=2h CONDITIONAL on net (added value within each net group, OOS)")
    print("="*70)
    for grp, g in [("net>=0", oos[oos.net>=0]), ("net<0", oos[oos.net<0])]:
        a = g[g.htf_tf=="2h"]; b = g[g.htf_tf=="1h"]
        sa = a.win.mean()*100 if len(a) else float('nan')
        sb = b.win.mean()*100 if len(b) else float('nan')
        print(f"  {grp}: 2h WR {sa:5.1f}% (n={len(a)}) / 1h WR {sb:5.1f}% (n={len(b)})  "
              f"diff {('na' if (len(a)<3 or len(b)<3) else f'{sa-sb:+.0f}pp')}")

    # ---- 4) FWER permutation across all 17 candidates ----
    print("\n" + "="*70)
    print("3) MULTI-TEST FWER permutation (17 candidates from etap_252)")
    print("="*70)
    # rebuild candidate net deltas
    def cand_deltas(df):
        net = base_net(df)
        c = {}
        align = (((df.direction=="LONG")&(df.p_green>=0.65))|((df.direction=="SHORT")&(df.p_green<=0.35))).astype(int)
        mis = (((df.direction=="LONG")&(df.p_green<=0.35))|((df.direction=="SHORT")&(df.p_green>=0.65))).astype(int)
        c["pg_align"]=net+align; c["pg_mis"]=net-mis
        c["pg_ext"]=net-((df.p_green>=0.8)|(df.p_green<=0.2)).astype(int)
        c["th_hi_g"]=net+(df.trend_hold>=0.7).astype(int)
        c["th_lo_b"]=net-(df.trend_hold<=0.4).astype(int)
        c["th_hi_b"]=net-(df.trend_hold>=0.7).astype(int)
        c["eff_sm_g"]=net+(df.eff>=0.062).astype(int)
        c["eff_rgh_b"]=net-(df.eff<=0.024).astype(int)
        c["eff_rgh_g"]=net+(df.eff<=0.024).astype(int)
        c["top12_g"]=net+(df.top_tf=="12h").astype(int)
        c["top1d_g"]=net+(df.top_tf=="1d").astype(int)
        c["mac6_g"]=net+(df.macro_tf=="6h").astype(int)
        c["mac4_g"]=net+(df.macro_tf=="4h").astype(int)
        c["htf2_g"]=net+(df.htf_tf=="2h").astype(int)
        c["htf1_g"]=net+(df.htf_tf=="1h").astype(int)
        c["fvg15_g"]=net+(df.fvg_tf=="15m").astype(int)
        return net, c

    def oos_spread(win, netcol, mask_oos):
        w=win[mask_oos]; n=netcol[mask_oos]
        hi=w[n>=0]; lo=w[n<0]
        if len(hi)==0 or len(lo)==0: return np.nan
        return (hi.mean()-lo.mean())*100

    mask_oos = (d.signal_time>=CUTOFF).values
    base_n, cand = cand_deltas(d)
    base_oos = oos_spread(d.win.values, base_n.values, mask_oos)
    obs_impr = {k: oos_spread(d.win.values, v.values, mask_oos)-base_oos for k,v in cand.items()}
    best_obs = max(obs_impr.values())
    best_rule = max(obs_impr, key=obs_impr.get)
    print(f"  baseline OOS spread = {base_oos:+.1f}pp")
    print(f"  observed best improvement: {best_rule} dOOS={best_obs:+.1f}pp")

    # permutation: shuffle win WITHIN train and WITHIN oos separately?
    # We shuffle win globally (null: marker carries no info about win), recompute base & all cands,
    # take MAX improvement over 17 rules -> FWER distribution.
    rng = np.random.RandomState(0)
    null_max = []
    win = d.win.values.copy()
    for i in range(2000):
        wp = rng.permutation(win)
        # base net unchanged (structural), but win permuted
        b = oos_spread(wp, base_n.values, mask_oos)
        if np.isnan(b): continue
        impr = [ (oos_spread(wp, v.values, mask_oos)-b) for v in cand.values() ]
        impr = [x for x in impr if not np.isnan(x)]
        if impr: null_max.append(max(impr))
    null_max = np.array(null_max)
    p_fwer = (null_max >= best_obs).mean()
    print(f"  FWER permutation (max-improvement over 17 rules, 2000 shuffles):")
    print(f"    null max-improvement: mean {null_max.mean():+.1f}pp  p95 {np.percentile(null_max,95):+.1f}pp  max {null_max.max():+.1f}pp")
    print(f"    p(best_obs explained by noise) = {p_fwer:.3f}")

    # also single-rule permutation just for htf2_g (no multitest penalty)
    null_h = []
    for i in range(2000):
        wp = rng.permutation(win)
        b = oos_spread(wp, base_n.values, mask_oos)
        x = oos_spread(wp, cand["htf2_g"].values, mask_oos)-b
        if not np.isnan(x): null_h.append(x)
    null_h=np.array(null_h)
    p_single = (null_h >= obs_impr["htf2_g"]).mean()
    print(f"  single-rule permutation htf2_g: p={p_single:.3f} (no multitest correction)")

    # ---- 5) cross-asset sanity ----
    print("\n" + "="*70)
    print("4) cross-asset: htf=2h vs 1h WR (OOS) on ETH/SOL")
    print("="*70)
    for a in ["ETHUSDT","SOLUSDT"]:
        g = load(a); go = g[g.signal_time>=CUTOFF]
        h2=go[go.htf_tf=="2h"]; h1=go[go.htf_tf=="1h"]
        print(f"  {a}: OOS 2h WR {h2.win.mean()*100 if len(h2) else float('nan'):.1f}% (n={len(h2)}) "
              f"1h WR {h1.win.mean()*100 if len(h1) else float('nan'):.1f}% (n={len(h1)})  "
              f"all 2h {g[g.htf_tf=='2h'].win.mean()*100:.1f}% (n={(g.htf_tf=='2h').sum()}) "
              f"1h {g[g.htf_tf=='1h'].win.mean()*100:.1f}% (n={(g.htf_tf=='1h').sum()})")


if __name__ == "__main__":
    main()
