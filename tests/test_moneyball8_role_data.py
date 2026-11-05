import pandas as pd
import pytest
from moneyball8_role_data import prepare_histories
from moneyball8_role_pipeline import check_sidecar,apply_verified_byes

def tables():
    ids=pd.DataFrame([{'pfr_id':'p','gsis_id':'g','sleeper_id':'123'}])
    stats=pd.DataFrame([{'player_id':'g','player_display_name':'Test','position':'RB',
        'season':2026,'season_type':'REG','week':7,'team':'SEA','carries':24,'targets':1,'fantasy_points_ppr':18.5}])
    snaps=pd.DataFrame([{'pfr_player_id':'p','season':2026,'week':8,'position':'RB','game_type':'REG',
        'player':'Test','team':'SEA','opponent':'CHI','game_id':'2026_08_CHI_SEA',
        'offense_snaps':0,'offense_pct':0.,'defense_snaps':0,'st_snaps':7}])
    return stats,snaps,ids

def test_zero_offense_record_joins_without_fabricated_ppr():
    h=prepare_histories(*tables())[0]['rows']
    assert len(h)==2 and h[-1]['snaps']==0 and h[-1]['snapObserved']
    assert h[-1]['gameStatus']=='PLAYED' and h[-1]['specialTeamsSnaps']==7
    assert h[-1]['carries'] is None and h[-1]['ppr'] is None

def test_duplicate_team_week_not_summed_into_fake_share():
    s,n,i=tables();other=n.copy();other['team']='DAL'
    rows=prepare_histories(s,pd.concat([n,other]),i)[0]['rows']
    assert rows[-1]['gameStatus']=='AMBIGUOUS_MULTI_TEAM_WEEK'
    assert rows[-1]['snapObserved'] is False and rows[-1]['snapShare'] is None

def test_absent_snap_row_is_coverage_unknown_not_zero():
    s,n,i=tables();row=prepare_histories(s,n.iloc[:0],i)[0]['rows'][0]
    assert row['snaps'] is None and not row['snapObserved']

def sidecars():
    f={'predictionVintage':'v','asOfWeek':8,'targetWeek':9,'bySleeper':{'1':{'projection':15.327}}}
    r={'schemaVersion':81,'forecastVintage':'v','asOfWeek':8,'targetWeek':9,
        'bySleeper':{'1':{'originalProjection':15.327,'adjustedProjection':None,'decisionProjection':None,
            'roleEvaluation':{'status':'ABRUPT_PARTICIPATION_LOSS','decisionAllowed':False}}}}
    return f,r

def test_sidecar_never_modifies_original_and_cannot_leak_alert_points():
    f,r=sidecars();assert check_sidecar(r,f)==1
    r['bySleeper']['1']['decisionProjection']=15.327
    with pytest.raises(ValueError):check_sidecar(r,f)

def test_wrong_vintage_or_point_adjustment_is_rejected():
    f,r=sidecars();r['forecastVintage']='other'
    with pytest.raises(ValueError):check_sidecar(r,f)
    f,r=sidecars();r['bySleeper']['1']['adjustedProjection']=0
    with pytest.raises(ValueError):check_sidecar(r,f)

def test_incomplete_schedule_cannot_create_false_bye():
    stats,snaps,ids=tables();h=prepare_histories(stats,snaps,ids)
    games=pd.DataFrame([{'season':2026,'game_type':'REG','game_id':'1','week':8,'home_team':'NE','away_team':'DAL'}])
    out,status=apply_verified_byes(h,games,2026,9)
    assert status=='SCHEDULE_INCOMPLETE_NO_BYE_INFERENCE' and out[0]['rows'][-1]['week']==8

def test_etl_retains_special_teams_evidence_and_game_identity():
    from moneyball5_etl import build_snap_index,PARQUET_FIELDS
    s,n,i=tables()
    out=build_snap_index(n,{'p':'123'},8)[('123',8)]
    assert out['snapObserved'] and out['snaps']==0 and out['snapShare']==0
    assert out['specialTeamsSnaps']==7 and out['snapTeam']=='SEA'
    assert out['snapGameId']=='2026_08_CHI_SEA'
    assert out['participationEvidence']=='POSITIVE_SNAP_IN_ANY_PHASE'
    assert {'team','game_id','st_snaps'}<=set(PARQUET_FIELDS['snaps'])

def test_missing_snap_percentage_is_not_manufactured_as_zero_share():
    from moneyball5_etl import build_snap_index
    s,n,i=tables();n['offense_pct']=float('nan')
    out=build_snap_index(n,{'p':'123'},8)[('123',8)]
    assert out['snapShare'] is None and not out['snapObserved']
