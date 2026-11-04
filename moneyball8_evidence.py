"""Source/event freshness and explicit gates, separate from point forecasting."""
from datetime import datetime, timezone
from urllib.parse import urlsplit

PRACTICE = {"DNP", "LIMITED", "FULL", "NOT_REPORTED"}
GAME_STATUS = {"QUESTIONABLE", "DOUBTFUL", "OUT", "INACTIVE", "NOT_LISTED", "UNKNOWN"}


def timestamp(raw):
    if not isinstance(raw, str) or "T" not in raw:
        raise ValueError("Explicit event timestamp required")
    t = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise ValueError("Timezone required")
    return t.astimezone(timezone.utc)


def assess_evidence(record, now, official_hosts=(), max_age_hours=72):
    """Preserve event/published/fetched timestamps; URL does not prove content.

    Official-source qualification additionally requires content_verified=True
    from a separately audited ingestion adapter and an exact allowlisted host.
    Even a verified FULL practice does not prove unrestricted game snaps.
    """
    if now.tzinfo is None or max_age_hours <= 0:
        raise ValueError("Aware now and positive freshness threshold required")
    try:
        event, published, fetched = (timestamp(record.get(k)) for k in ("event_at", "published_at", "fetched_at"))
    except (ValueError, TypeError):
        return {"status": "UNVERIFIED_DATES", "usable_current": False, "official": False}
    if event > published or published > fetched or fetched > now:
        return {"status": "INVALID_TIME_ORDER", "usable_current": False, "official": False}
    if record.get("practice", "NOT_REPORTED") not in PRACTICE or record.get("game_status", "UNKNOWN") not in GAME_STATUS:
        return {"status": "INVALID_STATUS", "usable_current": False, "official": False}
    source = record.get("source_url", "")
    parsed = urlsplit(source)
    valid_url = parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username and not parsed.password
    official = valid_url and parsed.hostname in official_hosts and record.get("content_verified") is True
    age = (now - event).total_seconds() / 3600
    usable = bool(official and age <= max_age_hours)
    return {"status": "VERIFIED_CURRENT_SOURCE" if usable else "STALE_EVENT" if age > max_age_hours else "SOURCE_NOT_VERIFIED",
            "usable_current": usable, "official": bool(official), "event_age_hours": round(age, 3),
            "event_at": event.isoformat(), "published_at": published.isoformat(), "fetched_at": fetched.isoformat(),
            "practice": record.get("practice", "NOT_REPORTED"), "game_status": record.get("game_status", "UNKNOWN"),
            "snap_restriction": record.get("snap_restriction"),
            "participation_probability": None, "source_url": source}


def championship_readiness(evidence):
    """Never manufacture odds; each input gate requires external audit evidence."""
    required = ("scoring_verified", "all_rosters_verified", "schedule_verified", "tiebreakers_verified",
                "bracket_verified", "availability_model_validated", "joint_score_calibration_validated",
                "out_of_sample_validation", "sensitivity_validated")
    missing = [k for k in required if evidence.get(k) is not True]
    return {"status": "INSUFFICIENT_DATA" if missing else "READY_FOR_SIMULATION",
            "missing": missing, "championship_probability": None,
            "note": "Gate checks attestations only; this module does not simulate or certify calibration."}
