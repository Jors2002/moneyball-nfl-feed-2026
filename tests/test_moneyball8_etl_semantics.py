"""Regressions for the additive opportunity naming migration; no network."""
import unittest
from unittest.mock import patch

import pandas as pd

from moneyball5_etl import METRIC_DEFINITIONS, make_feed, pbp_index


def play(play_id, *, down=3, qtr=2, seconds=60, rush=False,
         complete=False, kneel=False):
    return {"season": 2026, "season_type": "REG", "week": 1,
            "game_id": "2026_01_TEST", "play_id": play_id,
            "posteam": "BUF", "rush_attempt": int(rush),
            "pass_attempt": int(not rush), "yardline_100": 30,
            "rusher_player_id": "00-0000001" if rush else None,
            "receiver_player_id": None if rush else "00-0000001",
            "complete_pass": int(complete), "qb_kneel": int(kneel),
            "down": down, "qtr": qtr,
            "quarter_seconds_remaining": seconds}


class OpportunitySemanticsTests(unittest.TestCase):
    def usage(self, plays):
        return pbp_index(pd.DataFrame(plays), {"00-0000001": "1"}, 1)[0]

    def test_incomplete_target_is_opportunity_and_legacy_count_is_preserved(self):
        row = self.usage([play(1, complete=False), play(2, complete=True),
                          play(3, rush=True)])[("1", 1)]
        self.assertEqual(row["thirdDownOpportunities"], 3)
        self.assertEqual(row["twoMinuteOpportunities"], 3)
        self.assertEqual(row["thirdDownTouches"], row["thirdDownOpportunities"])
        self.assertEqual(row["twoMinuteTouches"], row["twoMinuteOpportunities"])

    def test_two_minute_clock_window_is_inclusive_and_excludes_other_quarters(self):
        plays = [play(1, down=1, seconds=120), play(2, down=1, seconds=0),
                 play(3, down=1, seconds=121), play(4, down=1, qtr=1),
                 play(5, down=1, qtr=3), play(6, down=1, qtr=5),
                 play(7, down=1, qtr=4)]
        row = self.usage(plays)[("1", 1)]
        self.assertEqual(row["twoMinuteOpportunities"], 3)
        self.assertIsNone(row["thirdDownOpportunities"])

    def test_qb_kneel_is_not_an_opportunity(self):
        self.assertEqual(self.usage([play(1, rush=True, kneel=True)]), {})

    def test_missing_clock_fields_does_not_manufacture_two_minute_zero(self):
        df = pd.DataFrame([play(1)]).drop(columns=["qtr", "quarter_seconds_remaining"])
        row = pbp_index(df, {"00-0000001": "1"}, 1)[0][("1", 1)]
        self.assertEqual(row["thirdDownOpportunities"], 1)
        self.assertIsNone(row["twoMinuteOpportunities"])

    def test_feed_schema_is_additive_and_documents_deprecated_legacy_names(self):
        box = {(str(i), 1): {"targets": 0, "carries": 0} for i in range(1, 101)}
        with patch("moneyball5_etl.load_identity", return_value=({}, {}, {})), \
             patch("moneyball5_etl.stats_index", return_value=(box, set(box))):
            feed = make_feed(pd.DataFrame(), pd.DataFrame(), None, None, None, None, 1)
        self.assertEqual(feed["schemaVersion"], 5)
        self.assertEqual(feed["metricDefinitions"], METRIC_DEFINITIONS)
        for name in ("thirdDown", "twoMinute"):
            old, new = name + "Touches", name + "Opportunities"
            self.assertTrue(feed["metricDefinitions"][old]["deprecated"])
            self.assertEqual(feed["metricDefinitions"][old]["aliasOf"], new)
            self.assertIsNone(feed["bySleeper"]["1"][0][old])
            self.assertIsNone(feed["bySleeper"]["1"][0][new])


if __name__ == "__main__":
    unittest.main()
