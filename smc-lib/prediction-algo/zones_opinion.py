"""
Каноническое экспертное заключение по зонам интереса.

Берёт ранжированный список зон из predict_zones (cli.py / zone_snapshot
+ LookupModel) и формирует структурированное текстовое заключение:

  1. Карта зон от верха до низа (около цены)
  2. Confluence-кластеры (зоны в радиусе ~0.2% друг от друга)
  3. Базовый прогноз = top-1 ближайшая зона by (P_D × близость)
  4. Развилка после базового касания: цепочка магнитов
  5. Сценарии A/B + invalidation уровень

Триггер: «экспертное заключение по зонам интереса» → run_zones_opinion(...)
или CLI: python3 zones_opinion.py

Формат вывода стабильный — voice-friendly text, можно зачитывать вслух.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from data import load_btc_1m
from model import LookupModel
from zones import ALL_TYPES, ActiveZone, precompute_zone_events, snapshot_from_events


SMC_LIB = Path(os.environ.get("SMCLIB_ROOT", str(Path.home() / "smc-lib")))

CLUSTER_RADIUS_PCT = 0.20    # зоны в радиусе 0.2% сливаются в кластер
STRONG_P_THRESHOLD = 0.80    # порог "сильной" зоны/кластера
HIGH_CONFIDENCE_P = 0.90     # очень высокая уверенность
NEAR_DIST_PCT = 0.50         # "рядом с ценой" = ≤ 0.5%
MIN_TARGET_DIST_PCT = 0.30   # минимальная дистанция, чтобы кластер считался "значимой целью".
                             # Зоны ближе — отображаются на карте, но не выбираются как base_target / FIRST-TARGET
# Селектор A′: используем P_hit_D ("будет ли зона задета за день") вместо P_first.
# Причина: P_first маржинальная — обнуляется на distance >0.5% (модель почти не видит first-touch далеко).
# P_hit_D работает симметрично на любой дистанции и взаимно сопоставим между сторонами.
# Метрика P_first остаётся в выводе как информация, но не используется для выбора target.


@dataclass
class ZoneCluster:
    """Слитая группа зон близких по уровню (confluence)."""
    side: str                   # 'above' / 'below'
    lo: float                   # min(zone.lo) по кластеру
    hi: float                   # max(zone.hi) по кластеру
    representative_level: float # репрезентативный уровень (центр)
    zones: list[ActiveZone]
    max_p_12h: float
    max_p_d: float
    mean_p_d: float
    max_p_first: float          # P(first_hit_above|below) — best zone в кластере как «первая в своей стороне»
    sum_p_first: float          # сумма P_first по зонам в кластере (≈ P что кластер целиком первый)
    distance_pct: float         # дистанция от текущей цены до ближайшей границы
    types: list[str] = field(default_factory=list)
    tfs: list[str] = field(default_factory=list)


def _cluster_zones(
    zones_with_preds: pd.DataFrame,
    price_now: float,
    radius_pct: float = CLUSTER_RADIUS_PCT,
) -> list[ZoneCluster]:
    """
    Слить зоны одной стороны в кластеры по близости (radius_pct% от цены).
    Возвращает список ZoneCluster отсортированный по distance_pct (ближайшие первые).
    """
    out: list[ZoneCluster] = []
    radius_abs = price_now * radius_pct / 100

    for side in ("above", "below"):
        side_df = zones_with_preds[zones_with_preds["side"] == side].copy()
        if side_df.empty:
            continue
        # Сортируем по уровню (для above — от ближайших снизу вверх; для below — сверху вниз)
        if side == "above":
            side_df = side_df.sort_values("lo")
            level_col = "lo"
        else:
            side_df = side_df.sort_values("hi", ascending=False)
            level_col = "hi"

        # Greedy clustering
        clusters_raw: list[list[dict]] = []
        for _, row in side_df.iterrows():
            placed = False
            for cl in clusters_raw:
                cl_level = cl[0][level_col]
                if abs(row[level_col] - cl_level) <= radius_abs:
                    cl.append(row.to_dict())
                    placed = True
                    break
            if not placed:
                clusters_raw.append([row.to_dict()])

        # Конвертим в ZoneCluster
        for cl in clusters_raw:
            lo = min(r["lo"] for r in cl)
            hi = max(r["hi"] for r in cl)
            zones_obj = [_row_to_active_zone(r) for r in cl]
            mean_p_d = float(sum(r["P_hit_D"] for r in cl) / len(cl))
            max_p_d = max(r["P_hit_D"] for r in cl)
            max_p_12h = max(r["P_hit_12h"] for r in cl)
            # P(first_hit) — берём по соответствующей стороне
            first_col = "P_first_hit_above" if side == "above" else "P_first_hit_below"
            p_firsts = [float(r.get(first_col, 0.0) or 0.0) for r in cl]
            max_p_first = max(p_firsts) if p_firsts else 0.0
            sum_p_first = sum(p_firsts)
            if side == "above":
                dist_pct = (lo - price_now) / price_now * 100
            else:
                dist_pct = (price_now - hi) / price_now * 100
            out.append(ZoneCluster(
                side=side,
                lo=lo, hi=hi,
                representative_level=(lo + hi) / 2,
                zones=zones_obj,
                max_p_12h=max_p_12h, max_p_d=max_p_d, mean_p_d=mean_p_d,
                max_p_first=max_p_first, sum_p_first=sum_p_first,
                distance_pct=dist_pct,
                types=sorted({r["type"] for r in cl}),
                tfs=sorted({r["tf"] for r in cl}),
            ))
    out.sort(key=lambda c: c.distance_pct)
    return out


def _selection_score(cluster: "ZoneCluster") -> float:
    """Селектор A′: P_hit_D — сопоставимо на любой дистанции, не теряет сигнал на дальних зонах."""
    return cluster.max_p_d


def _row_to_active_zone(row: dict) -> ActiveZone:
    return ActiveZone(
        tf=row["tf"], type=row["type"], direction=row["direction"],
        lo=row["lo"], hi=row["hi"],
        level=row.get("level") if pd.notna(row.get("level")) else None,
        born_ts=row.get("born_ts"),
        age_bars=int(row.get("age_bars", 0)),
        side=row["side"], distance_pct=row["distance_pct"],
        mitigation_model=row.get("mitigation_model", "?"),
    )


def _fetch_latest_1m() -> None:
    fetch = SMC_LIB / "scripts" / "fetch_btc_1m_missing.py"
    if not fetch.exists():
        return
    subprocess.run([sys.executable, str(fetch)], capture_output=True, text=True, timeout=120)


@dataclass
class ZonesOpinion:
    cut_off_utc: pd.Timestamp
    cut_off_msk: pd.Timestamp
    price_now: float
    n_zones: int
    clusters_above: list[ZoneCluster]
    clusters_below: list[ZoneCluster]
    base_target: ZoneCluster | None       # ближайшая зона базового прогноза
    chain_after_base: list[ZoneCluster]   # цепочка магнитов в том же направлении
    counter_target: ZoneCluster | None    # ближайшая на противоположной стороне (= invalidation)
    text: str


def run_zones_opinion(
    training_dataset: Path = Path.home() / "Desktop" / "btc_full.csv",
    train_days: int = 365,
    tfs: tuple[str, ...] = ("1h", "4h", "12h", "1d"),
    fetch: bool = True,
    cluster_radius_pct: float = CLUSTER_RADIUS_PCT,
    min_target_dist_pct: float = MIN_TARGET_DIST_PCT,
) -> ZonesOpinion:
    """Сформировать каноническое заключение по зонам интереса в текущий момент."""
    if fetch:
        _fetch_latest_1m()

    ds_train = pd.read_csv(training_dataset)
    ds_train["cut_off_ts"] = pd.to_datetime(ds_train["cut_off_ts"], utc=True)
    now = pd.Timestamp.now(tz="UTC")
    train_lo = now - pd.Timedelta(days=train_days)
    train_data = ds_train[ds_train["cut_off_ts"] >= train_lo]
    model = LookupModel.fit(train_data, min_count=50, alpha=1.0)

    df_1m = load_btc_1m(start=now - pd.Timedelta(days=120))
    cut_off = df_1m.index[-1] + pd.Timedelta(minutes=1)
    cut_msk = cut_off + pd.Timedelta(hours=3)
    price_now = float(df_1m["close"].iloc[-1])

    events, resampled = precompute_zone_events(df_1m, tfs=tfs, types=ALL_TYPES)
    zones = snapshot_from_events(events, resampled, df_1m, cut_off)

    rows = []
    for z in zones:
        rows.append({
            "tf": z.tf, "type": z.type, "direction": z.direction,
            "lo": z.lo, "hi": z.hi, "level": z.level if z.level is not None else float("nan"),
            "width": z.hi - z.lo,
            "side": z.side, "distance_pct": z.distance_pct, "age_bars": z.age_bars,
            "mitigation_model": z.mitigation_model, "born_ts": z.born_ts,
            "hit_12h": False, "hit_D": False, "time_to_hit_minutes": -1,
            "first_hit_horizon": "none", "first_hit_above": False, "first_hit_below": False,
        })
    snap_df = pd.DataFrame(rows)
    preds = model.predict(snap_df)
    snap_df["P_hit_12h"] = preds["P_hit_12h"].to_numpy()
    snap_df["P_hit_D"] = preds["P_hit_D"].to_numpy()
    if "P_first_hit_above" in preds.columns:
        snap_df["P_first_hit_above"] = preds["P_first_hit_above"].to_numpy()
        snap_df["P_first_hit_below"] = preds["P_first_hit_below"].to_numpy()
    else:
        snap_df["P_first_hit_above"] = 0.0
        snap_df["P_first_hit_below"] = 0.0

    clusters = _cluster_zones(snap_df, price_now, cluster_radius_pct)
    clusters_above = [c for c in clusters if c.side == "above"]
    clusters_below = [c for c in clusters if c.side == "below"]

    # Кандидаты на target — только кластеры с дистанцией ≥ min_target_dist_pct.
    # Ближние зоны остаются на карте, но не выбираются как base_target / FIRST-TARGET.
    significant = [c for c in clusters if c.distance_pct >= min_target_dist_pct]

    # Базовый прогноз: селектор A′ — P_hit_D, сопоставимо между сторонами на любой дистанции
    base_target = max(significant, key=_selection_score) if significant else None

    # Цепочка после базового касания: следующие 1-2 значимых кластера в том же направлении
    chain_after_base: list[ZoneCluster] = []
    counter_target: ZoneCluster | None = None
    if base_target is not None:
        same_side = clusters_above if base_target.side == "above" else clusters_below
        same_side_significant = [c for c in same_side if c.distance_pct >= min_target_dist_pct]
        idx = same_side_significant.index(base_target)
        chain_after_base = same_side_significant[idx + 1: idx + 3]
        other_side = clusters_below if base_target.side == "above" else clusters_above
        if other_side:
            counter_target = other_side[0]

    text = _format_opinion_text(cut_msk, price_now, len(zones),
                                  clusters_above, clusters_below,
                                  base_target, chain_after_base, counter_target,
                                  min_target_dist_pct=min_target_dist_pct)

    return ZonesOpinion(
        cut_off_utc=cut_off, cut_off_msk=cut_msk, price_now=price_now,
        n_zones=len(zones),
        clusters_above=clusters_above, clusters_below=clusters_below,
        base_target=base_target, chain_after_base=chain_after_base,
        counter_target=counter_target,
        text=text,
    )


def _format_cluster(c: ZoneCluster, price_now: float) -> str:
    types_str = "/".join(c.types)
    tfs_str = "/".join(c.tfs)
    delta = c.lo - price_now if c.side == "above" else price_now - c.hi
    pf = f", P_first={c.max_p_first:.2f}" if c.max_p_first > 0 else ""
    if abs(c.lo - c.hi) < 1.0:
        return (f"{c.representative_level:.0f}   (P_D={c.max_p_d:.2f}{pf}, "
                f"{len(c.zones)} зон: {types_str} на {tfs_str}, "
                f"дист {delta:+.0f}$/{c.distance_pct:.2f}%)")
    return (f"[{c.lo:.0f}, {c.hi:.0f}]   (P_D={c.max_p_d:.2f}{pf}, "
            f"mean={c.mean_p_d:.2f}, {len(c.zones)} зон: {types_str} на {tfs_str}, "
            f"дист {delta:+.0f}$/{c.distance_pct:.2f}%)")


def _format_opinion_text(
    cut_msk: pd.Timestamp, price_now: float, n_zones: int,
    clusters_above: list[ZoneCluster], clusters_below: list[ZoneCluster],
    base_target: ZoneCluster | None, chain: list[ZoneCluster],
    counter_target: ZoneCluster | None,
    min_target_dist_pct: float = MIN_TARGET_DIST_PCT,
) -> str:
    lines: list[str] = []
    lines.append("=" * 70)
    lines.append(f"  ЭКСПЕРТНОЕ ЗАКЛЮЧЕНИЕ ПО ЗОНАМ ИНТЕРЕСА")
    lines.append("=" * 70)
    lines.append(f"  BTC = {price_now:,.0f}   |   {cut_msk.strftime('%d-%m-%Y %H:%M')} MSK")
    lines.append(f"  Активных зон: {n_zones}")
    lines.append("")

    # Карта зон
    lines.append("КАРТА КЛАСТЕРОВ (от верха до низа)")
    lines.append("-" * 70)
    for c in clusters_above[:6][::-1]:  # сверху-вниз → разворачиваем для отображения
        marker = "🔥" if c.max_p_d >= HIGH_CONFIDENCE_P else ("⭐" if c.max_p_d >= STRONG_P_THRESHOLD else "  ")
        lines.append(f"  {marker} ↑ {_format_cluster(c, price_now)}")
    lines.append(f"  ─── ЦЕНА {price_now:,.0f} ───")
    for c in clusters_below[:6]:
        marker = "🔥" if c.max_p_d >= HIGH_CONFIDENCE_P else ("⭐" if c.max_p_d >= STRONG_P_THRESHOLD else "  ")
        lines.append(f"  {marker} ↓ {_format_cluster(c, price_now)}")
    lines.append("")

    # Первые таргеты на каждой стороне — селектор A′ (P_hit_D, сопоставимая метрика)
    sig_above = [c for c in clusters_above if c.distance_pct >= min_target_dist_pct]
    sig_below = [c for c in clusters_below if c.distance_pct >= min_target_dist_pct]
    top_above = max(sig_above, key=_selection_score) if sig_above else None
    top_below = max(sig_below, key=_selection_score) if sig_below else None

    # Информация о пропущенных близких зонах (transit zones)
    skipped_above = [c for c in clusters_above if c.distance_pct < min_target_dist_pct]
    skipped_below = [c for c in clusters_below if c.distance_pct < min_target_dist_pct]

    lines.append(
        f"FIRST-TARGET ПО СТОРОНАМ (Модель A′: селектор по P_hit_D, только зоны ≥ {min_target_dist_pct:.2f}%)"
    )
    lines.append("-" * 70)
    if top_above is not None:
        lines.append(f"  ↑ UP first:    {_format_cluster(top_above, price_now)}")
    else:
        lines.append(f"  ↑ UP first:    нет значимых зон выше ≥ {min_target_dist_pct:.2f}%")
    if top_below is not None:
        lines.append(f"  ↓ DOWN first:  {_format_cluster(top_below, price_now)}")
    else:
        lines.append(f"  ↓ DOWN first:  нет значимых зон ниже ≥ {min_target_dist_pct:.2f}%")
    if skipped_above or skipped_below:
        skipped_labels = []
        for c in skipped_above:
            skipped_labels.append(f"↑[{c.lo:.0f},{c.hi:.0f}] ({c.distance_pct:.2f}%)")
        for c in skipped_below:
            skipped_labels.append(f"↓[{c.lo:.0f},{c.hi:.0f}] ({c.distance_pct:.2f}%)")
        lines.append(f"  (пропущены как незначительные: {', '.join(skipped_labels)})")
    lines.append("")

    # Базовый прогноз (выбираем сторону с большим P_first среди значимых)
    lines.append(f"БАЗОВЫЙ ПРОГНОЗ (модель выбирает направление, target ≥ {min_target_dist_pct:.2f}%)")
    lines.append("-" * 70)
    if base_target is None:
        lines.append(f"  Нет значимых зон (≥ {min_target_dist_pct:.2f}%) — нейтральная позиция.")
    else:
        arrow = "ВНИЗ" if base_target.side == "below" else "ВВЕРХ"
        own_score = _selection_score(base_target)
        other = (top_below if base_target.side == "above" else top_above)
        other_score = _selection_score(other) if other is not None else 0.0
        margin = own_score - other_score
        lines.append(f"  Направление: {arrow}")
        lines.append(f"  Цель: {_format_cluster(base_target, price_now)}")
        lines.append(f"  P_hit_D выбранной = {own_score:.2f}")
        lines.append(f"  P_hit_D противоп. = {other_score:.2f}")
        lines.append(f"  Margin = {margin:+.2f}  ({'уверенный' if abs(margin) >= 0.15 else 'небольшой' if abs(margin) >= 0.05 else 'предельно слабый — стороны почти равны'})")
        # Дополнительный «race condition» сигнал — P_first ближайших зон (информативен только вблизи)
        nearest_above = clusters_above[0] if clusters_above else None
        nearest_below = clusters_below[0] if clusters_below else None
        race_lines = []
        if nearest_above and nearest_above.max_p_first > 0:
            race_lines.append(f"↑ {nearest_above.distance_pct:.2f}% P_first={nearest_above.max_p_first:.2f}")
        if nearest_below and nearest_below.max_p_first > 0:
            race_lines.append(f"↓ {nearest_below.distance_pct:.2f}% P_first={nearest_below.max_p_first:.2f}")
        if race_lines:
            lines.append(f"  Race на ближайших: {' vs '.join(race_lines)}")
        if base_target.distance_pct <= 0.05:
            lines.append(f"  Дистанция микро ({base_target.distance_pct:.2f}%) — фактически у цены.")
        elif base_target.distance_pct <= NEAR_DIST_PCT:
            lines.append(f"  Близко к цене — короткое движение в ближайшие часы.")
    lines.append("")

    # Цепочка магнитов
    if chain:
        lines.append("ЦЕПОЧКА МАГНИТОВ (если базовая зона пробивается в ту же сторону)")
        lines.append("-" * 70)
        for c in chain:
            lines.append(f"  → {_format_cluster(c, price_now)}")
        lines.append("")

    # Сценарии
    lines.append("СЦЕНАРИИ")
    lines.append("-" * 70)
    if base_target is not None and counter_target is not None:
        base_dir = "вниз" if base_target.side == "below" else "вверх"
        cnt_dir = "вверх" if counter_target.side == "above" else "вниз"
        lines.append(f"  A (базовый): касание {base_target.representative_level:.0f} ({base_dir})")
        if chain:
            chain_top = chain[-1]
            lines.append(f"     → продолжение до {chain_top.representative_level:.0f}")
        lines.append(f"  B (отскок):  если базовая зона удерживает, разворот {cnt_dir} к {counter_target.representative_level:.0f}")
        lines.append(f"     P_D на отскок-цели = {counter_target.max_p_d:.2f}")
    lines.append("")

    # Invalidation
    if base_target is not None:
        lines.append("INVALIDATION")
        lines.append("-" * 70)
        if base_target.side == "below":
            inv_level = clusters_above[0].representative_level if clusters_above else None
            if inv_level:
                lines.append(f"  Сценарий A отменяется при пробое {inv_level:.0f} вверх.")
        else:
            inv_level = clusters_below[0].representative_level if clusters_below else None
            if inv_level:
                lines.append(f"  Сценарий A отменяется при пробое {inv_level:.0f} вниз.")
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--train-days", type=int, default=365)
    p.add_argument("--training-dataset", default=str(Path.home() / "Desktop" / "btc_full.csv"))
    p.add_argument("--tfs", default="1h,4h,12h,1d")
    p.add_argument("--no-fetch", action="store_true")
    p.add_argument("--cluster-radius-pct", type=float, default=CLUSTER_RADIUS_PCT)
    p.add_argument("--min-target-dist-pct", type=float, default=MIN_TARGET_DIST_PCT,
                   help="Минимальная дистанция кластера для роли target / FIRST-TARGET (percent)")
    args = p.parse_args()

    op = run_zones_opinion(
        training_dataset=Path(args.training_dataset),
        train_days=args.train_days,
        tfs=tuple(args.tfs.split(",")),
        fetch=not args.no_fetch,
        cluster_radius_pct=args.cluster_radius_pct,
        min_target_dist_pct=args.min_target_dist_pct,
    )
    print(op.text)


if __name__ == "__main__":
    main()
