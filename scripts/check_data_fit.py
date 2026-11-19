"""Data-fit check: can this simulated world answer Culprit's questions at all?

Run before building on a world (methodology M20). Usage:

    uv run python scripts/check_data_fit.py configs/small.yaml --seeds 101 102 103 104 105
    uv run python scripts/check_data_fit.py configs/test.yaml --regime second --seeds 301 302 303

It simulates each seed in memory (so it can use the simulator's truth; it
never reads a sealed answer key from disk) and measures:

1. Signal versus noise per fault: the true rate drop at the fault's target
   segment against the binomial noise of that segment's hourly rate.
2. Masking: faults whose drop in the overall rate is smaller than the overall
   rate's normal hour-to-hour noise, so they hide in the total.
3. Surge traps: share of promotions and paydays that fire a naive detector
   (seasonal naive, robust z above 3 for 2 hours) on their own segment.
4. Headroom: forecast error of the true normal rate (an oracle) against the
   error of seasonal naive, on the fault-free calibration window. If the two
   are close, no forecaster can beat seasonal naive by much.
5. Too easy: how often "the segment with the largest rate drop" is already
   the true culprit. It must be well under 90%.
6. Bookkeeping: counts reconcile, faults only in evaluation, event counts.

Writes JSON to artifacts/data-fit/<config>.json and prints a Markdown summary.
Simulated data only.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

from culprit.config import load_config, world_hash
from culprit.panel import aggregate, rate
from culprit.segments import node_key
from culprit.sim.build import simulate

Z_NAIVE = 3.0
PERSIST = 2
MIN_WINDOW_ATTEMPTS = 200
EASY_WINDOW_HOURS = 6


def candidate_nodes(seg):
    nodes = [n for n in seg.monitored_nodes() if n]
    for issuer in seg.values["issuer"]:
        nodes += [{"issuer": issuer, "method": m} for m in seg.values["method"]]
    return nodes


def robust_sd(x: np.ndarray) -> float:
    x = x[np.isfinite(x)]
    if len(x) == 0:
        return float("nan")
    return float(1.4826 * np.median(np.abs(x - np.median(x))))


def naive_fires(rates: np.ndarray, start: int, end: int, lookback: int = 672) -> bool:
    """Seasonal-naive drop z above Z_NAIVE for PERSIST consecutive hours inside [start, end)."""
    resid = np.full_like(rates, np.nan)
    resid[168:] = rates[:-168] - rates[168:]
    lo = max(168, start - lookback)
    scale = robust_sd(resid[lo:start])
    if not np.isfinite(scale) or scale == 0:
        return False
    z = resid[start:end] / scale
    run = 0
    for v in z:
        run = run + 1 if np.isfinite(v) and v > Z_NAIVE else 0
        if run >= PERSIST:
            return True
    return False


def check_seed(config: dict, seed: int) -> dict:
    cfg = json.loads(json.dumps(config))
    cfg["seed"] = seed
    t0 = time.perf_counter()
    sim = simulate(cfg)
    sim_seconds = time.perf_counter() - t0
    obs = sim.observed
    seg = obs.segments
    tl = obs.timeline
    lam = sim.expected_volume
    att = obs.attempts.astype(float)
    app = obs.approved.astype(float)

    # --- bookkeeping
    nodes = seg.monitored_nodes()
    m = seg.membership(nodes)
    total_ok = bool(np.allclose((m @ att)[0], att.sum(axis=0)))
    recon_ok = True
    for node in nodes[: 1 + sum(len(seg.values[k]) for k in seg.values)]:
        for kids in seg.refinements(node).values():
            s = sum(att[seg.mask(k)].sum(axis=0) for k in kids)
            recon_ok &= bool(np.array_equal(s, att[seg.mask(node)].sum(axis=0)))
    lo_eval = tl.calibration_end
    book = {
        "seed": seed,
        "world_hash": world_hash(cfg),
        "dataset_hash": obs.meta["dataset_hash"],
        "leaves": seg.n_leaves,
        "hours": tl.n_hours,
        "rows": int(seg.n_leaves * tl.n_hours),
        "mean_attempts_per_hour": float(att.sum() / tl.n_hours),
        "approval_rate": float(app.sum() / att.sum()),
        "zero_attempt_leaf_hours": float((obs.attempts == 0).mean()),
        "hierarchy_reconciles": bool(recon_ok and total_ok),
        "declines_reconcile": bool((obs.declines.sum(-1) == obs.attempts - obs.approved).all()),
        "approved_le_attempts": bool((obs.approved <= obs.attempts).all()),
        "faults_only_in_evaluation": all(f.start >= lo_eval for f in sim.faults),
        "faults": len(sim.faults),
        "faults_by_type": {
            t: sum(f.type == t for f in sim.faults) for t in sorted({f.type for f in sim.faults})
        },
        "surges_by_type": {
            t: sum(s.type == t for s in sim.surges) for t in sorted({s.type for s in sim.surges})
        },
        "overlapping_fault_pairs": sum(
            1
            for i, a in enumerate(sim.faults)
            for b in sim.faults[i + 1 :]
            if a.start < b.end
            and b.start < a.end
            and (seg.mask(a.target) & seg.mask(b.target)).any()
        ),
        "simulate_seconds": sim_seconds,
    }

    # Total-rate noise: robust sd of seasonal-naive residual of the total in calibration.
    total_rate = rate(app.sum(0), att.sum(0))
    c0, c1 = tl.window_hours("calibration")
    total_resid = total_rate[c0:c1] - total_rate[c0 - 168 : c1 - 168]
    total_noise = robust_sd(total_resid) / np.sqrt(2)  # one observation's share of the noise

    faults = []
    for f in sim.faults:
        rows = seg.mask(f.target)
        h = slice(f.start, f.end)
        lam_n = lam[rows, h]
        p_n = (lam_n * sim.p_normal[rows, h]).sum(0) / lam_n.sum(0)
        p_a = (lam_n * sim.p_actual[rows, h]).sum(0) / lam_n.sum(0)
        drop = p_n - p_a
        noise = np.sqrt(p_n * (1 - p_n) / lam_n.sum(0))
        snr_hour = float(np.median(drop / noise))
        # Empirical noise the detectors face: robust sd of the seasonal-naive residual of this
        # segment's observed rate on the calibration window, per observation.
        r_seg = rate(app[rows].sum(0), att[rows].sum(0))
        emp = robust_sd(r_seg[c0:c1] - r_seg[c0 - 168 : c1 - 168]) / np.sqrt(2)
        snr_hour_emp = float(np.median(drop) / emp)
        snr_window = float(drop.mean() / np.sqrt((p_n * (1 - p_n)).mean() / lam_n.sum()))
        lam_all = lam[:, h]
        total_drop = float(
            ((lam_all * (sim.p_normal[:, h] - sim.p_actual[:, h])).sum(0) / lam_all.sum(0)).mean()
        )
        faults.append(
            {
                "id": f.id,
                "type": f.type,
                "target": node_key(f.target),
                "hours": f.end - f.start,
                "severity": f.severity,
                "segment_drop": float(drop.mean()),
                "snr_hour": snr_hour,
                "snr_hour_empirical": snr_hour_emp,
                "snr_window": snr_window,
                "total_drop": total_drop,
                "total_drop_over_noise": total_drop / total_noise,
            }
        )

    # --- surge traps (only surges with a week of history before them)
    surges = []
    for s in sim.surges:
        if s.start < 168 + 24:
            continue
        rows = seg.mask(s.target)
        r = rate(app[rows].sum(0), att[rows].sum(0))
        surges.append({"type": s.type, "fires": naive_fires(r, s.start, s.end)})
    # Base rate: the same naive rule on random quiet windows of 8 hours on the same segments.
    rng = np.random.default_rng(seed)
    quiet = []
    busy = np.zeros(tl.n_hours, dtype=bool)
    for e in sim.surges + sim.faults:
        busy[max(0, e.start - 24) : e.end + 24] = True
    targets = [s.target for s in sim.surges] or [{}]
    for _ in range(200):
        start = int(rng.integers(168 + 24, tl.n_hours - 8))
        if busy[start : start + 8].any():
            continue
        tgt = targets[int(rng.integers(len(targets)))]
        rows = seg.mask(tgt)
        quiet.append(naive_fires(rate(app[rows].sum(0), att[rows].sum(0)), start, start + 8))

    # --- headroom on the calibration window, per monitored node
    p_true_node = aggregate(seg, att * sim.p_normal, nodes) / np.maximum(m @ att, 1)
    obs_rate = rate(m @ app, m @ att)
    cal = slice(c0, c1)
    lag = slice(c0 - 168, c1 - 168)
    err_oracle = np.abs(obs_rate[:, cal] - p_true_node[:, cal])
    err_naive = np.abs(obs_rate[:, cal] - obs_rate[:, lag])
    # Pooled 4-week same-hour baseline: approvals / attempts over the same hour of the 4 prior weeks.
    n_att = m @ att
    n_app = m @ app
    back = [k for k in range(1, 5) if c0 - 168 * k >= 0]
    pool_att = sum(n_att[:, c0 - 168 * k : c1 - 168 * k] for k in back)
    pool_app = sum(n_app[:, c0 - 168 * k : c1 - 168 * k] for k in back)
    err_pool = np.abs(obs_rate[:, cal] - rate(pool_app, pool_att))
    levels = {}
    for i, n in enumerate(nodes):
        level = "total" if not n else ("leaf" if len(n) == 3 else next(iter(n)))
        levels.setdefault(level, []).append(i)
    headroom = {}
    np.seterr(divide="ignore", invalid="ignore")  # a leaf can have zero naive error
    for level, idx in levels.items():
        eo = np.nanmean(err_oracle[idx], axis=1)
        en = np.nanmean(err_naive[idx], axis=1)
        ep = np.nanmean(err_pool[idx], axis=1)
        headroom[level] = {
            "nodes": len(idx),
            "median_oracle_mae": float(np.median(eo)),
            "median_naive_mae": float(np.median(en)),
            "median_pooled4_mae": float(np.median(ep)),
            "median_ratio": float(np.median(eo / en)),
            "median_ratio_vs_pooled4": float(np.median(eo / ep)),
        }

    # --- too easy: largest rate drop (and largest shortfall) versus the same hours last week
    cands = candidate_nodes(seg)
    cm = seg.membership(cands)
    c_att = cm @ att
    c_app = cm @ app
    cand_keys = [node_key(n) for n in cands]
    easy = []
    for f in sim.faults:
        h = slice(f.start, min(f.end, f.start + EASY_WINDOW_HOURS))
        hb = slice(h.start - 168, h.stop - 168)
        a_now, a_then = c_att[:, h].sum(1), c_att[:, hb].sum(1)
        r_now = c_app[:, h].sum(1) / np.maximum(a_now, 1)
        r_then = c_app[:, hb].sum(1) / np.maximum(a_then, 1)
        ok = (a_now >= MIN_WINDOW_ATTEMPTS) & (a_then >= MIN_WINDOW_ATTEMPTS)
        drop = np.where(ok, r_then - r_now, -np.inf)
        shortfall = np.where(ok, (r_then - r_now) * a_now, -np.inf)
        truth = node_key(f.target)
        easy.append(
            {
                "type": f.type,
                "largest_drop_right": cand_keys[int(np.argmax(drop))] == truth,
                "largest_shortfall_right": cand_keys[int(np.argmax(shortfall))] == truth,
            }
        )
    return {
        "bookkeeping": book,
        "faults": faults,
        "surges": surges,
        "quiet_fires": quiet,
        "headroom": headroom,
        "too_easy": easy,
        "total_noise": total_noise,
    }


def summarize(results: list[dict]) -> dict:
    faults = [f for r in results for f in r["faults"]]
    surges = [s for r in results for s in r["surges"]]
    quiet = [q for r in results for q in r["quiet_fires"]]
    easy = [e for r in results for e in r["too_easy"]]
    snr_w = np.array([f["snr_window"] for f in faults])
    snr_h = np.array([f["snr_hour"] for f in faults])
    snr_e = np.array([f["snr_hour_empirical"] for f in faults])
    masked = np.array([f["total_drop_over_noise"] < 3.0 for f in faults])
    visible = snr_w >= 3.0

    def share(x):
        x = np.asarray(x, dtype=float)
        return float(x.mean()) if len(x) else float("nan")

    by_type = {}
    for t in sorted({f["type"] for f in faults}):
        idx = [i for i, f in enumerate(faults) if f["type"] == t]
        by_type[t] = {
            "faults": len(idx),
            "median_snr_hour": float(np.median(snr_h[idx])),
            "median_snr_window": float(np.median(snr_w[idx])),
            "median_snr_hour_empirical": float(np.median(snr_e[idx])),
            "share_masked": share(masked[idx]),
            "largest_drop_right": share([easy[i]["largest_drop_right"] for i in idx]),
        }
    levels = sorted({lv for r in results for lv in r["headroom"]})
    headroom = {
        lv: {
            k: float(np.median([r["headroom"][lv][k] for r in results]))
            for k in (
                "median_oracle_mae",
                "median_naive_mae",
                "median_pooled4_mae",
                "median_ratio",
                "median_ratio_vs_pooled4",
            )
        }
        | {"nodes": results[0]["headroom"][lv]["nodes"]}
        for lv in levels
    }
    out = {
        "seeds": [r["bookkeeping"]["seed"] for r in results],
        "faults": len(faults),
        "signal": {
            "median_snr_hour": float(np.median(snr_h)),
            "median_snr_window": float(np.median(snr_w)),
            "share_snr_window_ge_3": share(visible),
            "share_snr_window_lt_1": share(snr_w < 1.0),
            "median_snr_hour_empirical": float(np.median(snr_e)),
            "share_snr_hour_empirical_lt_3": share(snr_e < 3.0),
            "share_snr_hour_empirical_ge_10": share(snr_e >= 10.0),
        },
        "masking": {
            "share_masked": share(masked),
            "share_masked_but_visible_at_segment": share(masked & visible),
        },
        "surge_traps": {
            "promotions": sum(s["type"] == "promotion" for s in surges),
            "promotion_fire_share": share([s["fires"] for s in surges if s["type"] == "promotion"]),
            "paydays": sum(s["type"] == "payday" for s in surges),
            "payday_fire_share": share([s["fires"] for s in surges if s["type"] == "payday"]),
            "quiet_windows": len(quiet),
            "quiet_fire_share": share(quiet),
        },
        "headroom": headroom,
        "too_easy": {
            "largest_drop_top1": share([e["largest_drop_right"] for e in easy]),
            "largest_shortfall_top1": share([e["largest_shortfall_right"] for e in easy]),
        },
        "by_type": by_type,
        "bookkeeping": [r["bookkeeping"] for r in results],
    }
    leaf_ratio = headroom.get("leaf", {}).get("median_ratio", float("nan"))
    out["gates"] = {
        "too_easy_below_0.9": out["too_easy"]["largest_drop_top1"] < 0.9,
        "masked_faults_exist": out["masking"]["share_masked_but_visible_at_segment"] > 0,
        "most_faults_visible_at_segment": out["signal"]["share_snr_window_ge_3"] >= 0.5,
        "detection_not_trivial": out["signal"]["share_snr_hour_empirical_ge_10"] < 0.5
        and out["signal"]["share_snr_hour_empirical_lt_3"] > 0.1,
        "surge_traps_fire_naive_more_than_quiet": out["surge_traps"]["promotion_fire_share"]
        > out["surge_traps"]["quiet_fire_share"],
        "headroom_leaf_ratio_below_0.9": leaf_ratio < 0.9,
        "bookkeeping_ok": all(
            b["hierarchy_reconciles"]
            and b["declines_reconcile"]
            and b["approved_le_attempts"]
            and b["faults_only_in_evaluation"]
            for b in out["bookkeeping"]
        ),
    }
    return out


def markdown(s: dict, config_path: str) -> str:
    sig, mask, trap, easy = s["signal"], s["masking"], s["surge_traps"], s["too_easy"]
    lines = [
        f"Config `{config_path}`, seeds {', '.join(map(str, s['seeds']))}, {s['faults']} faults.",
        "",
        "| Check | Measured |",
        "|---|---|",
        f"| Signal: median hourly SNR at the fault's segment | {sig['median_snr_hour']:.2f} |",
        f"| Signal: median whole-window SNR | {sig['median_snr_window']:.2f} |",
        f"| Signal: share of faults with window SNR >= 3 | {sig['share_snr_window_ge_3']:.1%} |",
        f"| Signal: share with window SNR < 1 | {sig['share_snr_window_lt_1']:.1%} |",
        f"| Signal: median hourly drop over empirical noise | {sig['median_snr_hour_empirical']:.2f} |",
        f"| Signal: share with hourly drop < 3 x empirical noise (hard) | {sig['share_snr_hour_empirical_lt_3']:.1%} |",
        f"| Signal: share with hourly drop >= 10 x empirical noise (easy) | {sig['share_snr_hour_empirical_ge_10']:.1%} |",
        f"| Masking: share of faults with total-rate drop < 3 x total noise | {mask['share_masked']:.1%} |",
        f"| Masking: masked in the total but window SNR >= 3 at the segment | {mask['share_masked_but_visible_at_segment']:.1%} |",
        f"| Surge traps: promotions firing the naive detector | {trap['promotion_fire_share']:.1%} of {trap['promotions']} |",
        f"| Surge traps: paydays firing it | {trap['payday_fire_share']:.1%} of {trap['paydays']} |",
        f"| Surge traps: quiet 8-hour windows firing it (base rate) | {trap['quiet_fire_share']:.1%} of {trap['quiet_windows']} |",
        f"| Too easy: largest rate drop is the culprit (top-1) | {easy['largest_drop_top1']:.1%} |",
        f"| Too easy: largest approval shortfall is the culprit | {easy['largest_shortfall_top1']:.1%} |",
        "",
        "Headroom on the calibration window (mean absolute error of the hourly rate, median over nodes):",
        "",
        "| Level | Nodes | Oracle MAE | Seasonal-naive MAE | 4-week pooled MAE | Oracle / naive | Oracle / pooled |",
        "|---|---|---|---|---|---|---|",
    ]
    for lv, h in s["headroom"].items():
        lines.append(
            f"| {lv} | {h['nodes']} | {h['median_oracle_mae']:.4f} | {h['median_naive_mae']:.4f} | {h['median_pooled4_mae']:.4f} | {h['median_ratio']:.2f} | {h['median_ratio_vs_pooled4']:.2f} |"
        )
    lines += [
        "",
        "By fault type:",
        "",
        "| Type | Faults | Median hourly SNR | Median window SNR | Median hourly empirical SNR | Masked | Largest drop right |",
        "|---|---|---|---|---|---|---|",
    ]
    for t, b in s["by_type"].items():
        lines.append(
            f"| {t} | {b['faults']} | {b['median_snr_hour']:.2f} | {b['median_snr_window']:.2f} | {b['median_snr_hour_empirical']:.2f} | {b['share_masked']:.1%} | {b['largest_drop_right']:.1%} |"
        )
    lines += ["", "Gates:", ""]
    lines += [f"- {k}: {'PASS' if v else 'FAIL'}" for k, v in s["gates"].items()]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("config")
    ap.add_argument("--seeds", type=int, nargs="+", default=[101, 102, 103, 104, 105])
    ap.add_argument("--out", default=None)
    ap.add_argument(
        "--regime", default=None, help="a test plan's regime, checked on development seeds only"
    )
    args = ap.parse_args(argv)
    config = load_config(args.config)
    if args.regime:
        from culprit.plan import regime_config

        test_seeds = (config.get("test") or {}).get("seeds")
        if isinstance(test_seeds, list) and set(test_seeds) & set(args.seeds):
            raise SystemExit("the fit check never runs on test seeds; pass development seeds")
        config = regime_config(config, args.regime)
    t0 = time.perf_counter()
    results = [check_seed(config, s) for s in args.seeds]
    summary = summarize(results)
    summary["seconds"] = time.perf_counter() - t0
    out = Path(args.out or f"artifacts/data-fit/{config['name']}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "per_seed": results}, indent=2, default=float))
    print(markdown(summary, args.config))
    print(f"\nWrote {out} in {summary['seconds']:.1f} s")
    return 0 if all(summary["gates"].values()) else 1


if __name__ == "__main__":
    sys.exit(main())
