from datetime import datetime,timezone
import copy
import pytest
from moneyball8_pipeline import validate_prediction

def fixture():
    return {'schemaVersion':80,'season':2026,'asOfWeek':8,'targetWeek':9,
        'generatedAt':datetime.now(timezone.utc).isoformat(),
        'sourceGeneratedAt':datetime.now(timezone.utc).isoformat(),
        'bySleeper':{str(i):{'position':'RB','projection':10,'interval80':{'lower':-2,'upper':22}} for i in range(100)}}

def test_realistic_prediction_gate(): assert validate_prediction(fixture(),2026,8)==100

@pytest.mark.parametrize('value',[None,float('nan'),float('inf'),True])
def test_nonfinite_fails_closed(value):
    f=fixture(); f['bySleeper']['1']['projection']=value
    with pytest.raises(ValueError):validate_prediction(f,2026,8)

def test_wrong_target_and_interval_fail():
    f=fixture();f['targetWeek']=10
    with pytest.raises(ValueError):validate_prediction(f,2026,8)
    f=fixture();f['bySleeper']['1']['interval80']['upper']=1
    with pytest.raises(ValueError):validate_prediction(f,2026,8)
