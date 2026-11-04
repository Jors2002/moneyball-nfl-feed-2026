"""Offline Moneyball 7 defense and kicker observed-event tests."""
import pandas as pd
import pytest
from moneyball7_context import build_context, merge_weekly_kickers

def fixture():
    return pd.DataFrame([
        {"season":2026,"season_type":"REG","week":8,"game_id":"2026_08_A_B",
         "play_id":1,"posteam":"AAA","defteam":"BBB","qb_dropback":1,
         "sack":1,"interception":0,"fumble_lost":0,"pass_attempt":0,
         "rush_attempt":0,"field_goal_attempt":0,"field_goal_result":None,
         "field_goal_kicker_player_id":None,"extra_point_attempt":0,
         "extra_point_result":None,"extra_point_kicker_player_id":None},
        {"season":2026,"season_type":"REG","week":8,"game_id":"2026_08_A_B",
         "play_id":2,"posteam":"AAA","defteam":"BBB","qb_dropback":1,
         "sack":0,"interception":1,"fumble_lost":0,"pass_attempt":1,
         "rush_attempt":0,"field_goal_attempt":0,"field_goal_result":None,
         "field_goal_kicker_player_id":None,"extra_point_attempt":0,
         "extra_point_result":None,"extra_point_kicker_player_id":None},
        {"season":2026,"season_type":"REG","week":8,"game_id":"2026_08_A_B",
         "play_id":3,"posteam":"AAA","defteam":"BBB","qb_dropback":0,
         "sack":0,"interception":0,"fumble_lost":0,"pass_attempt":0,
         "rush_attempt":0,"field_goal_attempt":1,"field_goal_result":"made",
         "field_goal_kicker_player_id":"00-0000001","kick_distance":42,
         "extra_point_attempt":0,"extra_point_result":None,
         "extra_point_kicker_player_id":None},
        {"season":2026,"season_type":"REG","week":8,"game_id":"2026_08_A_B",
         "play_id":4,"posteam":"AAA","defteam":"BBB","qb_dropback":0,
         "sack":0,"interception":0,"fumble_lost":0,"pass_attempt":0,
         "rush_attempt":0,"field_goal_attempt":0,"field_goal_result":None,
         "field_goal_kicker_player_id":None,"extra_point_attempt":1,
         "extra_point_result":"good","extra_point_kicker_player_id":"00-0000001"}
    ])

def test_defense_sacks_turnovers_and_kicker_made():
    f=build_context(fixture(), {"00-0000001":"12345"},8)
    defense=f["byDefense"]["BBB"][0]
    assert defense["opponentDropbacks"] == 2
    assert defense["sacks"] == 1
    assert defense["interceptions"] == 1
    assert defense["sacksPerDropback"] == .5
    kicker=f["byKickerSleeper"]["12345"][0]
    assert kicker["fieldGoalAttempts"] == 1
    assert kicker["fieldGoalsMade"] == 1
    assert kicker["fieldGoalDistancesMade"] == [42]
    assert kicker["extraPointsMade"] == 1

def test_missing_defense_metric_stays_null():
    f=build_context(fixture().drop(columns=["sack"]), {},8)
    assert f["byDefense"]["BBB"][0]["sacks"] is None
    assert f["byDefense"]["BBB"][0]["sacksPerDropback"] is None
    assert not f["byKickerSleeper"]

def test_unknown_fg_result_does_not_turn_into_miss():
    df=fixture()
    df.loc[df.play_id==3,"field_goal_result"]="pending"
    f=build_context(df,{"00-0000001":"12345"},8)
    assert f["byKickerSleeper"]["12345"][0]["fieldGoalAttempts"] is None

def test_future_week_excluded():
    df=fixture()
    future=df.copy()
    future["week"]=9
    future["sack"]=99
    got=build_context(pd.concat([df,future]),{"00-0000001":"12345"},8)
    assert got["byDefense"]["BBB"][0]["sacks"]==1
    assert got["asOfWeek"]==8

def test_incomplete_latest_week_rejected():
    with pytest.raises(ValueError,match="Latest"):
        build_context(fixture(),{},9)

def test_mandatory_columns():
    with pytest.raises(ValueError,match="Missing required"):
        build_context(fixture().drop(columns=["defteam"]),{},8)


def test_kicker_weekly_fallback_fills_missing_pbp_ids():
    context=build_context(fixture().drop(columns=[
        "field_goal_kicker_player_id", "extra_point_kicker_player_id"
    ]), {"00-0000001":"12345"}, 8)
    stats=pd.DataFrame([
        {"season":2026,"season_type":"REG","week":8,"player_id":"00-0000001",
         "position":"K","fg_att":2,"fg_made":1,"pat_att":4,"pat_made":4}
    ])
    out=merge_weekly_kickers(context,stats,{"00-0000001":"12345"},8)
    row=out["byKickerSleeper"]["12345"][0]
    assert row["fieldGoalAttempts"]==2
    assert row["fieldGoalsMade"]==1
    assert row["extraPointAttempts"]==4
    assert out["coverage"]["kickerMappedWeeks"]==1

def test_missing_kicker_column_remains_null():
    context=build_context(fixture().drop(columns=[
        "field_goal_kicker_player_id", "extra_point_kicker_player_id"
    ]),{},8)
    stats=pd.DataFrame([
        {"season":2026,"season_type":"REG","week":8,"player_id":"00-0000001",
         "position":"K","fg_att":2}
    ])
    out=merge_weekly_kickers(context,stats,{"00-0000001":"12345"},8)
    row=out["byKickerSleeper"]["12345"][0]
    assert row["fieldGoalAttempts"]==2
    assert row["fieldGoalsMade"] is None
    assert row["extraPointAttempts"] is None

def test_future_kicker_week_excluded():
    context=build_context(fixture(),{},8)
    stats=pd.DataFrame([
        {"season":2026,"season_type":"REG","week":9,"player_id":"00-0000001",
         "position":"K","fg_att":33,"fg_made":33}
    ])
    out=merge_weekly_kickers(context,stats,{"00-0000001":"12345"},8)
    assert out["coverage"]["kickers"]==0
