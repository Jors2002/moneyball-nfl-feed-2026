"""Regression: separate last-observed-week BYE from forecast target-week BYE."""
import pandas as pd
from moneyball8_role_pipeline import verified_target_schedule, target_week_role_gate

TEAMS = "ARI ATL BAL BUF CAR CHI CIN CLE DAL DEN DET GB HOU IND JAX KC LAC LAR LV MIA MIN NE NO NYG NYJ PHI PIT SEA SF TB TEN WAS".split()
def schedule():
    b = {w:[] for w in range(1,19)}
    b[10]=['CHI','DEN','PHI','TB']
    rest = [t for t in TEAMS if t not in b[10]]
    for w in [5,6,7,8,9,11,12]:
        b[w]=rest[:4]
        rest=rest[4:]
    assert not rest
    out=[]
    for w in range(1,19):
        playing=[t for t in TEAMS if t not in b[w]]
        for i in range(0,len(playing),2):
            out.append(dict(season=2026,game_type='REG',week=w,
                            game_id=f'{2026}_{w}_{i}',home_team=playing[i],
                            away_team=playing[i+1]))
    assert len(out)==272
    return pd.DataFrame(out)

def test_week10_byes_and_legacy_week9_status():
    byes,active = verified_target_schedule(schedule(),2026,10)
    assert byes == ['CHI','DEN','PHI','TB']
    assert {'PIT','TEN','GB','NO'} <= active
    sidecar = {'bySleeper':{
        'p':{'team':'PHI','decisionProjection':12.0,
             'roleEvaluation':{'status':'NO_ABRUPT_SNAP_SIGNAL','decisionAllowed':True,'quality':'OK','signals':[]}},
        'd':{'team':'DEN','decisionProjection':8.0,
             'roleEvaluation':{'status':'NO_ABRUPT_SNAP_SIGNAL','decisionAllowed':True,'quality':'OK','signals':[]}},
        't':{'team':'TEN','decisionProjection':None,
             'roleEvaluation':{'status':'BYE','decisionAllowed':False,'quality':'VERIFIED_BYE','signals':[]}},
        's':{'team':'PIT','decisionProjection':None,
             'roleEvaluation':{'status':'BYE','decisionAllowed':False,'quality':'VERIFIED_BYE','signals':[]}},
    }}
    x=target_week_role_gate(sidecar,byes,active,10)['bySleeper']
    for id in ('p','d'):
        assert x[id]['targetWeekSchedule']['status']=='BYE'
        assert x[id]['roleEvaluation']['status']=='TARGET_WEEK_BYE'
        assert x[id]['roleEvaluation']['decisionAllowed'] is False
        assert x[id]['decisionProjection'] is None
    for id in ('t','s'):
        assert x[id]['targetWeekSchedule']['status']=='SCHEDULED'
        assert x[id]['roleEvaluation']['status']=='PREVIOUS_WEEK_BYE'
        assert x[id]['roleEvaluation']['decisionAllowed'] is False
        assert x[id]['decisionProjection'] is None

def test_missing_team_never_assumed_active():
    byes,active=verified_target_schedule(schedule(),2026,10)
    sidecar={'bySleeper':{'n':{'team':'N/D','decisionProjection':10,
                 'roleEvaluation':{'status':'NO_ABRUPT_SNAP_SIGNAL','quality':'OK',
                     'decisionAllowed':True,'signals':[]}}}}
    x=target_week_role_gate(sidecar,byes,active,10)['bySleeper']['n']
    assert x['roleEvaluation']['status']=='TARGET_SCHEDULE_UNVERIFIED'
    assert x['decisionProjection'] is None

def test_incomplete_schedule_fails_closed():
    bad = schedule().iloc[:-1].copy()
    try:
        verified_target_schedule(bad,2026,10)
    except ValueError as e:
        assert 'TARGET_SCHEDULE' in str(e)
    else:
        assert False, 'incomplete schedule was accepted'
