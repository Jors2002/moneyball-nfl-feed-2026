#!/usr/bin/env python3
"""Moneyball 7.0 scouting foundation: observed utilization, not projections.

Pure standard-library functions; no network, league metadata, private inputs,
fabricated routes, or hidden lookahead. Source: normalized Moneyball 5 feed.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from math import isfinite
from statistics import mean
from typing import Any

FIELDS = ("snapShare", "targetShare", "carries", "targets", "routes",
          "routeParticipation", "targetsPerRoute", "redzoneCarries",
          "inside5Carries", "redzoneTargets", "firstReads", "firstReadShare",
          "receivingAirYards", "aDOT", "ppr")


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if isfinite(value) else None


def _average(rows: list[dict], field: str) -> dict:
    available = [_num(row.get(field)) for row in rows]
    values = [v for v in available if v is not None]
    return {"mean": round(mean(values), 5) if values else None,
            "observations": len(values), "windowGames": len(rows)}


def player_trend(weekly: list[dict], as_of_week: int, short: int = 2,
                 long: int = 4) -> dict:
    """No row with week > as_of_week is inspected; older baseline excludes recent rows.

    Empty/no-coverage weeks do not count as zero. No statistical significance or
    causal interpretation is claimed. A 'direction' requires 2 observations in
    BOTH disjoint windows; delta is descriptive, not a forecast.
    """
    if not isinstance(as_of_week, int) or isinstance(as_of_week, bool) or not 1 <= as_of_week <= 18:
        raise ValueError("as_of_week must be a regular-season week 1..18")
    if not 1 <= short <= 4 or not short < long <= 8:
        raise ValueError("windows require 1 <= short < long <= 8")
    rows = [r for r in weekly if isinstance(r, dict)
            and type(r.get("week")) is int and 1 <= r["week"] <= as_of_week]
    weeks = [r["week"] for r in rows]
    if len(weeks) != len(set(weeks)):
        raise ValueError("duplicate player-week")
    rows.sort(key=lambda r: r["week"])
    recent = rows[-short:]
    previous = rows[-long:-short]
    fields = {}
    for field in FIELDS:
        now = _average(recent, field)
        before = _average(previous, field)
        delta = (round(now["mean"] - before["mean"], 5)
                 if now["observations"] >= 2 and before["observations"] >= 2
                 and now["mean"] is not None and before["mean"] is not None
                 else None)
        fields[field] = {"recent": now, "previous": before, "delta": delta,
                         "direction": ("up" if delta > 0 else "down" if delta < 0 else "flat")
                         if delta is not None else "insufficient_data"}
    return {"asOfWeek": as_of_week, "shortWindow": short, "longWindow": long,
            "recentWeeks": [r["week"] for r in recent],
            "previousWeeks": [r["week"] for r in previous],
            "metrics": fields}


def scout_feed(feed: dict, as_of_week: int | None = None) -> dict:
    """Add read-only scouting output; never mutate the validated source feed."""
    if feed.get("schemaVersion") != 5 or feed.get("season") != 2026:
        raise ValueError("requires validated Moneyball 5 2026 feed")
    through = feed.get("thruWeek")
    if type(through) is not int or not 1 <= through <= 18:
        raise ValueError("invalid thruWeek")
    cutoff = through if as_of_week is None else as_of_week
    if type(cutoff) is not int or not 1 <= cutoff <= through:
        raise ValueError("as_of_week exceeds data coverage")
    source = feed.get("bySleeper")
    if not isinstance(source, dict):
        raise ValueError("bySleeper missing")
    players = {}
    coverage = defaultdict(int)
    for sid, weekly in sorted(source.items()):
        if not isinstance(sid, str) or not sid.isdigit() or not isinstance(weekly, list):
            raise ValueError("invalid bySleeper key/rows")
        result = player_trend(weekly, cutoff)
        players[sid] = result
        for key, item in result["metrics"].items():
            if item["delta"] is not None:
                coverage[key] += 1
    return {"schemaVersion": 7, "sourceSchemaVersion": 5, "season": 2026,
            "sourceGeneratedAt": feed.get("generatedAt"),
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "asOfWeek": cutoff, "trackedPlayers": len(players),
            "comparablePlayersByMetric": dict(sorted(coverage.items())),
            "limitations": [
                "Descriptive utilization changes; not projections, calibrated probabilities, or causal findings.",
                "Unknown routes/first reads/injuries remain unavailable, never zero.",
                "A player-week without a row is not a confirmed zero.",
                "As-of weeks prevent future game statistics entering historical evaluations."
            ], "bySleeper": players}
