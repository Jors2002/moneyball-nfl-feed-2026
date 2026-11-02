"""Pruebas sin red para el validador Moneyball 6.0."""
import copy
import unittest
from datetime import datetime, timezone

from moneyball6_validate import audit


def fixture():
    return {
        "schemaVersion": 5,
        "season": 2026,
        "fromWeek": 1,
        "thruWeek": 2,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "mappedPlayers": 1,
        "bySleeper": {
            "1234": [
                {"week": 1, "targets": 2, "carries": 0, "snaps": 20,
                 "routes": None, "firstReads": None, "snapShare": .5},
                {"week": 2, "targets": 4, "carries": 0, "snaps": 30,
                 "routes": None, "firstReads": None, "snapShare": .7},
            ]
        },
        "coverage": {"boxWeeks": [1, 2], "snapWeeks": [1, 2],
                     "pbpWeeks": [1], "routePlayerWeeks": 0},
        "injuriesBySleeper": {},
        "sources": {"snaps": "PARCIAL", "routes": "NO DISPONIBLE"},
    }


class Moneyball6AuditTests(unittest.TestCase):
    def test_optional_missing_routes_only_warns(self):
        result = audit(fixture())
        self.assertEqual(result["status"], "PASS_WITH_WARNINGS")
        self.assertEqual(result["metrics"]["routesPlayerWeeks"], 0)

    def test_duplicate_player_week_blocks(self):
        data = fixture()
        data["bySleeper"]["1234"].append(copy.deepcopy(data["bySleeper"]["1234"][0]))
        self.assertEqual(audit(data)["status"], "FAIL")

    def test_missing_latest_box_score_blocks(self):
        data = fixture()
        data["coverage"]["boxWeeks"] = [1]
        self.assertEqual(audit(data)["status"], "FAIL")

    def test_mismatched_mapped_players_blocks(self):
        data = fixture()
        data["mappedPlayers"] = 500
        self.assertEqual(audit(data)["status"], "FAIL")

    def test_invalid_route_share_blocks(self):
        data = fixture()
        data["bySleeper"]["1234"][0]["routeParticipation"] = 1.3
        self.assertEqual(audit(data)["status"], "FAIL")

    def test_missing_injury_timestamp_warns(self):
        data = fixture()
        data["injuriesBySleeper"] = {"1234": [{
            "week": 2, "dateModified": None, "dateVerified": False,
            "practiceStatus": "Full Participation in Practice"}]}
        result = audit(data)
        self.assertEqual(result["status"], "PASS_WITH_WARNINGS")
        self.assertEqual(result["metrics"]["injuryReportsDated"], 0)

    def test_claimed_verified_injury_without_date_blocks(self):
        data = fixture()
        data["injuriesBySleeper"] = {"1234": [{
            "week": 2, "dateModified": None, "dateVerified": True}]}
        self.assertEqual(audit(data)["status"], "FAIL")

    def test_future_generated_at_blocks(self):
        data = fixture()
        data["generatedAt"] = "2099-01-01T00:00:00+00:00"
        self.assertEqual(audit(data)["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
