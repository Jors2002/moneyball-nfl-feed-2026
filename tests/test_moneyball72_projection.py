from datetime import datetime, timezone
import copy
import json
import gzip
from pathlib import Path
import pytest
from moneyball72_projection import build, observed_games, baseline, walk_forward, injury_evidence

def fixture():
    return {
        "schemaVersion": 5, "season": 2026, "thruWeek": 8,
        "generatedAt": "2026-11-04T10:00:00+00:00",
        "bySleeper": {
            "101": [{"week": w, "ppr": float(w)} for w in range(1, 9)],
            "102": [{"week": 1, "ppr": None}, {"week": 2, "ppr": 4.0}],
        },
        "injuriesBySleeper": {
            "101": [{"week": 8, "dateModified": "2026-11-03T12:00:00+00:00",
                      "practiceStatus": "Limited", "reportStatus": "Questionable"}],
            "102": [{"week": 9, "dateModified": "2026-11-04",
                      "practiceStatus": "Full", "reportStatus": ""}]
        }
    }

def test_forward_cutoff_and_mean():
    f=build(fixture(), 7)
    p=f["bySleeper"]["101"]
    assert p["weeks"] == [4,5,6,7]
    assert p["mean"] == 5.5
    assert p["games"] == 4
    assert f["asOfWeek"] == 7
    assert all(x<=7 for x in p["weeks"])
    # Week 8 changes data, but must not influence week-7 baseline.
    g=fixture();g["bySleeper"]["101"][-1]["ppr"]=100000.
    assert build(g,7)["bySleeper"]["101"]["mean"] == 5.5

def test_null_or_no_games_is_not_zero():
    b=build(fixture())
    assert b["bySleeper"]["102"]["mean"] is None
    assert b["bySleeper"]["102"]["quality"] == "INSUFFICIENT_DATA"

def test_duplicate_weeks_invalid():
    with pytest.raises(ValueError, match="Duplicate"):
        observed_games([{"week":1,"ppr":2},{"week":1,"ppr":4}],5)

def test_walking_is_strictly_past():
    f=fixture()
    diag=walk_forward(f["bySleeper"],8)
    assert diag["status"]=="EXPLORATORY_WALK_FORWARD"
    assert diag["weeksTested"] == [8]
    assert diag["examples"] == 1
    assert diag["eligibility"] == "historical baseline >= 5 PPR"

def test_injuries_no_false_freshness_and_source_time():
    f=build(fixture(),8)
    assert f["injuryEvidenceBySleeper"]["101"]["evidence"] in ("DATED_BUT_OLD","DATED_SOURCE_RECORD")
    assert f["injuryEvidenceBySleeper"]["102"]["evidence"] == "DATE_ONLY_NOT_EVENT_TIMESTAMP"
    assert f["quality"]["injuries"]["datedRecords"] == 1

def test_future_injury_week_is_ignored():
    f=build(fixture(),7)
    assert "102" not in f["injuryEvidenceBySleeper"]

def test_absent_timezone_not_verified():
    g=fixture();g["injuriesBySleeper"]["101"][0]["dateModified"]="2026-11-03T12:00:00"
    f=build(g)
    assert f["injuryEvidenceBySleeper"]["101"]["sourceTimestamp"] is None
    assert f["injuryEvidenceBySleeper"]["101"]["evidence"]=="TIMEZONE_UNKNOWN"

def test_invalid_schema_does_not_publish(tmp_path):
    inp=tmp_path/"v5.json.gz";out=tmp_path/"new.json.gz"
    out.write_bytes(b"preserve")
    with gzip.open(inp,"wt") as fh:json.dump({"schemaVersion":7},fh)
    import subprocess,sys
    run=subprocess.run([sys.executable,"moneyball72_projection.py",
        "--source-gzip",str(inp),"--output",str(out)],capture_output=True)
    assert run.returncode !=0
    assert out.read_bytes()==b"preserve"

def test_no_mutation():
    f=fixture();before=copy.deepcopy(f)
    build(f)
    assert f==before


def test_zero_point_fringe_players_do_not_hide_real_error():
    rows = [{"week": w, "ppr": 0.0} for w in range(1, 9)]
    out = walk_forward({"111": rows, "112": rows}, 8)
    assert out["examples"] == 0
    assert out["mae"] is None
