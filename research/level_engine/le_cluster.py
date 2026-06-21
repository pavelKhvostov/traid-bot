"""le_cluster — RawZone[] -> Level[] (агломерация по цене, мульти-TF + ликвидность).

«Уровень» = скопление зон из разных TF (не одна OB-D/FVG-12h) — требование пользователя.
Слияние: пересечение (ov_frac>=0.5) ИЛИ близость mid<=tol; с КАПОМ ширины (анти-chaining).
Геометрия/конфлюэнс уровня причинны: считаются из members (все form_time<=T уже отобраны
в le_zones). Сила/доказательства — отдельный слой (le_belief). Здесь только структура.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np

from le_zones import RawZone, W_TF

MAGNET_KINDS = {"POC", "HVN", "VAH", "VAL"}
LIQ_KINDS = {"BSL", "SSL"}


@dataclass
class Level:
    lid: str
    bottom: float
    top: float
    center: float
    members: list[RawZone] = field(default_factory=list)
    side: str = "?"            # support|resistance (vs цена снапшота)
    up_neighbor: str | None = None
    down_neighbor: str | None = None

    # --- конфлюэнс-вектор (причинно из members) ---
    @property
    def n_zones(self) -> int:
        return len(self.members)

    @property
    def tfs(self) -> set:
        return {m.tf for m in self.members}

    @property
    def kinds(self) -> set:
        return {m.kind for m in self.members}

    @property
    def sum_w(self) -> float:
        return float(sum(m.w for m in self.members))

    @property
    def max_tf_w(self) -> float:
        return max((m.w for m in self.members), default=0.0)

    @property
    def has_magnet(self) -> bool:
        return any(m.kind in MAGNET_KINDS for m in self.members)

    @property
    def has_liquidity(self) -> bool:
        return any(m.kind in LIQ_KINDS for m in self.members)


def ov_frac(b1, t1, b2, t2) -> float:
    """Доля пересечения относительно меньшей ширины (etap_263 L126-127)."""
    inter = max(0.0, min(t1, t2) - max(b1, b2))
    return inter / max(1e-9, min(t1 - b1, t2 - b2))


def _center(members: list[RawZone]) -> float:
    sw = sum(m.w for m in members)
    return float(sum(m.w * m.mid for m in members) / sw) if sw > 0 else float(np.mean([m.mid for m in members]))


def cluster_density(raws: list[RawZone], price: float, atr1d: float,
                    min_sep_frac: float = 0.005, band_frac: float = 0.45,
                    max_width_frac: float = 0.012) -> list[Level]:
    """[v1] Уровни = ПИКИ взвешенной плотности зон. Минус (audit): сливает 8-10 TF в
    КАЖДУЮ полосу -> C/W сатурируют. Оставлено для сравнения; по умолчанию cluster()=HTF-якорь.

    Каждая зона голосует массой W_TF, размазанной по своим бинам. Плотность сглажена;
    локальные максимумы (на расстоянии >= min_sep) = уровни; полоса уровня = пока
    сглаж.плотность >= band_frac*пика, но не шире max_width_frac*price. Зоны в гэпах
    плотности (шум без конфлюэнции) в уровни не входят — это и есть «скопление зон».
    """
    if not raws:
        return []
    bw = max(40.0, 0.0007 * price)                       # бин ~0.07% цены
    los = min(z.bottom for z in raws); his = max(z.top for z in raws)
    nb = int((his - los) / bw) + 2
    dens = np.zeros(nb)
    for z in raws:
        b0 = max(0, int((z.bottom - los) / bw)); b1 = min(nb - 1, int((z.top - los) / bw))
        dens[b0:b1 + 1] += z.w / (b1 - b0 + 1)
    win = max(1, int((0.0015 * price) / bw))             # сглаживание ~0.15%
    sm = np.convolve(dens, np.ones(2 * win + 1) / (2 * win + 1), mode="same")
    centers = (np.arange(nb) + 0.5) * bw + los
    sep = max(1, int((min_sep_frac * price) / bw))
    max_w = max_width_frac * price
    # жадный отбор пиков по убыванию плотности с минимальной сепарацией
    taken = np.zeros(nb, bool); peaks = []
    for b in np.argsort(sm)[::-1]:
        if sm[b] <= 0:
            break
        if taken[max(0, b - sep):b + sep + 1].any():
            continue
        peaks.append(int(b)); taken[max(0, b - sep):b + sep + 1] = True
    levels: list[Level] = []
    for i, b in enumerate(sorted(peaks)):
        thr = band_frac * sm[b]
        lo = b
        while lo > 0 and sm[lo - 1] >= thr and (centers[b] - centers[lo - 1]) <= max_w / 2:
            lo -= 1
        hi = b
        while hi < nb - 1 and sm[hi + 1] >= thr and (centers[hi + 1] - centers[b]) <= max_w / 2:
            hi += 1
        band_lo = centers[lo] - bw / 2; band_hi = centers[hi] + bw / 2
        members = [z for z in raws if band_lo <= z.mid <= band_hi]
        if not members:
            continue
        levels.append(_mk_level_band(members, i, band_lo, band_hi))
    _assign_sides_and_neighbors(levels, price)
    return levels


def _mk_level_band(members: list[RawZone], i: int, band_lo: float, band_hi: float) -> Level:
    c = _center(members)
    return Level(lid=f"L{i:04d}@{c:.0f}", bottom=float(band_lo), top=float(band_hi),
                 center=c, members=list(members))


def _assign_sides_and_neighbors(levels: list[Level], price: float) -> None:
    levels.sort(key=lambda L: L.center)
    for i, L in enumerate(levels):
        L.side = "support" if L.center <= price else "resistance"
        L.down_neighbor = levels[i - 1].lid if i > 0 else None
        L.up_neighbor = levels[i + 1].lid if i + 1 < len(levels) else None


HTF_TFS = {"12h", "1d", "3d", "1w", "1M"}
LINE_KINDS = MAGNET_KINDS | LIQ_KINDS   # POC/HVN/VAH/VAL/BSL/SSL — якоря; LVN (вакуум) НЕ якорь


def cluster_htf(raws: list[RawZone], price: float, atr1d: float,
                max_levels: int = 60) -> list[Level]:
    """[v2/#8] Якоря = HTF-структура (>=12h OB/FVG/iFVG/RDRB) + одиночные линии
    (POC/HVN/VAH/VAL/BSL/SSL любого TF); LTF-зоны ПРИЦЕПЛЯЮТСЯ как подтверждение.

    Чинит сатурацию C/W density-кластеризации: уровень с 0 LTF-подтверждений отличается
    от уровня с 5; линии становятся своими уровнями -> флагуют has_magnet/has_liquidity.
    Причинно: работает на raws (form_time<=T уже отобраны в le_zones); level-интерфейс тот же.
    """
    if not raws:
        return []
    tol = max(0.0015 * price, 0.25 * (atr1d or 0.0))
    seeds = [z for z in raws if (z.tf in HTF_TFS and z.kind in ("OB", "FVG", "iFVG", "RDRB"))
             or z.kind in LINE_KINDS]
    if not seeds:
        return cluster_density(raws, price, atr1d)        # нет HTF/линий -> fallback на плотность
    anchors: list[list] = []                              # [bottom, top, [seed zones]]
    for z in sorted(seeds, key=lambda z: -z.w):           # HTF/сильнейшие первыми
        b, t = (z.bottom, z.top) if z.top > z.bottom else (z.mid - tol, z.mid + tol)
        hit = None
        for an in anchors:
            if ov_frac(an[0], an[1], b, t) >= 0.3 or abs((an[0] + an[1]) / 2 - (b + t) / 2) <= tol:
                hit = an; break
        if hit:
            hit[0] = min(hit[0], b); hit[1] = max(hit[1], t); hit[2].append(z)
        else:
            anchors.append([b, t, [z]])
    levels: list[Level] = []
    for i, (b, t, seedz) in enumerate(anchors):
        members = [z for z in raws if b <= z.mid <= t]
        levels.append(_mk_level_band(members or seedz, i, b, t))
    if len(levels) > max_levels:                          # кап: сильнейшие по сумме весов
        levels = sorted(levels, key=lambda L: -L.sum_w)[:max_levels]
    _assign_sides_and_neighbors(levels, price)
    return levels


# ИТОГ #8: HTF-якорная кластеризация ОТВЕРГНУТА — wide HTF OB-боксы chain-merge в
# мега-якоря (4 уровня, один на 10k зон). И глубже: C сатурирует не из-за кластеризации,
# а из-за РЕАЛЬНОСТИ ДАННЫХ — за 2.5г зоны навалены на КАЖДУЮ приценовую полосу по всем TF,
# любой узкий бэнд near price ловит все TF. Density-peak (v1) даёт чистые 38 уровней —
# оставляем его. Дифференциация идёт от реакции/пробоя/order-flow (v2.1), не от структуры C/W.
def cluster(raws: list[RawZone], price: float, atr1d: float) -> list[Level]:
    return cluster_density(raws, price, atr1d)
