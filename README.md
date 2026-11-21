# Eventline Forecast

Predict the units of demand in the **next hour** from synthetic, timestamped purchase events. Rust produces and replays the delivery log. Python fits a small ridge regression and serves it from a JSON file. No Cargo packages, Python packages, network service or credentials are needed to run the pipeline.

## Reproduce locally

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
