#!/usr/bin/env python3
"""Publish validated Moneyball 7 scouting trends from a Moneyball 5 gzip feed.

Public NFL utilization ONLY. No Sleeper private league data, trade advice,
injury recency claims or estimated routes. The existing 5/6 feed stays intact.
"""
from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path

from moneyball6_validate import audit
from moneyball7_scout import scout_feed

def build(input_file: Path, output_file: Path, as_of_week: int | None = None) -> dict:
    opener = gzip.open if input_file.suffix == ".gz" else open
    with opener(input_file, "rt", encoding="utf-8") as handle:
        feed = json.load(handle)
    report = audit(feed, max_age_hours=168)
    if report["errors"]:
        raise ValueError("Moneyball6 validation failed: " + "; ".join(report["errors"][:8]))
    trends = scout_feed(feed, as_of_week)
    trends["sourceQuality"] = {
        "status": report["status"],
        "warnings": report["warnings"],
        "metrics": report["metrics"],
    }
    trends["sourceCoverage"] = feed.get("coverage", {})
    trends["sourceStates"] = feed.get("sources", {})
    trends["attribution"] = feed.get("attribution", {})
    output_file.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(trends, ensure_ascii=False, separators=(",", ":"),
                         allow_nan=False).encode("utf-8")
    temporary = Path(str(output_file) + ".tmp")
    if output_file.suffix == ".gz":
        with gzip.open(temporary, "wb", compresslevel=6) as handle:
            handle.write(encoded)
    else:
        temporary.write_bytes(encoded)
    temporary.replace(output_file)
    return {"players": trends["trackedPlayers"],
            "week": trends["asOfWeek"],
            "sourceQuality": report["status"],
            "bytes": output_file.stat().st_size}

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--as-of-week", type=int)
    args = parser.parse_args()
    summary = build(args.input, args.output, args.as_of_week)
    print("MONEYBALL7_SCOUT_FEED_OK", json.dumps(summary, ensure_ascii=False))

if __name__ == "__main__":
    main()
