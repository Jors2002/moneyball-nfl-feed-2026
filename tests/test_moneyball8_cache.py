import io
import json
from urllib.error import HTTPError
import pytest
from moneyball8_cache import fetch

URL = 'https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_2024.csv'

class Response(io.BytesIO):
    headers = {'ETag': 'v1'}

def test_cache_checks_hash_and_source_without_redownload(tmp_path):
    path = tmp_path/'stats.csv'
    first = fetch(URL, path, opener=lambda *a,**k: Response(b'player,week\na,1\n'))
    assert first['event_timestamp'] is None
    def offline(*a,**k):
        raise AssertionError('Should not download immutable data twice')
    assert fetch(URL,path,immutable=True,opener=offline)['cache_status']=='VERIFIED_IMMUTABLE_HIT'
    path.write_text('corrupt')
    with pytest.raises(AssertionError): fetch(URL,path,immutable=True,opener=offline)

def test_http304_and_invalid_response_preserve_last_good(tmp_path):
    path=tmp_path/'stats.csv'
    fetch(URL,path,opener=lambda *a,**k: Response(b'player,week\na,1\n'))
    def not_modified(*a,**k): raise HTTPError(URL,304,'Not modified',{},None)
    assert fetch(URL,path,opener=not_modified)['cache_status']=='HTTP_NOT_MODIFIED'
    old=path.read_bytes()
    with pytest.raises(ValueError): fetch(URL,path,opener=lambda *a,**k:Response(b'<html>bad</html>'))
    assert path.read_bytes()==old

def test_reject_private_or_unapproved_endpoints(tmp_path):
    with pytest.raises(ValueError):fetch('https://example.com/private',tmp_path/'a')

def test_corrupt_provenance_refreshes_instead_of_trusting_old_bytes(tmp_path):
    path=tmp_path/'stats.csv'
    path.write_text('corrupt')
    (tmp_path/'stats.csv.provenance.json').write_text('{partial')
    result=fetch(URL,path,immutable=True,opener=lambda *a,**k:Response(b'player,week\nb,2\n'))
    assert result['cache_status']=='DOWNLOADED'
    assert path.read_text()=='player,week\nb,2\n'
