#!/usr/bin/env python3
"""Moneyball 7.2: forward-only PPR baselines, walk-forward diagnostics, injury provenance.

A statistical baseline conditional on participation is NOT an NFL game forecast.
No data about the user's fantasy league enters this public repository.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import json
import math
from pathlib import Path
from statistics import mean, median, stdev

SEASON = 2026
SCHEMA = 72


def finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(value)


def observed_games(rows: list, as_of_week: int) -> list[tuple[int, float]]:
    """No placeholders for bye, injured weeks, or stats that were not charted."""
    if not isinstance(rows, list):
        raise ValueError("Player weekly rows must be a list")
    game_map = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Player row is not an object")
        week = row.get("week")
        if not isinstance(week, int) or isinstance(week, bool) or not 1 <= week <= 18:
            raise ValueError("Invalid week in player history")
        if week > as_of_week:
            continue  # Hard cutoff: never see the future.
        if week in game_map:
            raise ValueError("Duplicate player-week (ambiguous observations)")
        game_map[week] = row.get("ppr")
    return sorted((w, float(p)) for w, p in game_map.items() if finite(p))


def baseline(games: list[tuple[int, float]], as_of_week: int,
             lookback: int = 4, minimum: int = 3) -> dict:
    prior = [(w, y) for w, y in games if w <= as_of_week][-lookback:]
    n = len(prior)
    result = {"mean": None, "median": None, "sd": None, "games": n,
              "weeks": [w for w, _ in prior], "lastObservedWeek": prior[-1][0] if prior else None,
              "quality": "INSUFFICIENT_DATA"}
    if n < minimum:
        return result
    scores = [y for _, y in prior]
    result.update({"mean": round(mean(scores), 4),
                   "median": round(median(scores), 4),
                   "sd": round(stdev(scores), 4) if n >= 2 else None,
                   "quality": "HISTORICAL_BASELINE"})
    if as_of_week - prior[-1][0] >= 2:
        result["quality"] = "STALE_PLAYER_HISTORY"
    return result


def walk_forward(by_sleeper: dict, as_of_week: int) -> dict:
    errors = []
    samples_per_week = {}
    for sid, rows in by_sleeper.items():
        games = observed_games(rows, as_of_week)
        truth = dict(games)
        for week, actual in games:
            if week < 4:
                continue
            guess = baseline(games, week - 1)
            if guess["mean"] is None or guess["quality"] == "STALE_PLAYER_HISTORY":
                continue
            deviation = guess["mean"] - actual
            errors.append((week, deviation))
            samples_per_week[week] = samples_per_week.get(week, 0) + 1
    if not errors:
        return {"status": "INSUFFICIENT_DATA", "examples": 0,
                "mae": None, "bias": None, "weeksTested": [], "nByWeek": {}}
    absolute = [abs(e) for _, e in errors]
    errors_by_week = sorted(samples_per_week)
    # Scores conditional on participation, with survivor bias. Do NOT label
    # success in playoffs or weekly win probability as validated.
    return {"status": "EXPLORATORY_WALK_FORWARD",
            "examples": len(errors),
            "mae": round(mean(absolute), 4),
            "bias": round(mean(e for _, e in errors), 4),
            "medianAbsoluteError": round(median(absolute), 4),
            "weeksTested": errors_by_week, "nByWeek": {str(w): samples_per_week[w] for w in errors_by_week},
            "restriction": "Only games with observed PPR; byes, missed games, lineup decisions and availability are NOT modeled."}


def evidence_date(raw, generated_at: datetime) -> tuple[str | None, str]:
    """Trust ONLY explicit time zone and a timestamp no later than publication."""
    if not isinstance(raw, str) or not raw.strip():
        return None, "NO_SOURCE_TIMESTAMP"
    raw = raw.strip()
    if len(raw) == 10 and raw[4:5] == "-":
        return None, "DATE_ONLY_NOT_EVENT_TIMESTAMP"
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None, "TIMEZONE_UNKNOWN"
        if parsed.astimezone(timezone.utc) > generated_at:
            return None, "FUTURE_TIMESTAMP"
        return parsed.astimezone(timezone.utc).isoformat(), "DATED_SOURCE_RECORD"
    except (ValueError, TypeError):
        return None, "UNPARSEABLE_TIMESTAMP"


def injury_evidence(injuries: dict, as_of_week: int, generated_at: datetime) -> tuple[dict, dict]:
    """Do not transform weekly history into a 'live' or official medical alert."""
    by_id = {}
    quality = {"records": 0, "datedRecords": 0, "withCurrentWeek": 0,
               "undatedRecords": 0, "staleDaysThreshold": 7}
    for sid, rows in injuries.items():
        if not str(sid).isdigit() or not isinstance(rows, list):
            continue
        eligible = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            w = r.get("week")
            if not isinstance(w, int) or w > as_of_week + 1 or w < 1:
                continue
            stamp, status = evidence_date(r.get("dateModified"), generated_at)
            quality["records"] += 1
            quality["datedRecords" if stamp else "undatedRecords"] += 1
            if w == as_of_week + 1:
                quality["withCurrentWeek"] += 1
            eligible.append((w, stamp or "", r, status, stamp))
        if not eligible:
            continue
        # Without a dated entry, week order is useful history, not current advice.
        w, _, latest, status, stamp = max(eligible, key=lambda x: (x[0], x[1]))
        age_days = (generated_at - datetime.fromisoformat(stamp)).total_seconds() / 86400 if stamp else None
        by_id[str(sid)] = {
            "week": w, "practiceStatus": latest.get("practiceStatus") or None,
            "reportStatus": latest.get("reportStatus") or None,
            "primaryInjury": latest.get("primaryInjury") or None,
            "sourceTimestamp": stamp,
            "evidence": ("DATED_BUT_OLD" if age_days is not None and age_days > 7
                         else status),
            "ageDaysAtGeneration": round(age_days, 2) if age_days is not None else None
        }
    quality["players"] = len(by_id)
    quality["status"] = ("PARTIAL_DATED" if quality["datedRecords"]
                         else "UNVERIFIED_DATES")
    return by_id, quality


def build(feed: dict, as_of_week: int | None = None) -> dict:
    if feed.get("schemaVersion") != 5 or feed.get("season") != SEASON:
        raise ValueError("Expected existing Moneyball 5 source, season 2026")
    source_through = feed.get("thruWeek")
    if not isinstance(source_through, int) or not 1 <= source_through <= 18:
        raise ValueError("Invalid source week")
    through = source_through if as_of_week is None else as_of_week
    if not isinstance(through, int) or not 1 <= through <= source_through:
        raise ValueError("Future-week request or invalid cutoff")
    players = feed.get("bySleeper")
    if not isinstance(players, dict) or not players:
        raise ValueError("No player histories")
    source_at = datetime.fromisoformat(str(feed["generatedAt"]).replace("Z", "+00:00"))
    if source_at.tzinfo is None:
        raise ValueError("Source generatedAt requires explicit UTC offset")
    generated_at = datetime.now(timezone.utc)
    if source_at > generated_at:
        raise ValueError("Source generatedAt is in the future")
    out = {}
    low = 0
    for sid, rows in players.items():
        if not str(sid).isdigit():
            raise ValueError("Invalid Sleeper ID")
        games = observed_games(rows, through)
        b = baseline(games, through)
        if b["mean"] is None:
            low += 1
        out[str(sid)] = b
    inj, quality = injury_evidence(feed.get("injuriesBySleeper", {}),
                                   through, generated_at)
    backtest = walk_forward(players, through)
    return {
        "schemaVersion": SCHEMA, "season": SEASON, "asOfWeek": through,
        "sourceGeneratedAt": feed["generatedAt"],
        "generatedAt": generated_at.isoformat(),
        "sourceSchemaVersion": 5,
        "bySleeper": out,
        "injuryEvidenceBySleeper": inj,
        "walkForward": backtest,
        "quality": {
            "players": len(out), "withHistoricalBaseline": len(out) - low,
            "withoutHistoricalBaseline": low, "injuries": quality,
            "routesAvailability": "NOT_INFERRED",
            "reliability": "CONDITIONAL_ON_GAME_PLAYED",
            "playoffOdds": "NOT_CALIBRATED",
        },
        "attribution": feed.get("attribution", {}),
        "limitations": [
            "Rolling four observed games, minimum three; NOT a future-game projection.",
            "Walk-forward error is conditional on games played and selection-biased.",
            "Byes, medical availability, lineup locks, opponent and weather are not modeled here.",
            "Injury records are relayed by nflverse, NOT separately confirmed against each team's current official report.",
            "Source dates without explicit timezone are unverified. Routes and private NFL tracking are not fabricated.",
            "No championship percentages or trade acceptance probabilities are calculated."
        ],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-gzip", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--as-of-week", type=int, default=None)
    a = ap.parse_args()
    with gzip.open(a.source_gzip, "rt", encoding="utf-8") as f:
        feed = json.load(f)
    result = build(feed, a.as_of_week)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(a.output) + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    tmp.replace(a.output)
    print("MONEYBALL72_BASELINES_OK", result["asOfWeek"], result["quality"],
          "WALK_FORWARD", result["walkForward"])

if __name__ == "__main__":
    main()
