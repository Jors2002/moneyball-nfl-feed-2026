import copy
import random
from datetime import datetime, timezone

import pytest

from moneyball8_decisions import SLOTS, ELIGIBLE, optimize_lineup, optimize_offense_conditional, evaluate_transaction, evaluate_trade
from moneyball8_evidence import assess_evidence, championship_readiness


def player(sid, position, score, **kwargs):
    return {"id": sid, "positions": [position], "projection": score, "available": True, **kwargs}


def roster(prefix=""):
    return [player(prefix + str(i), pos, score) for i, (pos, score) in enumerate(
        [("QB", 20), ("RB", 15), ("RB", 12), ("WR", 14), ("WR", 11), ("TE", 10), ("RB", 9), ("K", 7), ("DEF", 6)])]


def test_complete_all_nine_and_no_mutation():
    rows = roster(); before = copy.deepcopy(rows)
    r = optimize_lineup(rows)
    assert r["status"] == "OK" and r["total"] == 104
    assert set(r["assignment"]) == set(SLOTS)
    assert len(set(r["assignment"].values())) == 9
    assert rows == before


def test_flex_forbids_te_and_exact_marginal_cut_cost():
    rows = roster() + [player("superTE", "TE", 100), player("rb4", "RB", 13)]
    r = optimize_lineup(rows)
    assert r["assignment"]["TE"] == "superTE"
    assert r["assignment"]["WRRB_FLEX"] in {"1", "2", "6", "rb4", "3", "4"}
    assert "5" not in r["assignment"].values()
    # RB4 already starts; cutting RB1 brings the nine-point RB into the FLEX.
    r = evaluate_transaction([p["id"] for p in rows], [], ["1"], {9: rows}, {"current": [9]})
    assert r["weeks"][9]["delta"] == -6


def test_unknown_never_becomes_zero_and_missing_k_incomplete():
    rows = roster()
    rows[7]["projection"] = None
    r = optimize_lineup(rows)
    assert r["status"] == "INSUFFICIENT_DATA" and r["total"] is None
    assert "K" in r["missing_slots"]
    assert r["missing"] == [{"id": "7", "reason": "PROJECTION_MISSING"}]
    rows = roster() + [player("unknown", "RB", 99, available=None)]
    partial = optimize_lineup(rows)
    assert partial["status"] == "INSUFFICIENT_DATA" and partial["total"] is None
    assert partial["known_candidate_total"] == 104


def test_real_zero_and_negative_are_valid():
    rows = roster(); rows[7]["projection"] = 0; rows[8]["projection"] = -5
    r = optimize_lineup(rows)
    assert r["status"] == "OK" and r["total"] == 86


@pytest.mark.parametrize("invalid", [True, float("nan"), float("inf"), "5"])
def test_projection_invalid(invalid):
    rows = roster(); rows[7]["projection"] = invalid
    assert optimize_lineup(rows)["total"] is None


def test_locked_slots_force_original_player_and_prohibit_duplicate():
    rows = roster() + [player("QB2", "QB", 99)]
    r = optimize_lineup(rows, {"QB": "0"})
    assert r["assignment"]["QB"] == "0" and r["total"] == 104
    with pytest.raises(ValueError, match="Duplicate"):
        optimize_lineup(rows, {"RB1": "1", "RB2": "1"})
    with pytest.raises(ValueError, match="Illegal"):
        optimize_lineup(rows, {"QB": "1"})


@pytest.mark.parametrize("flag", ["bye", "reserve"])
def test_bye_and_ir_not_allowed(flag):
    rows = roster(); rows[0][flag] = True
    assert optimize_lineup(rows)["total"] is None
    assert optimize_lineup(rows, {"QB": "0"})["total"] is None


def test_unavailable_skips_unknown_score_without_false_missing():
    rows = roster() + [player("IR", "RB", None, available=False)]
    assert optimize_lineup(rows)["status"] == "OK"


def test_duplicate_players_rejected():
    with pytest.raises(ValueError, match="Duplicate"):
        optimize_lineup(roster() + [roster()[0]])


@pytest.mark.parametrize("bad", [1, 0, "yes", [], {}])
def test_availability_requires_bool(bad):
    rows = roster(); rows[0]["available"] = bad
    with pytest.raises(ValueError, match="available"):
        optimize_lineup(rows)


def brute(rows):
    def visit(i, used):
        if i == len(SLOTS):
            return 0
        values = [p["projection"] + visit(i + 1, used | {p["id"]})
                  for p in rows if p["id"] not in used and set(p["positions"]) & ELIGIBLE[i]]
        return max(values, default=-float("inf"))
    return visit(0, set())


def test_exact_against_bruteforce_random_multieligibility():
    rng = random.Random(72)
    for _ in range(10):
        rows = roster()
        for p in rows:
            p["projection"] = rng.randint(-5, 25)
        rows += [player("x", "RB", rng.randint(-5, 25)), player("y", "WR", rng.randint(-5, 25))]
        rows[-1]["positions"] = ["WR", "RB"]
        assert optimize_lineup(rows)["total"] == brute(rows)


def test_horizons_missing_week_cannot_silently_average():
    rows = roster() + [player("add", "RB", 20)]
    r = evaluate_transaction([str(i) for i in range(9)], ["add"], ["6"], {9: rows}, {"weekly": [9], "playoffs": [15, 16, 17]})
    assert r["horizons"]["weekly"]["total_delta"] == 11
    assert r["horizons"]["playoffs"]["total_delta"] is None
    assert r["championship_probability_delta"] is None


