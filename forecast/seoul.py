"""Backfill UCI Seoul Bike Sharing Demand into dated, complete hourly partitions."""

import argparse
import csv
import hashlib
import io
import json
import re
import urllib.request
import zipfile
from collections.abc import Iterator
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .__main__ import train
from .history import HOUR

ROOT = Path(__file__).resolve().parents[1] / "out" / "seoul"
URL = "https://archive.ics.uci.edu/static/public/560/seoul+bike+sharing+demand.zip"
SHA256 = "139e9908f0a3544bb222386855c9ce107e96467306bb8e4ce936aab59e7baac4"
FIRST, END, HOLDOUT = date(2017, 12, 1), date(2018, 12, 1), date(2018, 11, 1)
KST = timezone(timedelta(hours=9))


def midnight(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=KST).timestamp())


def days(start: date, end: date) -> Iterator[date]:
    for offset in range((end - start).days):
        yield start + timedelta(days=offset)


def replace(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(path)


def source(root: Path) -> str:
    path = root / "uci-560.zip"
    if path.exists():
        raw = path.read_bytes()
    else:
        with urllib.request.urlopen(URL, timeout=60) as response:
            raw = response.read()
    if hashlib.sha256(raw).hexdigest() != SHA256:
        raise ValueError("UCI archive SHA-256 mismatch; no partitions changed")
    if not path.exists():
        path.write_bytes(raw)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        return archive.read("SeoulBikeData.csv").decode("latin-1")


def backfill(text: str, root: Path, start: date, end: date) -> dict:
    if not FIRST <= start < end <= END:
        raise ValueError(f"dates outside archive: expected [{FIRST}, {END})")
    reader = csv.reader(io.StringIO(text))
    header = next(reader, [])
    required = ("Date", "Hour", "Rented Bike Count")
    if len(set(header)) != len(header) or not set(required) <= set(header):
        raise ValueError("missing or duplicate source columns")
    date_col, hour_col, count_col = (header.index(name) for name in required)
    partitions: dict[date, dict[int, int]] = {day: {} for day in days(start, end)}
    rejected = []
    duplicates = out_of_order = 0
    latest = -1
    for line, row in enumerate(reader, 2):
        def reject(reason: str) -> None:
            rejected.append({"line": line, "reason": reason, "row": row})

        if len(row) != len(header):
            reject("wrong column count")
            continue
        try:
            day = datetime.strptime(row[date_col], "%d/%m/%Y").date()
        except ValueError:
            reject("invalid local date")
            continue
        if not FIRST <= day < END:
            reject("date outside archive")
            continue
        if not start <= day < end:
            continue
        if not re.fullmatch(r"[0-9]{1,2}", row[hour_col]) or int(row[hour_col]) >= 24:
            reject("hour outside 0..23 or not an integer")
            continue
        h = int(row[hour_col])
        if not re.fullmatch(r"[0-9]{1,10}", row[count_col]) or int(row[count_col]) >= 2**32:
            reject("count outside uint32 or not an integer")
            continue
        count = int(row[count_col])
        timestamp = midnight(day) + h * HOUR
        out_of_order += timestamp < latest
        latest = max(latest, timestamp)
        old = partitions[day].get(h)
        if old is not None:
            if old == count:
                duplicates += 1
            else:
                reject("conflicting duplicate hour")
        else:
            partitions[day][h] = count
    for day, hourly in partitions.items():
        missing = sorted(set(range(24)) - hourly.keys())
        if missing:
            rejected.append({"date": day.isoformat(), "reason": "missing hours", "hours": missing})
    last_expected = midnight(end) - HOUR
    if latest != last_expected:
        rejected.append({"reason": "stale archive coverage", "latest_hour": latest, "expected": last_expected})
    root.mkdir(parents=True, exist_ok=True)
    replace(root / "quarantine.jsonl", "".join(json.dumps(r) + "\n" for r in rejected))
    if rejected:
        raise ValueError(f"{len(rejected)} quarantine records; backfill not applied (see {root / 'quarantine.jsonl'})")
    target = root / "days"
    target.mkdir(exist_ok=True)
    for day, hourly in partitions.items():
        replace(target / f"{day}.csv", "hour,count\n" + "".join(f"{h},{hourly[h]}\n" for h in range(24)))
    return {"days": len(partitions), "hours": len(partitions) * 24, "duplicate_rows": duplicates,
            "out_of_order_rows": out_of_order, "latest_hour": latest, "quarantine_records": len(rejected)}


def export_events(root: Path, start: date = FIRST, end: date = END) -> Path:
    rows = [f"eventline-v1,{midnight(start)},{midnight(end)},1,{midnight(end)+1}\n",
            "event_id,occurred_at,available_at,units\n"]
    for day in days(start, end):
        with (root / "days" / f"{day}.csv").open(encoding="ascii", newline="") as stream:
            reader = csv.reader(stream)
            if next(reader, None) != ["hour", "count"]:
                raise ValueError(f"invalid partition header: {day}")
            hours = list(reader)
        if len(hours) != 24:
            raise ValueError(f"incomplete partition: {day}")
        for h, row in enumerate(hours):
            if len(row) != 2 or row[0] != str(h) or not re.fullmatch(r"[0-9]{1,10}", row[1]) or int(row[1]) >= 2**32:
                raise ValueError(f"invalid partition row: {day} hour {h}")
            if int(row[1]):
                close = midnight(day) + (h + 1) * HOUR
                rows.append(f"seoul-{day}-{h:02d},{close-1},{close},{row[1]}\n")
    events = root / "events.csv"
    replace(events, "".join(rows))
    return events


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", type=date.fromisoformat, help="rebuild only this Seoul calendar date")
    args = parser.parse_args()
    ROOT.mkdir(parents=True, exist_ok=True)
    try:
        start, end = (args.date, args.date + timedelta(days=1)) if args.date else (FIRST, END)
        counts = backfill(source(ROOT), ROOT, start, end)
        if not args.date:
            counts.update(train(export_events(ROOT), midnight(HOLDOUT), ROOT))
        print(json.dumps(counts, sort_keys=True))
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        parser.exit(1, f"seoul: {exc}\n")


if __name__ == "__main__":
    main()
