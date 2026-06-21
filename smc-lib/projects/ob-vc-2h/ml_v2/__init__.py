"""ML v2 — full TBM excursion, multi-RR labels, R% filter, entry delay.

Phase 1: Labels & Filters
  - TBM v2: MFE / MAE / sl_hit / time_to_mfe per event (1m sweep)
  - Multi-RR binary labels: hit_RR_{14, 15, 17, 20, 23, 25, 28}
  - R% filter: r_pct >= 0.5 для futures viability
  - Entry delay: minutes from born to first entry-touch
"""
