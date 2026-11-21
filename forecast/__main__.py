"""Train, evaluate and serve a local one-hour demand forecast."""

import argparse
import json
import sys
from math import fsum
from pathlib import Path

from .history import History
from .model import Model, write_json


def train(events: Path, cutoff: int, output: Path) -> dict:
    h = History.load(events)
    model = Model.fit(h, cutoff)
    origins = h.mature_origins(cutoff, h.through)
    if not origins:
        raise ValueError("no mature held-out targets at this cutoff")
    heldout = [{**model.forecast(h, t), "actual": h.label(t, h.through)} for t in origins]
    metrics = {
        "training_rows": model.training_rows, "training_cutoff": cutoff,
        "test_rows": len(heldout), "first_test_origin": origins[0], "last_test_origin": origins[-1],
        "observed_through": h.through, "occurrence_start": h.start, "occurrence_end": h.end,
        "model_mae": fsum(abs(row["prediction"] - row["actual"]) for row in heldout) / len(heldout),
        "seasonal_mae": fsum(abs(row["seasonal"] - row["actual"]) for row in heldout) / len(heldout),
    }
    output.mkdir(parents=True, exist_ok=True)
    model.save(output / "model-v1.json")
    write_json(output / "metrics.json", metrics)
    with (output / "heldout.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for row in heldout:
            f.write(json.dumps(row, allow_nan=False) + "\n")
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    fit = commands.add_parser("train", help="fit on mature pre-cutoff labels and score held-out hours")
    fit.add_argument("events", type=Path)
    fit.add_argument("cutoff", type=int, help="whole-hour UTC Unix seconds")
    fit.add_argument("output", type=Path)
    predict = commands.add_parser("predict", help="forecast using a saved model")
    predict.add_argument("events", type=Path)
    predict.add_argument("model", type=Path)
    predict.add_argument("origin", type=int, help="whole-hour UTC Unix seconds")
    args = parser.parse_args()
    try:
        if args.command == "train":
            result = train(args.events, args.cutoff, args.output)
        else:
            result = Model.load(args.model).forecast(History.load(args.events), args.origin)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"forecast: {exc}\n")
    sys.stdout.write(json.dumps(result, sort_keys=True, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
