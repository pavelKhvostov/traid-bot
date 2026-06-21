"""bb_dataset Phase 2 builder — PARALLEL VERSION for PC1 (multiprocessing).

Архитектура:
  1. Main: load 1m, precompute zone events on 9 TFs × 10 types, scan ob_vc events,
           build score series.
  2. Pickle всё это в STATE_PICKLE.
  3. Pool(N) воркеров, каждый:
       - init: load STATE_PICKLE один раз (~5-10s startup)
       - process: для chunk-а событий extract_features + simulate_floating
  4. Main: aggregate, save parquet.

Tested on Mac single-threaded → ~2.5h. Expected on PC1 16T parallel → ~10-20 мин.

Output: ./output/bb_obvc_1h2h_v2.parquet (~6683 rows × ~115 cols)
"""
from __future__ import annotations

import argparse
import logging
import os
import pickle
import sys
import time
from multiprocessing import Pool, cpu_count
from pathlib import Path

import numpy as np
import pandas as pd

# Resolve paths relative to this file
ROOT = Path(__file__).resolve().parent
# Archive layout: ROOT = <archive>/smc-lib/projects/bb_dataset
SMC_LIB = ROOT.parents[1]
TRAID_BOT = SMC_LIB.parent / "traid-bot"
ARCHIVE_ROOT = SMC_LIB.parent

sys.path.insert(0, str(SMC_LIB))
sys.path.insert(0, str(SMC_LIB / "projects"))
sys.path.insert(0, str(SMC_LIB / "projects" / "bb_dataset"))
sys.path.insert(0, str(SMC_LIB / "strategies" / "strategy_1_1_1"))
sys.path.insert(0, str(SMC_LIB / "strategies" / "strategy_1_1_1" / "strategy_ob_vc_v1rules"))
sys.path.insert(0, str(SMC_LIB / "prediction-algo"))
sys.path.insert(0, str(TRAID_BOT))

# Default paths
DEFAULT_DATA = ARCHIVE_ROOT / "data" / "BTCUSDT_1m_vic_vadim.csv"
OUTPUT_DIR = ARCHIVE_ROOT / "output"
STATE_PICKLE = OUTPUT_DIR / "_builder_state.pkl"
OUTPUT_PARQUET = OUTPUT_DIR / "bb_obvc_1h2h_v2.parquet"
LOG_FILE = OUTPUT_DIR / "builder_v2.log"


