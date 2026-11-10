"""Synthetic regression cases. No private user/league records in public GitHub."""
import json
import unittest
from datetime import datetime, timezone, timedelta
from moneyball82_integrity import (
    IntegrityError, read_registry, validate_registry, review, reconcile_points,
)

NOW = datetime(2026, 11, 10, 6, tzinfo=timezone.utc)
LEAGUE = "synthetic"

def fixture():
    return {
        "schema_version": 1, "league_id": LEAGUE, "facts": [
            {"id": "SCORED_FUMBLE", "points": 6.9},
            {"id": "DEF_ACQUIRED", "kind": "TRANSACTION"},
        ], "decisions": [
            {"id": "PLAYOFF_D_STASH", "status": "ACTIVA", "asset": "DST_PLAYOFF",
             "protected": True, "why": "Keep for elimination matchups",
             "decided_at": "2026-11-09", "source": "Prior documented decision",
             "linked_fact_ids": ["DEF_ACQUIRED"], "reversal": "Compare playoff value"},
            {"id": "BYE_GAP", "status": "PENDIENTE", "asset": "QB",
             "kind": "LINEUP_GAP", "why": "QB on bye", "decided_at": "2026-11-09",
             "source": "Dated schedule"}
        ],
    }

def proposal(kind="WAIVER"):
    return {
        "league_id": LEAGUE, "kind": kind, "drops": [], "gives": [],
        "receives": ["FREE_RB"], "user_authorized": True,
        "snapshot_at": (NOW - timedelta(hours=2)).isoformat(),
        "scoring_source": "SLEEPER_BRR",
        "horizons": {k: {"reviewed": True} for k in
                     ("week", "next_3_5", "playoffs_15_17")},
        "checks": {**{k: True for k in (
            "roster", "scoring", "health", "role", "replacement", "lineup",
            "all_drops", "do_nothing", "playoffs", "deadline",
            "bye_gaps_reviewed", "opponent_lineup", "acceptance",
            "two_market_sources", "rival_risk"
        )}},
    }


class DecisionIntegrityTests(unittest.TestCase):
    def test_valid_private_export(self):
        blob = "Private notes\nBEGIN_MONEYBALL_DECISIONS_JSON\n" + json.dumps(fixture()) + "\nEND_MONEYBALL_DECISIONS_JSON"
        self.assertEqual(read_registry(blob)["league_id"], LEAGUE)

    def test_duplicate_registry_markers_refused(self):
        blob = "BEGIN_MONEYBALL_DECISIONS_JSON " + json.dumps(fixture()) + " END_MONEYBALL_DECISIONS_JSON"
        with self.assertRaises(IntegrityError):
            read_registry(blob + blob)

    def test_unknown_fact_or_duplicate_decision_refused(self):
        r = fixture()
        r["decisions"][0]["linked_fact_ids"] = ["MISSING"]
        with self.assertRaises(IntegrityError):
            validate_registry(r)
        r = fixture()
        r["decisions"].append(dict(r["decisions"][0]))
        with self.assertRaises(IntegrityError):
            validate_registry(r)

    def test_protected_dst_never_default_cut(self):
        p = proposal()
        p["drops"] = ["DST_PLAYOFF"]
        out = review(fixture(), p, now=NOW)
        self.assertEqual(out["state"], "CONDICIONADA")
        self.assertIn("HISTORICAL_DECISION_NEEDS_NEW_EVIDENCE_AND_COST", out["missing"])
        self.assertEqual(out["conflicts"][0]["id"], "PLAYOFF_D_STASH")

    def test_incomplete_new_evidence_still_conditional(self):
        p = proposal()
        p["drops"] = ["DST_PLAYOFF"]
        p["reversal"] = dict(before="stash", new_evidence="new role", change="drop",
                             source="dated official", user_authorized=False)
        self.assertEqual(review(fixture(), p, now=NOW)["state"], "CONDICIONADA")

    def test_new_evidence_can_reverse_strategy_without_permission_to_recommend(self):
        p = proposal()
        p["drops"] = ["DST_PLAYOFF"]
        p["reversal"] = dict(before="stash", new_evidence="verified replacement",
                             change="drop after audit", cost="playoff DST hedge lost",
                             source="dated official", user_authorized=False)
        o = review(fixture(), p, now=NOW)
        self.assertEqual(o["state"], "APROBADA")
        self.assertFalse(o["executed"])
        self.assertFalse(o["execution_authorized"])
        self.assertTrue(o["recommendation_allowed"])

    def test_recommendations_do_not_require_execution_authorization(self):
        p = proposal()
        p["user_authorized"] = False
        out = review(fixture(), p, now=NOW)
        self.assertEqual(out["state"], "APROBADA")
        self.assertFalse(out["execution_authorized"])

    def test_any_active_asset_strategy_is_reconsidered(self):
        reg = fixture()
        reg["decisions"].append({
            "id": "QB_BACKUP_PLAN", "status": "ACTIVA", "kind": "ROSTER_STRATEGY",
            "asset": "BACKUP_QB", "why": "Injury hedge",
            "source": "prior analysis", "decided_at": "2026-11-09"
        })
        p = proposal()
        p["drops"] = ["BACKUP_QB"]
        self.assertEqual(review(reg, p, now=NOW)["state"], "CONDICIONADA")
        p["reversal"] = dict(before="Keep handcuff", new_evidence="Healthy starter",
                             change="Drop for stronger marginal asset",
                             cost="Loss of insurance", source="dated medical news")
        self.assertEqual(review(reg, p, now=NOW)["state"], "APROBADA")

    def test_missing_horizon_and_scoring_fail_closed(self):
        p = proposal()
        p["scoring_source"] = "GENERIC_PPR"
        del p["horizons"]["playoffs_15_17"]
        o = review(fixture(), p, now=NOW)
        self.assertIn("LEAGUE_SCORING_SOURCE", o["missing"])
        self.assertIn("HORIZON_PLAYOFFS_15_17", o["missing"])

    def test_stale_snapshot_no_zero_filling(self):
        p = proposal()
        p["snapshot_at"] = (NOW - timedelta(days=8)).isoformat()
        self.assertEqual(review(fixture(), p, now=NOW)["state"], "CONDICIONADA")

    def test_trade_requires_counterparty_and_market_checks(self):
        p = proposal("TRADE")
        p["checks"]["two_market_sources"] = False
        self.assertIn("CHECK_TWO_MARKET_SOURCES", review(fixture(), p, now=NOW)["missing"])

    def test_malformed_check_map_is_conditioned(self):
        p = proposal()
        p["checks"] = []
        self.assertEqual(review(fixture(), p, now=NOW)["state"], "CONDICIONADA")

    def test_wrong_league_rejected(self):
        p = proposal()
        p["league_id"] = "another"
        self.assertEqual(review(fixture(), p, now=NOW)["state"], "DESCARTADA")

    def test_fumble_exact_reconciliation(self):
        self.assertEqual(reconcile_points(8.9, 1, -2.0), 6.9)
        self.assertNotEqual(reconcile_points(8.9, 1, -2.0), 8.9)

    def test_missing_fumble_inputs_not_zero(self):
        with self.assertRaises(IntegrityError):
            reconcile_points(8.9, None, -2.0)
        with self.assertRaises(IntegrityError):
            reconcile_points(8.9, 1, None)


if __name__ == "__main__":
    unittest.main()
