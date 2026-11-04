import json
from datetime import datetime, timezone

from moneyball8_official import parse_report

NOW = datetime(2026, 11, 4, 23, tzinfo=timezone.utc)


def page(published="2026-11-04T21:25:49Z", modified="2026-11-04T21:58:16Z", extra="", event=""):
    metadata = {"@type": "NewsArticle", "headline": "Week 9 Injury Report | Jets vs. Chiefs",
                "datePublished": published, "dateModified": modified}
    return ('<script type="application/ld+json">' + json.dumps(metadata) + '</script>'
            '<h2>Kansas City Chiefs</h2><h3 ' + event + '>Wednesday</h3>'
            '<li>WR Rashee Rice - Hamstring / Knee - LP</li>' + extra)


def parse(html, **kwargs):
    return parse_report(html, fetched_at=NOW.isoformat(), now=NOW, **kwargs)


def test_date_only_never_invents_practice_time():
    result = parse(page(), event_date="2026-11-04")
    row = result["records"][0]
    assert row["practice"] == "LIMITED"
    assert row["event_date"] == "2026-11-04"
    assert row["event_at"] is None
    assert not row["assessment"]["usable_current"]
    assert row["assessment"]["official"]


def test_explicit_source_offsets_are_normalized_and_assessed():
    result = parse(page(published="2026-11-04T15:25:49-06:00",
                        event='data-event-at="2026-11-04T14:00:00-06:00"'))
    assert result["published_at"] == "2026-11-04T21:25:49+00:00"
    assert result["records"][0]["assessment"]["usable_current"]


def test_ambiguous_publication_clock_is_rejected():
    result = parse(page(published="2026-11-04T15:25:49"))
    assert "AMBIGUOUS_PUBLISHED_AT" in result["issues"]
    assert not result["records"][0]["assessment"]["usable_current"]


def test_old_explicit_practice_is_stale():
    result = parse(page(event='data-event-at="2026-10-28T14:00:00-06:00"'))
    assert result["records"][0]["assessment"]["status"] == "STALE_EVENT"


def test_future_publication_is_blocked():
    result = parse(page(published="2026-11-05T21:25:49Z", modified="2026-11-05T22:00:00Z"))
    assert "FUTURE_OR_INVALID_PUBLICATION_ORDER" in result["issues"]
    assert not result["records"][0]["assessment"]["usable_current"]


def test_displayed_update_before_publication_blocks_even_valid_jsonld():
    display = '<span>Published: Nov 04, 2026 at 03:25 PM</span><span>Updated: Oct 31, 2026 at 02:18 PM</span>'
    result = parse(page(extra=display))
    assert "DISPLAY_UPDATED_BEFORE_PUBLISHED" in result["issues"]


def test_metadata_modification_before_publication_blocks():
    result = parse(page(modified="2026-10-31T21:58:16Z"))
    assert "INVALID_MODIFICATION_ORDER" in result["issues"]


def test_two_teams_wednesday_are_distinct_but_same_team_duplicate_blocks():
    jets = '<h2>New York Jets</h2><h3>Wednesday</h3><li>RB Breece Hall - Quad - LP</li>'
    result = parse(page(extra=jets))
    assert len(result["records"]) == 2
    assert not result["issues"]
    duplicate = '<h3>Wednesday</h3><li>WR Rashee Rice - Hamstring / Knee - FP</li>'
    result = parse(page(extra=duplicate))
    assert "DUPLICATE_TEAM_DAY_SECTION" in result["issues"]
    assert all(not r["assessment"]["usable_current"] for r in result["records"])
