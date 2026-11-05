from copy import deepcopy
import pytest
from moneyball8_roles import detect,calibrate,annotate_forecasts

POLICY={'positions':{p:{'status':'CALIBRATED_ALERT_THRESHOLD','drop':.3,'gain':.25} for p in ('RB','WR','TE','QB')}}
NOW='2026-11-05T12:00:00+00:00'

def rows(shares,team='SEA'):
    return [{'week':i+1,'season':2026,'playerId':'1','team':team,'snapObserved':True,
        'snapShare':s,'snaps':int(s*100),'gameStatus':'PLAYED','carries':20,'targets':3,
        'routes':None,'targetsPerRoute':None} for i,s in enumerate(shares)]

def context(kind):
    return {'kind':kind,'team':'SEA','positions':['RB'],'eventWeek':4,'season':2026,
            'playerId':'1','verified':True,'publishedAt':'2026-11-03T12:00:00+00:00',
            'sourceUrl':'https://www.seahawks.com/news/test','officialHosts':['www.seahawks.com']}

def test_wilson_observed_zero_is_review_not_fixed_haircut():
    r=detect(rows([.59,.32,.48,0]),'RB',4,POLICY,decision_at=NOW,contexts=[context('TEAMMATES_RETURNED')])
    assert r['status']=='ABRUPT_PARTICIPATION_LOSS'
    assert r['cause'].startswith('VERIFIED_TEAMMATE_RETURNS')
    assert r['decisionAllowed'] is False and r['adjustedProjection'] is None
    assert r['participationProbability'] is None

def test_stable_starter_is_not_suppressed():
    assert detect(rows([.7,.73,.69,.72]),'RB',4,POLICY)['decisionAllowed']

def test_in_game_injury_is_confounded_not_depth_chart_loss():
    r=detect(rows([.8,.8,.8,.1]),'RB',4,POLICY,decision_at=NOW,contexts=[context('PLAYER_EXIT_INJURY')])
    assert r['status']=='INJURY_CONFOUNDED_DROP' and r['cause']=='VERIFIED_IN_GAME_INJURY'

def test_recovery_after_absent_teammate_is_contextual_not_assumed():
    r=detect(rows([.15,.2,.8,.85]),'RB',4,POLICY,decision_at=NOW,contexts=[context('TEAMMATES_ABSENT')])
    assert r['status']=='TEMPORARY_VOLUME_RISK' and not r['decisionAllowed']
    assert detect(rows([.15,.2,.8,.85]),'RB',4,POLICY)['cause']=='UNKNOWN'

def test_wr_targets_down_routes_retained_is_not_role_loss():
    x=rows([.8]*4)
    for i,r in enumerate(x):r.update(routes=30,targets=10 if i<2 else 3)
    out=detect(x,'WR',4,POLICY)
    assert out['status']=='TARGET_VARIATION_WITH_ROUTES_RETAINED' and out['decisionAllowed']

def test_bye_is_not_zero():
    x=rows([.7]*4);x[-1].update(gameStatus='BYE',snapObserved=False,snaps=None,snapShare=None)
    assert detect(x,'RB',4,POLICY)['status']=='BYE'

def test_missing_snap_coverage_is_not_zero():
    x=rows([.7]*4);x[-1].update(snapObserved=False,snaps=None,snapShare=None)
    assert detect(x,'RB',4,POLICY)['status']=='INSUFFICIENT_EVIDENCE'

def test_inactive_and_zero_without_active_evidence_are_not_tactical_loss():
    x=rows([.7,.7,.7,0]);x[-1]['gameStatus']='INACTIVE'
    assert detect(x,'RB',4,POLICY)['status']=='INACTIVE'
    x[-1]['gameStatus']='ZERO_ROW_STATUS_UNKNOWN'
    assert detect(x,'RB',4,POLICY)['status']=='INSUFFICIENT_EVIDENCE'

def test_trade_resets_comparison():
    x=rows([.7]*4);x[-1]['team']='DAL'
    assert detect(x,'RB',4,POLICY)['status']=='TEAM_CHANGE'

def test_rookie_small_sample():
    assert detect(rows([.2,.7]),'RB',2,POLICY)['status']=='INSUFFICIENT_EVIDENCE'

def test_sustained_increase_requires_both_recent_games():
    assert detect(rows([.1,.1,.8,.8]),'RB',4,POLICY)['status']=='SUSTAINED_UTILIZATION_INCREASE'
    assert detect(rows([.1,.1,.1,.8]),'RB',4,POLICY)['status']!='SUSTAINED_UTILIZATION_INCREASE'

def test_future_rows_and_news_cannot_change_current_decision():
    x=rows([.6,.6,.6,.6,0]);x[-1]['availableAt']='2026-11-06T00:00:00+00:00'
    assert detect(x,'RB',4,POLICY)==detect(x[:4],'RB',4,POLICY)
    c=context('PLAYER_EXIT_INJURY');c['publishedAt']='2026-11-06T00:00:00+00:00'
    r=detect(rows([.8,.8,.8,.1]),'RB',4,POLICY,decision_at=NOW,contexts=[c])
    assert r['cause']=='UNKNOWN'

def test_duplicate_and_invalid_observation_rejected():
    x=rows([.6]*4)
    with pytest.raises(ValueError):detect(x+[x[-1]],'RB',4,POLICY)
    x[-1]['snaps']=float('nan')
    with pytest.raises(ValueError):detect(x,'RB',4,POLICY)

def test_missing_current_week_no_stale_signal():
    assert detect(rows([.6,.6,.6,0]),'RB',5,POLICY)['status']=='NO_CURRENT_OBSERVATION'

def test_threshold_calibration_never_uses_test_season():
    a={'season':2023,'position':'RB','rows':rows([.1,.2,.5,.8]*4)}
    p=calibrate([a]);b=deepcopy(a);b['season']=2025
    assert p==calibrate([a,b])

def test_qb_documented_change_requires_dated_context():
    c=context('QB_STARTER_CHANGE');c['positions']=['QB']
    out=detect(rows([.7]*4),'QB',4,POLICY,contexts=[c],decision_at=NOW)
    assert out['status']=='POSSIBLE_HIERARCHY_CHANGE'

def test_news_from_another_season_cannot_supply_current_cause():
    c=context('PLAYER_EXIT_INJURY');c['season']=2025
    assert detect(rows([.8,.8,.8,.1]),'RB',4,POLICY,decision_at=NOW,contexts=[c])['cause']=='UNKNOWN'

def test_ambiguous_historical_zero_does_not_depress_comparison_baseline():
    x=rows([.7,.7,0,.7,.7]);x[2]['gameStatus']='ZERO_ROW_STATUS_UNKNOWN'
    out=detect(x,'RB',5,POLICY)
    assert out['previous']['snapShareMedian3']==.7
    assert out['priorWeeks']==[1,2,4]

def test_future_modified_context_is_excluded_and_same_week_future_row_is_unknown():
    c=context('PLAYER_EXIT_INJURY');c['modifiedAt']='2026-11-06T00:00:00+00:00'
    assert detect(rows([.8,.8,.8,.1]),'RB',4,POLICY,decision_at=NOW,contexts=[c])['cause']=='UNKNOWN'
    x=rows([.8,.8,.8,0]);x[-1]['availableAt']='2026-11-06T00:00:00+00:00'
    assert detect(x,'RB',4,POLICY,decision_at=NOW)['status']=='NO_CURRENT_OBSERVATION'
