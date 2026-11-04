#!/usr/bin/env python3
"""Moneyball 7 context: defense and kicking opportunity data from public nflverse PBP.

Observations, NOT projected fantasy points. A metric missing in the source is
not converted into a zero. No private league data, cloud subscription, or
scraping. Source: nflverse (CC-BY 4.0) / DynastyProcess ID crosswalk.
"""
from __future__ import annotations
import argparse
import gzip
import json
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

from moneyball5_etl import SEASON, SOURCES, pull, load_identity, json_native

COLUMNS = ["season", "season_type", "week", "game_id", "play_id",
           "posteam", "defteam", "qb_dropback", "pass_attempt",
           "sack", "interception", "fumble_lost", "rush_attempt",
           "field_goal_attempt", "field_goal_result",
           "field_goal_kicker_player_id", "kick_distance",
           "extra_point_attempt", "extra_point_result",
           "extra_point_kicker_player_id"]

# Never silently infer a missing field as 0.
DEFENSE_METRICS = {"opponentDropbacks": "qb_dropback", "sacks": "sack",
                   "interceptions": "interception",
                   "opponentFumblesLost": "fumble_lost",
                   "opponentPassAttempts": "pass_attempt",
                   "opponentRushAttempts": "rush_attempt"}


def build_context(pbp: pd.DataFrame, gsis_to_sid: dict[str, str], through: int) -> dict:
    required = {"season", "season_type", "week", "game_id", "play_id", "posteam", "defteam"}
    missing = required - set(pbp.columns)
    if missing:
        raise ValueError("Missing required PBP columns: " + ", ".join(sorted(missing)))
    if not 1 <= through <= 18:
        raise ValueError("invalid week")
    df = pbp.loc[
        (pd.to_numeric(pbp.season, errors="coerce") == SEASON)
        & (pbp.season_type.astype(str).str.upper() == "REG")
        & pd.to_numeric(pbp.week, errors="coerce").between(1, through)
    ].copy()
    df["week"] = pd.to_numeric(df["week"]).astype(int)
    if df.empty or through not in df.week.values:
        raise ValueError("Latest completed week missing")
    # Retain legitimate zero only if the dataset provides the relevant column
    # and observed rows with numeric values for that metric.
    defense = {}
    for (week, team), group in df.groupby(["week", "defteam"], dropna=True):
        team = str(team).strip().upper()
        if not (2 <= len(team) <= 3 and team.isalpha()):
            continue
        rec = {"week": int(week), "team": team, "playsObserved": int(len(group))}
        for outname, col in DEFENSE_METRICS.items():
            if col not in group.columns:
                rec[outname] = None
            else:
                vals = pd.to_numeric(group[col], errors="coerce")
                rec[outname] = int(vals.sum()) if vals.notna().any() else None
        if rec["sacks"] is not None and rec["opponentDropbacks"] not in (None, 0):
            rec["sacksPerDropback"] = round(rec["sacks"] / rec["opponentDropbacks"], 5)
        else:
            rec["sacksPerDropback"] = None
        defense.setdefault(team, []).append(rec)

    kickers = {}
    for kind, id_field, attempt_field, result_field in [
        ("fieldGoal", "field_goal_kicker_player_id", "field_goal_attempt", "field_goal_result"),
        ("extraPoint", "extra_point_kicker_player_id", "extra_point_attempt", "extra_point_result"),
    ]:
        if any(k not in df.columns for k in (id_field, attempt_field, result_field)):
            continue
        attempts = pd.to_numeric(df[attempt_field], errors="coerce") == 1
        part = df.loc[attempts & df[id_field].notna()].copy()
        for (week, gsis), g in part.groupby(["week", id_field]):
            sid = gsis_to_sid.get(str(gsis))
            if not sid:
                continue
            key = (str(sid), int(week))
            rec = kickers.setdefault(key, {"week": int(week), "fieldGoalAttempts": None,
                                          "fieldGoalsMade": None, "extraPointAttempts": None,
                                          "extraPointsMade": None, "fieldGoalDistancesMade": None})
            results = g[result_field].astype(str).str.lower().str.strip()
            # A player with a valid mapped attempt may have 0 made. An unknown
            # result must NEVER be counted as a known miss.
            known = results.isin(["made", "good", "missed", "blocked", "no good", "failed"])
            if not known.all():
                continue
            made = results.isin(["made", "good"])
            if kind == "fieldGoal":
                rec["fieldGoalAttempts"] = int(len(g))
                rec["fieldGoalsMade"] = int(made.sum())
                if "kick_distance" in g.columns:
                    distances = pd.to_numeric(g.loc[made, "kick_distance"], errors="coerce")
                    rec["fieldGoalDistancesMade"] = ([int(v) for v in distances]
                        if distances.notna().all() else None)
            else:
                rec["extraPointAttempts"] = int(len(g))
                rec["extraPointsMade"] = int(made.sum())
    bykicker = {}
    for (sid, week), row in sorted(kickers.items()):
        bykicker.setdefault(sid, []).append(row)
    return {"schemaVersion": 7, "kind": "nfl-observed-defense-kicking",
            "season": SEASON, "asOfWeek": through,
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "sources": {"pbp": SOURCES["pbp"], "identity": SOURCES["crosswalk"]},
            "attribution": "nflverse CC-BY 4.0; DynastyProcess crosswalk",
            "scope": "Public NFL play-by-play; no Sleeper fantasy scoring configured",
            "limitations": [
                "Observed events are not forecasts or win probabilities.",
                "Defense sacks/turnovers exclude unverified defensive scoring adjustments.",
                "Fantasy points, league-specific DST/K scoring, pressure, routes and practices are NOT inferred.",
                "Missing source columns and unmapped kicker IDs stay null or absent.",
                "Kicker distances reflect only made FGs when charted and valid."
            ],
            "coverage": {"defenseTeams": len(defense), "kickers": len(bykicker),
                         "pbpRows": int(len(df)),
                         "availableColumns": sorted(set(COLUMNS) & set(pbp.columns)),
                         "missingColumns": sorted(set(COLUMNS) - set(pbp.columns))},
            "byDefense": defense, "byKickerSleeper": bykicker}


