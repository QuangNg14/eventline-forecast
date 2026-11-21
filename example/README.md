# Measured synthetic run

The fixed generator (seed 173) spans **2025-01-06 00:00 to 2025-02-17 00:00 UTC**, with the end excluded for occurrence and included for deliveries. It mixes a daily shape, weekday effect, drifting demand level, sparse zero hours and bounded receipt delays. Rust 1.85.1 on x86-64 WSL Ubuntu produced **20,477 deliveries**, **18,429 distinct events** and **2,048 retries**. Python 3.12.3 fitted one model.

| Frozen forecast, same 286 test hours | Held-out MAE (units/hour) |
|---|---:|
| Fitted ridge regression | 4.573041681331119 |
| Previous day, same hour | 8.573426573426573 |

The ridge model won this comparison. This is one synthetic series, one seed, one chronological split and one fixed horizon; it is not evidence of real-world forecasting performance. Both stages hold the small dataset in memory. The result depends on continuous coverage, immutable facts and the declared delivery guarantee.

Of 1,008 occurrence hours, 24 warm up the features. **694 training origins** run from Jan 7 00:00 through Feb 4 21:00. The next two origins have labels that are not yet final at the Feb 5 00:00 cutoff. **286 test origins** run Feb 5 00:00 through Feb 16 21:00. The last two hours of the snapshot are also not mature and are not scored.

| Issue time (UTC) | Predicted units | Seasonal | Actual units |
|---|---:|---:|---:|
| Feb 5 00:00, first held-out hour | 24.28955541333481 | 22 | 22 |
| Feb 17 00:00, next unseen hour | 21.367152929686792 | 23 | Unknown; outside coverage |

## Reproduce and inspect

From the project root, `bash run.sh` builds and runs every stage (see [prerequisites and isolated compiler](../README.md)). `out/heldout.jsonl` has one row per scored hour, including the origin, exclusive target end, both forecasts and the actual. For example, from WSL Bash:

```bash
unset GH_TOKEN GITHUB_TOKEN
python3 -B -s -m forecast predict out/events.csv example/model-v1.json 1738713600
head -n 1 out/heldout.jsonl
sha256sum out/{deliveries.csv,events.csv,model-v1.json,metrics.json,heldout.jsonl}
```

| Generated file | SHA-256 on measured toolchain |
|---|---|
| `deliveries.csv` | `b47c7da239f07d59d5cefc09de3901229600a2805897842cc230eb0bf85eea5d` |
| `events.csv` | `ae598ecdd4938b1f1db809ebdfa984e1818afad0d6b34b22015ae33f2e581c1f` |
| `model-v1.json` | `1827e8a791db40a8e8ed3626cf23d158d75755bc0915958fbd03c2ac6de14273` |
| `metrics.json` | `4f17fa283303186e4909466e553657ad63df644fb32833fbea856130bb2bf0af` |
| `heldout.jsonl` | `dd0a7928c31a395977ea8705e35f866cf36f3a423ee7037994548dfea40a7711` |

## Acceptance checks

`bash run.sh` compiles `ingest/main.rs` with `rustc --test`, runs the binary, and runs `python3 -m unittest discover -s tests -v` after the demo.

| Test | What it checks |
|---|---|
| `retries_keep_first_receipt_regardless_of_order` | Permutation, normalization and repeated replay produce the same canonical facts. |
| `conflicts_are_errors_in_either_order` | Changed units or occurrence for an ID is not a retry. |
| `rejects_invalid_deliveries_and_windows` | Receipt bounds, lateness, amount, schema and window violations fail. |
| `test_known_lag_and_rolling_at_receipt_boundary` | Hand-computed lag and rolling values exclude a late receipt and target-hour occurrence; the late receipt enters later. |
| `test_target_requires_coverage_and_maturity_even_if_empty` | A mature zero and an unknown target are distinct, including after the end of coverage. |
| `test_ridge_matches_hand_solved_fit` | Solver reproduces analytic slope and intercept on a three-row problem. |
| `test_cli_parity_and_mae_on_every_heldout_hour` | Reload matches training-time evaluation on all 286 rows; three separate CLI calls match exactly. Recomputes both MAEs and serves an unlabeled future hour. |
| `test_changed_future_and_late_facts_leave_fit_and_issue_unchanged` | At Feb 5 01:00, inflate every later-received fact, including two already occurred. Refit bytes, as-of features and CLI forecast are unchanged. A physically truncated snapshot gives the same fit and forecast. The changed target and next prediction differ. |
| `test_identical_rerun_and_reordered_redelivery` | Two in-place reruns match all five original outputs byte for byte. Reverse and redeliver the full input and canonical bytes still match. |
| `test_incompatible_artifact_or_backdated_issue_rejected` | Reject incompatible version/order/horizon/weights, an impossible training cutoff and a pre-fit issue time. |

## File inventory

| Directory | Files |
|---|---|
| Root | `.gitattributes`, `.gitignore`, `LICENSE`, `README.md`, `run.sh` |
| `ingest/` | `main.rs`, `replay.rs`, `synthetic.rs` |
| `forecast/` | `__init__.py`, `__main__.py`, `history.py`, `model.py` |
| `tests/` | `test_forecast.py`, `test_pipeline.py` |
| `example/` | `README.md`, `model-v1.json`, `metrics.json` |
| `out/` (ignored, reproducible) | `deliveries.csv`, `events.csv`, `heldout.jsonl`, `metrics.json`, `model-v1.json` |
