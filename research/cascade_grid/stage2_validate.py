"""Stage 2 — глубокая адверсарная валидация финалистов грида (прошедших все 5 гейтов).

Читает grid_results.csv (PASS==1), переиспользует движок grid.py, по каждому конфигу:
  - RR-кривая {1.5,2.0,2.5,3.0} на BTC/ETH/SOL (RR-робастность, не cherry-pick)
  - per-trade expectancy (ΣR/closed) на каждом символе — снимает завышение от PER_TOP_CAP
  - per-year ΣR на ВСЕХ ТРЁХ символах (walk-forward по годам), доля плюс-лет
  - permutation-null 2000 сэмплов (random-time entry) на BTC @RR2.0 -> p
Ранжирует по робастности: min(per-trade по 3 символам) и доле плюс-лет.

Запуск: set PYTHONIOENCODING=utf-8
        venv/Scripts/python.exe research/cascade_grid/stage2_validate.py
Выход: research/cascade_grid/stage2_report.txt
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import grid as G  # noqa: E402

RR_CURVE = [1.5, 2.0, 2.5, 3.0]
NULL_N = 2000


def load_passers():
    df = pd.read_csv(HERE / "grid_results.csv")
    df = df[df["PASS"] == 1].copy()
    cfgs = []
    for _, r in df.iterrows():
        cfgs.append((r["top"], r["macro"], r["htf"], r["entry"], bool(int(r["swept"]))))
    return cfgs


def per_year_line(year_R):
    return " ".join(f"{y}:{year_R.get(y, 0):+.0f}" for y in range(2020, 2027))


def main():
    t0 = time.time()
    cfgs = load_passers()
    print(f"[stage2] финалистов: {len(cfgs)}", flush=True)

    print("[stage2] precompute (3 символа)...", flush=True)
    PC = {s: G.build_precomp(s) for s in G.SYMBOLS}
    print(f"   готово {time.time()-t0:.0f}s", flush=True)

    results = []
    for ci, cfg in enumerate(cfgs, 1):
        name = G.cfg_name(cfg)
        per = {}
        sigs_by = {}
        for s in G.SYMBOLS:
            sigs = G.scan_cascade(PC[s], cfg)
            sigs_by[s] = sigs
            per[s] = {rr: G.sim(sigs, PC[s], rr) for rr in RR_CURVE}
        # per-trade @RR2.0
        ptt = {}
        posyrs = {}
        for s in G.SYMBOLS:
            m = per[s][2.0]
            ptt[s] = m["sumR"] / m["closed"] if m["closed"] else 0.0
            yr = m["year_R"]
            posyrs[s] = (sum(1 for v in yr.values() if v > 0), len([1 for v in yr.values()]))
        null_p = G.perm_null(sigs_by["BTCUSDT"], PC["BTCUSDT"], 2.0, n_samples=NULL_N)
        min_ptt = min(ptt.values())
        # RR-робастность: доля (символ×RR) с ΣR>0
        rr_pos = sum(1 for s in G.SYMBOLS for rr in RR_CURVE if per[s][rr]["sumR"] > 0)
        rr_tot = len(G.SYMBOLS) * len(RR_CURVE)
        results.append({"name": name, "cfg": cfg, "per": per, "ptt": ptt,
                        "posyrs": posyrs, "null_p": null_p, "min_ptt": min_ptt,
                        "rr_pos": rr_pos, "rr_tot": rr_tot})
        print(f"[{ci:2}/{len(cfgs)}] {name:30} minPTT={min_ptt:+.3f} "
              f"null_p={null_p:.3f} RRpos={rr_pos}/{rr_tot} "
              f"yrs(B/E/S)={posyrs['BTCUSDT'][0]}/{posyrs['ETHUSDT'][0]}/{posyrs['SOLUSDT'][0]}",
              flush=True)

    # ранжирование: robust = min per-trade>0 AND null<0.05 AND RRpos high
    results.sort(key=lambda r: (r["null_p"] < 0.05, r["min_ptt"], r["rr_pos"]), reverse=True)

    rep = HERE / "stage2_report.txt"
    with rep.open("w", encoding="utf-8") as f:
        f.write(f"STAGE 2 — глубокая валидация {len(cfgs)} финалистов, {time.time()-t0:.0f}s\n")
        f.write("Робастность: min per-trade (3 символа) > 0, null<0.05, RR-кривая, per-year x3.\n\n")
        for r in results:
            robust = "ROBUST" if (r["min_ptt"] > 0 and r["null_p"] < 0.05
                                  and r["rr_pos"] >= r["rr_tot"] - 2) else ""
            f.write(f"=== {r['name']}  {robust}\n")
            f.write(f"  null_p(2000)={r['null_p']:.3f}  min_per_trade={r['min_ptt']:+.3f}  "
                    f"RR>0: {r['rr_pos']}/{r['rr_tot']}\n")
            for s in G.SYMBOLS:
                rrs = "  ".join(f"RR{rr}:{r['per'][s][rr]['sumR']:+.0f}" for rr in RR_CURVE)
                m = r["per"][s][2.0]
                f.write(f"  {s:8} closed={m['closed']:4} ptt={r['ptt'][s]:+.3f}  {rrs}  "
                        f"+yrs={r['posyrs'][s][0]}/{r['posyrs'][s][1]}\n")
                f.write(f"           per-year: {per_year_line(m['year_R'])}\n")
            f.write("\n")
        robust_list = [r for r in results if r["min_ptt"] > 0 and r["null_p"] < 0.05
                       and r["rr_pos"] >= r["rr_tot"] - 2]
        f.write(f"=== ROBUST (min per-trade>0 & null<0.05 & RR>0 почти везде): "
                f"{len(robust_list)} ===\n")
        for r in robust_list:
            f.write(f"  {r['name']:30} minPTT={r['min_ptt']:+.3f} null={r['null_p']:.3f} "
                    f"RR={r['rr_pos']}/{r['rr_tot']} "
                    f"yrs B/E/S={r['posyrs']['BTCUSDT'][0]}/{r['posyrs']['ETHUSDT'][0]}/{r['posyrs']['SOLUSDT'][0]}\n")
    print(f"\n[stage2] DONE {time.time()-t0:.0f}s; report={rep.name}; robust={len(robust_list)}",
          flush=True)


if __name__ == "__main__":
    main()
