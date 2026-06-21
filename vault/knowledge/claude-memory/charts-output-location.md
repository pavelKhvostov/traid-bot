---
name: charts-output-location
description: Графики (PNG) для i-RDRB/FVG исследований сохраняются в ~/Desktop/i-rdrb-charts/
metadata: 
  node_type: memory
  type: reference
  originSessionId: 3cacc97d-b7e5-4c77-9746-69e316174b22
---

# Папка для графиков

`~/Desktop/i-rdrb-charts/` — стандартное место для PNG-графиков по i-RDRB / FVG / VWAP-стратегиям. Пользователь создал её заранее и держит там все визуализации (по состоянию на 2026-05-23 — 27 файлов).

## Соглашение об именах

Существующие категории:
- `pattern*.png`, `case_*.png` — конкретные паттерны / варианты RDRB
- `i_rdrb_v1_*.png` — графики стратегии i-RDRB V1 (reference, equity, combined и т.д.)
- `trade_NN_YYYY-MM-DD_dir.png` — конкретные сделки в хронологическом порядке
- `vwap_entry_YYYY-MM-DD_dir_(win|loss).png` — VWAP-entry бэктест-кейсы

## Использование

- Не писать в `/tmp/` — оно тленное и теряется при перезагрузке.
- В скриптах из `~/smc-lib/scripts/` указывать `~/Desktop/i-rdrb-charts/` как `OUT_DIR`.
- Дата в имени файла — в MSK (как пользователь видит на чартах).

Связано: [[smc-lib-location]], [[btc-data-1m-csv]].
