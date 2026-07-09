# SWE-bench two-way gauge — Track C interventional subset

Status: generated 2026-07-09. Claim level: **coding-agent diagnostic (interventional subset)**. Not SOTA. Fingerprint flags remain correlational for the full matrix; this subset upgrades force-retrieve positives with a second-run leak perturbation (`LEAK_MARKER:` → `ALT_LEAK:`).

## Acceptance

On force-retrieve positives, leak probe changes commitment ≥ 0.80 of replayed cells (issue text unchanged).

## Results

| metric | value |
|---|---:|
| cells | 3 |
| leak commitment changed | 3 |
| rate | 1.00 |

### Per-instance

| instance_id | leak_changed | base has LEAK_MARKER | alt has ALT_LEAK |
|---|---|---|---|
| astropy__astropy-12907 | True | True | True |
| astropy__astropy-14182 | True | True | True |
| astropy__astropy-14365 | True | True | True |

## Read

PASS (1.00): intervening on the leak carrier moved the commitment on ≥80% of flagged cells — interventional confirmation of the marker heuristic on this subset.

## Artifacts

- `runs/two_way_gauge_n3`
- `runs/two_way_gauge_n3/two_way_gauge.json`
