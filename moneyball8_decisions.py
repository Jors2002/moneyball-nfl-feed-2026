"""Exact legal-lineup and marginal roster scenarios; never executes Sleeper moves.

All projections must already use the same league scoring and target week.
``available=True`` is a caller assertion, NOT a medical clearance. Unknown
availability/projection makes the result incomplete rather than a numeric zero.
Private roster IDs are inputs only: this module does not persist or publish them.
"""
from __future__ import annotations

import math

SLOTS = ("QB", "RB1", "RB2", "WR1", "WR2", "TE", "WRRB_FLEX", "K", "DEF")
ELIGIBLE = ({"QB"}, {"RB"}, {"RB"}, {"WR"}, {"WR"}, {"TE"}, {"RB", "WR"}, {"K"}, {"DEF"})


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _ids(values, name):
    values = [str(v) for v in values]
    if len(values) != len(set(values)) or any(not v for v in values):
        raise ValueError(f"Duplicate/empty ID in {name}")
    return values


def _optimize(players, locked_slots=None, slots=SLOTS, eligible_positions=ELIGIBLE):
    """Maximize expected points in nine legal slots via exact bitmask DP.

    Player schema: id, positions (list), projection, available (bool), bye
    (bool, default False), reserve (bool, default False). DEF also accepts DST.
    locked_slots maps exact slot names to player IDs and cannot be reassigned.
    Deterministic ties use sorted player IDs. Missing candidates are reported
    even if the remaining known candidates fill every slot. In that case total
    is None; known_candidate_total is inspection-only, conditional on excluding
    unknown candidates, and must not be consumed as the global optimum.
    """
    SLOTS, ELIGIBLE = slots, eligible_positions
    locked_slots = {k: str(v) for k, v in (locked_slots or {}).items()}
    if set(locked_slots) - set(SLOTS):
        raise ValueError("Unknown locked slot")
    _ids(locked_slots.values(), "locked slots")
    records, missing, excluded = {}, [], []
    for raw in players:
        p = dict(raw)
        sid = str(p.get("id", ""))
        if not sid or sid in records:
            raise ValueError("Duplicate/empty player ID")
        pos = p.get("positions")
        if not isinstance(pos, (list, tuple, set)) or not pos:
            raise ValueError(f"Invalid positions for {sid}")
        p["positions"] = {"DEF" if q == "DST" else q for q in pos}
        for flag in ("bye", "reserve"):
            if flag in p and not isinstance(p[flag], bool):
                raise ValueError(f"{flag} requires a boolean")
        if p.get("available") is not None and type(p.get("available")) is not bool:
            raise ValueError("available requires bool or None")
        records[sid] = p
    for sid, p in records.items():
        if p.get("bye") or p.get("reserve") or p.get("available") is False:
            excluded.append(sid)
        elif p.get('roleDecisionAllowed') is False:
            missing.append({'id':sid,'reason':'ROLE_REVIEW_REQUIRED'})
        elif p.get("available") is not True or not _number(p.get("projection")):
            missing.append({"id": sid, "reason": "AVAILABILITY_UNKNOWN" if p.get("available") is not True else "PROJECTION_MISSING"})
    usable = {sid: p for sid, p in records.items() if sid not in excluded and not any(x["id"] == sid for x in missing)}
    initial_mask, initial_score, initial_assignment = 0, 0.0, {}
    for slot, sid in locked_slots.items():
        if sid not in records:
            raise ValueError("Locked player absent from roster")
        i = SLOTS.index(slot)
        if not records[sid]["positions"] & ELIGIBLE[i]:
            raise ValueError("Illegal locked position")
        if sid not in usable:
            return {"status": "INSUFFICIENT_DATA", "assignment": {}, "total": None,
                    "missing": missing + [{"id": sid, "reason": "LOCKED_PLAYER_UNUSABLE"}],
                    "missing_slots": list(SLOTS), "excluded": excluded}
        initial_mask |= 1 << i
        initial_score += usable[sid]["projection"]
        initial_assignment[slot] = sid
    dp = {initial_mask: (initial_score, initial_assignment)}
    for sid in sorted(usable):
        if sid in locked_slots.values():
            continue
        p = usable[sid]
        # Snapshot is essential: one player can fill at most one slot.
        for mask, (score, assignment) in list(dp.items()):
            for i, eligible in enumerate(ELIGIBLE):
                if mask & (1 << i) or not p["positions"] & eligible:
                    continue
                next_mask, next_score = mask | (1 << i), score + p["projection"]
                if next_mask not in dp or next_score > dp[next_mask][0]:
                    dp[next_mask] = (next_score, {**assignment, SLOTS[i]: sid})
    complete = (1 << len(SLOTS)) - 1
    best_mask = complete if complete in dp else max(dp, key=lambda m: (m.bit_count(), dp[m][0]))
    score, assignment = dp[best_mask]
    return {"status": "OK" if best_mask == complete and not missing else "INSUFFICIENT_DATA",
            "assignment": assignment, "total": round(score, 6) if best_mask == complete and not missing else None,
            "known_candidate_total": round(score, 6) if best_mask == complete else None,
            "missing": missing, "missing_slots": [s for s in SLOTS if s not in assignment],
            "excluded": excluded,
            "interpretation": "Expected-points optimum conditional on supplied scoring, week, availability and locks; no win probability."}


