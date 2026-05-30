"""Volume Profile + POC / VAH / VAL.

Vertical histogram объёма по price-buckets. Объём бара распределяется
равномерно по бакетам, попадающим в его [low, high] диапазон.

POC = price-bucket с максимальным cumulative volume.
Value Area = диапазон bucket'ов вокруг POC, содержащий 70% объёма
(VAH = top, VAL = bottom). Expansion алгоритмом from-POC-outward.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VolumeProfile:
    poc: float           # center of bucket с макс volume
    val: float           # value area low
    vah: float           # value area high
    bucket_size: float
    buckets: tuple[tuple[float, float], ...]   # (price_center, volume) per bucket — для отрисовки
    total_volume: float


def volume_profile(
    bars: list[tuple[float, float, float, float, float]],
    bucket_size: float,
    value_area_pct: float = 0.70,
) -> VolumeProfile | None:
    """bars = [(o, h, l, c, v), ...]. bucket_size = ширина одного ценового бакета."""
    if not bars or bucket_size <= 0:
        return None

    # Глобальный диапазон
    glob_low = min(b[2] for b in bars)
    glob_high = max(b[1] for b in bars)
    if glob_high <= glob_low:
        return None

    n_buckets = max(1, int((glob_high - glob_low) / bucket_size) + 1)
    bucket_vol = [0.0] * n_buckets

    for o, h, l, c, v in bars:
        if h <= l or v <= 0:
            continue
        # Индексы первого и последнего бакета, которые свеча покрывает
        lo_idx = max(0, int((l - glob_low) / bucket_size))
        hi_idx = min(n_buckets - 1, int((h - glob_low) / bucket_size))
        span = hi_idx - lo_idx + 1
        per = v / span
        for i in range(lo_idx, hi_idx + 1):
            bucket_vol[i] += per

    # POC
    poc_idx = max(range(n_buckets), key=lambda i: bucket_vol[i])
    total = sum(bucket_vol)
    poc_center = glob_low + (poc_idx + 0.5) * bucket_size

    # Value Area — expansion from POC
    target = total * value_area_pct
    in_va = [False] * n_buckets
    in_va[poc_idx] = True
    running = bucket_vol[poc_idx]
    lo, hi = poc_idx, poc_idx
    while running < target:
        lo_candidate = lo - 1 if lo > 0 else None
        hi_candidate = hi + 1 if hi < n_buckets - 1 else None
        vol_lo = bucket_vol[lo_candidate] if lo_candidate is not None else -1
        vol_hi = bucket_vol[hi_candidate] if hi_candidate is not None else -1
        if vol_lo < 0 and vol_hi < 0:
            break
        if vol_hi >= vol_lo:
            in_va[hi_candidate] = True
            hi = hi_candidate
            running += vol_hi
        else:
            in_va[lo_candidate] = True
            lo = lo_candidate
            running += vol_lo

    val = glob_low + lo * bucket_size
    vah = glob_low + (hi + 1) * bucket_size

    buckets = tuple((glob_low + (i + 0.5) * bucket_size, bucket_vol[i]) for i in range(n_buckets))

    return VolumeProfile(poc=poc_center, val=val, vah=vah,
                         bucket_size=bucket_size, buckets=buckets, total_volume=total)
