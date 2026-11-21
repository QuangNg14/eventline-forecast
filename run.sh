#!/usr/bin/env bash
set -euo pipefail
unset GH_TOKEN GITHUB_TOKEN PYTHONHOME PYTHONPATH
cd -- "$(dirname -- "$0")"
mkdir -p .work/build out
export TMPDIR="$PWD/.work/build" PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1

flags=(--edition=2021 -D warnings)
if command -v rustc >/dev/null; then
    compiler=rustc
elif [[ -x .work/tc/bin/rustc ]]; then
    compiler=.work/tc/bin/rustc
    flags+=(--target x86_64-unknown-linux-musl -C linker=rust-lld)
else
    echo 'rustc unavailable; see the isolated x86-64 WSL recipe in README.md' >&2
    exit 1
fi
"$compiler" "${flags[@]}" --test ingest/main.rs -o .work/build/ingest-tests
.work/build/ingest-tests
"$compiler" "${flags[@]}" ingest/main.rs -o .work/build/ingest
.work/build/ingest generate out/deliveries.csv
.work/build/ingest replay out/deliveries.csv out/events.csv
python3 -m forecast train out/events.csv 1738713600 out
python3 -m forecast predict out/events.csv out/model-v1.json 1739750400
python3 -m unittest discover -s tests -v
