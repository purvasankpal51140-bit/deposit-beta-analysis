# Results

Data: FDIC call reports, 10 banks, 2021Q1 to 2025Q4; Fed funds from FRED.

## Average deposit beta by group

| group                 |   Full hiking cycle |   By end of 2022 |   Easing |
|:----------------------|--------------------:|-----------------:|---------:|
| Large                 |                0.56 |             0.36 |     0.45 |
| Super-regional        |                0.51 |             0.28 |     0.36 |
| Regional              |                0.54 |             0.23 |     0.45 |
| Large excl. Citigroup |                0.49 |             0.28 |     0.37 |

## Beta by bank

| bank            | group          |   beta_full_hiking |   beta_by_end_2022 |   beta_easing |
|:----------------|:---------------|-------------------:|-------------------:|--------------:|
| Wells Fargo     | Large          |              0.481 |              0.252 |         0.407 |
| JPMorgan Chase  | Large          |              0.49  |              0.343 |         0.317 |
| Bank of America | Large          |              0.495 |              0.237 |         0.379 |
| Citigroup       | Large          |              0.78  |              0.619 |         0.699 |
| PNC             | Super-regional |              0.483 |              0.285 |         0.302 |
| Truist          | Super-regional |              0.52  |              0.253 |         0.375 |
| U.S. Bancorp    | Super-regional |              0.523 |              0.292 |         0.399 |
| KeyCorp         | Regional       |              0.512 |              0.185 |         0.414 |
| Fifth Third     | Regional       |              0.549 |              0.283 |         0.486 |
| Huntington      | Regional       |              0.555 |              0.225 |         0.441 |

## Lag regression by group

Report the total. Individual lags are highly correlated (back-to-back Fed moves), so the split between them is not reliable.

| group          |   d_ff |   d_ff_l1 |   d_ff_l2 |   d_ff_l3 |   total |   total_se |    r2 |   n |
|:---------------|-------:|----------:|----------:|----------:|--------:|-----------:|------:|----:|
| Large          |  0.253 |     0.281 |    -0.175 |     0.195 |   0.553 |      0.041 | 0.832 |  64 |
| Super-regional |  0.171 |     0.267 |    -0.111 |     0.173 |   0.5   |      0.041 | 0.867 |  48 |
| Regional       |  0.125 |     0.264 |    -0.023 |     0.2   |   0.566 |      0.034 | 0.907 |  48 |