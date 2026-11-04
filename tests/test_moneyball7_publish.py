"""Moneyball 7 publish integration tests against synthetic NFL-only fixtures."""
import gzip
import json
from pathlib import Path

import pytest

from moneyball7_publish import build


def fixture(weeks=8):
    rows = [{"week": i, "targets": i, "carries": i,
             "snapShare": round(i / 10, 4), "routes": None}
            for i in range(1, weeks + 1)]
    return {
        "schemaVersion": 5, "season": 2026,
        "generatedAt": "2026-11-04T12:00:00+00:00",
        "fromWeek": 1, "thruWeek": weeks, "mappedPlayers": 1,
        "bySleeper": {"12345": rows},
        "coverage": {"boxWeeks": list(range(1, weeks + 1)),
                     "snapWeeks": list(range(1, weeks + 1)),
                     "pbpWeeks": list(range(1, weeks + 1)),
                     "routePlayerWeeks": 0},
        "injuriesBySleeper": {}, "sources": {}, "attribution": {},
    }


def test_end_to_end_gzip_no_leak_and_missingness(tmp_path: Path):
    original = fixture()
    infile = tmp_path / "v5.json.gz"
    outfile = tmp_path / "v7.json.gz"
    with gzip.open(infile, "wt", encoding="utf-8") as fh:
        json.dump(original, fh)
    summary = build(infile, outfile, as_of_week=7)
    assert summary["players"] == 1
    assert summary["week"] == 7
    with gzip.open(outfile, "rt", encoding="utf-8") as fh:
        published = json.load(fh)
    assert published["sourceSchemaVersion"] == 5
    assert published["bySleeper"]["12345"]["recentWeeks"] == [6, 7]
    assert published["bySleeper"]["12345"]["metrics"]["routes"]["delta"] is None
    assert published["sourceQuality"]["status"] in ("PASS", "PASS_WITH_WARNINGS")


def test_invalid_source_does_not_replace_last_good_file(tmp_path: Path):
    infile = tmp_path / "invalid.json"
    outfile = tmp_path / "v7.json.gz"
    outfile.write_bytes(b"preserve")
    invalid = fixture()
    invalid["bySleeper"]["12345"].append({"week": 8, "targets": -3})
    infile.write_text(json.dumps(invalid))
    with pytest.raises((ValueError, TypeError)):
        build(infile, outfile)
    assert outfile.read_bytes() == b"preserve"


def test_no_missing_input_file_creates_output(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        build(tmp_path / "no.json.gz", tmp_path / "output.gz")
    assert not (tmp_path / "output.gz").exists()
