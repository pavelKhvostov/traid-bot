import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]          # research/level_engine
ROOT = Path(__file__).resolve().parents[3]         # repo root
for p in (str(PKG), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)
