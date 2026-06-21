"""le_belief — LE-STR v2: МНОГОФАКТОРНАЯ описательная сила уровня (прозрачно, причинно).

Переписано после критики «сила = просто счёт отбоев vs пробоев» (тонко И теоретически
инвертировано: затёртая зона СЛАБЕЕ, а не сильнее). Дизайн: wf_81bf28b3 + адверс-проверка
«дифференциация vs dwell». Каждый фактор — отдельное прозрачное слагаемое (аргумент-строка).

Факторы (∈[0,1]) и вес (макс. баллы из 10):
  A ORIGIN displacement (импульс происхождения, max в σ as-of формации) ×2.4  [чистый]
  C HTF-доминанта (max-TF/9 + capped diversity; бьёт raw-count)            ×2.4  [чистый]
  V объёмный узел (POC/HVN; LVN→0+вакуум-гейт)                              ×1.0
  O локация (премиум/дисконт + дистанция от value + круглые)               ×0.8
  W ширина (inverted-U, пик ~1σ)                                           ×1.0
  L непротестир. ликвидность (BSL/SSL), ×gate свежести                     ×1.0
  Q качество РЕАКЦИИ (лучший REJECT, MAX не сумма!), ×gate                  ×1.4
  B СВЕЖЕСТЬ: касания ДЕКРЕМЕНТИРУЮТ (gate на L+Q) — фикс инверсии          ×(≤1)
  K ущерб от ПРОБОЯ (max BREAK, decay) — вычитает                          −2.0
sumм положительных = 10. strength_index = clip(core/10,0,1); сила = 1+9·index.
predicts_hold=False: ОПИСАНИЕ структуры, НЕ прогноз (hold/break = монетка, AUC 0.53).
"""
from __future__ import annotations
import numpy as np
import pandas as pd

from le_cluster import MAGNET_KINDS, LIQ_KINDS

TAU_DAYS = 45.0
W_TF_MAX = 9.0


def _sig(atr_d, t):
    if atr_d is None:
        return float("nan")
    try:
        v = atr_d.asof(t)
        return float(v) if (v == v and v > 0) else float("nan")
    except Exception:
        return float("nan")


def _squash(x, k=1.5):
    return x / (x + k) if x > 0 else 0.0


