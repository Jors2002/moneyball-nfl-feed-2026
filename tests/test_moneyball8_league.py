from copy import deepcopy
import pytest
from moneyball8_league import build, scoring_compatibility, score_decimal, write_private_report, NFLVERSE_SCORING, STARTERS


def fixture():
    league = {'season':'2026','roster_positions':STARTERS+['BN']*5,
              'settings':{'num_teams':10,'playoff_teams':6,'playoff_week_start':15,'reserve_slots':1,
                          'trade_deadline':11,'trade_review_days':2,'reserve_allow_out':1},
              'scoring_settings':dict(NFLVERSE_SCORING,pass_int=-1)}
    rosters = [{'roster_id':i,'players':[f'{i}_{j}' for j in range(9)],
                'starters':[f'{i}_{j}' for j in range(9)],'reserve':[],
                'settings':{'wins':i%7,'losses':8-i%7,'ties':0,'fpts':1000+i,'fpts_decimal':5,
                            'fpts_against':900,'fpts_against_decimal':99}} for i in range(1,11)]
    bracket = [{'m':1,'r':1,'t1':3,'t2':6},{'m':2,'r':1,'t1':4,'t2':5},
               {'m':3,'r':2,'t1':1,'t2':None,'t2_from':{'w':1}},
               {'m':4,'r':2,'t1':2,'t2':None,'t2_from':{'w':2}},
               {'m':5,'r':3,'t1':None,'t2':None,'t1_from':{'w':3},'t2_from':{'w':4}}]
    return league,rosters,bracket,{'season':'2026','week':9}


def test_realistic_synthetic_reconstruction():
    r=build(*fixture())
    assert r['standings'][0]['roster_id']==6
    assert r['standings'][0]['pf']==1006.05
    assert r['standings'][0]['pa']==900.99
    assert r['scoring']['pass_interception_adjustment']==1
    assert r['playoffs']['provisional_bye_roster_ids']==[1,2]
    assert r['championship']['probability'] is None
    assert r['rules']['trade_deadline']==11


def test_decimal_not_binary_concatenation():
    assert score_decimal({'p':9,'d':7},'p','d')==9.07
    with pytest.raises(ValueError):score_decimal({'p':9,'d':100},'p','d')


def test_all_scoring_differences_are_disclosed():
    s=dict(NFLVERSE_SCORING,pass_td=6,rec=.5)
    assert scoring_compatibility(s)['status']=='RECOMPUTE_OFFENSIVE_SCORING'
    assert set(scoring_compatibility(s)['differences'])=={'pass_td','rec'}


@pytest.mark.parametrize('mutation', ['flex','season','duplicates','ownership','reserve','bracket','backref'])
def test_reject_invalid_inputs(mutation):
    l,r,b,n=fixture()
    if mutation=='flex':l['roster_positions'][6]='FLEX'
    if mutation=='season':n['season']='2025'
    if mutation=='duplicates':r[1]['roster_id']=r[0]['roster_id']
    if mutation=='ownership':r[0]['starters'][0]='unknown'
    if mutation=='reserve':r[0]['reserve']=['unknown']
    if mutation=='bracket':b[0]['t1']=100
    if mutation=='backref':b[2]['t2_from']={'w':5}
    with pytest.raises(ValueError):build(l,r,b,n)


def test_protect_private_output_from_git(tmp_path, monkeypatch):
    import moneyball8_league
    (tmp_path/'.git').mkdir()
    monkeypatch.setattr(moneyball8_league, '__file__', str(tmp_path/'moneyball8_league.py'))
    with pytest.raises(ValueError):write_private_report(tmp_path/'audit.json',{'test':1})
    target=tmp_path.parent/(tmp_path.name+'_private')/'audit.json'
    write_private_report(target,{'test':1})
    assert target.exists()


@pytest.mark.parametrize('coefficient', [float('nan'),float('inf'),float('-inf'),True])
def test_nonfinite_scoring_rejected(coefficient):
    scoring=dict(NFLVERSE_SCORING,pass_int=coefficient)
    with pytest.raises(ValueError):scoring_compatibility(scoring)


def test_cross_team_duplicate_ownership_rejected():
    l,r,b,n=fixture()
    r[1]['players'][0]=r[0]['players'][0]
    r[1]['starters'][0]=r[0]['players'][0]
    with pytest.raises(ValueError,match='cross-team'):build(l,r,b,n)