def setup_logging():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s"))
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(logging.Formatter("%(asctime)s  %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler, stream], force=True)


def main_precompute(args):
    """Main: load + precompute + pickle state."""
    # Set env var BEFORE importing data.py (which reads env at module load)
    os.environ["BTC_DATA_PATH"] = str(args.data)

    from data import load_btc_1m
    from zones import precompute_zone_events, ALL_TYPES
    from strategy_1_1_1_floating import build_score_series, FLOATING_TP_CONFIG
    from backtest import scan_ob_vc_events, HTFS
    from smc_context import SMC_TFS

    logging.info(f"loading 1m BTC from {args.data}")
    if not args.data.exists():
        raise FileNotFoundError(f"data CSV missing: {args.data}")
    t1 = time.time()
    df_1m = load_btc_1m(path=args.data)
    logging.info(f"  {len(df_1m):,} bars in {time.time()-t1:.1f}s")
    logging.info(f"  range: {df_1m.index[0]} -> {df_1m.index[-1]}")

    logging.info(f"precomputing zone events: {len(SMC_TFS)} TFs × {len(ALL_TYPES)} types")
    t1 = time.time()
    # Custom logged loop (mirrors precompute_zone_events with per-iteration logs)
    from resample import resample_many
    from zones import _SCANNERS, _scan_ob_vc_cross_tf, OB_VC_HTF_TO_LTF

    end_ts = df_1m.index[-1] + pd.Timedelta(minutes=1)
    logging.info(f"  resampling 1m -> {SMC_TFS}...")
    t_rs = time.time()
    resampled = resample_many(df_1m, SMC_TFS, end_ts)
    logging.info(f"  resample done in {time.time()-t_rs:.1f}s")
    for tf, df_tf in resampled.items():
        logging.info(f"    {tf}: {len(df_tf):,} bars")

    events_by_tf_type = {}
    # Sequential scan with per-(tf, ztype) logging
    n_total = len(SMC_TFS) * len(ALL_TYPES)
    n_done = 0
    for tf, df_tf in resampled.items():
        for ztype in ALL_TYPES:
            if ztype == "ob_vc":
                continue  # handled separately below
            scanner = _SCANNERS.get(ztype)
            if scanner is None:
                n_done += 1
                continue
            t_scan = time.time()
            events = scanner(df_tf)
            for ev in events:
                ev["born_ts"] = df_tf.index[ev["born_idx"]]
            events_by_tf_type[(tf, ztype)] = events
            n_done += 1
            logging.info(f"  [{n_done}/{n_total}] {tf}/{ztype}: {len(events)} events "
                         f"in {time.time()-t_scan:.1f}s")

    # Cross-TF ob_vc scan (special)
    if "ob_vc" in ALL_TYPES:
        logging.info(f"  cross-TF scan: ob_vc on htf {list(OB_VC_HTF_TO_LTF.keys())}")
        needed_ltfs = {ltf for ltfs in OB_VC_HTF_TO_LTF.values() for ltf in ltfs}
        missing_ltfs = needed_ltfs - set(resampled.keys())
        if missing_ltfs:
            from resample import resample_one
            for ltf in missing_ltfs:
                try:
                    resampled[ltf] = resample_one(df_1m, ltf, end_ts)
                    logging.info(f"    added LTF {ltf}: {len(resampled[ltf]):,} bars")
                except Exception as e:
                    logging.warning(f"    failed LTF {ltf}: {e}")
        t_obvc = time.time()
        ob_vc_per_htf = _scan_ob_vc_cross_tf(resampled, df_1m)
        for htf, events in ob_vc_per_htf.items():
            df_tf = resampled.get(htf)
            if df_tf is None:
                continue
            for ev in events:
                ev["born_ts"] = df_tf.index[ev["born_idx"]]
            events_by_tf_type[(htf, "ob_vc")] = events
            logging.info(f"    ob_vc htf={htf}: {len(events)} events")
        logging.info(f"  ob_vc total in {time.time()-t_obvc:.1f}s")

    logging.info(f"  precompute DONE in {(time.time()-t1)/60:.1f} min, "
                 f"{len(events_by_tf_type)} (tf,type) keys")
    total_zone_events = sum(len(v) for v in events_by_tf_type.values())
    logging.info(f"  total zone events across all (tf,type): {total_zone_events:,}")

    logging.info("scanning ob_vc events on HTF={1h,2h}")
    all_events = []
    for htf in HTFS:
        t1 = time.time()
        events = scan_ob_vc_events(resampled, df_1m, htf)
        logging.info(f"  htf={htf}: {len(events)} ob_vc events in {time.time()-t1:.1f}s")
        all_events.extend(events)
    logging.info(f"  total ob_vc events: {len(all_events)}")

    logging.info("building 4-indicator score series (1h)")
    t1 = time.time()
    score_long, score_short = build_score_series(resampled["1h"])
    logging.info(f"  done in {time.time()-t1:.1f}s")

    cfg = FLOATING_TP_CONFIG["BTCUSDT"]
    logging.info(f"simulator config (BTC): {cfg}")

    logging.info(f"pickling state to {STATE_PICKLE}")
    t1 = time.time()
    state = {
        "df_1m": df_1m,
        "events_by_tf_type": events_by_tf_type,
        "resampled": resampled,
        "score_long": score_long,
        "score_short": score_short,
        "cfg": cfg,
    }
    with open(STATE_PICKLE, "wb") as f:
        pickle.dump(state, f, protocol=pickle.HIGHEST_PROTOCOL)
    state_size_mb = STATE_PICKLE.stat().st_size / 1024 / 1024
    logging.info(f"  pickled in {time.time()-t1:.1f}s, size {state_size_mb:.0f} MB")

    return all_events


# ───────────────────────── Worker code ─────────────────────────

WORKER_STATE = None  # populated in init_worker


def init_worker(state_pickle_path: str):
    """Load STATE once per worker process."""
    global WORKER_STATE
    # Ensure sys.path is set inside worker (Windows spawn doesn't inherit)
    _here = Path(state_pickle_path).resolve()
    _smc = _here.parents[2]
    _archive = _smc.parent
    sys.path.insert(0, str(_smc))
    sys.path.insert(0, str(_smc / "projects"))
    sys.path.insert(0, str(_smc / "projects" / "bb_dataset"))
    sys.path.insert(0, str(_smc / "strategies" / "strategy_1_1_1"))
    sys.path.insert(0, str(_smc / "strategies" / "strategy_1_1_1" / "strategy_ob_vc_v1rules"))
    sys.path.insert(0, str(_smc / "prediction-algo"))
    sys.path.insert(0, str(_archive / "traid-bot"))
    os.environ.setdefault("BTC_DATA_PATH", str(_archive / "data" / "BTCUSDT_1m_vic_vadim.csv"))

    with open(state_pickle_path, "rb") as f:
        WORKER_STATE = pickle.load(f)


def process_chunk(events_chunk):
    """Worker function: extract features + simulate trade for each event."""
    from smc_context import extract_features
    from strategy_1_1_1_floating import simulate_floating

    state = WORKER_STATE
    out_rows = []
    n_err = 0
    for ev in events_chunk:
        try:
            feats = extract_features(ev, state["events_by_tf_type"],
                                       state["resampled"], state["df_1m"])
        except Exception as e:
            n_err += 1
            continue
        if not feats:
            continue
        result = simulate_floating(
            ev, state["df_1m"], state["resampled"]["1h"],
            state["score_long"], state["score_short"],
            R_cap=state["cfg"]["R_cap"],
            threshold=state["cfg"]["threshold"],
            confirm=state["cfg"]["confirm"],
        )
        trade_label = -1
        trade_R = np.nan
        exit_reason = "no_result"
        outcome = "no_result"
        if result is not None:
            outcome = result.outcome
            if result.outcome in ("win", "loss", "flat"):
                trade_label = 1 if result.R > 0 else 0
            trade_R = float(result.R)
            exit_reason = result.exit_reason

        out_rows.append({
            "signal_time": ev["signal_time"],
            "tf": ev["ob_htf_tf"],
            "direction": ev["direction"],
            "fvg_tf": ev["fvg_tf"],
            "ob_lo": ev["ob_htf_zone"][0],
            "ob_hi": ev["ob_htf_zone"][1],
            "trade_label": trade_label,
            "trade_R": trade_R,
            "exit_reason": exit_reason,
            "outcome": outcome,
            **feats,
        })
    return out_rows, n_err


def chunkify(items, n_chunks):
    """Split items into n_chunks roughly-equal lists."""
    if n_chunks <= 0:
        n_chunks = 1
    out = [[] for _ in range(n_chunks)]
    for i, x in enumerate(items):
        out[i % n_chunks].append(x)
    return [c for c in out if c]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=DEFAULT_DATA, help="Path to 1m CSV")
    ap.add_argument("--workers", type=int, default=max(1, cpu_count() - 2),
                    help=f"# workers (default cpu_count-2 = {max(1, cpu_count()-2)})")
    ap.add_argument("--chunk-divisor", type=int, default=4,
                    help="More chunks than workers helps load balancing (chunks = workers*divisor)")
    args = ap.parse_args()

    setup_logging()
    logging.info("=" * 70)
    logging.info(f"bb-builder-v2-parallel start")
    logging.info(f"  workers={args.workers}  cpu_count={cpu_count()}")
    logging.info(f"  data={args.data}")
    logging.info(f"  output={OUTPUT_PARQUET}")
    logging.info("=" * 70)

    t0 = time.time()

    # 1) Main precompute (sequential)
    all_events = main_precompute(args)

    if not all_events:
        logging.error("no ob_vc events found, aborting")
        return

    # 2) Chunked parallel processing
    n_chunks = args.workers * args.chunk_divisor
    chunks = chunkify(all_events, n_chunks)
    logging.info(f"distributing {len(all_events)} events into {len(chunks)} chunks "
                 f"across {args.workers} workers")
    sizes = [len(c) for c in chunks]
    logging.info(f"  chunk sizes: min={min(sizes)} max={max(sizes)} mean={int(np.mean(sizes))}")

    t1 = time.time()
    out_rows = []
    n_err_total = 0
    with Pool(args.workers, initializer=init_worker, initargs=(str(STATE_PICKLE),)) as pool:
        for idx, (rows, n_err) in enumerate(pool.imap_unordered(process_chunk, chunks)):
            out_rows.extend(rows)
            n_err_total += n_err
            elapsed = time.time() - t1
            done_pct = (idx + 1) / len(chunks) * 100
            eta_min = (elapsed / (idx + 1) * (len(chunks) - idx - 1)) / 60
            logging.info(f"  chunk {idx+1}/{len(chunks)} done; "
                         f"rows so far: {len(out_rows)}; errs: {n_err_total}; "
                         f"elapsed {elapsed/60:.1f}m; ETA {eta_min:.1f}m")

    logging.info(f"parallel extraction done in {(time.time()-t1)/60:.1f} min")
    logging.info(f"  total rows: {len(out_rows)}, errors dropped: {n_err_total}")

    df_out = pd.DataFrame(out_rows)
    logging.info(f"dataframe: {len(df_out)} rows × {len(df_out.columns)} cols")

    valid = df_out[df_out["trade_label"] >= 0]
    logging.info(f"  valid trade labels: {len(valid)}")
    if len(valid):
        wins = (valid["trade_label"] == 1).sum()
        losses = (valid["trade_label"] == 0).sum()
        logging.info(f"  wins={wins}  losses={losses}  WR base = {wins/len(valid)*100:.1f}%")
        total_R = valid["trade_R"].sum()
        logging.info(f"  total R (base): {total_R:+.1f}")

    df_out.to_parquet(OUTPUT_PARQUET, engine="pyarrow", compression="zstd", index=False)
    logging.info(f"saved parquet to {OUTPUT_PARQUET}")

    # Cleanup state pickle
    try:
        STATE_PICKLE.unlink()
        logging.info(f"removed temporary state pickle")
    except Exception:
        pass

    logging.info(f"TOTAL TIME: {(time.time()-t0)/60:.1f} min")


if __name__ == "__main__":
    main()
