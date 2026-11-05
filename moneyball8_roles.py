"""Evidence-first role diagnostics. No availability probabilities or point haircut.

Tail thresholds are learned on 2023 snap-share changes per position. They are
alert thresholds, not p-values or probabilities of a real depth-chart change.
Missing rows/bye/inactive/unknown coverage are never observed zero snaps.
"""
from __future__ import annotations
from datetime import datetime, timezone
from statistics import median, mean
import math
from urllib.parse import urlsplit
import numpy as np

POSITIONS = ('QB', 'RB', 'WR', 'TE')
ROLE_VERSION = '8.1.0'
REVIEW_STATUSES = {'ABRUPT_PARTICIPATION_LOSS','INJURY_CONFOUNDED_DROP',
                   'TEMPORARY_VOLUME_RISK','POSSIBLE_HIERARCHY_CHANGE',
                   'TEAM_CHANGE','INSUFFICIENT_EVIDENCE','NO_CURRENT_OBSERVATION'}

def numeric(x):
    return type(x) in (int,float) and math.isfinite(x)

def stamp(value):
    t=datetime.fromisoformat(value.replace('Z','+00:00'))
    if t.tzinfo is None: raise ValueError('Explicit timezone required')
    return t.astimezone(timezone.utc)

def verified_snap(row):
    return (row.get('snapObserved') is True and numeric(row.get('snaps')) and
            row['snaps'] >= 0 and numeric(row.get('snapShare')) and 0<=row['snapShare']<=1)

def comparable_snap(row):
    return (verified_snap(row) and row.get('gameStatus') not in ('BYE','INACTIVE') and
            (row['snaps']>0 or row.get('gameStatus')=='PLAYED'))

def eligible_rows(rows, through, decision_at=None):
    if type(through) is not int or not 1<=through<=18: raise ValueError('Invalid cutoff')
    decision=stamp(decision_at) if decision_at else None
    out=[];seen=set()
    for raw in rows:
        row=dict(raw); w=row.get('week')
        if type(w) is not int or not 1<=w<=18: raise ValueError('Invalid week')
        if w>through: continue
        if decision and row.get('availableAt'):
            if stamp(row['availableAt'])>decision: continue
        if w in seen: raise ValueError('Ambiguous duplicate player-week; resolve trade first')
        seen.add(w)
        if row.get('snapObserved') is True:
            if not verified_snap(row): raise ValueError('Invalid observed snap record')
        for key in ('routes','targetsPerRoute','routeParticipation','carries','targets','redzoneCarries','redzoneTargets'):
            v=row.get(key)
            if v is not None and (not numeric(v) or v<0 or (key=='targetsPerRoute' and v>1)):
                raise ValueError('Invalid observed metric '+key)
        out.append(row)
    return sorted(out,key=lambda r:r['week'])

def calibrate(histories, calibration_season=2023, quantile=0.95):
    """Fix thresholds before evaluation; 95th percentile = alert budget, not truth."""
    if not 0.5<quantile<1: raise ValueError('Invalid alert quantile')
    samples={p:[] for p in POSITIONS}; gain_samples={p:[] for p in POSITIONS}
    for h in histories:
        if h['season']!=calibration_season or h['position'] not in samples: continue
        prior=[]
        for row in eligible_rows(h['rows'],18):
            if not comparable_snap(row): continue
            if prior and row.get('team')!=prior[-1].get('team'): prior=[]
            if len(prior)>=3:
                previous=median(r['snapShare'] for r in prior[-3:])
                samples[h['position']].append(row['snapShare']-previous)
                gain_samples[h['position']].append(min(prior[-1]['snapShare'],row['snapShare'])-
                    mean(r['snapShare'] for r in prior[-3:-1]))
            prior.append(row)
    positions={}
    for pos,values in samples.items():
        if len(values)<30:
            positions[pos]={'status':'INSUFFICIENT_CALIBRATION','n':len(values)};continue
        drops=[-v for v in values if v<0];gains=[v for v in gain_samples[pos] if v>0]
        # No Wilson-specific floor or tuned constants: position empirical tails.
        positions[pos]={'status':'CALIBRATED_ALERT_THRESHOLD','n':len(values),
            'drop':float(np.quantile(drops,quantile)) if drops else 1.,
            'gain':float(np.quantile(gains,quantile)) if gains else 1.,
            'gainBasis':'min(recent2) minus mean(previous2)',
            'quantile':quantile}
    return {'version':ROLE_VERSION,'calibrationSeason':calibration_season,'positions':positions,
        'interpretation':'Empirical utilization-tail alert thresholds; NOT a calibrated causal classifier',
        'adjustmentPromoted':False,'adjustedProjection':None}

