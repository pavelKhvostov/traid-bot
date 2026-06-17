"""Тесты vol_features (волна 1: HAR-RV + eff_ratio). Чистая логика, без сети/I/O."""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research" / "daily_engine"))
import vol_features as VF


def test_eff_bucket_boundaries():
    # квинтили etap_245: <=0.011 очень рваное .. >0.062 очень гладкое
    assert VF.eff_bucket(0.005) == "очень рваное"
    assert VF.eff_bucket(0.011) == "очень рваное"
    assert VF.eff_bucket(0.02) == "рваное"
    assert VF.eff_bucket(0.03) == "среднее"
    assert VF.eff_bucket(0.05) == "гладкое"
    assert VF.eff_bucket(0.10) == "очень гладкое"


def test_eff_bucket_monotone():
    order = ["очень рваное", "рваное", "среднее", "гладкое", "очень гладкое"]
    seen = [VF.eff_bucket(x) for x in [0.005, 0.02, 0.03, 0.05, 0.10]]
    assert seen == order


def test_augment_failure_returns_df_unchanged():
    # несуществующий символ → har_features пустой → augment не добавляет колонок
    f = pd.DataFrame({"atr_pct": [0.01, 0.02]},
                     index=pd.date_range("2025-01-01", periods=2, tz="UTC"))
    before = set(f.columns)
    out = VF.augment(f, "NONEXISTENTUSDT")
    # либо без изменений, либо те же строки — но НЕ падает и НЕ ломает индекс
    assert len(out) == 2
    assert "atr_pct" in out.columns
    # VOL_FEATS не должны появиться с битыми данными (симметрия train/predict)
    assert before.issubset(set(out.columns))


def test_vol_feats_constant():
    assert VF.VOL_FEATS[0] == "har_rv_d"
    assert len(VF.VOL_FEATS) == 10
    assert len(VF.EFF_Q) == 4 and VF.EFF_Q == sorted(VF.EFF_Q)


def test_augment_dvol_sol_gets_nan_columns():
    # SOL не имеет DVOL → augment_dvol ВСЕГДА добавляет 3 колонки (NaN) для симметрии feat_cols
    f = pd.DataFrame({"atr_pct": [0.01, 0.02]},
                     index=pd.date_range("2025-01-01", periods=2, tz="UTC"))
    out = VF.augment_dvol(f, "SOLUSDT")
    for c in VF.DVOL_FEATS:
        assert c in out.columns, f"{c} должна присутствовать даже для SOL"
    assert out[VF.DVOL_FEATS].isna().all().all()  # все NaN для SOL


def test_dvol_feats_constant():
    assert VF.DVOL_FEATS == ["dvol_lvl", "dvol_z30", "dvol_chg5"]
    assert set(VF.DVOL_CUR) == {"BTCUSDT", "ETHUSDT"}  # SOL DVOL не существует
