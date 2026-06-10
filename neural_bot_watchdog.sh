#!/bin/bash
# Watchdog для neural_bot.py — держит бота живым (перезапуск при падении).
# Запуск: nohup bash neural_bot_watchdog.sh > /tmp/neural_bot_watchdog.log 2>&1 &
cd "$(dirname "$0")"
PY=".venv-pivot/bin/python"
while true; do
  if ! pgrep -f "neural_bot.py" > /dev/null; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] bot down — restarting"
    OMP_NUM_THREADS=1 nohup "$PY" -u neural_bot.py >> /tmp/neural_bot.log 2>&1 &
  fi
  sleep 30
done
