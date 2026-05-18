---
tags: [session, floating-tp, multi-symbol, 1.1.1, 1.1.2, 1.1.4, c2, hull, ema, audit]
date: 2026-05-15
---

# Сессия 2026-05-15 — Floating TP framework, multi-symbol audit, C2 trend filter

## Контекст

Длинная сессия. Основные блоки:
1. Retry-after-SL для 1.1.1 (etap_98-99)
2. Audit инфляции «+313R BTC» из etap_100 — обнаружено что etap_42 instant-fill model даёт ×3-7 инфляции
3. Multi-shot detector inflation — ×1.7-2.3
4. Floating TP framework (4-indicator momentum score) для 1.1.1
5. Per-symbol config tuning (D variant: R-cap + score)
6. PDF guide на человеческом для floating TP
7. Floating TP для 1.1.2 — работает (+31%)
8. Funnel audit 1.1.2 — 2157 trades из-за multi-shot
9. C2 trend filter A/B test: EMA-200 vs Hull-6h vs combinations
10. Floating TP для 1.1.4 BFJK — НЕ работает (−67%)
11. 10 alternative auto-trail для 1.1.4 — все хуже baseline

## Главные открытия

### 1. Floating TP работает только на стратегиях с НИЗКИМ baseline WR

| Strategy | Baseline WR | Floating effect |
|---|---:|---|
| 1.1.1 SWEPT | 45% | ★ +15% PnL — works |
| 1.1.2 macro-OB | 42% | ★ +31% PnL — works |
| **1.1.4 BFJK** | **64%** | ✗ −67% PnL — does NOT work |

См. [[floating-tp-only-helps-low-wr-strategies]].

### 2. etap_42 instant-fill simulator завысил PnL в 3-7×

Не было баг lookahead — была неправильная exec model. etap_42 PDF
«M0 Fixed RR=2.5 → +168R BTC» это **screening tool**, в реальной торговле
с limit-fill симулятором даёт ~+42R (×4 меньше). См. [[etap-42-instant-fill-3-7x-inflation]].

### 3. Multi-shot detector добавляет ×1.7-2.3 inflation

Multi-shot framework собирает все (OB-htf, entry-FVG) пары в каждой
macro-зоне отдельно. Один и тот же `(signal_time, direction, entry)`
часто появляется 2-14 раз из разных macro путей. **С дедупом числа
реальнее ×2 меньше**. См. [[multi-shot-detector-2.3x-inflation]].

### 4. Per-symbol Hull/MH/RSI/ASVK score для 1.1.1 + 1.1.2

Final config:

**1.1.1** (per-symbol):
- BTC/ETH: R_cap=4.5, threshold=−0.25, confirm=2
- SOL: R_cap=3.5, threshold=0.00, confirm=1
- Total 6y: BTC +180R / ETH +152R / SOL +97R = **+429R**

**1.1.2** (universal):
- BTC/ETH/SOL: R_cap=4.5, threshold=0.00, confirm=2
- Total 6y: BTC +1016R / ETH +1018R / SOL +727R = **+2761R** (multi-shot inflated)
- После дедупа ÷2.23×: ~+1240R (realistic)

См. [[4-indicator-momentum-score]] и [[strategy-1-1-1-floating-tp-final]] / [[strategy-1-1-2-floating-tp-final]].

### 5. C2 trend filter: EMA OR Hull-6h винит на BTC/SOL, AND wins on ETH

| Symbol | Best filter | PnL 3y | vs EMA-only | Bad |
|---|---|---:|---:|---:|
| BTC | EMA OR Hull-6h | +41R | +24% | 0/4 |
| ETH | EMA AND Hull-6h | +23R | +1050% | 1/4 |
| SOL | EMA OR Hull-6h | +41R | +193% | 0/4 |

Per-symbol filter: +105R vs original +49R. См. [[c2-ema-or-hull6h-trend-filter-winner]].

### 6. 1.1.4 BFJK уже оптимальна с fixed RR=2.0

Все 10 альтернативных автоследований (BE-ratchet, lock-step, ATR trail,
strict-score, conditional TP extension) дают −12R до −72R от baseline +107R.
Только G2 (TP extension at +0.5 score) trade-off: −13R за 0 bad years
(vs 1 у baseline) — robustness option.

См. [[strategy-1-1-4-floating-tp-not-applicable]].

## ETH/SOL data fetched

Дофетчены 1m + 15m + HTF для ETH (с 2020-05-15) и SOL (с 2020-08-11).
Раньше было только с 2023-04-26. Теперь полный 6y backtest возможен.

Скрипты: `fetch_eth_sol_6y.py`, `fetch_eth_sol_htf_6y.py`.

## Файлы

- `research/elements_study/etap_98_retry_after_sl_111.py` — retry-after-SL для 1.1.1
- `research/elements_study/etap_99_retry_111_multi_sym.py` — multi-symbol BTC+ETH+SOL
- `research/elements_study/etap_100_retry_111_e42_params.py` — etap_42 params replication
- `research/elements_study/etap_101_audit_300r.py` — instant/limit/market audit, 3-7× inflation discovery
- `research/elements_study/etap_102_clean_111_max.py` — clean numbers с дедупом
- `research/elements_study/etap_103_floating_tp.py` — 4-indicator momentum score, base floating
- `research/elements_study/etap_104_floating_variants.py` — 14 variants smoothness audit
- `research/elements_study/etap_105_d_variant_tuning.py` — D variant grid 7×3×3
- `research/elements_study/etap_106_sol_specific.py` — SOL tighter cap
- `research/elements_study/etap_107_sol_extended.py` — SOL extended grid 8×4×4
- `research/elements_study/etap_108_floating_tp_pdf.py` — human-friendly PDF guide
- `research/elements_study/etap_109_floating_112.py` — 1.1.2 floating
- `research/elements_study/etap_110_112_signals_audit.py` — funnel audit
- `research/elements_study/etap_111_c2_hull_trend.py` — C2 trend filter A/B
- `research/elements_study/etap_112_c2_combined_trend.py` — combined filters
- `research/elements_study/etap_113_c2_combined_3sym.py` — ETH/SOL verify
- `research/elements_study/etap_114_floating_1_1_4.py` — 1.1.4 floating (fail)
- `research/elements_study/etap_115_alternatives_1_1_4.py` — 10 alternative trails

## Связи

- [[floating-tp-only-helps-low-wr-strategies]]
- [[4-indicator-momentum-score]]
- [[strategy-1-1-1-floating-tp-final]]
- [[strategy-1-1-2-floating-tp-final]]
- [[strategy-1-1-4-floating-tp-not-applicable]]
- [[etap-42-instant-fill-3-7x-inflation]]
- [[multi-shot-detector-2.3x-inflation]]
- [[c2-ema-or-hull6h-trend-filter-winner]]