def belief(members, interactions, T, neighbor_broken=False, df1h=None, atr_d=None,
           price=None, level=None, daily_hl=None, flow=None, tau_days=TAU_DAYS) -> dict | None:
    """Причинная многофакторная сила уровня на момент T (чистая функция от
    members[form_time<=T] и interactions[t_resolved<=T])."""
    if T.tz is None:
        T = T.tz_localize("UTC")
    ms = [m for m in members if pd.Timestamp(m.form_time) <= T]
    if not ms:
        return None
    ints = sorted([I for I in interactions if pd.Timestamp(I.t_resolved) <= T],
                  key=lambda x: x.t_resolved)
    tfs = {m.tf for m in ms}; kinds = {m.kind for m in ms}
    max_tf_w = max((m.w for m in ms), default=0.0)
    sumw = float(sum(m.w for m in ms))
    if level is not None:
        bottom, top, center = level.bottom, level.top, level.center
    else:
        bottom = min(m.bottom for m in ms); top = max(m.top for m in ms)
        center = (sum(m.w * m.mid for m in ms) / sumw) if sumw > 0 else float(np.mean([m.mid for m in ms]))
    has_mag = any(m.kind in MAGNET_KINDS for m in ms)
    has_liq = any(m.kind in LIQ_KINDS for m in ms)
    if price is None and df1h is not None:
        try:
            price = float(df1h["close"].asof(T))
        except Exception:
            price = None
    pref = price or center
    sigma_T = _sig(atr_d, T)
    if not (sigma_T > 0):
        sigma_T = 0.01 * pref

    # A — ORIGIN displacement (max member, precomputed meta['disp'] в σ as-of формации)
    A = _squash(max((float(m.meta.get("disp", 0.0)) for m in ms), default=0.0), 1.5)

    # C — HTF dominance + capped diversity (бьёт raw-count: 666×1h≤0.21, 1×1w=0.78)
    diversity = (len(tfs) - 1) + (len(kinds) - 1)
    C = min(1.0, max_tf_w / W_TF_MAX + 0.10 * (1 - np.exp(-max(diversity, 0) / 3.0)))

    # V — volume node (POC/HVN); чистый LVN -> 0 + вакуум-гейт для локации
    has_poc = "POC" in kinds; n_hvn = sum(1 for m in ms if m.kind == "HVN")
    is_pure_lvn = ("LVN" in kinds) and not (has_poc or n_hvn > 0)
    V = 0.0 if is_pure_lvn else float(np.clip(0.6 * has_poc + 0.4 * min(n_hvn, 2) / 2.0, 0, 1))
    vacuum = 1.0 if is_pure_lvn else 0.0

    # L — untested liquidity (BSL/SSL уже untested by construction)
    n_liq = sum(1 for m in ms if m.kind in ("BSL", "SSL"))
    L = min(n_liq, 2) / 2.0

    # Q (MAX REJECT/FLIP) + K (MAX BREAK), РАЗДЕЛЁННЫЕ ПО СТОРОНЕ подхода (audit #5):
    # why['side']=='above' -> тест ПОДДЕРЖКИ (цена пришла сверху); 'below' -> СОПРОТИВЛЕНИЯ.
    # Свежесть реакции медленная (TAU_Q=270д, история уровня ~годы; 45д всё крушило).
    role = "support" if center <= pref else "resistance"
    want = "above" if role == "support" else "below"
    TAU_Q = 270.0
    bestQ = bestQ_opp = 0.0; Kd = Kd_opp = 0.0
    rej = brk = flp = 0; sig_sum = 0.0; last_rej_age = None; best_rej_I = None
    for I in ints:
        age = (T - pd.Timestamp(I.t_resolved)).total_seconds() / 86400.0
        recq = float(np.exp(-age / TAU_Q))
        side = I.why.get("side")
        on_role = (side == want) or (side is None)
        if I.cls in ("REJECT", "FLIP"):
            if I.cls == "REJECT":
                rej += 1; sig_sum += I.m; last_rej_age = age
            else:
                flp += 1
            q = I.m * recq
            if on_role:
                if q > bestQ: bestQ = q; best_rej_I = I
            else: bestQ_opp = max(bestQ_opp, q)
        elif I.cls == "BREAK":
            brk += 1; k = I.m * recq
            if on_role: Kd = max(Kd, k)
            else: Kd_opp = max(Kd_opp, k)
    # ORDER-FLOW absorption (audit #6) — ОПИСАТЕЛЬНО (signed delta, не dwell): сколько
    # объёма поглотила лучшая on-role реакция и какой знак потока. НЕ в score (ждёт null).
    absorp_effort = 0.0; absorp_delta = 0.0
    if flow is not None and best_rej_I is not None:
        try:
            w = flow.loc[pd.Timestamp(best_rej_I.t_touch):pd.Timestamp(best_rej_I.t_resolved)]
            if len(w):
                vol = float(w["volume"].sum()); dl = float(w["delta"].sum())
                trail = flow["volume"].loc[:pd.Timestamp(best_rej_I.t_touch)].tail(720)
                med = float(trail.median()) if len(trail) >= 50 else 0.0
                absorp_effort = (vol / len(w)) / med if med > 0 else 0.0   # bar-vol / трейлинг-медиана
                absorp_delta = dl / max(vol, 1e-9)                          # signed imbalance [-1,1]
        except Exception:
            pass
    Q = float(np.clip(bestQ / 2.0, 0, 1)); Q_opp = float(np.clip(bestQ_opp / 2.0, 0, 1))
    K = float(np.clip(Kd / 2.0, 0, 1)); K_opp = float(np.clip(Kd_opp / 2.0, 0, 1))
    touches = rej + brk + flp
    B = float(np.exp(-touches / 6.0))            # СВЕЖЕСТЬ: касания ДЕКРЕМЕНТИРУЮТ (un-saturated)
    fresh_gate = 0.5 + 0.5 * B                   # затёртые уровни держат 50% пола ликвидности

    # O — location (премиум/дисконт + дистанция от value + круглые)
    O = 0.0
    try:
        d1 = None
        if daily_hl is not None:
            d1 = daily_hl[daily_hl.index <= T].tail(60)
        elif df1h is not None:
            d1 = df1h[df1h.index <= T].resample("1D").agg({"high": "max", "low": "min"}).dropna().tail(60)
        if d1 is not None and len(d1) >= 10:
            lo = float(d1["low"].min()); hi = float(d1["high"].max())
            pos = (center - lo) / max(1e-9, hi - lo)
            side = "support" if center <= pref else "resistance"
            aligned = (side == "support" and pos < 0.5) or (side == "resistance" and pos > 0.5)
            poc = next((m.mid for m in ms if m.kind == "POC"), None)
            dist_val = abs(center - poc) / sigma_T if poc is not None else 0.0
            grid = 10 ** np.floor(np.log10(max(center, 1))) / 2
            rnd = 1.0 - min(1.0, abs(center - round(center / grid) * grid) / (0.05 * center))
            O = float(np.clip(0.5 * aligned + 0.3 * np.clip(dist_val / 3, 0, 1) + 0.2 * max(0, rnd), 0, 1))
            O *= (1 - 0.5 * vacuum)
    except Exception:
        O = 0.0

    # W — СОГЛАСИЕ участников (audit #1): прежний W мерил ширину кластер-полосы (мёртв,
    # std 0.029, упёрт в cap). Теперь = насколько тесно совпадают mid'ы зон-членов:
    # 1d+12h+4h на одной цене (плотно) >> размазаны по полосе. Геометрия, не dwell.
    mids = [m.mid for m in ms]
    spread = (max(mids) - min(mids)) / sigma_T if (sigma_T > 0 and len(mids) > 1) else 0.0
    Wf = float(np.exp(-(spread / 0.6) ** 2))

    core = 2.4 * A + 2.4 * C + 1.0 * V + 0.8 * O + 1.0 * Wf
    core += 1.0 * L * fresh_gate          # ликвидность ГАСНЕТ с касаниями (потреблена)
    core += 1.4 * Q                       # реакция: своя свежесть (TAU_Q), без двойного штрафа
    core += -2.0 * K
    if neighbor_broken:
        core -= 0.3
    raw01 = float(np.clip(core / 10.0, 0, 1))
    s10 = int(round(1 + 9 * raw01))

    state = "active"
    if ints:
        state = {"BREAK": "broken", "FLIP": "flipped", "REJECT": "active"}.get(ints[-1].cls, "active")
    conf = float(min(12.0, touches + np.log1p(sumw)))

    return dict(s10=s10, raw01=raw01, conf=conf, core=float(core),
                A=A, C=C, V=V, O=O, W=Wf, L=L, Q=Q, B=B, K=K, fresh_gate=fresh_gate,
                Q_opp=Q_opp, K_opp=K_opp, role=role, spread=spread,
                absorp_effort=absorp_effort, absorp_delta=absorp_delta,
                touches=touches, rejects=rej, breaks=brk, flips=flp,
                avg_rej_m=(sig_sum / rej if rej else 0.0), last_rej_age_d=last_rej_age,
                disp_sigma=max((float(m.meta.get("disp", 0.0)) for m in ms), default=0.0),
                max_tf_w=max_tf_w, tfs=sorted(tfs), kinds=sorted(kinds),
                sumw=sumw, has_magnet=has_mag, has_liquidity=has_liq, state=state,
                n_used=len(ints), neighbor_broken=neighbor_broken)


