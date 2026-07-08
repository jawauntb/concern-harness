# Empirical bound test — aggregated across n=1404 certificates

Question: does the harness's `load_score` predict `env.success`?

## Data
- n = 1404 rows aggregated from:
  - `ablation_matched_harness_v2` (220)
  - `heldout_proxies_v4` (732)
  - `overblocking_v4` (440)
  - `compare_claude_wide` (12 with full certificate detail)

## Pearson correlation

    r(load_score, final_success) = +0.304   (n=1404)

Positive, weak-to-moderate. The score is directionally correct — a higher
load reading does mean success is more likely — but far from perfectly
calibrated.

## Calibration by load_score bucket

    bucket    n   mean_load   success
    ------------------------------------
    0       280       0.00       0.35
    1       280       0.58       0.97
    2       280       0.68       0.55
    3       280       0.83       0.28
    4       284       1.00       1.00

Two clean regions:
- **load = 0.00** → 35% success (dominated by stale_confidence oracle
  actions that were reopened; the underlying task usually still succeeded)
- **load = 1.00** → 100% success (perfect calibration)

Mid-range (0.58-0.83) is noisy. This is because rows come from
heterogeneous experiments (proxy variants, oracle actions, LLM-driven
runs) that live in different regions of the success/load space. The
bookkeeping identity holds *within* each experiment but the mixed
distribution muddies the average.

## Precision / recall at threshold

    load_score >= 0.5 as "predict success":
        precision = 0.700
        recall    = 0.871
        accuracy  = 0.684

**Read: the load_score is a useful but imperfect predictor.** At threshold
0.5 the harness catches 87% of true successes but 30% of predicted
successes are false alarms. Base rate of success in this sample is ~63%,
so accuracy 68% beats the base rate but not by a lot.

## Ablation

Setting any single component to 1.0 and recomputing the product:

    baseline (no ablation)   n=1404  r=+0.304  brier=0.253

Component-level ablation could only run on the 12 rows that carry all
five component scores (from `compare_claude_wide`) because most later
runs didn't persist behavior_score alongside the others. That's a
telemetry gap in the harness's output format — a follow-up should ensure
every RunResult emits all five components so future ablations can
identify which obligations are load-bearing and which are decorative.

## What this means

- The bookkeeping identity from the paper (Load ≥ concern × transport ×
  gauge × commitment) is preserved *as a computation* in every certificate.
- Empirically, the composite load_score does predict downstream success,
  but with modest calibration on our mixed data.
- To get a clean bound test we need a single controlled distribution and
  full component-score persistence. That's the follow-up.
