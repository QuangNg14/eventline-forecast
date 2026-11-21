"""Small centered ridge regression; only the training rows enter the fit."""

import json
from dataclasses import asdict, dataclass
from math import fsum, isfinite, sqrt
from pathlib import Path

from .history import DAY, EVENT_SCHEMA, FEATURES, FEATURE_SCHEMA, HOUR, History

ARTIFACT = "eventline-ridge-v1"
PENALTY = 1.0
SCHEMA = {
    "artifact": ARTIFACT, "event_schema": EVENT_SCHEMA, "feature_schema": FEATURE_SCHEMA,
    "features": list(FEATURES), "target": "units_in_[origin,origin+horizon)",
    "horizon_s": HOUR, "ridge_lambda": PENALTY,
}


def dot(a: tuple[float, ...] | list[float], b: tuple[float, ...] | list[float]) -> float:
    return fsum(x * y for x, y in zip(a, b, strict=True))


def ridge(rows: list[tuple[float, ...]], targets: list[int]) -> tuple[float, tuple[float, ...]]:
    """Solve (X'X + I)w = X'y by Cholesky; intercept is not penalized."""
    n = len(rows)
    means = [fsum(column) / n for column in zip(*rows, strict=True)]
    y_mean = fsum(targets) / n
    columns = [[row[i] - mean for row in rows] for i, mean in enumerate(means)]
    y = [target - y_mean for target in targets]
    size = len(columns)
    lower = [[0.0] * size for _ in columns]
    for i in range(size):
        for j in range(i + 1):
            v = dot(columns[i], columns[j]) - dot(lower[i][:j], lower[j][:j])
            lower[i][j] = sqrt(v + PENALTY) if i == j else v / lower[j][j]
    z = [0.0] * size
    weights = [0.0] * size
    for i in range(size):
        z[i] = (dot(columns[i], y) - dot(lower[i][:i], z[:i])) / lower[i][i]
    for i in reversed(range(size)):
        weights[i] = (z[i] - fsum(lower[j][i] * weights[j] for j in range(i + 1, size))) / lower[i][i]
    return y_mean - dot(weights, means), tuple(weights)


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, sort_keys=True, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8", newline="\n")


@dataclass(frozen=True)
class Model:
    training_start: int
    training_cutoff: int
    last_training_origin: int
    training_rows: int
    max_lateness_s: int
    intercept: float
    weights: tuple[float, ...]

    @classmethod
    def fit(cls, history: History, cutoff: int) -> "Model":
        if cutoff % HOUR:
            raise ValueError("training cutoff must be a whole UTC hour")
        origins = history.mature_origins(history.start + DAY, cutoff)
        if not origins:
            raise ValueError("no mature training labels after warm-up")
        intercept, weights = ridge([history.features(t) for t in origins],
                                   [history.label(t, cutoff) for t in origins])
        return cls(origins[0], cutoff, origins[-1], len(origins), history.lateness, intercept, weights)

    def forecast(self, history: History, origin: int) -> dict:
        if origin < self.training_cutoff or self.max_lateness_s != history.lateness:
            raise ValueError("forecast predates model cutoff or snapshot lateness does not match")
        x = history.features(origin)
        return {
            "origin": origin, "target_end": origin + HOUR,
            "prediction": max(0.0, self.intercept + dot(self.weights, x)),
            "seasonal": x[FEATURES.index("lag_24h")],
        }

    def save(self, path: Path) -> None:
        write_json(path, {**asdict(self), **SCHEMA})

    @classmethod
    def load(cls, path: Path) -> "Model":
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or any(data.get(k) != v for k, v in SCHEMA.items()):
            raise ValueError("incompatible model artifact or feature schema")
        try:
            params = {k: v for k, v in data.items() if k not in SCHEMA}
            if not isinstance(params.get("weights"), list):
                raise ValueError("expected model weights")
            params["weights"] = tuple(params["weights"])
            model = cls(**params)
            times = (model.training_start, model.last_training_origin, model.training_cutoff)
            if not (all(type(t) is int and t >= 0 and t % HOUR == 0 for t in times)
                    and type(model.max_lateness_s) is int and model.max_lateness_s >= 0
                    and type(model.training_rows) is int and model.training_rows > 0
                    and model.training_start + (model.training_rows - 1) * HOUR == model.last_training_origin
                    and model.last_training_origin + HOUR + model.max_lateness_s <= model.training_cutoff
                    and len(model.weights) == len(FEATURES)
                    and all(type(v) in (int, float) and isfinite(v) for v in [model.intercept, *model.weights])):
                raise ValueError("invalid model parameters or training metadata")
        except TypeError as exc:
            raise ValueError("invalid model fields") from exc
        return model
