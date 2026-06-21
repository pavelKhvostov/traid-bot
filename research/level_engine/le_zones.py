"""le_zones — причинные адаптеры канон-детекторов -> RawZone (мульти-TF).

Часть движка силы уровней (дизайн: wf_ade4de60). Единственный источник зон для движка.
КАНОН (не реимплементируем — etap_263 это делал, отвергнуто):
  OB   <- strategies.strategy_1_1_1.detect_ob_pair
  FVG  <- strategies.strategy_1_1_1.detect_fvg
  iFVG <- etap_93.find_inverse_fvgs (detect_all_fvgs + first_touch_idx)
  RDRB <- strategies.rdrb.detect_zones (структурный Zone)
  POC/VAH/VAL/HVN/LVN <- etap_205.vp
  BSL/SSL (untested liquidity) <- etap_205.untested_swings

ПРИЧИННОСТЬ (lookahead-register A/B/C/D): зона наблюдаема только на ЗАКРЫТИИ формирующего
бара. form_time = open формирующего бара + длительность TF (ВЕРХНЯЯ оценка — никогда не
занижаем, иначе утечка). VP/ликвидность вычисляются по окну <= T и наблюдаемы в T
(form_time=T). Вызывающий ОБЯЗАН передавать df1h, усечённый по T -> ни одна зона не может
прочитать будущее (срез детектора физически не достаёт строк > T).

TFs: 1,2,4,6,8,12h, 1d, 3d, 1w, 1M (ресемпл из 1h-базы, origin=epoch, label/closed=left).
"""
from __future__ import annotations
import sys
from dataclasses import dataclass, field
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "research" / "daily_engine", ROOT / "research" / "elements_study"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from strategies.strategy_1_1_1 import detect_ob_pair, detect_fvg  # noqa: E402
from strategies.rdrb import detect_zones as rdrb_detect            # noqa: E402
import etap_93_inverse_fvg as IF                                   # noqa: E402
import etap_205_multi_horizon_zones as VP                          # noqa: E402

TF_LIST = ["1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w", "1M"]
RULE = {"1h": "1h", "2h": "2h", "4h": "4h", "6h": "6h", "8h": "8h", "12h": "12h",
        "1d": "1D", "3d": "3D", "1w": "W-MON", "1M": "MS"}
# верхняя оценка длительности бара (для form_time; M=31d — НИКОГДА не занижаем)
TF_TD = {"1h": "1h", "2h": "2h", "4h": "4h", "6h": "6h", "8h": "8h", "12h": "12h",
         "1d": "1D", "3d": "3D", "1w": "7D", "1M": "31D"}
# вес TF для приоритета силы (старше TF -> весомее), дизайн-спек
W_TF = {"1h": 1.0, "2h": 1.3, "4h": 1.8, "6h": 2.1, "8h": 2.4, "12h": 3.0,
        "1d": 4.0, "3d": 5.5, "1w": 7.0, "1M": 9.0}
RDRB_TF_OK = {"1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d"}   # pd.Timedelta(tf) парсится


@dataclass
class RawZone:
    kind: str            # OB|FVG|iFVG|RDRB|POC|VAH|VAL|HVN|LVN|BSL|SSL
    tf: str
    direction: str       # LONG(demand)|SHORT(supply)|NEUTRAL(VP/liquidity)
    bottom: float
    top: float           # для линий (POC/BSL...) bottom==top
    form_time: pd.Timestamp   # причинный якорь наблюдаемости (закрытие формир. бара)
    meta: dict = field(default_factory=dict)

    @property
    def mid(self) -> float:
        return (self.bottom + self.top) / 2

    @property
    def w(self) -> float:
        return W_TF.get(self.tf, 1.0)


