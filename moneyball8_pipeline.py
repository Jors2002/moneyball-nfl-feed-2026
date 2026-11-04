#!/usr/bin/env python3
"""Incremental public data acquisition and validated last-good forecast publishing."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
from moneyball8_cache import fetch

def validate_prediction(feed, season, through):
    if feed.get('schemaVersion') != 80 or feed.get('season') != season:
        raise ValueError('Wrong prediction schema/season')
    if feed.get('asOfWeek') != through or feed.get('targetWeek') != through+1:
        raise ValueError('Wrong prediction target/cutoff')
    for field in ('generatedAt','sourceGeneratedAt'):
        date=datetime.fromisoformat(feed[field].replace('Z','+00:00'))
        if date.tzinfo is None or date > datetime.now(timezone.utc):
            raise ValueError('Invalid prediction timestamp')
    players=feed.get('bySleeper')
    if not isinstance(players,dict) or len(players)<100:
        raise ValueError('Insufficient mapped forecast coverage')
    for sid,p in players.items():
        if not str(sid).isdigit() or p.get('position') not in ('QB','RB','WR','TE'):
            raise ValueError('Invalid mapped player')
        values=[p.get('projection'),p.get('interval80',{}).get('lower'),p.get('interval80',{}).get('upper')]
        if any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in values):
            raise ValueError('Missing/nonfinite projection')
        if not values[1]<=values[0]<=values[2]:
            raise ValueError('Unordered prediction interval')
    return len(players)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source-gzip',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--cache-dir',type=Path,default=Path('.cache/moneyball8'))
    ap.add_argument('--validation-output',type=Path,default=Path('data/_MONEYBALL8_VALIDATION.json'))
    ap.add_argument('--pass-int-points',type=float,default=-2)
    args=ap.parse_args()
    with gzip.open(args.source_gzip,'rt') as f: source=json.load(f)
    season,through=source['season'],source['thruWeek']
    if source.get('schemaVersion')!=5 or season!=2026 or type(through) is not int or not 1<=through<=17:
        raise ValueError('Need verified regular-season source cutoff')
    from moneyball6_validate import audit
    quality=audit(source,max_age_hours=168)
    if quality['status']=='FAIL' or quality['metrics']['ageHours']>168:
        raise ValueError('Source failed strict quality/freshness gate')
    provenance=[]
    histories=[]
    for year in range(2023,season+1):
        path=args.cache_dir/f'stats_player_week_{year}.csv'
        provenance.append(fetch(f'https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{year}.csv',path,immutable=year<season))
        histories.extend(['--history',str(path)])
    crosswalk=args.cache_dir/'db_playerids.csv'
    provenance.append(fetch('https://raw.githubusercontent.com/dynastyprocess/data/master/files/db_playerids.csv',crosswalk))
    staging=Path(str(args.output)+'.staging.gz')
    validation_staging=Path(str(args.validation_output)+'.staging')
    cmd=[sys.executable,str(Path(__file__).with_name('moneyball8_forecast.py')),*histories,
         '--output',str(validation_staging),'--crosswalk',str(crosswalk),
         '--forecast-output',str(staging),'--forecast-season',str(season),
         '--as-of-week',str(through),'--source-generated-at',source['generatedAt'],
         '--pass-int-points',str(args.pass_int_points)]
    try:
        subprocess.run(cmd,check=True,capture_output=True,text=True)
    except subprocess.CalledProcessError as error:
        raise RuntimeError('Forecast build failed; published feed retained. '+
                           (error.stderr or error.stdout or '')[-4000:]) from error
    with gzip.open(staging,'rt') as f: feed=json.load(f)
    count=validate_prediction(feed,season,through)
    feed['dataProvenance']=provenance
    model_sha=hashlib.sha256(Path(__file__).with_name('moneyball8_forecast.py').read_bytes()).hexdigest()
    fingerprint=hashlib.sha256(json.dumps({'sources':[p['sha256'] for p in provenance],
        'model_sha256':model_sha,'season':season,'through':through,
        'pass_int_points':args.pass_int_points},sort_keys=True).encode()).hexdigest()
    feed['modelVersion']='8.0.0'
    feed['modelCodeSha256']=model_sha
    feed['predictionVintage']=fingerprint
    # All gates pass before replacing a published feed. A failed run retains it.
    with gzip.open(staging,'wt',encoding='utf-8') as f:
        json.dump(feed,f,ensure_ascii=False,allow_nan=False,separators=(',',':'))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    staging.replace(args.output)
    args.validation_output.parent.mkdir(parents=True,exist_ok=True)
    validation_staging.replace(args.validation_output)
    archive=args.output.parent/'history'/f'moneyball8_{season}_w{through+1:02d}_{fingerprint[:12]}.json.gz'
    archive.parent.mkdir(parents=True,exist_ok=True)
    if not archive.exists():
        archive.write_bytes(args.output.read_bytes())
    print(f'MONEYBALL8_PUBLISHED players={count} target={through+1}; conditional participation, no title odds')

if __name__=='__main__': main()
