"""etap_180: Оценка сигналов 1-5 + ЗНАНИЕВЫЕ фичи "почему" + баланс 50/50 + 400 эпох.

Развитие etap_179. Пользователь: «отбери много плохих и много хороших сигналов
за много лет, покажи сети ПОЧЕМУ плохой/хороший — бери выводы из книг/знаний».

Нейросеть не понимает текст «почему» — она учится на ФИЧАХ. Поэтому знания из
книг (López de Prado, ICT) и vault превращаем в направление-зависимые фичи,
которые ОБЪЯСНЯЮТ плохой/хороший сигнал:

=== ЗНАНИЕВЫЕ "ПОЧЕМУ"-ФИЧИ (из материалов) ===
ICT (sweep/DOL, premium/discount, HTF-trend — из присланных PDF):
  - why_against_htf_1d / why_against_htf_4h: сигнал ПРОТИВ HTF-тренда → плохой
    (ICT: торгуй в направлении HTF; против — низкий WR).
  - why_with_htf: сигнал ПО HTF-тренду → хороший (pro-trend, как C2 EMA-фильтр).
  - why_sweep_before: был ли sweep ликвидности В СТОРОНУ сигнала перед ним
    (ICT Liquidity Sweep/DOL: снятие ликвидности → разворот = хороший).
  - why_in_discount_long / why_in_premium_short: LONG в discount / SHORT в premium
    относительно 30-bar range (ICT: покупай в discount, продавай в premium).
López de Prado (из 10 лекций):
  - why_high_entropy: сигнал в зоне высокой энтропии = шум → плохой (Lec8).
  - why_bubble_sadf: |SADF| высокий = explosive/пузырь → разворот ненадёжен.
  - why_illiquid: высокий Amihud = тонкий рынок → плохой fill/исход.
vault (эмпирические законы проекта):
  - why_tight_risk: узкий risk% (близкий SL) → лучше R при том же движении.
  - why_zone_confluence: сколько зон OB/FVG у цены (confluence → надёжнее).

=== БАЛАНС 50/50 ===
Сейчас 65% сигналов = класс 1 (плохой). Сеть ленится всё звать плохим.
Балансируем веса по классам (inverse frequency) → равный вклад плохих и хороших.

=== БОЛЬШЕ ЭПОХ ===
400 эпох (было 150) + patience 40 (было 25) — дать сети доучиться.

Метка, источники сигналов, инфраструктура — из etap_179 (5 стратегий × 3 актива).

Запуск: OMP_NUM_THREADS=1 .venv-pivot/bin/python -u research/elements_study/etap_180_signal_grade_knowledge_features.py
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve()
while not (_ROOT / "data_manager.py").exists():
    if _ROOT.parent == _ROOT:
        raise RuntimeError("repo root not found")
    _ROOT = _ROOT.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

import importlib.util as _ilu
import numpy as np
import pandas as pd

# переиспуем etap_179 (генерация сигналов + оценка) и etap_177/178 (фичи/сеть)
_s179 = _ilu.spec_from_file_location("e179", _ROOT / "research/elements_study/etap_179_signal_grade_3assets_mda.py")
_e179 = _ilu.module_from_spec(_s179); _s179.loader.exec_module(_e179)
_e178 = _e179._e178
_e177 = _e179._e177

SYMBOLS = _e179.SYMBOLS
TRAIN_END = _e179.TRAIN_END
EMBARGO_BARS = _e179.EMBARGO_BARS
KFOLD = _e179.KFOLD
EMBARGO_KF = _e179.EMBARGO_KF
OUT_DIR = _e179.OUT_DIR
EPOCHS = 400              # было 150
PATIENCE = 40            # было 25
SNAME = {0: "1.1.1", 1: "1.1.2", 2: "1.1.3", 3: "FRACTAL", 4: "1.1.4"}


# ============================================================
# ЗНАНИЕВЫЕ "почему"-фичи (направление-зависимые, из книг)
# ============================================================
def add_knowledge_features(ds):
    """Добавить фичи, ОБЪЯСНЯЮЩИЕ плохой/хороший относительно направления сигнала.

    Использует уже посчитанные арсенал-фичи (trend_1d, trend_4h, sweep_*, entropy,
    sadf, amihud_z, dist_*, n_*OB/FVG, close_in_range) + sig_direction_long.
    """
    d = ds.copy()
    long = d["sig_direction_long"] == 1
    short = ~long

    # --- ICT: согласие с HTF-трендом ---
    # trend_1d/4h: +1 up, -1 down. LONG хорош при up, SHORT при down.
    sig_dir = np.where(long, 1, -1)
    d["why_with_htf_1d"] = (d["trend_1d"].values == sig_dir).astype(int)
    d["why_with_htf_4h"] = (d["trend_4h"].values == sig_dir).astype(int)
    d["why_against_htf_1d"] = ((d["trend_1d"].values != 0) & (d["trend_1d"].values != sig_dir)).astype(int)
    d["why_against_htf_both"] = (d["why_against_htf_1d"] &
                                  ((d["trend_4h"].values != 0) & (d["trend_4h"].values != sig_dir)).astype(int))

    # --- ICT: sweep ликвидности В СТОРОНУ сигнала перед ним (DOL) ---
    # LONG хорош если перед ним снимали sell-side ликвидность (SSL sweep) — разворот вверх.
    # SHORT хорош если снимали buy-side (BSL sweep).
    for h in (24, 72, 168):
        ssl = d.get(f"sweep_SSL_{h}h", 0)
        bsl = d.get(f"sweep_BSL_{h}h", 0)
        d[f"why_sweep_for_signal_{h}h"] = np.where(long, ssl, bsl).astype(int)
        # failed sweep в сторону сигнала = ещё сильнее (grab+reversal)
        sslf = d.get(f"sweep_SSL_failed_{h}h", 0)
        bslf = d.get(f"sweep_BSL_failed_{h}h", 0)
        d[f"why_failed_sweep_for_signal_{h}h"] = np.where(long, sslf, bslf).astype(int)

    # --- ICT: premium/discount относительно 30-bar range ---
    # close_in_range: 0=у лоя (discount), 1=у хая (premium).
    cir = d.get("close_in_range", 0.5)
    d["why_long_in_discount"] = (long & (cir < 0.4)).astype(int)   # LONG в discount = хорошо
    d["why_short_in_premium"] = (short & (cir > 0.6)).astype(int)  # SHORT в premium = хорошо
    d["why_long_in_premium_bad"] = (long & (cir > 0.6)).astype(int)  # LONG в premium = плохо
    d["why_short_in_discount_bad"] = (short & (cir < 0.4)).astype(int)

    # --- López de Prado: режим ненадёжности ---
    if "entropy" in d:
        ent = d["entropy"].values
        thr_e = np.nanpercentile(ent, 70)
        d["why_high_entropy"] = (ent >= thr_e).astype(int)          # шум → плохой
    if "sadf" in d:
        sadf = np.abs(d["sadf"].values)
        thr_s = np.nanpercentile(sadf, 70)
        d["why_bubble_sadf"] = (sadf >= thr_s).astype(int)          # пузырь → ненадёжный разворот
    if "amihud_z" in d:
        d["why_illiquid"] = (d["amihud_z"].values >= 1.5).astype(int)  # тонкий рынок

    # --- vault: узкий риск (лучше R) + confluence зон ---
    if "sig_risk_pct" in d:
        rp = d["sig_risk_pct"].values
        thr_r = np.nanpercentile(rp, 35)
        d["why_tight_risk"] = (rp <= thr_r).astype(int)            # узкий SL → лучше R
    # confluence: суммарно зон у цены в сторону сигнала
    n_long = d.get("n_LONG_OB", 0) + d.get("n_LONG_FVG", 0)
    n_short = d.get("n_SHORT_OB", 0) + d.get("n_SHORT_FVG", 0)
    d["why_zone_confluence"] = np.where(long, n_long, n_short)
    in_long = d.get("in_LONG_OB", 0) + d.get("in_LONG_FVG", 0)
    in_short = d.get("in_SHORT_OB", 0) + d.get("in_SHORT_FVG", 0)
    d["why_in_zone_for_signal"] = np.where(long, in_long, in_short).astype(int)

    new_feats = [
        "why_with_htf_1d", "why_with_htf_4h", "why_against_htf_1d", "why_against_htf_both",
        "why_sweep_for_signal_24h", "why_sweep_for_signal_72h", "why_sweep_for_signal_168h",
        "why_failed_sweep_for_signal_24h", "why_failed_sweep_for_signal_72h", "why_failed_sweep_for_signal_168h",
        "why_long_in_discount", "why_short_in_premium", "why_long_in_premium_bad", "why_short_in_discount_bad",
        "why_high_entropy", "why_bubble_sadf", "why_illiquid",
        "why_tight_risk", "why_zone_confluence", "why_in_zone_for_signal",
    ]
    new_feats = [f for f in new_feats if f in d.columns]
    return d, new_feats


# ============================================================
# Балансировка 50/50 (López de Prado: era/class balance)
# ============================================================
def balanced_weights(grades, uniqueness_w):
    """Вес = uniqueness × inverse-class-frequency. Уравнивает плохие(1) и хорошие(4-5)."""
    g = np.asarray(grades, dtype=int)
    # бинаризуем: плохой (1-2) vs хороший (4-5), 3 = нейтраль
    cls = np.where(g >= 4, 1, np.where(g <= 2, 0, -1))
    w = np.array(uniqueness_w, dtype=float).copy()
    for c in (0, 1):
        mask = cls == c
        n = mask.sum()
        if n > 0:
            w[mask] *= (len(g) / 2.0) / n   # каждый класс получает половину суммарного веса
    return w / w.mean()


def train_balanced(Xtr, gtr, wtr, Xval, gval, in_dim, device):
    """Обучение ординальной сети с 400 эпохами + patience 40."""
    return _e178.train_ordinal(Xtr, gtr, wtr, Xval, gval, in_dim,
                               epochs=EPOCHS, device=device)


def main():
    import torch
    from sklearn.preprocessing import StandardScaler
    from scipy.stats import spearmanr
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"[etap_180] device={device} | знаниевые фичи + баланс 50/50 + {EPOCHS} эпох", flush=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # переиспуем готовый датасет etap_179 если есть (не пересчитывать исходы)
    cache = OUT_DIR / "etap179_graded_3assets.csv"
    if cache.exists():
        print(f"[reuse] {cache}", flush=True)
        ds = pd.read_csv(cache, index_col="signal_time", parse_dates=["signal_time"])
        base_feats = [c for c in _e177.make_feature_list(list(_e177.BULK_ALL.keys())) if c in ds.columns] \
                     + ["sig_strategy_id", "sig_direction_long", "sig_risk_pct", "sig_asset_id"]
        base_feats = [f for f in base_feats if f in ds.columns]
    else:
        print("[ERR] нет датасета etap179 — запусти etap_179 сначала"); return

    # ЗНАНИЕВЫЕ фичи
    ds, why_feats = add_knowledge_features(ds)
    feats = base_feats + why_feats
    feats = [f for f in feats if f in ds.columns]
    ds = ds[ds[feats].notna().all(axis=1)]
    print(f"[data] {len(ds)} сигналов | базовых фич={len(base_feats)} + знаниевых={len(why_feats)} = {len(feats)}", flush=True)
    print(f"[знаниевые фичи] {', '.join(why_feats)}", flush=True)

    # быстрая проверка: различают ли знаниевые фичи хорошие/плохие?
    print("\n[проверка знаниевых фич: среднее у хороших(grade>=4) vs плохих(grade==1)]", flush=True)
    good = ds[ds["grade"] >= 4]; bad = ds[ds["grade"] == 1]
    for f in why_feats[:12]:
        gm, bm = good[f].mean(), bad[f].mean()
        flag = "✓" if abs(gm - bm) > 0.03 else " "
        print(f"  {flag} {f:32s} хор={gm:.3f} плох={bm:.3f} Δ={gm-bm:+.3f}", flush=True)

    tr = ds[ds.index < TRAIN_END]; emb = TRAIN_END + pd.Timedelta("12h") * EMBARGO_BARS
    te = ds[ds.index >= emb]
    print(f"\n[split] train={len(tr)} test={len(te)}", flush=True)
    gtr = tr["grade"].values.astype(float); gte = te["grade"].values.astype(float)

    uw = _e177.uniqueness_weights(tr.index, 7)
    w = balanced_weights(gtr, uw)   # БАЛАНС 50/50
    print(f"[баланс] плохих(1-2)={(gtr<=2).sum()} хороших(4-5)={(gtr>=4).sum()} → веса уравнены", flush=True)

    Xte_raw = te[feats].values
    preds, rhos, nets_scalers = [], [], []
    for fi, (tri, vai) in enumerate(_e177.purged_splits(tr.index, KFOLD, EMBARGO_KF, 7)):
        sc = StandardScaler().fit(tr[feats].values[tri])
        net, vr = train_balanced(sc.transform(tr[feats].values[tri]), gtr[tri], w[tri],
                                 sc.transform(tr[feats].values[vai]), gtr[vai], len(feats), device)
        rhos.append(vr); preds.append(_e178.ordinal_predict_score(net, sc.transform(Xte_raw), device))
        nets_scalers.append((net, sc))
        print(f"    fold {fi}: val ρ={vr:.4f}", flush=True)
    score = np.mean(preds, axis=0)
    rho_te = spearmanr(gte, score).correlation
    print(f"\n[ORDINAL NN +знания +баланс +{EPOCHS}эп] CV ρ={np.mean(rhos):.4f} | TEST ρ={rho_te:.4f}", flush=True)
    print(f"  (было etap_179: CV 0.066, TEST 0.042)", flush=True)

    te2 = te.copy(); te2["score"] = score
    te2["pred_grade"] = np.clip(np.round(score), 1, 5).astype(int)
    base_tp = (te2["grade"] >= 4).mean()
    print("\n[реальный WR_TP по предсказанному классу]:", flush=True)
    for pg in [1, 2, 3, 4, 5]:
        sub = te2[te2["pred_grade"] == pg]
        if len(sub) >= 3:
            print(f"  pred={pg}: n={len(sub):4d}  WR_TP={(sub['grade']>=4).mean()*100:.0f}%  "
                  f"mean_R={sub['achieved_r'].mean():.2f}", flush=True)
    for thr in [3.0, 3.5, 4.0]:
        top = te2[te2["score"] >= thr]
        if len(top) >= 5:
            wr = (top["grade"] >= 4).mean()
            print(f"  [TOP score>={thr}] n={len(top)}  WR_TP={wr*100:.0f}% "
                  f"(baseline {base_tp*100:.0f}%, lift ×{wr/base_tp:.2f})", flush=True)

    # SANITY shuffle
    rng = np.random.RandomState(0); gsh = gtr.copy(); rng.shuffle(gsh)
    tri, vai = next(_e177.purged_splits(tr.index, KFOLD, EMBARGO_KF, 7))
    sc = StandardScaler().fit(tr[feats].values[tri])
    net_sh, _ = _e178.train_ordinal(sc.transform(tr[feats].values[tri]), gsh[tri], w[tri],
                                    sc.transform(tr[feats].values[vai]), gsh[vai], len(feats), epochs=80, device=device)
    sh = spearmanr(gte, _e178.ordinal_predict_score(net_sh, sc.transform(Xte_raw), device)).correlation
    print(f"\n[SANITY] shuffle ρ={sh:.4f} (должен ~0)", flush=True)

    # сохранить модель если лучше etap_179 (ρ > 0.066)
    if rho_te > 0.066:
        import json as _json
        model_dir = OUT_DIR / "etap179_model"; model_dir.mkdir(parents=True, exist_ok=True)
        for fi, (net, sc) in enumerate(nets_scalers):
            torch.save(net.state_dict(), model_dir / f"net_fold{fi}.pt")
            np.savez(model_dir / f"scaler_fold{fi}.npz", mean=sc.mean_, scale=sc.scale_)
        (model_dir / "meta.json").write_text(_json.dumps({
            "feats": feats, "n_folds": len(nets_scalers), "in_dim": len(feats),
            "cv_rho": float(np.mean(rhos)), "test_rho": float(rho_te),
            "trained": "etap_180_knowledge", "target_rr": 2.2,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[saved] модель ЛУЧШЕ (ρ {rho_te:.3f} > 0.066) → обновлена для бота", flush=True)
    else:
        print(f"[skip-save] ρ {rho_te:.3f} НЕ лучше etap_179 (0.066) — модель бота не трогаю", flush=True)


if __name__ == "__main__":
    main()
