#!/usr/bin/env python3
"""Moneyball 8.2: fail-closed review of PRIVATE decisions, without publishing them.

Input only; no Sleeper action, Drive write, public roster, odds or projections.
The caller must provide a dated roster/scoring snapshot and manually authorized
evidence. 'APROBADA' is a review gate, NEVER confirmation of an executed move.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

START = "BEGIN_MONEYBALL_DECISIONS_JSON"
END = "END_MONEYBALL_DECISIONS_JSON"
REQUIRED = (
    "roster", "scoring", "health", "role", "replacement", "lineup",
    "all_drops", "do_nothing", "playoffs", "deadline",
)
HORIZONS = ("week", "next_3_5", "playoffs_15_17")


class IntegrityError(ValueError):
    pass


def read_registry(text):
    if text.count(START) != 1 or text.count(END) != 1:
        raise IntegrityError("Missing or duplicated private registry markers")
    try:
        return validate_registry(json.loads(text.split(START, 1)[1].split(END, 1)[0]))
    except json.JSONDecodeError as exc:
        raise IntegrityError("Invalid private JSON") from exc


def validate_registry(reg):
    if not isinstance(reg, dict) or reg.get("schema_version") != 1:
        raise IntegrityError("Unsupported registry schema")
    if not isinstance(reg.get("league_id"), str) or not reg["league_id"]:
        raise IntegrityError("Missing league ID")
    if not isinstance(reg.get("decisions"), list) or not isinstance(reg.get("facts"), list):
        raise IntegrityError("Missing decisions or facts")
    for key in ("decisions", "facts"):
        rows = reg[key]
        if any(not isinstance(row, dict) or not isinstance(row.get("id"), str) or
               not row["id"] for row in rows):
            raise IntegrityError("Invalid entry in " + key)
        ids = [row["id"] for row in rows]
        if len(set(ids)) != len(ids):
            raise IntegrityError("Duplicate ID in " + key)
    fact_ids = {row["id"] for row in reg["facts"]}
    for row in reg["decisions"]:
        if not all(isinstance(row.get(k), str) and row[k].strip()
                   for k in ("status", "why", "source", "decided_at")):
            raise IntegrityError("Decision without status, reason, source or date")
        if not set(row.get("linked_fact_ids", [])) <= fact_ids:
            raise IntegrityError("Decision references unknown fact")
    return reg


def _set(values, label):
    if not isinstance(values, list) or any(not isinstance(v, str) or not v for v in values):
        raise IntegrityError("Invalid " + label)
    if len(values) != len(set(values)):
        raise IntegrityError("Duplicate " + label)
    return set(values)


def _dated(value):
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo is not None else None
    except (ValueError, AttributeError):
        return None


def review(reg, proposal, *, now=None, max_age_hours=72):
    """No implicit consent. Fail closed on missing data, protected cuts and old snapshots."""
    validate_registry(reg)
    if not isinstance(proposal, dict):
        raise IntegrityError("Invalid proposal")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise IntegrityError("Timezone-aware now required")
    if proposal.get("league_id") != reg["league_id"]:
        return dict(state="DESCARTADA", reasons=["WRONG_LEAGUE"], conflicts=[],
                    missing=[], executed=False)
    if proposal.get("kind") not in ("WAIVER", "DROP", "TRADE", "LINEUP", "NO_MOVE"):
        raise IntegrityError("Unsupported action")
    drops = _set(proposal.get("drops", []), "drops")
    gives = _set(proposal.get("gives", []), "gives")
    receives = _set(proposal.get("receives", []), "receives")
    if (drops & gives) or (gives & receives) or (drops & receives):
        raise IntegrityError("Conflicting player movements")
    missing = []
    checks = proposal.get("checks", {})
    if not isinstance(checks, dict):
        checks = {}
    for check in REQUIRED:
        if not isinstance(checks, dict) or checks.get(check) is not True:
            missing.append("CHECK_" + check.upper())
    # Exact league points must use reconciled scoring; generic PPR is insufficient.
    if proposal.get("scoring_source") != "SLEEPER_BRR":
        missing.append("LEAGUE_SCORING_SOURCE")
    timestamp = _dated(proposal.get("snapshot_at"))
    if timestamp is None or timestamp > now or now - timestamp > timedelta(hours=max_age_hours):
        missing.append("SNAPSHOT_STALE_OR_UNKNOWN")
    horizons = proposal.get("horizons", {})
    if not isinstance(horizons, dict):
        horizons = {}
    for k in HORIZONS:
        if not isinstance(horizons.get(k), dict) or horizons[k].get("reviewed") is not True:
            missing.append("HORIZON_" + k.upper())
    if proposal.get("kind") == "TRADE":
        for check in ("opponent_lineup", "acceptance", "two_market_sources", "rival_risk"):
            if checks.get(check) is not True:
                missing.append("CHECK_" + check.upper())
    conflicts = []
    for row in reg["decisions"]:
        if row["status"] not in ("ACTIVA", "PENDIENTE"):
            continue
        asset = row.get("asset")
        if row.get("protected") is True and asset in drops | gives:
            conflicts.append(dict(id=row["id"], reason="PROTECTED_ASSET",
                                  asset=asset, reversal=row.get("reversal", "NOT_RECORDED")))
        if row.get("kind") == "LINEUP_GAP" and proposal.get("kind") in ("WAIVER", "DROP", "TRADE"):
            # Warning only: gaps do not veto a movement, but must be reviewed.
            if checks.get("bye_gaps_reviewed") is not True:
                missing.append("EXISTING_BYE_GAPS")
    override = proposal.get("reversal")
    allowed_override = (isinstance(override, dict) and
        all(isinstance(override.get(k), str) and override[k].strip()
            for k in ("before", "new_evidence", "change", "cost", "source")) and
        override.get("user_authorized") is True)
    if conflicts and not allowed_override:
        missing.append("PROTECTED_ASSET_REQUIRES_REVERSAL")
    # Approval needs an explicit user's permission AND all gates; no external mutation.
    if proposal.get("user_authorized") is not True:
        missing.append("USER_AUTHORIZATION")
    missing = sorted(set(missing))
    state = "CONDICIONADA" if missing else "APROBADA"
    return dict(state=state, reasons=missing, missing=missing,
                conflicts=conflicts, executed=False, league_id=reg["league_id"],
                interpretation="Review-only; verify actual Sleeper state before acting")


def reconcile_points(raw_without_fumbles, fumbles_lost, loss_penalty):
    """Reconcile an explicitly supplied pre-fumble score with league penalty."""
    if isinstance(raw_without_fumbles, bool) or not isinstance(raw_without_fumbles, (int, float)):
        raise IntegrityError("Score must be numeric")
    if type(fumbles_lost) is not int or fumbles_lost < 0:
        raise IntegrityError("Invalid fumble count")
    if isinstance(loss_penalty, bool) or not isinstance(loss_penalty, (int, float)):
        raise IntegrityError("Penalty must be numeric")
    return round(raw_without_fumbles + fumbles_lost * loss_penalty, 3)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry-text", type=Path, required=True,
                        help="Private exported Google Doc text, NEVER committed")
    parser.add_argument("--proposal", type=Path, required=True,
                        help="Private local proposal JSON, NEVER committed")
    args = parser.parse_args()
    reg = read_registry(args.registry_text.read_text(encoding="utf-8-sig"))
    prop = json.loads(args.proposal.read_text(encoding="utf-8"))
    result = review(reg, prop)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["state"] == "APROBADA" else 2)


if __name__ == "__main__":
    main()