def contexts_before(contexts, row, position, decision_at):
    if not decision_at:return []
    out=[]
    for c in contexts:
        try:
            if (c.get('verified') is True and c.get('team')==row.get('team') and
                position in c.get('positions',[]) and c.get('eventWeek')==row['week'] and
                c.get('season')==row.get('season') and
                stamp(c['publishedAt'])<=stamp(decision_at) and
                (not c.get('modifiedAt') or stamp(c['modifiedAt'])<=stamp(decision_at)) and
                urlsplit(c['sourceUrl']).scheme=='https' and
                urlsplit(c['sourceUrl']).hostname in c.get('officialHosts',[])):
                out.append(c)
        except (KeyError,ValueError,TypeError):continue
    return out

def detect(rows, position, through, policy, *, decision_at=None, contexts=()):
    rows=eligible_rows(rows,through,decision_at)
    result={'status':'INSUFFICIENT_EVIDENCE','decisionAllowed':False,
        'adjustedProjection':None,'adjustmentStatus':'NOT_VALIDATED_ALERT_ONLY',
        'participationProbability':None,'cause':'UNKNOWN','causeEvidence':[],
        'signals':[],'priorWeeks':[],'recentWeeks':[],'previous':None,'recent':None,
        'quality':'INSUFFICIENT','version':ROLE_VERSION}
    if not rows or rows[-1]['week']!=through:
        result['status']='NO_CURRENT_OBSERVATION';return result
    latest=rows[-1]
    result['team']=latest.get('team')
    if latest.get('gameStatus')=='BYE':
        return {**result,'status':'BYE','quality':'VERIFIED_BYE','signals':['Explicit schedule bye; not a zero-snap game']}
    if latest.get('gameStatus')=='INACTIVE':
        return {**result,'status':'INACTIVE','quality':'VERIFIED_INACTIVE','signals':['Explicit inactive; not evidence of tactical loss']}
    if not verified_snap(latest):
        result['signals']=['No explicit snap observation for latest completed week'];return result
    if latest['snaps']==0 and latest.get('gameStatus')!='PLAYED':
        result['signals']=['Zero snap row without independent participation evidence; inactive/coverage ambiguity'];return result
    observed=[r for r in rows if comparable_snap(r)]
    if len(observed)<4:
        result['signals']=['Fewer than 3 prior comparable snap observations'];return result
    old=observed[-4:-1]
    if any(r.get('team')!=latest.get('team') for r in old):
        return {**result,'status':'TEAM_CHANGE','signals':['Team differs across comparison window; hierarchy reset required']}
    baseline=median(r['snapShare'] for r in old);change=latest['snapShare']-baseline
    p=policy.get('positions',{}).get(position,{})
    if p.get('status')!='CALIBRATED_ALERT_THRESHOLD':
        result['signals']=['No position-specific threshold calibrated'];return result
    previous_two=observed[-4:-2];recent_two=observed[-2:]
    result.update(quality='OBSERVED_SNAPS',priorWeeks=[r['week'] for r in old],recentWeeks=[r['week'] for r in recent_two],
        previous={'snapShareMedian3':baseline,'snapShareMean2':mean(r['snapShare'] for r in previous_two)},
        recent={'snapShareLatest':latest['snapShare'],'snapShareMean2':mean(r['snapShare'] for r in recent_two),
                'snapsLatest':latest['snaps']},delta=change,
        thresholds={'drop':p['drop'],'gain':p['gain']},team=latest.get('team'))
    for key in ('carries','targets','targetShare','redzoneCarries','redzoneTargets','routes','targetsPerRoute','routeParticipation'):
        past=[r[key] for r in old if numeric(r.get(key))]
        result['previous'][key]=mean(past) if len(past)==len(old) else None
        result['recent'][key]=latest.get(key)
    evidence=contexts_before(contexts,latest,position,decision_at)
    result['causeEvidence']=[{'kind':c['kind'],'sourceUrl':c['sourceUrl'],'publishedAt':c['publishedAt'],
        'modifiedAt':c.get('modifiedAt'),'eventWeek':c['eventWeek'],'season':c['season'],'fact':c.get('fact')} for c in evidence]
    injury=any(c['kind']=='PLAYER_EXIT_INJURY' and c.get('playerId')==latest.get('playerId') for c in evidence)
    returned=any(c['kind']=='TEAMMATES_RETURNED' for c in evidence)
    absent=any(c['kind']=='TEAMMATES_ABSENT' for c in evidence)
    qb_change=any(c['kind']=='QB_STARTER_CHANGE' for c in evidence)
    # An observed offensive zero is a descriptive event, not a causal conclusion.
    zero=latest['snaps']==0 and latest.get('gameStatus')=='PLAYED'
    drop=change < -p['drop'] or (zero and baseline>0)
    if drop:
        result['status']='INJURY_CONFOUNDED_DROP' if injury else 'ABRUPT_PARTICIPATION_LOSS'
        result['signals'].append(f"Observed snap-share change {change:.4f}; empirical drop boundary {-p['drop']:.4f}")
        if zero:result['signals'].append('Explicit zero offensive snaps with separate positive participation evidence')
        if injury:result['cause']='VERIFIED_IN_GAME_INJURY'
        elif returned:result['cause']='VERIFIED_TEAMMATE_RETURNS; causal size UNKNOWN'
    else:
        # Two consecutive high observations protect against a one-game volume spike.
        earlier=observed[-4:-2]
        reference=mean(r['snapShare'] for r in earlier)
        gains=[r['snapShare']-reference for r in recent_two]
        if min(gains)>p['gain']:
            result['status']='TEMPORARY_VOLUME_RISK' if absent else 'SUSTAINED_UTILIZATION_INCREASE'
            result['signals'].append('Both recent snap shares exceed prior two-game mean by empirical gain threshold')
            if absent:result['cause']='VERIFIED_TEAMMATE_ABSENCE; durability UNKNOWN'
        elif qb_change:
            result['status']='POSSIBLE_HIERARCHY_CHANGE';result['cause']='VERIFIED_QB_STARTER_CHANGE'
        else:
            result['status']='NO_ABRUPT_SNAP_SIGNAL'
            if position in ('WR','TE') and all(numeric(r.get('routes')) for r in observed[-4:]):
                oldroutes=mean(r['routes'] for r in earlier);newroutes=mean(r['routes'] for r in recent_two)
                oldtargets=[r.get('targets') for r in earlier];newtargets=[r.get('targets') for r in recent_two]
                if oldroutes>0 and newroutes>=oldroutes and all(numeric(x) for x in oldtargets+newtargets) and mean(newtargets)<mean(oldtargets):
                    result['status']='TARGET_VARIATION_WITH_ROUTES_RETAINED'
                    result['signals'].append('Targets fell while observed routes were retained; no snap-role collapse inferred')
    result['decisionAllowed']=result['status'] not in REVIEW_STATUSES
    if not result['decisionAllowed']:
        result['action']='REVIEW_ROLE_BEFORE_USING_HISTORICAL_PROJECTION'
    else:result['action']='NO_ROLE_VETO; verify health, schedule and locks separately'
    return result