def test_missing_bench_player_is_explicit():
    r = evaluate_transaction([str(i) for i in range(9)] + ["missing"], [], [], {9: roster()}, {"weekly": [9]})
    assert r["weeks"][9]["delta"] is None
    assert r["weeks"][9]["missing_ids"] == ["missing"]


def test_trade_bilateral_and_no_execution():
    a, b = roster("a"), roster("b")
    b[1]["projection"] = 30
    r = evaluate_trade([p["id"] for p in a], [p["id"] for p in b], ["a1"], ["b1"], {9: a + b}, {"weekly": [9]})
    assert r["a"]["weeks"][9]["delta"] == 15
    assert r["b"]["weeks"][9]["delta"] == -15
    assert not r["executed"] and r["championship_probability_delta"] is None


def test_ownership_capacity_explicit_cut():
    rows = roster()
    with pytest.raises(ValueError, match="capacity"):
        evaluate_transaction([p["id"] for p in rows], ["extra"], [], {9: rows}, {"weekly": [9]}, capacity=9)
    with pytest.raises(ValueError, match="ownership"):
        evaluate_transaction([p["id"] for p in rows], [], ["notours"], {9: rows}, {"weekly": [9]})
    with pytest.raises(ValueError, match="ownership"):
        evaluate_trade(["a"], ["b"], ["b"], ["a"], {}, {"weekly": [9]})


def evidence():
    return {"event_at": "2026-11-03T20:00:00Z", "published_at": "2026-11-03T21:00:00Z",
            "fetched_at": "2026-11-04T15:00:00Z", "source_url": "https://www.nfl.com/report",
            "content_verified": True, "practice": "FULL", "game_status": "QUESTIONABLE"}


NOW = datetime(2026, 11, 4, 16, tzinfo=timezone.utc)


def test_source_verification_and_full_does_not_imply_unrestricted_snaps():
    r = assess_evidence(evidence(), NOW, ["www.nfl.com"])
    assert r["usable_current"] and r["official"]
    assert r["snap_restriction"] is None and r["participation_probability"] is None


@pytest.mark.parametrize("field,value,status", [
    ("event_at", "2026-11-03", "UNVERIFIED_DATES"),
    ("event_at", "2026-11-03T20:00:00", "UNVERIFIED_DATES"),
    ("event_at", "2026-10-30T20:00:00Z", "STALE_EVENT"),
    ("published_at", "2026-11-05T21:00:00Z", "INVALID_TIME_ORDER"),
    ("fetched_at", "2026-11-05T21:00:00Z", "INVALID_TIME_ORDER"),
    ("source_url", "https://www.nfl.com.evil.test/report", "SOURCE_NOT_VERIFIED"),
    ("content_verified", False, "SOURCE_NOT_VERIFIED"),
    ("practice", "good", "INVALID_STATUS")])
def test_reject_ambiguous_freshness_and_forged_hosts(field, value, status):
    rec = evidence(); rec[field] = value
    r = assess_evidence(rec, NOW, ["www.nfl.com"])
    assert not r["usable_current"] and r["status"] == status


def test_odds_gate_never_prints_probabilities():
    r = championship_readiness({"scoring_verified": True})
    assert r["status"] == "INSUFFICIENT_DATA" and r["championship_probability"] is None
    assert "joint_score_calibration_validated" in r["missing"]


def test_offense_scope_is_separate_and_never_certifies_nine_starters():
    rows = roster()[:7]
    assert optimize_lineup(rows)["total"] is None
    before = optimize_offense_conditional(rows)
    after = optimize_offense_conditional(rows + [player("upgrade", "RB", 20)])
    assert before["scope"] == "SEVEN_OFFENSIVE_STARTERS_ONLY"
    assert before["excluded_slots"] == ["K", "DEF"]
    assert before["total"] == 91 and after["total"] - before["total"] == 11
    assert before["slots_count"] == 7
    assert before["complete_fantasy_lineup_verified"] is False
    assert set(before["assignment"]) == set(SLOTS[:7])


def test_offense_unknown_still_blocks_total():
    rows = roster()[:7] + [player("unknown", "RB", None)]
    assert optimize_offense_conditional(rows)["total"] is None


def test_private_case_study_missing_rival_forecast_is_not_filled_with_zero(tmp_path):
    import json
    from moneyball8_case_study import build
    a, b = roster("a"), roster("b")
    data = a + b + [player("free", "WR", 30)]
    metadata = {p["id"]: {"position": p["positions"][0], "full_name": p["id"], "injury_status": None} for p in data}
    forecast = {"generatedAt": "2026-11-04T23:00:00Z", "targetWeek": 9,
                "bySleeper": {p["id"]: {"position": p["positions"][0], "projection": p["projection"]} for p in data if p["id"] != "b2"}}
    for name, value in {"rosters": [{"roster_id": 1, "players": [p["id"] for p in a]},
                                     {"roster_id": 2, "players": [p["id"] for p in b]}],
                        "players": metadata, "league": {"status": "in_season"}}.items():
        (tmp_path / (name + ".json")).write_text(json.dumps(value))
    result = build(tmp_path, forecast, 1, 2, "a1", "b1")
    assert result["trade"]["rival"]["status"] == "INSUFFICIENT_DATA"
    assert result["trade"]["rival"]["offensive_points_delta"] is None
    assert result["trade"]["rival_missing_forecasts"] == ["b2"]
    assert result["complete_fantasy_lineup_verified"] is False
    assert result["waivers"]["candidates_evaluated"] == 1
    assert result["waivers"]["ranked_conditional_scenarios"][0]["add"] == "free"