def resample_tf(df1h: pd.DataFrame, tf: str, T: pd.Timestamp) -> pd.DataFrame:
    """Ресемпл 1h-базы в TF, оставляем ТОЛЬКО бары, ЗАКРЫВШИЕСЯ к T (close<=T)."""
    if df1h.index.tz is None:
        df1h = df1h.tz_localize("UTC")
    base = df1h[df1h.index <= T]
    if base.empty:
        return base
    d = base.resample(RULE[tf], origin="epoch", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
    if d.empty:
        return d
    td = pd.Timedelta(TF_TD[tf])
    # close = open + td (верхняя оценка); держим только закрытые к T
    return d[d.index + td <= T]


def _sig_asof(atr_d, t):
    if atr_d is None:
        return float("nan")
    try:
        v = atr_d.asof(t)
        return float(v) if (v == v and v > 0) else float("nan")
    except Exception:
        return float("nan")


def _ohlc_zones(d: pd.DataFrame, tf: str, atr_d=None) -> list[RawZone]:
    """OB / FVG / iFVG / RDRB на одном TF-фрейме d (уже усечён по T).

    meta['disp'] = сила импульса-ПРОИСХОЖДЕНИЯ зоны в σ as-of формации (ORIGIN-фактор
    LE-STR v2): OB=|close-open| импульсной свечи, FVG/iFVG=высота гэпа, RDRB=диапазон
    якоря. Считаем здесь (1 раз при детекции) -> belief остаётся дешёвым.
    """
    out: list[RawZone] = []
    if len(d) < 3:
        return out
    td = pd.Timedelta(TF_TD[tf])
    idx = d.index
    O = d["open"].values; C = d["close"].values
    for i in range(1, len(d)):
        ob = detect_ob_pair(d, i)
        if ob is None:
            continue
        s = _sig_asof(atr_d, idx[i] + td)
        disp = (abs(C[i] - O[i]) / s) if s > 0 else 0.0
        out.append(RawZone("OB", tf, ob.direction, float(ob.bottom), float(ob.top),
                           idx[i] + td, {"disp": float(disp)}))
    for i in range(2, len(d)):
        fv = detect_fvg(d, i)
        if fv is None:
            continue
        gap = float(fv.top - fv.bottom)
        s = _sig_asof(atr_d, idx[i] + td)
        out.append(RawZone("FVG", tf, fv.direction, float(fv.bottom), float(fv.top),
                           idx[i] + td, {"gap": gap, "disp": (gap / s) if s > 0 else 0.0}))
    try:
        for A, B, touch in IF.find_inverse_fvgs(d):
            s = _sig_asof(atr_d, B.c2_time + td)
            h = float(B.top - B.bottom)
            out.append(RawZone("iFVG", tf, B.direction, float(B.bottom), float(B.top),
                               B.c2_time + td, {"inverted_from": A.direction,
                                                "disp": (h / s) if s > 0 else 0.0}))
    except Exception:
        pass
    if tf in RDRB_TF_OK:
        try:
            for z in rdrb_detect(d, "BTCUSDT", RULE[tf] if tf != "1d" else "1D"):
                ft = z.trigger_time
                if ft.tz is None:
                    ft = ft.tz_localize("UTC")
                m = dict(z.meta)
                ah, al = m.get("anchor_high"), m.get("anchor_low")
                s = _sig_asof(atr_d, ft)
                m["disp"] = (abs(float(ah) - float(al)) / s) if (ah is not None and al is not None and s > 0) else 0.0
                out.append(RawZone("RDRB", tf, z.direction, float(z.zone_bottom),
                                   float(z.zone_top), ft, m))
        except Exception:
            pass
    return out


def _vp_liq_zones(d: pd.DataFrame, tf: str, T: pd.Timestamp, price: float,
                  vp_lookback: int = 180) -> list[RawZone]:
    """POC/VAH/VAL/HVN/LVN + untested BSL/SSL по окну<=T; наблюдаемы в T (form_time=T)."""
    out: list[RawZone] = []
    if len(d) < 20:
        return out
    w = slice(max(0, len(d) - vp_lookback), len(d))
    H = d["high"].values[w]; L = d["low"].values[w]; Vv = d["volume"].values[w]
    try:
        poc, vah, val, hvn, lvn = VP.vp(H, L, Vv)
    except Exception:
        return out
    for kind, lvl in (("POC", poc), ("VAH", vah), ("VAL", val)):
        out.append(RawZone(kind, tf, "NEUTRAL", float(lvl), float(lvl), T, {}))
    for x in hvn[:6]:
        out.append(RawZone("HVN", tf, "NEUTRAL", float(x), float(x), T, {}))
    for x in lvn[:5]:
        out.append(RawZone("LVN", tf, "NEUTRAL", float(x), float(x), T, {}))
    # untested swing liquidity (резерв ликвидности) — единственный фактор с механизмом
    try:
        bsl, ssl = VP.untested_swings(d["high"].values, d["low"].values, price, band=0.5, N=2)
        for x in bsl:
            out.append(RawZone("BSL", tf, "NEUTRAL", float(x), float(x), T, {}))
        for x in ssl:
            out.append(RawZone("SSL", tf, "NEUTRAL", float(x), float(x), T, {}))
    except Exception:
        pass
    return out


def build_raw_zones(df1h: pd.DataFrame, T: pd.Timestamp, price: float | None = None,
                    tfs: list[str] | None = None, window_usd: float = 15000.0,
                    with_vp: bool = True, atr_d=None) -> list[RawZone]:
    """Все RawZone, наблюдаемые к моменту T, в пределах +-window_usd от price.

    ПРИЧИННО: df1h усекается по T внутри resample_tf -> ни одна зона form_time>T.
    Прокс-гейт window_usd применяется как ОТБОР ПОКАЗА (для снапшота); для валидации
    отключается (window_usd=inf), чтобы не вносить survivorship (lookahead-register #9).
    """
    if df1h.index.tz is None:
        df1h = df1h.tz_localize("UTC")
    if T.tz is None:
        T = T.tz_localize("UTC")
    tfs = tfs or TF_LIST
    base = df1h[df1h.index <= T]
    if base.empty:
        return []
    if price is None:
        price = float(base["close"].iloc[-1])
    zones: list[RawZone] = []
    for tf in tfs:
        d = resample_tf(df1h, tf, T)
        if d.empty:
            continue
        zones += _ohlc_zones(d, tf, atr_d=atr_d)
        if with_vp:
            zones += _vp_liq_zones(d, tf, T, price)
    # причинный инвариант (страховка): отбрасываем всё с form_time>T
    zones = [z for z in zones if pd.Timestamp(z.form_time) <= T]
    # прокс-гейт показа
    if np.isfinite(window_usd):
        zones = [z for z in zones if abs(z.mid - price) <= window_usd]
    return zones
