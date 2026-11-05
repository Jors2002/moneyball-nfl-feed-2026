#!/usr/bin/env python3
"""Chronological retrospective audit: original opportunity model vs learned role candidate.

2023 learns alert thresholds; 2024 early residuals estimate intervals; 2024 late
is development validation; 2025 is a frozen retrospective audit. None is a new
prospective trial: source files were revised and model family already exists.
Unobserved fantasy outcomes remain missing, including zero-offense participants.
"""
import argparse
from collections import Counter
import json
import hashlib
from pathlib import Path
import numpy as np
import pandas as pd
from moneyball8_forecast import load_history,adjust_scoring,feature_rows,walk_forward,ridge_predict,metrics,interval_radius
from moneyball8_role_data import prepare_histories
from moneyball8_roles import calibrate,detect,POSITIONS

COLUMNS=['original','last_share','prior_share','share_delta','last_carries','last_targets']

def paired_interval(rows,seed=810,draws=1000):
    """Paired MAE difference, resampling whole weeks to retain shared-week shocks."""
    if rows.empty:return None
    diffs=np.abs(rows.candidate-rows.actual)-np.abs(rows.original-rows.actual)
    blocks=pd.DataFrame({'week':rows.week,'diff':diffs}).groupby('week')['diff'].agg(['sum','count'])
    if len(blocks)<4:return None
    rng=np.random.default_rng(seed);idx=rng.integers(0,len(blocks),size=(draws,len(blocks)))
    estimates=blocks['sum'].to_numpy()[idx].sum(1)/blocks['count'].to_numpy()[idx].sum(1)
    return {'difference':float(diffs.mean()),'lower95':float(np.quantile(estimates,.025)),
            'upper95':float(np.quantile(estimates,.975)),'weekClusters':len(blocks),'draws':draws}

