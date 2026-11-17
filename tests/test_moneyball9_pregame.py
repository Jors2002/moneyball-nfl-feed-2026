import pandas as pd
import pytest
from moneyball9_pregame import evidence_at, instant, pregame, select_vintage
from moneyball9_scenarios import rank_bounds


def test_evidence_deduplicates_origin_and_rejects_late_news():
    event = dict(subject="WR", kind="trade", origin="club", source="club",
                 mechanism="new slot receiver", counterargument="different personnel",
                 invalidation="route share stable", publishedAt="2026-01-01T10:00Z",
                 observedAt="2026-01-01T10:30Z", **{"class": "HECHO"})
    copies = [event, dict(event, source="syndication"),
              dict(event, observedAt="2026-01-01T12:01Z")]
    assert evidence_at(copies, instant("2026-01-01T12:00Z")) == [event]


def test_postkick_refresh_excluded():
    v = dict(season=2026, targetWeek=10, asOfWeek=9, generatedAt="2026-11-10T12:00Z",
             sourceGeneratedAt="2026-11-10T10:00Z")
    later = dict(v, generatedAt="2026-11-15T18:00Z")
    assert select_vintage([v,later],2026,10,"2026-11-15T18:00Z") == v


def test_matchup_prior_weeks_missing_rates_and_game_lock():
    row = dict(season=2026, season_type="REG", week=1, game_id="1", play_id=1,
               posteam="A", defteam="B", play_type="pass", qb_dropback=1, sack=0,
               qb_hit=None, score_differential=0, qtr=1, xpass=.6)
    games = pd.DataFrame([dict(season=2026, game_type="REG", week=2, game_id="2",
                               gameday="2026-09-20", gametime="13:00",home_team="A",away_team="B")])
    plays = pd.DataFrame([row, dict(row,week=2,sack=1)])
    t="2026-09-18T12:00Z"
    result=pregame(plays,games,2026,2,t,t)
    offense=result["gamesByTeam"][0]["offense"]
    assert offense["sackRate"]==0 and offense["hitRate"] is None
    assert offense["neutralPROE"]==.4 and offense["games"]==["1"]
    assert not pregame(plays,games,2026,2,t,"2026-09-20T17:00Z")["gamesByTeam"]
    with pytest.raises(ValueError): pregame(plays,games,2026,2,t,"2026-09-17T12:00Z")


def test_rank_bounds_accounts_for_shared_games():
    assert rank_bounds({"a":1,"b":1,"c":0},[("a","b"),("b","c")],"a")=={1:(2,3),2:(1,2)}


def test_player_role_and_missing_routes():
    from moneyball9_pregame import player_windows
    t = "2026-11-17T12:00Z"
    feed = dict(season=2026, thruWeek=10, generatedAt=t, bySleeper={"x":[
        dict(week=9,snapTeam="A",snaps=25),dict(week=10,snapTeam="B",snapObserved=True,
                                                 snaps=0,specialTeamsSnaps=8,routes=None)]})
    result = player_windows(feed,2026,11,t)["x"]
    assert [a["kind"] for a in result["alerts"]] == ["TEAM_CHANGE","PLAYED_ZERO_OFFENSE"]
    assert result["rows"][-1]["routes"] is None
    with pytest.raises(ValueError): player_windows(feed,2026,12,t)


@pytest.mark.parametrize("kind", ["injury", "rest", "return", "signing", "trade",
                                  "qb_change", "coordinator", "snap_limit", "depth_chart"])
def test_event_kinds_preserve_uncertainty_without_point_adjustments(kind):
    event=dict(subject="player",kind=kind,source="team",origin="team",
               mechanism="potential opportunity change",counterargument="role may hold",
               invalidation="next usage report",publishedAt="2026-11-16T10:00Z",
               observedAt="2026-11-17T10:00Z",**{"class":"INFERENCIA"})
    result=evidence_at([event],instant("2026-11-17T12:00Z"))
    assert result[0]["class"]=="INFERENCIA"
    assert "projection" not in result[0]


def test_rank_bounds_rejects_bad_games():
    with pytest.raises(ValueError): rank_bounds({"a":1},[("a","a")],"a")


def test_naive_time_rejected():
    with pytest.raises(ValueError): instant("2026-11-17T12:00")


def test_duplicate_pbp_rejected():
    from moneyball9_pregame import matchup_features
    row=dict(season=2026,season_type="REG",week=1,game_id="g",play_id=1,
             play_type="pass",posteam="A",defteam="B")
    with pytest.raises(ValueError):matchup_features(pd.DataFrame([row,row]),2026,2)
