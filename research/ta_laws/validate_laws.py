"""Валидатор законов v2 — 1h->D с 2020. Фокус: FADE (инверсия континуации) через все гейты.

Метрика: triple-barrier fade R (+1 если против импульса первым, -1 если по импульсу).
Закон ПРИНЯТ если: fade expR>0.05 И p(null)<0.05 И >=2/3 символов+ И оба режима+ И обе дирекшн+
И положителен на большинстве ТФ.  (+ продолжение/measured-move — для контекста.)

Запуск: set PYTHONIOENCODING=utf-8 && venv/Scripts/python.exe research/ta_laws/validate_laws.py
Выход: research/ta_laws/laws_report.txt
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
RNG = np.random.default_rng(11)
TFS = ["1h", "2h", "4h", "6h", "12h", "1d"]


def null_p_ge(sub_mean, null_vals, n, iters=3000):
    if len(null_vals) < 5 or n < 3:
        return 1.0
    nv = np.asarray(null_vals, float)
    means = nv[RNG.integers(0, len(nv), size=(iters, n))].mean(axis=1)
    return float((means >= sub_mean).mean())


def fade(sub):
    d = sub[sub.tb != "none"]
    if not len(d):
        return None
    return d.tb_fade_R.mean(), len(d), (d.tb_fade_R > 0).mean()


def fline(label, sub, null_fade):
    d = sub[sub.tb != "none"]
    if len(d) < 15:
        return f"  {label:30} n={len(d):4}  (мало)", False
    m = d.tb_fade_R.mean()
    p = null_p_ge(m, null_fade, len(d))
    pag = (d.tb_fade_R > 0).mean() * 100
    persym = d.groupby("symbol").tb_fade_R.mean()
    sym_pos = int((persym > 0).sum())
    bull = d[d.regime == 1].tb_fade_R.mean() if (d.regime == 1).any() else np.nan
    bear = d[d.regime == -1].tb_fade_R.mean() if (d.regime == -1).any() else np.nan
    up = d[d.dir == "UP"].tb_fade_R.mean() if (d.dir == "UP").any() else np.nan
    dn = d[d.dir == "DOWN"].tb_fade_R.mean() if (d.dir == "DOWN").any() else np.nan
    ok = (m > 0.05 and p < 0.05 and sym_pos >= 2 and bull > 0 and bear > 0 and up > 0 and dn > 0)
    return (f"  {label:30} n={len(d):4} fadeR={m:+.3f} p={p:.3f} sym+={sym_pos}/3 "
            f"bull={bull:+.2f} bear={bear:+.2f} UP={up:+.2f} DN={dn:+.2f}{'  <<ЗАКОН' if ok else ''}"), ok


def main():
    df = pd.read_csv(HERE / "law_records.csv")
    arche = df[df.is_null == 0].copy()
    null = df[df.is_null == 1]
    null_fade = null[null.tb != "none"].tb_fade_R.values
    pivn = df[df.is_null == 2]
    pivn_fade = pivn[pivn.tb != "none"].tb_fade_R.values

    out = []
    out.append("ЗАКОНЫ ТА v2 — 1h->D, с 2020. Метрика: triple-barrier FADE (инверсия континуации).")
    out.append(f"Архетипов {len(arche)} | Null {len(null)} | null fadeR={null_fade.mean():+.3f}")
    out.append("Закон: fadeR>0.05 И p<0.05 И >=2/3 символов+ И оба режима+ И UP&DOWN+.\n")

    laws = []

    def add(label, sub):
        ln, ok = fline(label, sub, null_fade)
        out.append(ln)
        if ok:
            laws.append(label)

    out.append("=== БАЗА: fade всех архетипов ===")
    add("ВСЕ архетипы", arche)

    out.append("\n=== По ТФ (1h -> 1d) ===")
    for tf in TFS:
        add(f"TF={tf}", arche[arche.tf == tf])

    out.append("\n=== Коррекция против/по импульсу ===")
    add("against=1 (флаг-ловушка)", arche[arche.against == 1])
    add("against=0 (по тренду)", arche[arche.against == 0])

    out.append("\n=== По типу коррекции ===")
    for k in sorted(arche.kind.unique()):
        add(f"kind={k}", arche[arche.kind == k])

    out.append("\n=== HTF-выравнивание ===")
    add("импульс ПО HTF", arche[arche.htf_aligned == 1])
    add("импульс ПРОТИВ HTF", arche[arche.htf_aligned == 0])

    out.append("\n=== По глубине ===")
    add("мелкая <50%", arche[arche.depth_pct < 50])
    add("средняя 50-80%", arche[(arche.depth_pct >= 50) & (arche.depth_pct < 80)])
    add("глубокая >=80%", arche[arche.depth_pct >= 80])

    out.append("\n=== По силе импульса ===")
    add("слабый <4ATR", arche[arche.imp_atr_mag < 4])
    add("сильный >=6ATR", arche[arche.imp_atr_mag >= 6])

    # год-стабильность базового fade
    out.append("\n=== Год-стабильность fade (ВСЕ) ===")
    d = arche[arche.tb != "none"]
    yr = d.groupby("year").tb_fade_R.mean()
    posyr = int((yr > 0).sum())
    out.append("  " + " ".join(f"{int(y)}:{v:+.2f}" for y, v in yr.items()) + f"   плюс-лет {posyr}/{len(yr)}")

    # against=1 год-стабильность (сильнейший кандидат)
    out.append("=== Год-стабильность fade (against=1) ===")
    d2 = arche[(arche.against == 1) & (arche.tb != "none")]
    yr2 = d2.groupby("year").tb_fade_R.mean()
    posyr2 = int((yr2 > 0).sum())
    out.append("  " + " ".join(f"{int(y)}:{v:+.2f}" for y, v in yr2.items()) + f"   плюс-лет {posyr2}/{len(yr2)}")

    # контекст: континуация (фольклор) measured-move
    out.append("\n=== Контекст: континуация measured-move (фольклор) ===")
    ent = arche[arche.outcome.isin(["win", "loss"])]
    out.append(f"  Воронка: {arche.outcome.value_counts().to_dict()}")
    if len(ent):
        out.append(f"  Вошло по импульсу: {len(ent)} WR={(ent.outcome=='win').mean()*100:.1f}% "
                   f"expR={ent.R.mean():+.3f} ΣR={ent.R.sum():+.1f}")

    # КОНТРОЛЬ: pivot-null (generic swing-continuation на любых пивотах)
    out.append("\n=== КОНТРОЛЬ pivot-null: паттерн или просто моментум после свинга? ===")
    pf_all = float(np.mean(pivn_fade)) if len(pivn_fade) else float("nan")
    out.append(f"  pivot-null fadeR (любой пивот, продолжение свинга) = {pf_all:+.3f}  n={len(pivn_fade)}")
    out.append(f"  ВСЕ архетипы fadeR = {arche[arche.tb!='none'].tb_fade_R.mean():+.3f}  "
               f"-> прирост паттерна = {arche[arche.tb!='none'].tb_fade_R.mean()-pf_all:+.3f}")
    for lab, sub in [("against=1", arche[arche.against == 1]),
                     ("FLAG", arche[arche.kind == "FLAG"]),
                     ("импульс ПРОТИВ HTF", arche[arche.htf_aligned == 0]),
                     ("against=0", arche[arche.against == 0])]:
        dd = sub[sub.tb != "none"]
        if len(dd):
            m = dd.tb_fade_R.mean()
            out.append(f"  {lab:20} fadeR={m:+.3f}  прирост над pivot-null={m-pf_all:+.3f}")
    out.append("  Интерпретация: прирост>0 = паттерн несёт сигнал СВЕРХ generic-моментума; "
               "≈0 = это просто продолжение свинга (моментум), паттерн не нужен.")

    out.append("\n=== СИНТЕЗ — ЗАКОНЫ ===")
    if laws:
        out.append(f"  Прошло гейты ({len(laws)}):")
        for x in laws:
            out.append(f"   • {x}")
    else:
        out.append("  Ни одна подвыборка не прошла ВСЕ гейты строго.")
    out.append("  Кавеат: arm=подтверждение пивота вносит «свежий момент»; чтобы отделить ЗАКОН-ПАТТЕРНА "
               "от тривиального пост-пивот-моментума, нужен pivot-arm null (следующий шаг).")

    rep = HERE / "laws_report.txt"
    rep.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))
    print(f"\n[validate] -> {rep.name}")


if __name__ == "__main__":
    main()
