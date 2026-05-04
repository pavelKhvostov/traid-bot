#!/bin/bash
# Дополнение к baseline: финальные оптимизации 1.1.x (без VIC/RDRB/1.2.0).
# Pavel: эталон 1.1.1 = stage3 RR sweep + monthly. Аналогично для 1.1.2 / 1.1.3.
set -u
cd /Users/pavelhvostov/Desktop/traiding/traid-bot
DIR="vault/baseline/2026-05-04-14-16"
PY="./venv/bin/python"
RUNLOG="$DIR/_runlog-optimized.md"
echo "# Optimized baseline run log" > "$RUNLOG"
echo "started: $(date -Iseconds)" >> "$RUNLOG"
echo "" >> "$RUNLOG"
echo "| script | exit | seconds |" >> "$RUNLOG"
echo "|---|---|---|" >> "$RUNLOG"

SCRIPTS=(
  optimize_1_1_1_swept_stage3.py
  analyze_1_1_1_swept_monthly.py
  optimize_1_1_2_stage3.py
  optimize_1_1_3_v1_stage3_compare_ep.py
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
touch "$DIR/_DONE-optimized"
