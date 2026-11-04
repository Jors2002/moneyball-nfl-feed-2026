"""Reproducible PRIVATE conditional seven-slot case study, never a live action.

CLI takes private Sleeper snapshots and public forecasts. Results are refused
inside a git checkout; no private roster data is sent to a provider or published.
"""
import argparse
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path

from moneyball8_decisions import optimize_offense_conditional
from moneyball8_league import write_private_report


OFFENSE = {"QB", "RB", "WR", "TE"}


def build(private_dir, forecast, ours, rival, give, receive, candidate_limit=200):
    directory = Path(private_dir)
    rosters = json.loads((directory / "rosters.json").read_text())
    metadata = json.loads((directory / "players.json").read_text())
    league = json.loads((directory / "league.json").read_text())
    players = forecast["bySleeper"]
    teams = {r["roster_id"]: r for r in rosters}
    a, b = teams[ours], teams[rival]
    if give not in a["players"] or receive not in b["players"]:
        raise ValueError("Trade ownership not verified in provided snapshot")

    def active_offense(team):
        return [sid for sid in team["players"] if sid not in (team.get("reserve") or [])
                and metadata.get(sid, {}).get("position") in OFFENSE]

    def rows(ids, overrides=None):
        return [{"id": sid, "positions": [metadata[sid]["position"]],
                 "projection": (overrides or {}).get(sid, players.get(sid, {}).get("projection")),
                 "available": True} for sid in ids]

    def named(result):
        result = dict(result)
        result["starters"] = [{"slot": slot, "id": sid,
                               "name": metadata[sid].get("full_name"),
                               "projection": players.get(sid, {}).get("projection"),
                               "sleeper_tag": metadata[sid].get("injury_status")}
                              for slot, sid in result["assignment"].items()]
        return result

    def compare(before_ids, after_ids, overrides=None):
        before = optimize_offense_conditional(rows(before_ids, overrides))
        after = optimize_offense_conditional(rows(after_ids, overrides))
        valid = before["status"] == after["status"] == "OK"
        return {"status": "CONDITIONAL_SCENARIO" if valid else "INSUFFICIENT_DATA",
                "before": named(before), "after": named(after),
                "offensive_points_delta": round(after["total"] - before["total"], 4) if valid else None}

    a_ids, b_ids = active_offense(a), active_offense(b)
    a_after = [sid for sid in a_ids if sid != give] + [receive]
    b_after = [sid for sid in b_ids if sid != receive] + [give]
    ours_trade, rival_trade = compare(a_ids, a_after), compare(b_ids, b_after)
    missing = [sid for sid in b_ids if players.get(sid, {}).get("projection") is None]
    sensitivity = []
    if len(missing) == 1:
        for value in (0., 10., 20., 30.):
            result = compare(b_ids, b_after, {missing[0]: value})
            sensitivity.append({"explicit_hypothetical_player": metadata[missing[0]].get("full_name"),
                                "assumed_projection_not_observed": value,
                                "rival_delta": result["offensive_points_delta"]})

    owned = {sid for team in rosters for sid in team["players"]}
    candidates = [sid for sid, p in players.items() if sid not in owned and p.get("position") in OFFENSE
                  and p.get("projection") is not None and sid in metadata
                  and metadata[sid].get("injury_status") not in {"Out", "IR", "PUP", "Sus", "Doubtful"}]
    candidates.sort(key=lambda sid: players[sid]["projection"], reverse=True)
    candidates = candidates[:candidate_limit]
    baseline = optimize_offense_conditional(rows(a_ids))
    waivers = []
    for sid in candidates:
        cuts = []
        for drop in a_ids:
            result = optimize_offense_conditional(rows([x for x in a_ids if x != drop] + [sid]))
            delta = round(result["total"] - baseline["total"], 4) if result["status"] == baseline["status"] == "OK" else None
            cuts.append({"drop": drop, "drop_name": metadata[drop].get("full_name"),
                         "status": result["status"], "offensive_points_delta": delta})
        valid = [c for c in cuts if c["offensive_points_delta"] is not None]
        best = max(valid, key=lambda c: (c["offensive_points_delta"], -players.get(c["drop"], {}).get("projection", 0))) if valid else None
        waivers.append({"add": sid, "add_name": metadata[sid].get("full_name"),
                        "projection": players[sid]["projection"], "sleeper_tag": metadata[sid].get("injury_status"),
                        "best_drop": best, "all_offensive_cut_comparisons": cuts,
                        "availability": "PUBLICLY_UNOWNED_ONLY; transaction eligibility and deadlines unverified"})
    waivers.sort(key=lambda w: w["best_drop"]["offensive_points_delta"] if w["best_drop"] else -float("inf"), reverse=True)
    return {"schemaVersion": 80, "generatedAt": datetime.now(timezone.utc).isoformat(),
            "forecastGeneratedAt": forecast["generatedAt"], "targetWeek": forecast["targetWeek"],
            "scope": "SEVEN_OFFENSIVE_STARTERS_ONLY", "league_scoring": forecast.get("scoring"),
            "complete_fantasy_lineup_verified": False, "championship_probability_delta": None,
            "assumptions": ["All modeled non-IR offensive players participate without restrictions: hypothetical, not medical evidence.",
                            "Byes, opponent, kickoff locks and actual waiver entitlement NOT modeled.",
                            "K/DEF scoring omitted; their terms cancel only for an offensive-only trade leaving those slots unchanged.",
                            "Only target week is modeled. Do not extrapolate to weeks 15-17.",
                            "Conditional forecasts have not established participation or joint-score calibration."],
            "trade": {"give": give, "give_name": metadata[give].get("full_name"),
                      "receive": receive, "receive_name": metadata[receive].get("full_name"),
                      "ours": ours_trade, "rival": rival_trade,
                      "rival_missing_forecasts": missing, "rival_hypothetical_sensitivity": sensitivity,
                      "recommendation": "DATOS_INSUFICIENTES", "executed": False},
            "waivers": {"candidate_limit": candidate_limit, "candidates_evaluated": len(candidates),
                        "offensive_cut_options_per_candidate": len(a_ids),
                        "excluded_cut_options": [{"id": sid, "reason": "K/DEF required and unscored; IR excluded"}
                                                 for sid in a["players"] if sid not in a_ids],
                        "ranked_conditional_scenarios": waivers},
            "league_snapshot_status": league.get("status")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-dir", required=True, type=Path)
    parser.add_argument("--feed", required=True, type=Path)
    parser.add_argument("--ours", required=True, type=int)
    parser.add_argument("--rival", required=True, type=int)
    parser.add_argument("--give", required=True)
    parser.add_argument("--receive", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    with gzip.open(args.feed, "rt") as handle:
        forecast = json.load(handle)
    report = build(args.private_dir, forecast, args.ours, args.rival, args.give, args.receive)
    write_private_report(args.output, report)
    print(json.dumps({"status": "PRIVATE_CONDITIONAL_CASE_WRITTEN", "targetWeek": report["targetWeek"],
                      "waiver_candidates": report["waivers"]["candidates_evaluated"]}))


if __name__ == "__main__":
    main()