def optimize_lineup(players, locked_slots=None):
    """Optimize all nine legal starting slots, requiring K and DEF projections."""
    result = _optimize(players, locked_slots)
    return {**result, "scope": "NINE_STARTERS", "slots_count": 9}


def optimize_offense_conditional(players, locked_slots=None):
    """Seven offensive slots ONLY; cannot certify a complete fantasy lineup.

    K/DEF scores are explicitly excluded. An offensive-only transaction leaves
    their projected scores unchanged, so their terms cancel in a point delta
    IF their ownership, lineup choices and availability truly remain identical.
    Supplied availability assertions remain assumptions, not medical evidence.
    """
    result = _optimize(players, locked_slots, SLOTS[:7], ELIGIBLE[:7])
    return {**result, "scope": "SEVEN_OFFENSIVE_STARTERS_ONLY", "slots_count": 7,
            "complete_fantasy_lineup_verified": False,
            "excluded_slots": ["K", "DEF"],
            "interpretation": "Conditional seven-slot offensive scenario; K/DEF unscored and full-lineup legality unverified. Availability, health and schedule require separate verification."}


def evaluate_transaction(roster_ids, add_ids, drop_ids, players_by_week, horizons, capacity=14, locked_by_week=None):
    """Compare complete lineups before/after an explicit add/drop across weeks.

    ``players_by_week`` maps int weeks to candidate lists using optimize schema.
    Availability/IR eligibility, actual waiver entitlement and deadlines must be
    verified externally; public roster absence does not prove a legal claim.
    Horizons map labels to explicit week lists; never silently average missing.
    """
    roster, adds, drops = (_ids(v, k) for v, k in ((roster_ids, "roster"), (add_ids, "adds"), (drop_ids, "drops")))
    if set(drops) - set(roster) or set(adds) & set(roster) or set(adds) & set(drops):
        raise ValueError("Invalid add/drop ownership")
    after = [sid for sid in roster if sid not in drops] + adds
    if len(after) > capacity:
        raise ValueError("Roster over capacity: specify an explicit cut")
    results = {}
    weeks = sorted({w for ws in horizons.values() for w in ws})
    if not weeks or any(type(w) is not int or not 1 <= w <= 18 for w in weeks):
        raise ValueError("Explicit valid weeks required")
    for week in weeks:
        rows = players_by_week.get(week, [])
        lookup = {str(p["id"]): p for p in rows}
        if len(lookup) != len(rows):
            raise ValueError("Duplicate player in weekly pool")
        missing_ids = sorted((set(roster) | set(after)) - set(lookup))
        before = optimize_lineup([lookup[sid] for sid in roster if sid in lookup], (locked_by_week or {}).get(week))
        post = optimize_lineup([lookup[sid] for sid in after if sid in lookup], (locked_by_week or {}).get(week))
        valid = not missing_ids and before["status"] == post["status"] == "OK"
        results[week] = {"status": "OK" if valid else "INSUFFICIENT_DATA", "before": before, "after": post,
                         "missing_ids": missing_ids,
                         "delta": round(post["total"] - before["total"], 6) if valid else None}
    aggregate = {}
    for label, ws in horizons.items():
        if not ws or len(ws) != len(set(ws)):
            raise ValueError("Empty/duplicate horizon weeks")
        good = all(results[w]["delta"] is not None for w in ws)
        aggregate[label] = {"weeks": list(ws), "status": "OK" if good else "INSUFFICIENT_DATA",
                            "total_delta": round(sum(results[w]["delta"] for w in ws), 6) if good else None,
                            "mean_delta": round(sum(results[w]["delta"] for w in ws) / len(ws), 6) if good else None}
    return {"status": "OK" if all(r["status"] == "OK" for r in results.values()) else "INSUFFICIENT_DATA",
            "weeks": results, "horizons": aggregate,
            "transaction_verified": False, "championship_probability_delta": None,
            "limitations": ["No waiver entitlement, transaction deadline or IR eligibility verified.",
                            "Missing projections/availability prevent marginal-value claims.",
                            "Expected-points changes are not championship probability changes."]}


def evaluate_trade(roster_a, roster_b, give_a, give_b, players_by_week, horizons, cuts_a=(), cuts_b=(), capacity=14):
    """Bilateral marginal lineups with verified ownership in supplied snapshot."""
    a, b, ga, gb, ca, cb = (_ids(v, name) for v, name in ((roster_a, "A"), (roster_b, "B"), (give_a, "give A"), (give_b, "give B"), (cuts_a, "cuts A"), (cuts_b, "cuts B")))
    if set(a) & set(b) or set(ga) - set(a) or set(gb) - set(b) or set(ga) & set(ca) or set(gb) & set(cb):
        raise ValueError("Trade ownership conflict")
    if not ga or not gb:
        raise ValueError("Both trade sides must be explicit")
    ours = evaluate_transaction(a, gb, ga + ca, players_by_week, horizons, capacity)
    theirs = evaluate_transaction(b, ga, gb + cb, players_by_week, horizons, capacity)
    return {"status": "OK" if ours["status"] == theirs["status"] == "OK" else "INSUFFICIENT_DATA",
            "a": ours, "b": theirs, "executed": False,
            "recommendation": "SCENARIO_ONLY" if ours["status"] == theirs["status"] == "OK" else "DATOS_INSUFICIENTES",
            "championship_probability_delta": None}
