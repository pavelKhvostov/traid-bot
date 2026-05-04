#!/bin/bash
# Baseline run — Фаза 1. 14 backtest-скриптов, последовательно.
# Логи в этой же папке. Завершение фиксируется в _DONE.
set -u
cd "$(git rev-parse --show-toplevel)" 2>/dev/null || cd /Users/pavelhvostov/Desktop/traiding/traid-bot
DIR="vault/baseline/2026-05-04-14-16"
PY="./venv/bin/python"
RUNLOG="$DIR/_runlog.md"
echo "# Baseline run log" > "$RUNLOG"
echo "started: $(date -Iseconds)" >> "$RUNLOG"
echo "" >> "$RUNLOG"
echo "| script | exit | seconds |" >> "$RUNLOG"
echo "|---|---|---|" >> "$RUNLOG"

SCRIPTS=(
  backtest_strategy_1_1_1.py
  backtest_1_1_1_sl_on_htf.py
  backtest_strategy_1_1_2.py
  backtest_strategy_1_1_2_extended.py
  backtest_strategy_1_1_3.py
  backtest_strategy_1_1_4.py
  backtest_strategy_1_2_0.py
  backtest_strategy_rdrb.py
  backtest_strategy_rdrb_premium.py
  backtest_strategy_rdrb_trend.py
  backtest_strategy_rdrb_wick.py
  backtest_rdrb_konfetka.py
  backtest_vic_bos.py
  backtest_vic_evot.py
)

for s in "${SCRIPTS[@]}"; do
  base="${s%.py}"
  echo ">>> $s" >&2
  start=$(date +%s)
  "$PY" "$s" > "$DIR/$base.log" 2>&1
  rc=$?
  end=$(date +%s)
  printf '| %s | %d | %d |\n' "$s" "$rc" $((end-start)) >> "$RUNLOG"
done

echo "" >> "$RUNLOG"
echo "finished: $(date -Iseconds)" >> "$RUNLOG"
touch "$DIR/_DONE"