def strength10(bel: dict) -> tuple[int, float, float]:
    return bel["s10"], bel["raw01"], bel["conf"]


def explain(level, bel: dict) -> list[str]:
    """Аргументы: каждая строка = вклад одного фактора в балл (макс-вес показан)."""
    a = []
    a.append(f"+ origin-импульс: {bel['disp_sigma']:.1f}σ → A {bel['A']:.2f}×2.4 = {2.4*bel['A']:.2f}")
    a.append(f"+ HTF-доминанта: max-TF w{bel['max_tf_w']:.0f} + {len(bel['tfs'])}TF/{len(bel['kinds'])}видов "
             f"→ C {bel['C']:.2f}×2.4 = {2.4*bel['C']:.2f}")
    if bel["V"] > 0:
        a.append(f"+ объём-узел (POC/HVN) → V {bel['V']:.2f}×1.0 = {bel['V']:.2f}")
    elif "LVN" in bel["kinds"]:
        a.append("· LVN-вакуум (узел проходной) → V 0 (gate локации)")
    if bel["O"] > 0:
        a.append(f"+ локация (прем/диск+value+круглые) → O {bel['O']:.2f}×0.8 = {0.8*bel['O']:.2f}")
    a.append(f"+ согласие TF: mid-spread {bel['spread']:.2f}σ (тесно=сильнее) → W {bel['W']:.2f}×1.0 = {bel['W']:.2f}")
    if bel["L"] > 0:
        a.append(f"+ непротест. ликвидность ×свежесть{bel['fresh_gate']:.2f} → L {bel['L']:.2f} = {bel['L']*bel['fresh_gate']:.2f}")
    if bel["Q"] > 0:
        age = bel["last_rej_age_d"]
        opp = f" (с др.стороны {bel['Q_opp']:.2f})" if bel["Q_opp"] > 0 else ""
        a.append(f"+ реакция как {bel['role']} (MAX, не сумма) {bel['avg_rej_m']:.1f}σ "
                 f"{'' if age is None else str(int(age))+'д'} → Q {bel['Q']:.2f}×1.4 = {1.4*bel['Q']:.2f}{opp}")
    a.append(f"− свежесть: {bel['touches']} касаний → gate {bel['fresh_gate']:.2f} на ликвидность"
             + ("  [касания СНИЖАЮТ, не повышают]" if bel["touches"] >= 3 else ""))
    if bel["K"] > 0:
        opp = f" (с др.стороны {bel['K_opp']:.2f})" if bel["K_opp"] > 0 else ""
        a.append(f"− пробой как {bel['role']}: ущерб K {bel['K']:.2f} → −{2.0*bel['K']:.2f}{opp}")
    if bel.get("absorp_effort", 0) > 0:
        d = bel["absorp_delta"]
        sgn = "поглощены продажи" if d < -0.1 else ("поглощены покупки" if d > 0.1 else "нейтрально")
        a.append(f"· поток на реакции: {bel['absorp_effort']:.1f}× объёма, дельта {d:+.2f} ({sgn}) "
                 f"[описательно, не в баллах]")
    if bel["neighbor_broken"]:
        a.append("− соседний уровень пробит → −0.3")
    a.append(f"  = индекс структуры {bel['raw01']:.2f} → сила {bel['s10']}/10  "
             f"(состояние {bel['state']}, описательно — НЕ прогноз)")
    return a
