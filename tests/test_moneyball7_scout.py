"""Moneyball 7: deterministic no-leakage and missingness tests."""
import copy
import pytest

from moneyball7_scout import player_trend, scout_feed


def row(w, **fields):
    return {"week": w, **fields}


def feed(rows):
    return {"schemaVersion": 5, "season": 2026, "thruWeek": 8,
            "generatedAt": "2026-11-04T12:00:00+00:00",
            "bySleeper": {"12345": rows}}


def test_observed_increase_with_two_disjoint_windows():
    result = player_trend([
        row(5, snapShare=.2, targets=2),
        row(6, snapShare=.3, targets=2),
        row(7, snapShare=.6, targets=5),
        row(8, snapShare=.7, targets=6)], 8)
    assert result["metrics"]["snapShare"]["delta"] == .4
    assert result["metrics"]["snapShare"]["direction"] == "up"
    assert result["metrics"]["targets"]["recent"]["mean"] == 5.5


def test_missing_metric_is_not_zero():
    result = player_trend([
        row(5, routes=None), row(6, routes=None),
        row(7, routes=None), row(8, routes=None)], 8)
    assert result["metrics"]["routes"]["delta"] is None
    assert result["metrics"]["routes"]["direction"] == "insufficient_data"
    assert result["metrics"]["routes"]["recent"]["observations"] == 0


def test_no_future_data_leakage():
    base = [row(5, carries=4), row(6, carries=4),
            row(7, carries=8), row(8, carries=10)]
    future = row(9, carries=1000)
    assert player_trend(base, 8) == player_trend(base + [future], 8)


def test_no_delta_for_short_coverage():
    result = player_trend([row(7, targets=8), row(8, targets=10)], 8)
    assert result["metrics"]["targets"]["delta"] is None


def test_missing_week_not_fabricated():
    result = player_trend([row(2, carries=4), row(7, carries=8),
                           row(8, carries=10)], 8)
    assert result["recentWeeks"] == [7, 8]
    assert result["previousWeeks"] == [2]
    assert result["metrics"]["carries"]["delta"] is None


def test_duplicate_weeks_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        player_trend([row(7), row(7)], 8)


def test_wrong_schema_and_future_cutoff_rejected():
    x = feed([row(7), row(8)])
    with pytest.raises(ValueError):
        scout_feed({**x, "schemaVersion": 6})
    with pytest.raises(ValueError):
        scout_feed(x, as_of_week=9)


def test_feed_unmodified_and_coverage_explicit():
    x = feed([row(5, targets=2), row(6, targets=3),
              row(7, targets=5), row(8, targets=6)])
    original = copy.deepcopy(x)
    result = scout_feed(x)
    assert x == original
    assert result["schemaVersion"] == 7
    assert result["comparablePlayersByMetric"]["targets"] == 1
    assert "routes" not in result["comparablePlayersByMetric"]
    assert result["bySleeper"]["12345"]["metrics"]["targets"]["direction"] == "up"


def test_nan_and_booleans_not_measured():
    result = player_trend([row(5, targets=True), row(6, targets=float("nan")),
                           row(7, targets=2), row(8, targets=3)], 8)
    assert result["metrics"]["targets"]["delta"] is None
