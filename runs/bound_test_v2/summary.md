# Empirical bound test

n = 232 certificates aggregated from 2 run dirs.

## Component correlation with final_success (Pearson r)
- load_score                     r = +0.242  (n=232)
- behavior_score                 r = +0.000  (n=12)
- transport_score                r = +0.093  (n=232)
- proxy_resistance_score         r = +0.527  (n=232)
- reopenability_score            r = -0.015  (n=232)
- commitment_validity_score      r = -0.008  (n=232)

## Calibration by load_score bucket
bucket       n   mean_load   success
0           46        0.55      0.93
1           46        0.62      1.00
2           46        0.79      1.00
3           46        1.00      1.00
4           48        1.00      1.00

## Ablation (set component to 1.0, recompute product-load, Pearson vs baseline)
baseline pearson r = +0.242, brier = 0.086, n = 232

ablated                              n       r       d_r     brier
behavior_score                      12  +0.000    -0.242     0.380
transport_score                     12  +0.000    -0.242     0.333
proxy_resistance_score              12  +0.000    -0.242     0.380
reopenability_score                 12  +0.000    -0.242     0.380
commitment_validity_score           12  +0.000    -0.242     0.380