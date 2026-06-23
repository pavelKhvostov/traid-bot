# ov_vc_2h_24zones — Шаги 1–3 (2026-06-23)

Канон-проект в библиотеке `~/smc-lib/поиск-элементов/ov_vc_2h_24zones/`. Поиск элементов + разбивка на 24 группы для будущего ML.

## Шаг 1 — Обновление 1m данных

Все три актива обновлены до cutoff **2026-06-22 23:59:00 UTC** (= 23-06 02:59 МСК), последняя 1m bar = последний бар D-свечи 22-06.

| Asset | Bars | Range |
|---|---|---|
| BTC | 4,447,713 | 2018-01 → 2026-06-22 23:59 |
| ETH | 3,403,254 | ~2017 → cutoff |
| SOL | 3,082,676 | 2020-08-11 → cutoff |

Bar `2026-06-23 00:00:00 UTC` отсутствует во всех. ML/scanners не имеют доступа к данным после cutoff.

## Шаг 2 — Canon ob_vc 2h detection

**Scanner**: `~/smc-lib/поиск-элементов/ov_vc_2h_24zones/scripts/scan_ob_vc_2h.py`

Использует canon `~/smc-lib/elements/ob_vc/code.py` (9 правил из `definition.md`). LTF mapping расширен с `(15m, 20m)` → `(15m, 20m, 30m)`.

**Результат**: `btc_ob_vc_2h_final_base.parquet` — **4,381 unique 2h ob_vc** (per-OB одна строка, без дубликатов).

### Канон vs e12 deviation

| | Unique 2h ob_vc |
|---|---|
| e12 (15m + 30m, упрощённая валидация) | 5,968 |
| Canon strict (15m + 20m, все 9 правил) | 4,268 |
| **Canon extended (15m + 20m + 30m, все 9 правил)** | **4,381** ← выбран |

Canon строже e12 на ~1,600 OBs (отсеяны rules #5, #8, #9: spatial range, temporal upper, FVG actionable).

### Schema final_base (26 полей)

- `ts_detect` — **canon detection time** = max(OB.cur.close, all FVG.c3.close, all first_FH/FL confirmation). Lookahead-free ML reference.
- `ts_cur_close`, `ts_cur_open`, `ts_prev_open`, `delay_ms`
- `direction`, `ltf` (primary = earliest by time)
- `fvg_zone_lo/hi` (primary FVG zone), `ob_zone_lo/hi`, `drop_rally_lo/hi`, `low_ob_vc`, `first_opp_frac_level`
- `n_components`, `n_15m`, `n_20m`, `n_30m`
- **`validating_zones_lo/hi`** — массивы всех same-LTF FVG zones (для primary LTF)
- `fvg_c1_ts`, `fvg_c3_ts`, `ob_idx`, `fvg_idx_in_components`, `is_primary`

### Sanity checks

- 4,381 unique `(ob_idx, direction)` ✓
- 4,381 unique `(prev.open, prev.close)` ✓
- 4,381 unique `(cur.open, cur.close)` ✓
- Ни одного `ob_idx` с обоими LONG+SHORT
- Σ `validating_zones` length = n_<primary_ltf> для всех строк

### LTF (primary) distribution

```
15m: 3,284 (75.0%)
20m:   912 (20.8%)
30m:   185 (4.2%)
```

### Direction × swept (canon 1.1.1)

```
LONG  swept:  1,075   LONG  not-swept: 1,136   (Σ 2,211)
SHORT swept:  1,126   SHORT not-swept: 1,044   (Σ 2,170)
LONG swept rate: 48.6%   SHORT swept rate: 51.9%
(совпадает с memory baseline 48.5% / 52.1%)
```

## Шаг 3 — 24-type classification + canonical PNG

24 type = direction × swept × n_FVG × extreme × wick_suffix (cur / preva / prevb)

**Canon PNG**: `~/smc-lib/поиск-элементов/ov_vc_2h_24zones/btc_24_breakdown.png`

Layout 1-в-1 с `~/smc-lib/projects/ob_vc/data/ob_vc_2h_24_btc_canon_format.png`:
- root → LONG/SHORT → 4 sw×n_FVG groups per direction → 24 leaves
- T1a..T16 nomenclature
- Counts только; WR / EV / Σ R / R% — пустое место (метрики не вычислены)

### Counts по 24 типам (BTC)

```
LONG (2,211):
  T1a 373  T1b 179  T2 310    (sw n2)
  T3a  94  T3b  47  T4  72    (sw n1)
  T5a 345  T5b 212  T6 279    (nsw n2)
  T7a 111  T7b 101  T8  88    (nsw n1)

SHORT (2,170):
  T9a 384   T9b 173  T10 326   (sw n2)
  T11a 108  T11b 51  T12  84   (sw n1)
  T13a 322  T13b 192 T14 238   (nsw n2)
  T15a 116  T15b 72  T16 104   (nsw n1)
```

## Состояние библиотеки

```
~/smc-lib/поиск-элементов/ov_vc_2h_24zones/
├── btc_24_breakdown.png             канон-визуализация 24 типов (counts only)
├── btc_events_e12_2020-2026.parquet 32M (для future context features)
├── btc_ob_vc_2h_final_base.parquet  главный итог — 4,381 × 26 полей
└── scripts/
    ├── scan_ob_vc_2h.py             единственный consolidated scanner
    └── plot_24_breakdown.py         PNG-генератор canon layout
```

## Что НЕ делали (планы)

- WR / EV / Σ R / R% метрики по 24 типам (требуют labeling: TBM forward 1m)
- s7b snapshots / c1 clusters на новой canon базе
- 24-type breakdown по ETH / SOL (cross-asset)
- ML training на новой базе

## Lessons learned

1. **e12 ≠ canon**: e12 использует `(15m, 30m)` для 2h ob_vc, что отличается от `definition.md` `(15m, 20m)`. Нужно либо обновить канон под код, либо переписать e12 mapping.
2. **`fvg_components[0] ≠ primary_fvg`**: canon упорядочивает по LTF order, primary = earliest by time. При сжатии final base нужно matchить identity с `obvc.primary_fvg`, не `[0]`.
3. **ts_detect critical**: ML должен видеть `ts_detect`, не `ts_cur_close`. Lag median 90 min, p90 210 min — за это время first_opp_fractal не успевает подтвердиться → ob_vc not yet activated.
4. **Canon строже e12**: 4,268 (15+20) vs 5,968 (e12) — 28% разница из-за rules #5, #8, #9.
