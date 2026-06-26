"""АНАЛИЗ: что не хватает магнитуде для роста точности и что её улучшит.

Магнитуда сейчас ≈ вола-персистентность (current ATR -> future range, Spearman 0.65; доп.фичи +1пп).
Чтобы улучшить, нужен сигнал ОРТОГОНАЛЬНЫЙ текущей воле. Анализ:
  1) потолок персистентности: сколько forward range объясняет текущая вола (rank-R²), что в остатке;
  2) ГДЕ модель падает: переходы режима (тихо->внезапный спайк, вола->коллапс) vs персистентность;
  3) несут ли ДОСТУПНЫЕ фичи сжатия сигнал перехода: Cohen's d (спайк-из-тихо vs остался-тихо);
  4) add-тест: добавляет ли squeeze-набор Spearman на подвыборке «тихо» сверх чистой волы.

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/ta_laws/magnitude_improve.py
Выход: research/ta_laws/magnitude_improve_report.txt
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
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import magnitude_engine as ME  # noqa: E402

SQUEEZE = ["bbw_pctile", "rangec", "nquiet", "inside3", "volofvol", "volz"]  # сжатие/переход
ORTHO = SQUEEZE + ["dow", "session", "dabs", "cvdabs", "dist_liq", "absret6"]


def tercile(x):
    lo, hi = np.nanquantile(x, [1 / 3, 2 / 3])
    return np.where(x <= lo, 0, np.where(x >= hi, 2, 1))


def main():
    rows = []
    for s in ME.SYMBOLS:
        print(f"[{s}] build...", flush=True); rows += ME.build(s)
    df = pd.DataFrame(rows).sort_values("ts").reset_index(drop=True)
    fr = df.fwd_range.values
    out = []; A = out.append
    A("АНАЛИЗ УЛУЧШЕНИЯ МАГНИТУДЫ — что не хватает и что поможет")
    A(f"Якорей {len(df)} (BTC/ETH/SOL, H={ME.H}, forward range медиана {np.median(fr):.1f}%).\n")

    # 1) потолок персистентности
    A("=== 1. ПОТОЛОК ПЕРСИСТЕНТНОСТИ (сколько forward range объясняет ТЕКУЩАЯ вола) ===")
    for f in ["atr_pct", "rstd12", "rstd24", "park", "atr_pctile"]:
        sp = ME.spearman(df[f].values, fr)
        A(f"  Spearman({f:10}, fwd_range) = {sp:+.3f}  (rank-R²={sp**2:.2f})")
    sp_atr = ME.spearman(df["atr_pct"].values, fr)
    A(f"  -> текущая вола объясняет ~{sp_atr**2*100:.0f}% ранговой дисперсии. Остальные ~{(1-sp_atr**2)*100:.0f}% = "
      f"ПОТЕНЦИАЛ улучшения (но часть необратимо случайна = новости/будущее).\n")

    # OOS предсказания: vol-only vs full
    d, pv, mv = ME.walk_forward(df, "fwd_range", reg=True, feats=ME.VOL_FEATS)
    _, pf, mf = ME.walk_forward(df, "fwd_range", reg=True, feats=ME.FEATS)
    m = mv & mf
    A(f"  OOS Spearman: vol-only {ME.spearman(pv[m], d.fwd_range.values[m]):.3f} | "
      f"full {ME.spearman(pf[m], d.fwd_range.values[m]):.3f} | ATR-alone {ME.spearman(d.atr_pct.values[m], d.fwd_range.values[m]):.3f}\n")

    # 2) ГДЕ ПАДАЕТ: переходы режима
    A("=== 2. ГДЕ МОДЕЛЬ ОШИБАЕТСЯ: переходы режима (cur-вола x forward-range, терцили) ===")
    cur_t = tercile(d.atr_pctile.values); fwd_t = tercile(d.fwd_range.values)
    names = ["низ", "сред", "верх"]
    A(f"  {'':14}" + "".join(f"fwd_{n:>5}" for n in names) + "   (доля строк по cur-воле)")
    for ci in range(3):
        row = []
        cm = (cur_t == ci) & m
        tot = cm.sum()
        for fi in range(3):
            cell = ((cur_t == ci) & (fwd_t == fi) & m).sum()
            row.append(cell / tot * 100 if tot else 0)
        A(f"  cur_вола {names[ci]:5}" + "".join(f"{r:7.0f}%" for r in row))
    surprise = ((cur_t == 0) & (fwd_t == 2) & m).sum() / max(1, ((cur_t == 0) & m).sum())
    collapse = ((cur_t == 2) & (fwd_t == 0) & m).sum() / max(1, ((cur_t == 2) & m).sum())
    A(f"  -> 'СЮРПРИЗ-СПАЙК' (тихо->большой ход): {surprise*100:.0f}% низковолатильных баров; модель их пропускает.")
    A(f"  -> 'КОЛЛАПС' (вола->тихо): {collapse*100:.0f}% высоковолатильных. Вот где остаток предсказуемости.\n")

    # 3) несут ли доступные фичи сигнал ПЕРЕХОДА (в низковолатильной подвыборке)
    A("=== 3. СИГНАЛ ПЕРЕХОДА: в НИЗКОволатильной подвыборке отделяют ли фичи спайк от тишины? ===")
    low = df[df.atr_pctile <= np.nanquantile(df.atr_pctile, 1 / 3)].copy()
    lo_fr = low.fwd_range.values
    thr_hi, thr_lo = np.nanquantile(lo_fr, [2 / 3, 1 / 3])
    low["spike"] = np.where(lo_fr >= thr_hi, 1, np.where(lo_fr <= thr_lo, 0, -1))
    sub = low[low.spike >= 0]
    A(f"  низковолат. баров {len(low)}, из них спайк/тишина {len(sub)} (терцили forward range)")
    A(f"  {'фича':12} {'Cohen d (спайк vs тихо)':>24}")
    dd = [(f, ME.cohens_d(sub[f].values, sub.spike.values)) for f in ORTHO]
    for f, d_ in sorted(dd, key=lambda r: -abs(r[1])):
        A(f"  {f:12} {d_:>+24.2f}")
    best = max(abs(d_) for _, d_ in dd)
    A(f"  -> макс|d| = {best:.2f}  ({'есть слабый сигнал перехода в доступных фичах' if best > 0.3 else 'доступные фичи почти НЕ отделяют сюрприз-спайк = он внешний/новостной'})\n")

    # 4) add-тест: vol-only vs vol+squeeze на низковолат. подвыборке (OOS)
    A("=== 4. ADD-ТЕСТ: добавляет ли squeeze-набор предсказуемость СВЕРХ волы (OOS на тихих барах) ===")
    _, pv2, mv2 = ME.walk_forward(df, "fwd_range", reg=True, feats=ME.VOL_FEATS)
    _, ps2, ms2 = ME.walk_forward(df, "fwd_range", reg=True, feats=ME.VOL_FEATS + SQUEEZE)
    lowmask = (df.atr_pctile.values <= np.nanquantile(df.atr_pctile.values, 1 / 3))
    mm = mv2 & ms2 & lowmask
    sp_v = ME.spearman(pv2[mm], df.fwd_range.values[mm])
    sp_vs = ME.spearman(ps2[mm], df.fwd_range.values[mm])
    A(f"  на ТИХИХ барах OOS Spearman: vol-only {sp_v:.3f} -> vol+squeeze {sp_vs:.3f} ({sp_vs-sp_v:+.3f})")
    A(f"  -> {'squeeze РЕАЛЬНО добавляет на переходах' if sp_vs > sp_v + 0.03 else 'squeeze почти не добавляет — переход в доступных данных не виден'}\n")

    # 5) вывод
    A("=== ВЫВОД: что улучшит магнитуду ===")
    A("  Потолок персистентности взят (ATR). Остаток = ПЕРЕХОДЫ (сюрприз-спайк/коллапс), и в наших price/flow")
    A(f"  данных он {'частично виден (squeeze/сжатие)' if best > 0.3 else 'почти НЕ виден'} -> большая часть всплесков = ВНЕШНИЕ/новостные.")
    A("  РЫЧАГИ роста точности (по ожидаемой отдаче и ортогональности к ATR):")
    A("   A. Implied Vol / DVOL (Deribit) — forward-looking вола, эталон прогноза; ИСТОРИЯ ограничена.")
    A("   B. Календарь событий (FOMC/CPI/экспирации CME&Deribit/анлоки) — известны заранее, ортогональны воле,")
    A("      реальный драйвер спайков. Самый дешёвый практичный рычаг (загрузить даты).")
    A("   C. Cross-asset вола (VIX/total-crypto/DXY-вола) — контагион волатильности; VIX есть длинная история.")
    A("   D. OI + funding экстремумы — позиционная вола/ликвид-каскады; история Binance ~30д (только недавнее окно).")
    A("   E. Leverage-effect (downside semivol, signed) — даунмуви поднимают будущую волу сильнее; ЕСТЬ в наших данных.")
    A("   F. HAR-RV / jump-компонента (Parkinson/Garman-Klass, bipower) — лучшая структура самой волы; ЕСТЬ.")
    A("  Дешёвые и сразу-тестируемые: E (leverage), F (HAR/jumps), B (календарь). Внешние данные: A, C, D.")

    rep = HERE / "magnitude_improve_report.txt"
    rep.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out)); print(f"\n[ok] -> {rep.name}")


if __name__ == "__main__":
    main()