def audit(stats,snaps,crosswalk,pass_int_points=-1):
    scored=adjust_scoring(stats,pass_int_points)
    histories=prepare_histories(scored,snaps,crosswalk)
    policy=calibrate(histories,2023)
    original=walk_forward(feature_rows(scored))
    lookup={(h['gsisId'],h['season']):h for h in histories}
    examples=[];counts=Counter()
    for p in original.to_dict('records'):
        h=lookup.get((p['player_id'],p['season']))
        if not h:counts['unmapped']=counts['unmapped']+1;continue
        before=[r for r in h['rows'] if r['week']<p['week']]
        role=detect(before,p['position'],p['week']-1,policy)
        prior=role.get('previous') or {};recent=role.get('recent') or {}
        examples.append({**p,'original':p['opportunity_ridge'],'roleStatus':role['status'],
            'flagged':not role['decisionAllowed'],
            'last_share':recent.get('snapShareLatest',np.nan),
            'prior_share':prior.get('snapShareMedian3',np.nan),
            'share_delta':role.get('delta',np.nan),
            'last_carries':recent.get('carries',np.nan),'last_targets':recent.get('targets',np.nan)})
    frame=pd.DataFrame(examples)
    frame[COLUMNS]=frame[COLUMNS].astype(float)
    predicted=[]
    for (year,week),group in frame.groupby(['season','week'],sort=True):
        earlier=frame[(frame.season<year)|((frame.season==year)&(frame.week<week))]
        for pos,test in group.groupby('position'):
            train=earlier[earlier.position==pos]
            if len(train)<60:continue
            candidate=ridge_predict(train,test,COLUMNS,penalty=30.)
            for row,guess in zip(test.to_dict('records'),candidate):predicted.append({**row,'candidate':float(guess)})
    results=pd.DataFrame(predicted)
    report={}
    for pos in POSITIONS:
        x=results[results.position==pos]
        cal=x[(x.season==2024)&(x.week<=8)]
        cohorts={}
        for label,cohort in [('development_2024_W9_18',x[(x.season==2024)&(x.week>8)]),
                             ('frozen_retrospective_audit_2025',x[x.season==2025])]:
            data={}
            for cname,y in [('all',cohort),('role_review',cohort[cohort.flagged]),
                            ('abrupt_loss',cohort[cohort.roleStatus=='ABRUPT_PARTICIPATION_LOSS']),
                            ('utilization_increase',cohort[cohort.roleStatus=='SUSTAINED_UTILIZATION_INCREASE']),
                            ('no_review',cohort[~cohort.flagged])]:
                data[cname]={}
                data[cname]['pairedMAEDifference']=paired_interval(y)
                for model in ('original','candidate'):
                    score=metrics(y.actual,y[model]); score['interval80_coverage']=None
                    if len(cal)>=20 and len(y):
                        radius=interval_radius(cal.actual-cal[model]);score['interval80_radius']=radius
                        score['interval80_coverage']=float((np.abs(y.actual-y[model])<=radius).mean())
                    data[cname][model]=score
            cohorts[label]=data
        report[pos]=cohorts
    # Count outcomes missing from the underlying stat table, never infer 0 PPR.
    zero_missing={};eligible_zero_missing={}
    persistence=Counter()
    for h in histories:
        if h['season'] not in (2024,2025):continue
        for row in h['rows']:
            if row.get('snaps')==0 and row.get('gameStatus')=='PLAYED' and row.get('ppr') is None:
                k=str(h['season']);zero_missing[k]=zero_missing.get(k,0)+1
                prior=[r for r in h['rows'] if r['week']<row['week'] and r.get('ppr') is not None]
                if (len(prior)>=3 and row['week']-prior[-1]['week']<=2 and
                    np.mean([r['ppr'] for r in prior[-4:]])>=5):
                    eligible_zero_missing[k]=eligible_zero_missing.get(k,0)+1
            w=row['week']
            if w<4:continue
            now=detect(h['rows'],h['position'],w,policy)
            if now['status']!='ABRUPT_PARTICIPATION_LOSS':continue
            future=next((r for r in h['rows'] if r['week']==w+1 and r.get('snapObserved') is True and r.get('team')==row.get('team')),None)
            if future is None:persistence['future_snap_unknown']+=1;continue
            persistence['alerts_with_next_snap_observed']+=1
            prior=now['previous']['snapShareMedian3']
            # Evaluation-only recovery proxy; never a causal role label.
            if future['snapShare']>=prior:persistence['next_game_recovered_prior_share']+=1
            else:persistence['next_game_below_prior_share']+=1
    return {'schemaVersion':81,'module':'ROLE_RETROSPECTIVE_AUDIT','positions':report,
        'policy':policy,'examples':len(results),'zeroOffenseMissingFantasyOutcome':zero_missing,
        'baselineEligibleZeroOffenseMissingOutcome':eligible_zero_missing,
        'missingOutcomeCountScope':'First count all mapped QB/RB/WR/TE snap rows; second count only original baseline eligibility',
        'alertPersistenceProxy':dict(persistence),
        'candidate':{'model':'expanding position-specific ridge, penalty30','features':COLUMNS,
                     'promoted':False,'adjustedProjection':None},
        'promotionGate':{'status':'NOT_PROMOTED','reasons':[
            'Verified zero-offense participants can have missing fantasy outcomes; complete-cohort performance is unestablished.',
            'Source publication-time vintages and availability calibration are absent.',
            'No independent future test of this new role-aware adjustment exists.']},
        'evaluationDesign':{'thresholds':'2023 only; empirical 95th conditional tail',
            'intervals':'2024 W1-8 residuals','development':'2024 W9-18',
            'audit':'2025 fixed retrospective comparison; not a prospective trial',
            'cohort':'Original8 opportunity forecasts with observed next PPR; same rows for both models',
            'week9_2026':'Preserved prospective vintage; no outcome used in design'},
        'limitations':['Persistence proxy is not labeled tactical role truth; injury exits can recover.',
            'No causal sensitivity/specificity claim without independently labeled role changes.',
            'No fabricated zero fantasy outcomes and no participation probabilities.']},results

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--cache-dir',type=Path,required=True)
    ap.add_argument('--snap-dir',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--policy-output',type=Path,required=True)
    a=ap.parse_args()
    stats=load_history([a.cache_dir/f'stats_player_week_{y}.csv' for y in (2023,2024,2025)])
    snaps=pd.concat([pd.read_csv(a.snap_dir/f'snaps_{y}.csv') for y in (2023,2024,2025)],ignore_index=True)
    r,p=audit(stats,snaps,pd.read_csv(a.cache_dir/'db_playerids.csv',low_memory=False))
    r['policy']['calibrationSourceSha256']={
        'snaps_2023':hashlib.sha256((a.snap_dir/'snaps_2023.csv').read_bytes()).hexdigest(),
        'identity_crosswalk':hashlib.sha256((a.cache_dir/'db_playerids.csv').read_bytes()).hexdigest()}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(r,ensure_ascii=False,allow_nan=False,indent=2)+'\n')
    a.policy_output.write_text(json.dumps(r['policy'],allow_nan=False,indent=2)+'\n')
    print('ROLE_RETROSPECTIVE_AUDIT_OK',r['examples'],r['promotionGate'])

if __name__=='__main__':main()
