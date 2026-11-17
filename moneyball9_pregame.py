"""Pregame scouting from frozen, timestamped inputs. All features are descriptive."""
import argparse
import gzip
from datetime import datetime
import json
from pathlib import Path

import pandas as pd


def instant(value):
    time = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if time.tzinfo is None:
        raise ValueError("An explicit timezone is required")
    return time


def matchup_features(plays, season, week):
    """Last four observed games, with separate denominators for pass rush and PROE."""
    data = plays.loc[(plays.season == season) & (plays.season_type == "REG")
                     & (plays.week < week) & plays.play_type.isin(["pass", "run"])
                     & plays.posteam.notna() & plays.defteam.notna()].copy()
    if data.duplicated(["game_id", "play_id"]).any():
        raise ValueError("Duplicate play")
    output = {}
    for side in ["posteam", "defteam"]:
        for team, group in data.groupby(side):
            games = group.sort_values("week").game_id.drop_duplicates().tail(4)
            recent = group[group.game_id.isin(games)]
            drops = recent[recent.qb_dropback == 1]
            neutral = recent[(recent.score_differential.abs() <= 7) & (recent.qtr <= 3)]
            neutral = neutral.dropna(subset=["xpass", "qb_dropback"])
            def mean(series):
                return round(float(series.mean()), 4) if series.count() else None
            output.setdefault(team, {})[side] = {
                "games": games.tolist(), "dropbacks": len(drops),
                "sackRate": mean(drops.sack), "hitRate": mean(drops.qb_hit),
                "neutralPassRate": mean(neutral.qb_dropback),
                "neutralPROE": mean(neutral.qb_dropback - neutral.xpass),
                "neutralPlays": len(neutral), "pressureRate": None, "blitzRate": None,
            }
    return output


def evidence_at(events, cutoff):
    """Dedupe observations by original source. Never upgrade or score an assertion."""
    seen, accepted = set(), []
    for event in events:
        if instant(event["publishedAt"]) > cutoff or instant(event["observedAt"]) > cutoff:
            continue
        if not all(event.get(k) for k in ("subject", "kind", "source", "origin", "mechanism",
                                          "counterargument", "invalidation")):
            raise ValueError("Incomplete event evidence")
        if event["class"] not in {"HECHO", "INFERENCIA", "CORAZONADA", "NO VERIFICADO"}:
            raise ValueError("Unknown evidence class")
        key = (event["subject"], event["kind"], event["origin"], event["publishedAt"])
        if key not in seen:
            accepted.append(event)
            seen.add(key)
    return accepted


def pregame(plays, games, season, week, observed_at, cutoff, events=()):
    observed, asof = instant(observed_at), instant(cutoff)
    if observed > asof:
        raise ValueError("Input vintage was unavailable at decision time")
    if not 1 <= week <= 18:
        raise ValueError("Invalid target week")
    features = matchup_features(plays, season, week)
    result = []
    scheduled = games[(games.season == season) & (games.game_type == "REG") & (games.week == week)]
    if scheduled.empty or scheduled.game_id.duplicated().any():
        raise ValueError("Missing or duplicate game schedule")
    for game in scheduled.itertuples():
        kickoff = pd.Timestamp(f"{game.gameday} {game.gametime}", tz="America/New_York")
        if kickoff <= asof:
            continue
        for team, opponent in [(game.home_team, game.away_team), (game.away_team, game.home_team)]:
            result.append({"team": team, "opponent": opponent, "kickoff": kickoff.isoformat(),
                           "offense": features.get(team, {}).get("posteam"),
                           "opponentDefense": features.get(opponent, {}).get("defteam")})
    return {"season": season, "targetWeek": week, "observedAt": observed_at,
            "decisionAt": cutoff, "gamesByTeam": result, "news": evidence_at(events, asof),
            "numericalAdjustment": None, "mode": "DESCRIPTIVE_ONLY"}


def select_vintage(vintages, season, week, kickoff):
    """Choose latest eligible original release per kickoff, never a postgame refresh."""
    eligible = [v for v in vintages if v["season"] == season and v["targetWeek"] == week
                and v["asOfWeek"] < week and instant(v["generatedAt"]) < instant(kickoff)
                and instant(v["sourceGeneratedAt"]) <= instant(v["generatedAt"])]
    return max(eligible, key=lambda v: instant(v["generatedAt"]), default=None)


def player_windows(feed, season, week, cutoff):
    if (feed["season"] != season or feed["thruWeek"] != week - 1
            or instant(feed["generatedAt"]) > instant(cutoff)):
        raise ValueError("Player feed does not match decision vintage")
    windows = {}
    for sid, rows in feed["bySleeper"].items():
        prior = sorted((r for r in rows if r["week"] < week), key=lambda r: r["week"])
        if len({r["week"] for r in prior}) != len(prior):
            raise ValueError("Duplicate player week")
        if not prior:
            continue
        recent = prior[-4:]
        alerts = []
        for previous, current in zip(recent, recent[1:]):
            if (previous.get("snapTeam") and current.get("snapTeam")
                    and previous["snapTeam"] != current["snapTeam"]):
                alerts.append({"kind": "TEAM_CHANGE", "week": current["week"],
                               "from": previous["snapTeam"], "to": current["snapTeam"]})
        latest = recent[-1]
        if (latest.get("snapObserved") is True and latest.get("snaps") == 0
                and (latest.get("specialTeamsSnaps") or 0) > 0):
            alerts.append({"kind": "PLAYED_ZERO_OFFENSE", "week": latest["week"]})
        windows[sid] = {"lastObservedWeek": latest["week"], "alerts": alerts, "rows": recent}
    return windows


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("plays", "schedule", "observed-at", "cutoff"):
        parser.add_argument("--" + arg, required=True)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--events", type=Path)
    parser.add_argument("--feed", type=Path)
    args = parser.parse_args()
    events = json.loads(args.events.read_text()) if args.events else []
    report = pregame(pd.read_parquet(args.plays), pd.read_csv(args.schedule, low_memory=False),
                     args.season, args.week, args.observed_at, args.cutoff, events)
    if args.feed:
        with gzip.open(args.feed, "rt") as stream:
            feed = json.load(stream)
        report["bySleeper"] = player_windows(feed, args.season, args.week, args.cutoff)
        report["sourceUrls"] = feed["sourceUrls"]
        report["coverage"] = feed["coverage"]
    print(json.dumps(report, allow_nan=False, indent=2))