def merge_weekly_kickers(context: dict, stats: pd.DataFrame,
                         gsis_to_sid: dict[str, str], through: int) -> dict:
    """Use official-style weekly kicking counts when PBP lacks kicker identity.

    nflverse player_stats weekly has K position and fg_att/fg_made,
    pat_att/pat_made (if actually present). Never infer absent values.
    """
    required = {"season", "week", "season_type", "player_id", "position"}
    if not required.issubset(stats.columns):
        context["coverage"]["kickerStatsStatus"] = "NO DISPONIBLE: columnas básicas ausentes"
        return context
    usable = [x for x in ("fg_att", "fg_made", "pat_att", "pat_made") if x in stats.columns]
    if not usable:
        context["coverage"]["kickerStatsStatus"] = "NO DISPONIBLE: columnas FG/PAT ausentes"
        return context
    filtered = stats.loc[
        (pd.to_numeric(stats.season, errors="coerce") == SEASON)
        & (stats.season_type.astype(str).str.upper() == "REG")
        & (stats.position.astype(str).str.upper() == "K")
        & pd.to_numeric(stats.week, errors="coerce").between(1, through)
    ].copy()
    mapping = {"fg_att": "fieldGoalAttempts", "fg_made": "fieldGoalsMade",
               "pat_att": "extraPointAttempts", "pat_made": "extraPointsMade"}
    updated = 0
    for (week, gid), group in filtered.groupby(["week", "player_id"], dropna=True):
        sid = gsis_to_sid.get(str(gid).strip())
        if not sid:
            continue
        row = {"week": int(week), "fieldGoalAttempts": None,
               "fieldGoalsMade": None, "extraPointAttempts": None,
               "extraPointsMade": None, "fieldGoalDistancesMade": None}
        for source, output in mapping.items():
            if source not in usable:
                continue
            numeric = pd.to_numeric(group[source], errors="coerce")
            if numeric.notna().any():
                value = numeric.sum()
                if value >= 0 and value == int(value):
                    row[output] = int(value)
        if not any(row[name] is not None for name in mapping.values()):
            continue
        items = context["byKickerSleeper"].setdefault(str(sid), [])
        items[:] = [old for old in items if old.get("week") != int(week)]
        items.append(row)
        updated += 1
    for items in context["byKickerSleeper"].values():
        items.sort(key=lambda r: r["week"])
    context["coverage"]["kickers"] = len(context["byKickerSleeper"])
    context["coverage"]["kickerMappedWeeks"] = updated
    context["coverage"]["kickerStatsStatus"] = (
        "OBSERVADO: nflverse weekly player stats" if updated else
        "NO DISPONIBLE: ningún kicker GSIS->Sleeper con estadísticas verificadas")
    context["sources"]["kickingWeeklyStats"] = SOURCES["stats"]
    return context


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-gzip", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, default=Path(".mb5-cache"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with gzip.open(args.source_gzip, "rt", encoding="utf8") as f:
        base = json.load(f)
    if base.get("schemaVersion") != 5 or base.get("season") != SEASON:
        raise ValueError("Require validated V5 feed")
    through = int(base["thruWeek"])
    # Original ETL has already downloaded this source in the production job.
    source = pull(SOURCES["pbp"], args.cache_dir / "pbp.parquet")
    import pyarrow.parquet as pq
    cols = [col for col in COLUMNS if col in pq.ParquetFile(source).schema.names]
    pbp = pd.read_parquet(source, columns=cols)
    cross = pull(SOURCES["crosswalk"], args.cache_dir / "crosswalk.csv")
    identity, _, _ = load_identity(pd.read_csv(cross, dtype=str))
    context = build_context(pbp, identity, through)
    # NFLverse PBP 2026 lacks kicker player IDs: use player-week box statistics.
    stats_file = pull(SOURCES["stats"], args.cache_dir / "stats.csv")
    stats = pd.read_csv(stats_file, low_memory=False)
    context = json_native(merge_weekly_kickers(context, stats, identity, through))
    if context["coverage"]["defenseTeams"] < 28:
        raise ValueError("Insufficient defensive team coverage")
    if not context["byKickerSleeper"]:
        # Not a failure for existing feed: nullable/optional kicker IDs.
        print("NOTICE: no mapped kicker identifiers; kicker observations unavailable")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(args.output) + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf8") as f:
        json.dump(context, f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    tmp.replace(args.output)
    print("MONEYBALL7_CONTEXT_OK", context["asOfWeek"], context["coverage"])

if __name__ == "__main__":
    main()
