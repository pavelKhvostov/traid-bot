"""Run e12 (Event Detector v12) on ETHUSDT 2023-01 → 2026-06-15.
Monkey-patches CSV_PATH and OUT_PATH to ETH-specific files,
then calls main() unchanged.
"""
import sys, pathlib
sys.path.insert(0, '/home/vadim/smc-lib/поиск-элементов')
import event_detector_v12 as e12

e12.CSV_PATH = pathlib.Path("/home/vadim/traid-bot/data/ETHUSDT_1m_vic_vadim.csv")
e12.OUT_PATH = pathlib.Path("/home/vadim/smc-lib/projects/ob_vc/eth/data/eth_events_e12_2023-2026.parquet")
print(f"ETH e12 — input {e12.CSV_PATH.name}  output {e12.OUT_PATH.name}", flush=True)
e12.main("2023-01-01", "2026-06-15", 30)