def annotate_forecasts(forecast, histories, policy, contexts=(), decision_at=None):
    index={h['sleeperId']:h for h in histories if h['season']==forecast['season']}
    output={}
    for sid,p in forecast['bySleeper'].items():
        h=index.get(sid,{'rows':[]})
        role=detect(h['rows'],p['position'],forecast['asOfWeek'],policy,
                    decision_at=decision_at,contexts=contexts)
        output[sid]={'name':p['name'],'position':p['position'],'team':role.get('team'),
            'originalProjection':p['projection'],'adjustedProjection':None,
            'decisionProjection':p['projection'] if role['decisionAllowed'] else None,
            'roleEvaluation':role}
    # Descriptive competition evidence, never an invented cause.
    for sid,p in output.items():
        peers=[]
        competition=[]
        for h in index.values():
            if h['position']!=p['position']:continue
            latest=next((r for r in h['rows'] if r['week']==forecast['asOfWeek']),None)
            if latest and latest.get('team')==p['team'] and verified_snap(latest):
                competition.append({'playerId':h['sleeperId'],'name':h['name'],
                    'snaps':latest['snaps'],'snapShare':latest['snapShare']})
        for other,q in output.items():
            qr=q['roleEvaluation']
            if (other!=sid and p['team'] and p['team']==q['team'] and p['position']==q['position'] and
                numeric(qr.get('delta')) and qr['delta']>qr.get('thresholds',{}).get('gain',1)):
                peers.append({'playerId':other,'name':q['name'],'snapShareDelta':qr['delta']})
        p['roleEvaluation']['samePositionPeerGains']=peers
        p['roleEvaluation']['teamCompetitionLatest']=competition
        if (p['roleEvaluation']['status']=='ABRUPT_PARTICIPATION_LOSS' and
            any(q['playerId']!=sid and q['snaps']>0 for q in competition)):
            p['roleEvaluation']['hierarchyAssessment']='POSSIBLE_HIERARCHY_CHANGE; not a verified causal label'
    return {'schemaVersion':81,'module':'ROLE_CHANGE_DETECTION','season':forecast['season'],
        'asOfWeek':forecast['asOfWeek'],'targetWeek':forecast['targetWeek'],
        'generatedAt':datetime.now(timezone.utc).isoformat(),'decisionAt':decision_at,
        'forecastVintage':forecast.get('predictionVintage'),'forecastGeneratedAt':forecast['generatedAt'],
        'bySleeper':output,'policy':policy,'adjustmentPromoted':False,
        'limitations':['No point adjustment or availability probability promoted.',
            'Tail utilization signals are not validated causes or depth-chart labels.',
            'Historical snapshot publication times are unknown; event-week chronological audit only.']}
