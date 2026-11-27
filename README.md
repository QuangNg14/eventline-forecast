# Eventline Forecast

Predict the **next hour** of demand from a real series of hourly Seoul bike rentals or a synthetic purchase stream. Both use the same Python ridge model, point-in-time features, previous-day baseline and JSON serving path. The synthetic stream also exercises the Rust delivery replay. No external packages, API key or hosted service are required.

On the **synthetic** [286 held-out hours](example/metrics.json), mean absolute error was **4.57 units/hour** for ridge regression and **8.57** for the previous-day, same-hour baseline. The calendar features reflect the [generator's](ingest/synthetic.rs) afternoon peak and weekday effect. The real series below is a separate experiment, not a combination of the two scores.

## Real hourly series: Seoul bike rentals

Source: Easwaramoorthy, S. (2020), *Seoul Bike Sharing Demand*, [UCI Machine Learning Repository](https://archive.ics.uci.edu/dataset/560/seoul+bike+sharing+demand), [DOI 10.24432/C5F62R](https://doi.org/10.24432/C5F62R), licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). This adapter selects the date, hour and rental count, converts Seoul time to UTC, and derives daily partitions and lag features. Weather, holidays, service flags and future counts are not inputs. Raw and derived data stay in ignored `out/seoul/`. The [adapter](forecast/seoul.py) verifies the archive SHA-256 `139e9908f0a3544bb222386855c9ce107e96467306bb8e4ce936aab59e7baac4` on every run.

```powershell
python -B -S -m forecast.seoul
python -B -S -m forecast.seoul --date 2018-11-01
python -B -S -m forecast predict out/seoul/events.csv out/seoul/model-v1.json 1540998000
```

The first command downloads the archive once, rebuilds all 365 local-date partitions and evaluates the model. `--date` replaces only that day's partition; run without it to regenerate the combined model and scores. The November 1 backfill and full rerun reproduced the same partition, replay, model, held-out rows and metrics bytes.

| Chronological evaluation | Result |
|---|---:|
| Coverage (Seoul local time, end exclusive) | Dec 1, 2017 to Dec 1, 2018: 8,760 hours |
| Training labels final at Nov 1, 2018 00:00 KST | 8,015 |
| Held-out origins, Nov 1 through Nov 30, one-hour horizon | 720 |
| Ridge MAE, rentals/hour | **172.38** |
| Previous day, same hour MAE, rentals/hour | **283.19** |

These are observed rental counts, not unconstrained demand. The 295 reported zero hours are retained; they coincide with the source's non-functioning hours. The existing model uses UTC calendar features, fixed ridge penalty 1, and no holdout tuning. One city's historical month and an assumed reporting schedule do not establish live forecast accuracy.

**Ingestion contract.** The CSV must contain unique column names and the three required columns. Every selected KST date must have all 24 integer hours (0–23), each with an unsigned integer count below 2³². Identical `(date, hour, count)` repeats collapse. Out-of-order rows, including earlier dates encountered later in the file, are counted and sorted into their occurrence partition. A conflicting count, bad field, missing hour, or stale final hour writes an explanation to `quarantine.jsonl` and fails the backfill before replacing partitions. A schema or archive-checksum mismatch stops before row processing. Freshness here means the greatest valid observation reaches the last hour of the **requested archive range**, not today's date. Partitions replace atomically per date; use one backfill writer.

**Availability assumption.** UCI does not provide original arrival timestamps. The backtest treats each hourly total as observable at hour close, never earlier: a nonzero aggregate is encoded at the last second of its hour with receipt one second later. The existing mature-label rule adds its conservative one-second margin after close; the terminal snapshot is one second past the last close. A zero is omitted from the sparse replay only after the partition contract proves the source supplied that hour. Missing hours never become zeros. This tests historical, as-of forecasting under that assumption, not live late-delivery behavior.

## Reproduce the synthetic stream locally

From this directory, use Bash, a working Rust compiler (edition 2021, Rust 1.65+), and Python 3.10+. On the measured WSL Ubuntu host, Python was already present but `rustc` and a C compiler were not. The [isolated toolchain recipe](#isolated-rust-for-x86-64-wsl) covers that case. With a compiler available:

```bash
bash run.sh
```

The script unsets `GH_TOKEN` and `GITHUB_TOKEN`, compiles Rust, tests replay, generates the dataset, replays it, fits and evaluates the model, issues an unscored forecast and runs the Python tests. It replaces the five generated data/model files under `out/`. Build and test scratch stays in `.work/`. From PowerShell on the measured machine:

```powershell
Set-Location 'C:\QuangNg14-Portfolio\eventline-forecast'
Remove-Item Env:GH_TOKEN,Env:GITHUB_TOKEN -ErrorAction SilentlyContinue
wsl -d Ubuntu --exec env -i PATH=/usr/bin:/bin LANG=C.UTF-8 /bin/bash run.sh
```

Use the stages separately after building, from the project root:

```bash
unset GH_TOKEN GITHUB_TOKEN
export PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1
.work/build/ingest generate out/deliveries.csv
.work/build/ingest replay out/deliveries.csv out/events.csv
python3 -m forecast train out/events.csv 1738713600 out
python3 -m forecast predict out/events.csv out/model-v1.json 1738713600
python3 -m forecast predict out/events.csv out/model-v1.json 1739750400
```

The last two commands issue forecasts at the first held-out origin and at the end of observation. `example/model-v1.json` is a copy of the measured model and can be substituted for `out/model-v1.json`. See [the measured run](example/README.md) for results, checksums, test names and file inventory.

## What was known when?

All timestamps are integer UTC Unix seconds. The first line of either dataset declares the window instead of inferring coverage from the last purchase:

```text
eventline-v1,occurrence_start,occurrence_end,max_lateness_s,observed_through
event_id,occurred_at,available_at,units
```

These are two header lines: the first contains **numeric values** in the file. The input is deliberately restricted, unquoted comma-separated ASCII, not general-purpose CSV. `occurred_at` assigns demand to an hour. `available_at` is the time that delivery was first observable, **not** its shuffled row position. The generator covers `[start,end)` continuously, emits all deliveries through the inclusive snapshot time and guarantees first receipt within two hours of occurrence. Some hours deliberately have no demand. Coverage is a producer promise; no replay can detect an event the producer silently lost.

| At issue time `t` (a whole UTC hour) | Rule |
|---|---|
| History | Only prior occurrence hours and first receipts `<= t`. An event occurring exactly at `t` belongs to the target, even if already received. |
| Features | Units in hour `t-1h`, mean hourly units over the previous 6 and 24 hours, units in hour `t-24h`, UTC hour, hours after noon, weekend indicator. Require 24 hours of history. |
| Target | Total units with occurrence in `[t,t+1h)`. Label only if the whole hour is covered **and** `t+1h+max_lateness <= label_as_of <= observed_through`. Only then can an empty target be zero. |
| Training | Labels must be final by the training cutoff; features still use each row's own issue time, not the cutoff. Ridge uses raw feature units, fixed penalty 1, centered columns, an unpenalized intercept and a nonnegative forecast. |
| Evaluation | Freeze the fitted model. Advance the issue time one hour per row, allowing newly arrived history. Compare its MAE with the previous day's same-hour units known at that identical origin. No tuning or random split. |
| Serving | The CLI loads the schema, horizon, feature order, weights and training cutoff. It calls the same `History.features` and `Model.forecast` used in evaluation. It rejects backdating and can predict at the observation boundary without looking up a label. |

**Training-time leakage:** [`Model.fit`](forecast/model.py) computes features at each training hour, not at the later cutoff used to finalize labels. The [receipt-boundary test](tests/test_forecast.py) checks those lag and rolling values by hand: a past-hour event received one second after the forecast cannot count yet, and a target-hour event cannot enter history.

**Inference parity:** The [CLI parity test](tests/test_pipeline.py) reloads the saved model and compares its forecasts with all 286 held-out rows. It also checks the CLI output at the first, middle, and last held-out hours. A separate test changes later receipts and confirms that an earlier forecast stays fixed.

Rust trims fields, normalizes ASCII identifiers to lowercase and unsigned decimal fields to integers. For repeated IDs, occurrence and units must agree; earliest delivery wins. Conflicting facts fail the replay before it writes a result. A canonical replay sorts by first receipt, occurrence and ID. Input order, identical redelivery and later retries do not change it.

## Isolated Rust for x86-64 WSL

Skip this if `rustc` already works. Otherwise, from the project root in **x86-64 Ubuntu Bash**, the following downloads two pinned archives from the official Rust distribution and checks their SHA-256 hashes **before** extraction. The bundled linker and musl target avoid installing a system linker or C development packages. No installer, `sudo`, shell profile or package cache is involved. Only this setup needs network access.

```bash
(
  set -euo pipefail
  unset GH_TOKEN GITHUB_TOKEN
  mkdir -p .work/tc
  cd .work
  host=rustc-1.85.1-x86_64-unknown-linux-gnu.tar.xz
  std=rust-std-1.85.1-x86_64-unknown-linux-musl.tar.xz
  base=https://static.rust-lang.org/dist/2025-03-18
  for file in "$host" "$std"; do
    curl -q --fail --show-error --silent --proto '=https' --max-time 240 \
      "$base/$file" -o "$file"
  done
  printf '%s  %s\n' \
    92a5c532b9e87912190128704e0d65825912e3b08a6ee9203c4068d6d1df62c4 "$host" \
    a2a99b60e86214a836e53396f3a0716a48724902b9dd8c69f146897efc76691e "$std" | sha256sum -c -
  tar -xJf "$host" --strip-components=2 -C tc --wildcards '*/rustc/bin' '*/rustc/lib'
  tar -xJf "$std" --strip-components=2 -C tc --wildcards '*/rust-std-x86_64-unknown-linux-musl/lib'
  tc/bin/rustc --version
)
```

Run `bash run.sh`, then remove the project-local `.work/` directory when finished. Python can still serve forecasts from `out/` without Rust.
