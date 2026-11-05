#!/usr/bin/env python3
"""Publish evidence-only role sidecar without editing original forecast vintages."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import pandas as pd
from moneyball8_cache import fetch
from moneyball8_roles import annotate_forecasts, stamp
from moneyball8_role_data import prepare_histories,overlay_current

def check_sidecar(sidecar,forecast):
    if not forecast.get('predictionVintage') or type(forecast.get('asOfWeek')) is not int:
        raise ValueError('Forecast vintage/cutoff required for role safety')
    if (sidecar.get('schemaVersion')!=81 or sidecar.get('forecastVintage')!=forecast.get('predictionVintage') or
        sidecar.get('targetWeek')!=forecast.get('targetWeek') or sidecar.get('asOfWeek')!=forecast.get('asOfWeek')):
        raise ValueError('Role evidence does not match forecast vintage/week')
    if set(sidecar['bySleeper'])!=set(forecast['bySleeper']):raise ValueError('Role coverage mismatch')
    for sid,p in sidecar['bySleeper'].items():
        if p['originalProjection']!=forecast['bySleeper'][sid]['projection']:raise ValueError('Original projection changed')
        if p.get('adjustedProjection') is not None:raise ValueError('Unvalidated adjustment forbidden')
        role=p['roleEvaluation']
        if type(role.get('decisionAllowed')) is not bool:raise ValueError('Role decision gate missing')
        if not role['decisionAllowed'] and p.get('decisionProjection') is not None:raise ValueError('Review-required projection leaked')
    return len(sidecar['bySleeper'])

def apply_verified_byes(histories,games,season,through):
    games=games[(games.season==season)&(games.game_type=='REG')]
    if len(games)!=272 or games.game_id.duplicated().any():
        return histories,'SCHEDULE_INCOMPLETE_NO_BYE_INFERENCE'
    aliases={'JAC':'JAX','LA':'LAR','WSH':'WAS'}
    norm=lambda t:aliases.get(t,t)
    week=games[games.week==through]
    teams=[norm(t) for t in list(week.home_team)+list(week.away_team)]
    allteams={norm(t) for t in list(games.home_team)+list(games.away_team)}
    if len(teams)!=len(set(teams)) or len(allteams)!=32:return histories,'SCHEDULE_INVALID'
    for h in histories:
        if h['season']!=season or not h['rows'] or h['rows'][-1]['week']>=through:continue
        team=norm(h['rows'][-1]['team'])
        if team in allteams and team not in teams:
            h['rows'].append({'week':through,'season':season,'playerId':h['sleeperId'],
                'team':team,'gameStatus':'BYE','snapObserved':False,'snaps':None,'snapShare':None})
    return histories,'FULL_272_GAME_SCHEDULE_VALIDATED'

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--forecast',type=Path,required=True)
    ap.add_argument('--source-gzip',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--cache-dir',type=Path,default=Path('.cache/moneyball8'))
    ap.add_argument('--policy',type=Path,default=Path('data/role_policy_v81.json'))
    ap.add_argument('--contexts',type=Path,default=Path('data/role_context_2026.json'))
    a=ap.parse_args()
    with gzip.open(a.forecast,'rt') as f:forecast=json.load(f)
    with gzip.open(a.source_gzip,'rt') as f:source=json.load(f)
    if source['season']!=forecast['season'] or source['thruWeek']!=forecast['asOfWeek']:raise ValueError('Mismatched utilization/forecast cutoff')
    through=forecast['asOfWeek'];season=forecast['season']
    # Reuse exactly the CSV already acquired by the forecast pipeline.
    stat_path=a.cache_dir/f'stats_player_week_{season}.csv'
    actual_hash=hashlib.sha256(stat_path.read_bytes()).hexdigest()
    provenance=forecast.get('dataProvenance',[])
    if not any(p.get('sha256')==actual_hash for p in provenance):raise ValueError('Stats vintage not linked to forecast')
    snaps_path=a.cache_dir/f'snaps_{season}.csv'
    snap_meta=fetch(f'https://github.com/nflverse/nflverse-data/releases/download/snap_counts/snap_counts_{season}.csv',snaps_path)
    games_path=a.cache_dir/'role_games.csv'
    games_meta=fetch('https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv',games_path)
    stats=pd.read_csv(stat_path,low_memory=False)
    snaps=pd.read_csv(snaps_path)
    stats=stats[(stats.season==season)&(stats.week<=through)]
    snaps=snaps[(snaps.season==season)&(snaps.week<=through)]
    h=prepare_histories(stats,snaps,pd.read_csv(a.cache_dir/'db_playerids.csv',low_memory=False))
    h=overlay_current(h,source)
    h,schedule=apply_verified_byes(h,pd.read_csv(games_path,low_memory=False),season,through)
    contexts=json.loads(a.contexts.read_text()) if a.contexts.exists() else []
    decision=datetime.now(timezone.utc).isoformat()
    out=annotate_forecasts(forecast,h,json.loads(a.policy.read_text()),contexts,decision)
    out['quality']={'statusCounts':dict(Counter(p['roleEvaluation']['status'] for p in out['bySleeper'].values())),
                    'schedule':schedule,'adjustment':'NOT_PROMOTED','validatedAvailabilityModel':False,
                    'observedZeroPolicy':'Explicit snap row plus positive participation in any phase required'}
    out['dataProvenance']=[snap_meta,games_meta]
    validation_path=Path(__file__).parent/'data/_MONEYBALL8_ROLE_VALIDATION.json'
    if validation_path.exists():
        audit=json.loads(validation_path.read_text())
        if audit['policy']!=out['policy']:raise ValueError('Role audit and deployed threshold policy differ')
        out['validationSummary']={
            'label':'FROZEN_RETROSPECTIVE_2025_NOT_PROSPECTIVE','promoted':False,
            'zeroOffenseMissingFantasyOutcome':audit['zeroOffenseMissingFantasyOutcome'],
            'baselineEligibleZeroOffenseMissingOutcome':audit['baselineEligibleZeroOffenseMissingOutcome'],
            'positions':{pos:v['frozen_retrospective_audit_2025'] for pos,v in audit['positions'].items()}}
    check_sidecar(out,forecast)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    tmp=Path(str(a.output)+'.tmp')
    with gzip.open(tmp,'wt',encoding='utf-8') as f:json.dump(out,f,ensure_ascii=False,allow_nan=False,separators=(',',':'))
    # Keep first immutable sidecar for each evidence/code vintage, separate from forecast archives.
    code=b''.join(Path(__file__).with_name(name).read_bytes() for name in
        ('moneyball8_roles.py','moneyball8_role_data.py','moneyball8_role_pipeline.py'))
    validation_bytes=validation_path.read_bytes() if validation_path.exists() else b''
    vintage=hashlib.sha256(code+a.policy.read_bytes()+a.contexts.read_bytes()+validation_bytes+
        forecast.get('predictionVintage','').encode()+snap_meta['sha256'].encode()+games_meta['sha256'].encode()).hexdigest()[:12]
    archive=a.output.parent/'role_history'/f'role_{season}_w{through+1:02d}_{vintage}.json.gz'
    archive.parent.mkdir(parents=True,exist_ok=True)
    if not archive.exists():archive.write_bytes(tmp.read_bytes())
    tmp.replace(a.output)
    print('MONEYBALL_ROLE_PUBLISHED',len(out['bySleeper']),out['quality'])

if __name__=='__main__':main()
