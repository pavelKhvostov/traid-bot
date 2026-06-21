"""
Wave-based features для MoneyHands multi-TF.

Идея пользователя: MH — это волны. Сигнал смены тренда формируется как
резонансный накопительный эффект:
  - bw2 пересекает 0 (смена фазы волны) на нескольких TF
  - жёлтая скользящая MF (Money Flow) подтверждает (МФ относительно 0)
  - чем больше TF выстроены в одной фазе → сильнее сигнал

Здесь собираем явные wave-фичи на основе MH snapshot:
  - n_bw2_pos / n_bw2_neg: сколько TF имеют bw2 > 0 / < 0
  - n_mf_pos / n_mf_neg: то же для MF
  - n_aligned_bull: TF где bw2 > 0 AND mf > 0 (полный bull)
  - n_aligned_bear: TF где bw2 < 0 AND mf < 0 (полный bear)
  - resonance_score: -7..+7 = (n_aligned_bull - n_aligned_bear)
  - bw2_consensus: -7..+7 = (n_bw2_pos - n_bw2_neg)
  - mf_consensus: -7..+7 = (n_mf_pos - n_mf_neg)

Также "крутые" features для cascade:
  - htf_phase: bw2-фаза на 1d/3d (HTF reference)
  - ltf_phase: bw2-фаза на 1h/2h (LTF current)
  - htf_ltf_divergence: htf bull, ltf bear (или наоборот) — конец тренда

Плюс per-TF дискретизация:
  - {tf}_bw2_phase: 'pos' / 'neg' / 'zero'
  - {tf}_mf_phase: 'pos' / 'neg'
"""
from __future__ import annotations

import pandas as pd

from multi_tf_mh import PIVOT_TFS

HTF_TFS = ("3d", "1d", "12h")
LTF_TFS = ("4h", "2h", "1h")


def _sign(v) -> int:
    """+1 если положительное, -1 если отрицательное, 0 если NaN/0."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 0
    if v != v:  # NaN check
        return 0
    if v > 0:
        return 1
    if v < 0:
        return -1
    return 0


def add_wave_features(ds: pd.DataFrame) -> pd.DataFrame:
    """Дописать к ds wave-фичи."""
    out = ds.copy()

    # per-TF phase знаки
    bw2_signs = {}
    mf_signs = {}
    for tf in PIVOT_TFS:
        bw2_signs[tf] = out[f"mh_{tf}_bw2"].apply(_sign)
        mf_signs[tf] = out[f"mh_{tf}_mf"].apply(_sign)
        out[f"{tf}_bw2_phase"] = bw2_signs[tf].map({1: "pos", -1: "neg", 0: "zero"})
        out[f"{tf}_mf_phase"] = mf_signs[tf].map({1: "pos", -1: "neg", 0: "zero"})

    # consensus метрики
    bw2_df = pd.DataFrame(bw2_signs)
    mf_df = pd.DataFrame(mf_signs)
    out["n_bw2_pos"] = (bw2_df > 0).sum(axis=1)
    out["n_bw2_neg"] = (bw2_df < 0).sum(axis=1)
    out["n_mf_pos"] = (mf_df > 0).sum(axis=1)
    out["n_mf_neg"] = (mf_df < 0).sum(axis=1)
    out["bw2_consensus"] = out["n_bw2_pos"] - out["n_bw2_neg"]    # -7..+7
    out["mf_consensus"] = out["n_mf_pos"] - out["n_mf_neg"]

    # aligned (bw2 и mf на одной стороне)
    aligned_bull = ((bw2_df > 0) & (mf_df > 0)).sum(axis=1)
    aligned_bear = ((bw2_df < 0) & (mf_df < 0)).sum(axis=1)
    out["n_aligned_bull"] = aligned_bull
    out["n_aligned_bear"] = aligned_bear
    out["resonance_score"] = aligned_bull - aligned_bear  # -7..+7

    # HTF vs LTF phases
    htf_bw2 = pd.DataFrame({tf: bw2_signs[tf] for tf in HTF_TFS}).sum(axis=1)  # -3..+3
    ltf_bw2 = pd.DataFrame({tf: bw2_signs[tf] for tf in LTF_TFS}).sum(axis=1)
    out["htf_bw2_score"] = htf_bw2
    out["ltf_bw2_score"] = ltf_bw2
    # divergence: HTF и LTF разные стороны
    out["htf_ltf_divergence"] = ((htf_bw2 * ltf_bw2) < 0).astype(int)

    return out


def rule_based_signal(row: pd.Series, strong_threshold: int = 5) -> str:
    """
    Простое rule-based направление по wave-фичам:
      - strong_long: aligned_bull >= strong_threshold AND mf_consensus > 0
      - strong_short: aligned_bear >= strong_threshold AND mf_consensus < 0
      - weak_long / weak_short / neutral в зависимости от consensus
    """
    nb = int(row["n_aligned_bull"])
    ns = int(row["n_aligned_bear"])
    bw2c = int(row["bw2_consensus"])
    mfc = int(row["mf_consensus"])
    if nb >= strong_threshold and mfc > 0:
        return "strong_long"
    if ns >= strong_threshold and mfc < 0:
        return "strong_short"
    if bw2c > 0 and mfc > 0:
        return "weak_long"
    if bw2c < 0 and mfc < 0:
        return "weak_short"
    return "neutral"


def evaluate_rule_signal(ds: pd.DataFrame, label_col: str = "up_12h") -> pd.DataFrame:
    """Для каждого rule-signal посчитать accuracy на label_col."""
    ds = ds.copy()
    ds[label_col] = ds[label_col].astype(int)
    ds["signal"] = ds.apply(rule_based_signal, axis=1)
    g = ds.groupby("signal").agg(
        n=(label_col, "size"),
        up_rate=(label_col, "mean"),
    ).reset_index()
    return g
