# Empirical bound test

n = 1404 certificates aggregated from 4 run dirs.

## Component correlation with final_success (Pearson r)
- load_score                     r = +0.304  (n=1404)
- behavior_score                 r = +0.000  (n=12)
- transport_score                r = +0.093  (n=232)
- proxy_resistance_score         r = +0.527  (n=232)
- reopenability_score            r = -0.015  (n=232)
- commitment_validity_score      r = -0.008  (n=232)

## Calibration by load_score bucket
bucket       n   mean_load   success
0          280        0.00      0.39
1          280        0.58      0.93
2          280        0.68      0.55
3          280        0.83      0.28
4          284        1.00      1.00

## Ablation (set component to 1.0, recompute product-load, Pearson vs baseline)
baseline pearson r = +0.304, brier = 0.253, n = 1404

ablated                              n       r       d_r     brier
behavior_score                      12  +0.000    -0.304     0.380
transport_score                     12  +0.000    -0.304     0.333
proxy_resistance_score              12  +0.000    -0.304     0.380
reopenability_score                 12  +0.000    -0.304     0.380
commitment_validity_score           12  +0.000    -0.304     0.380