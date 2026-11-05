"""Conservative NFLverse stats/snaps join, keyed by unique player and event week."""
from collections import defaultdict
import math
import pandas as pd
from moneyball8_roles import POSITIONS

def value(x):
    if isinstance(x,str):return x
    return float(x) if pd.notna(x) and math.isfinite(x) else None

def prepare_histories(stats, snaps, crosswalk):
    ids=crosswalk[['pfr_id','gsis_id','sleeper_id']].dropna().copy()
    ids['sleeper_id']=ids.sleeper_id.astype(str).str.replace(r'\.0$','',regex=True)
    ids=ids.drop_duplicates()
    ids=ids[~ids.pfr_id.duplicated(keep=False)&~ids.gsis_id.duplicated(keep=False)&~ids.sleeper_id.duplicated(keep=False)]
    mapping={r.pfr_id:(r.gsis_id,r.sleeper_id) for r in ids.itertuples()}
    smap={r.gsis_id:r.sleeper_id for r in ids.itertuples()}
    records={}; metadata={}
    regular=stats[stats.position.isin(POSITIONS)].copy()
    if 'season_type' in regular:regular=regular[regular.season_type=='REG']
    for r in regular.to_dict('records'):
        sid=smap.get(r['player_id'])
        if not sid:continue
        k=(sid,int(r['season']),int(r['week']))
        if k in records: raise ValueError('Duplicate stats player-season-week')
        team=r.get('team',r.get('recent_team'))
        records[k]={'week':k[2],'season':k[1],'playerId':sid,'team':team,'snapObserved':False,
            'snaps':None,'snapShare':None,'gameStatus':'STATS_RECORDED',
            'carries':value(r.get('carries',r.get('rushing_attempts'))),
            'targets':value(r.get('targets')),'targetShare':value(r.get('target_share')),
            'ppr':value(r.get('fantasy_points_ppr')),
            'routes':None,'targetsPerRoute':None,'routeParticipation':None}
        metadata[(sid,k[1])]={'position':r['position'],'name':r.get('player_display_name') or r.get('player_name'),
            'gsisId':r['player_id']}
    regular_snaps=snaps[snaps.position.isin(POSITIONS)&(snaps.game_type=='REG')]
    duplicate=set()
    for r in regular_snaps.to_dict('records'):
        pair=mapping.get(r['pfr_player_id'])
        if not pair:continue
        gsis,sid=pair;k=(sid,int(r['season']),int(r['week']))
        row=records.setdefault(k,{'week':k[2],'season':k[1],'playerId':sid,'carries':None,'targets':None,
            'ppr':None,'targetShare':None,'routes':None,'targetsPerRoute':None,'routeParticipation':None})
        if row.get('snapObserved') is True or k in duplicate:
            duplicate.add(k);row.update(snapObserved=False,snaps=None,snapShare=None,gameStatus='AMBIGUOUS_MULTI_TEAM_WEEK');continue
        observed=pd.notna(r['offense_snaps']) and pd.notna(r['offense_pct'])
        positive=any(pd.notna(r.get(key)) and r[key]>0 for key in ('offense_snaps','defense_snaps','st_snaps'))
        row.update(team=r['team'],gameId=r['game_id'],snapObserved=observed,
            snaps=value(r['offense_snaps']),snapShare=value(r['offense_pct']),
            specialTeamsSnaps=value(r.get('st_snaps')),gameStatus='PLAYED' if positive else 'ZERO_ROW_STATUS_UNKNOWN',
            snapSource=f"https://github.com/nflverse/nflverse-data/releases/download/snap_counts/snap_counts_{k[1]}.csv")
        metadata[(sid,k[1])]={'position':r['position'],'name':r['player'],'gsisId':gsis}
    grouped=defaultdict(list)
    for (sid,season,w),row in records.items():grouped[(sid,season)].append(row)
    return [{'sleeperId':sid,'season':season,**metadata[(sid,season)],'rows':sorted(rows,key=lambda x:x['week'])}
            for (sid,season),rows in grouped.items()]

def overlay_current(histories, feed):
    """Use existing observed premium metrics only; never synthesize route data."""
    for h in histories:
        if h['season']!=feed['season']:continue
        index={r['week']:r for r in feed['bySleeper'].get(h['sleeperId'],[])}
        for row in h['rows']:
            source=index.get(row['week'],{})
            for k in ('redzoneCarries','inside5Carries','redzoneTargets','inside5Targets','routes','targetsPerRoute','routeParticipation'):
                row[k]=source.get(k)
    return histories
