#!/bin/bash
# Phase 4 re-baseline. 14 backtests + 4 optimize/analyze (1.1.x).
# Скрипты теперь в research/<v>/<sub>/.
set -u
cd /Users/pavelhvostov/Desktop/traiding/traid-bot
DIR="vault/baseline/2026-05-04-16-37-after-refactor"
PY="./venv/bin/python"
RUNLOG="$DIR/_runlog.md"
echo "# Re-baseline run log (after Phase 3 refactor)" > "$RUNLOG"
echo "started: $(date -Iseconds)" >> "$RUNLOG"
echo "" >> "$RUNLOG"
echo "| script | exit | seconds |" >> "$RUNLOG"
echo "|---|---|---|" >> "$RUNLOG"

SCRIPTS=(
  research/1_1_1/backtest/backtest_strategy_1_1_1.py
  research/1_1_1/backtest/backtest_1_1_1_sl_on_htf.py
  research/1_1_2/backtest/backtest_strategy_1_1_2.py
  research/1_1_2/backtest/backtest_strategy_1_1_2_extended.py
  research/1_1_3/backtest/backtest_strategy_1_1_3.py
  research/1_1_4/backtest/backtest_strategy_1_1_4.py
  research/1_2_0/backtest/backtest_strategy_1_2_0.py
  research/rdrb/backtest/backtest_strategy_rdrb.py
  research/rdrb/backtest/backtest_strategy_rdrb_premium.py
  research/rdrb/backtest/backtest_strategy_rdrb_trend.py
  research/rdrb/backtest/backtest_strategy_rdrb_wick.py
  research/rdrb/backtest/backtest_rdrb_konfetka.py
  research/vic/backtest/backtest_vic_bos.py
  research/vic/backtest/backtest_vic_evot.py
  research/1_1_1/optimize/optimize_1_1_1_swept_stage3.py
  research/1_1_1/analyze/analyze_1_1_1_swept_monthly.py
  research/1_1_2/optimize/optimize_1_1_2_stage3.py
  research/1_1_3/optimize/optimize_1_1_3_v1_stage3_compare_ep.py
)

for s in "${SCRIPTS[@]}"; do
  base=$(basename "${s%.py}")
  echo ">>> $s" >&2
  start=$(date +%s)
  "$PY" "$s" > "$DIR/$base.log" 2>&1
  rc=$?
  end=$(date +%s)
  printf '| %s | %d | %d |\n' "$base.py" "$rc" $((end-start)) >> "$RUNLOG"
done

echo "" >> "$RUNLOG"
echo "finished: $(date -Iseconds)" >> "$RUNLOG"
touch "$DIR/_DONE"
