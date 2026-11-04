import copy
import gzip
import json
from pathlib import Path
import pytest
from moneyball6_validate import audit

@pytest.fixture
def real_feed():
    with gzip.open(Path(__file__).resolve().parents[1]/'data/_MONEYBALL_FEED_2026.json.gz','rt') as f:
        return json.load(f)

@pytest.mark.parametrize('field,bad',[('ppr',float('nan')),('ppr',float('inf')),
    ('teamDropbacks',-999),('targetsPerRoute',999),('teamSnaps',True),('aDOT',float('inf'))])
def test_invalid_observation_cannot_pass_real_feed_audit(real_feed,field,bad):
    feed=copy.deepcopy(real_feed)
    next(iter(feed['bySleeper'].values()))[0][field]=bad
    assert audit(feed,max_age_hours=10000)['status']=='FAIL'

def test_negative_fantasy_scores_and_air_yards_are_legal(real_feed):
    row=next(iter(real_feed['bySleeper'].values()))[0]
    row['ppr']=-2.0
    row['receivingAirYards']=-4.0
    assert audit(real_feed,max_age_hours=10000)['status']!='FAIL'
