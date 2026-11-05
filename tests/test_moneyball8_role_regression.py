from pathlib import Path
import hashlib
import gzip
import json
import random
from moneyball8_roles import detect
from moneyball8_role_validate import paired_interval
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]

def test_original_week9_vintages_remain_byte_identical():
    expected={'moneyball8_2026_w09_28bcadbec736.json.gz':'b0eb6c85de9a0701d4581dcdeb4487d9b72a8015c1c556c080cb9ae654f9a8e2',
              'moneyball8_2026_w09_5510980e6eac.json.gz':'03cf3ac58d1941424d109732bdd1bdcdd18fbe78dab128d5c196335573a72064'}
    for name,sha in expected.items():assert hashlib.sha256((ROOT/'data/history'/name).read_bytes()).hexdigest()==sha
    with gzip.open(ROOT/'data/history/moneyball8_2026_w09_5510980e6eac.json.gz','rt') as f:original=json.load(f)
    assert original['bySleeper']['11435']['projection']==15.327

def test_stable_role_control_no_systematic_alert_under_bounded_noise():
    policy=json.loads((ROOT/'data/role_policy_v81.json').read_text())
    rng=random.Random(81);n=0
    for pos in ('RB','WR','TE','QB'):
        for _ in range(100):
            base=rng.uniform(.2,.8)
            rows=[{'week':i+1,'season':2026,'team':'T','snapObserved':True,'snaps':40,
                'snapShare':base+rng.uniform(-.02,.02),'gameStatus':'PLAYED'} for i in range(4)]
            assert detect(rows,pos,4,policy)['status']=='NO_ABRUPT_SNAP_SIGNAL';n+=1
    assert n==400

def test_paired_week_bootstrap_reports_known_worse_model():
    rows=pd.DataFrame([{'week':w,'actual':10.,'original':10.,'candidate':12.} for w in range(1,12)])
    result=paired_interval(rows)
    assert result['difference']==2 and result['lower95']==result['upper95']==2
