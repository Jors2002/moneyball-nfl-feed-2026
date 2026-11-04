import unittest
import numpy as np
import pandas as pd
from moneyball8_forecast import (normalize, feature_rows, walk_forward, metrics,
                                interval_radius, evaluate, build, forecast, adjust_scoring)


def fixture():
    return pd.DataFrame([dict(player_id=f"p{i}", position="RB", season=y, week=w,
                             fantasy_points_ppr=10+i+w/10, carries=10+i, targets=3,
                             season_type="REG") for y in [2023,2024,2025]
                         for i in range(8) for w in range(1,19)])


class ForecastTests(unittest.TestCase):
    def test_no_current_or_future_outcome_in_features(self):
        h = normalize(fixture())
        a = feature_rows(h)
        h.loc[(h.season == 2025) & (h.week >= 12), "fantasy_points_ppr"] = 9999
        b = feature_rows(h)
        cols = ["season_mean", "recent4", "recent2", "carries", "targets"]
        pd.testing.assert_frame_equal(a[(a.season==2025)&(a.week==12)][cols],
                                      b[(b.season==2025)&(b.week==12)][cols])
        self.assertTrue((a.feature_through_week < a.week).all())

    def test_duplicate_rejected(self):
        h = fixture()
        with self.assertRaisesRegex(ValueError,"Duplicate"):
            normalize(pd.concat([h,h.iloc[:1]]))

    def test_missing_outcome_not_zero(self):
        h = fixture(); h.loc[0,"fantasy_points_ppr"] = np.nan
        with self.assertRaises(ValueError):normalize(h)

    def test_observed_zero_is_kept(self):
        h = fixture(); h.loc[0,"fantasy_points_ppr"] = 0
        self.assertEqual(normalize(h).fantasy_points_ppr.min(),0)

    def test_holdout_cannot_choose_winner(self):
        h = fixture();extra=h[h.season==2025].copy();extra["season"]=2026
        p = walk_forward(feature_rows(normalize(pd.concat([h,extra]))),minimum_train=10)
        a = evaluate(p)["RB"]
        p.loc[p.season==2026,"actual"] = 1000
        b = evaluate(p)["RB"]
        self.assertEqual(a["selected_model"],b["selected_model"])
        self.assertEqual(a["interval80_radius"],b["interval80_radius"])
        self.assertNotEqual(a["final_test"],b["final_test"])

    def test_future_data_cannot_change_earlier_walkforward(self):
        h = fixture()
        a = walk_forward(feature_rows(normalize(h)),minimum_train=10)
        h.loc[(h.season==2025)&(h.week>=12),"fantasy_points_ppr"] = 99
        b = walk_forward(feature_rows(normalize(h)),minimum_train=10)
        cols = ["season_mean","recent4","opportunity_ridge","position_ridge"]
        pd.testing.assert_frame_equal(a[(a.season==2025)&(a.week==12)][cols],
                                      b[(b.season==2025)&(b.week==12)][cols])

    def test_known_metrics(self):
        self.assertEqual(metrics([0,2],[1,1]),dict(n=2,mae=1.0,rmse=1.0,bias=0.0))

    def test_conformal_rank(self):
        self.assertEqual(interval_radius([1,2,3,4,5],.8),5)

    def test_regular_season_only_and_no_cross_season_history(self):
        h = fixture(); h.loc[0,"season_type"] = "POST"
        n = normalize(h)
        self.assertEqual(len(n),len(h)-1)
        f = feature_rows(n)
        self.assertTrue((f.week>=4).all())

    def test_insufficient_position_explicit(self):
        report,_ = build(fixture())
        self.assertEqual(report["positions"]["QB"]["status"],"INSUFFICIENT_DATA")
        self.assertNotIn("championship_probability",report)

    def test_interception_scoring_adjustment_and_mixed_schema_alias(self):
        h = fixture()
        h["interceptions"] = np.where(h.season==2023,2,np.nan)
        h["passing_interceptions"] = np.where(h.season!=2023,1,np.nan)
        x = adjust_scoring(h,-1)
        h = normalize(h)
        np.testing.assert_allclose(x[x.season==2023].fantasy_points_ppr.to_numpy(),
                                   h[h.season==2023].fantasy_points_ppr.to_numpy()+2)
        np.testing.assert_allclose(x[x.season==2024].fantasy_points_ppr.to_numpy(),
                                   h[h.season==2024].fantasy_points_ppr.to_numpy()+1)

    def test_scoring_adjustment_requires_observed_interceptions(self):
        with self.assertRaises(ValueError):adjust_scoring(fixture(),-1)

    def test_forecast_omits_ambiguous_mapping_and_does_not_claim_health(self):
        h = fixture()
        report,_ = build(h)
        live = h[h.season==2025].copy();live["season"] = 2026; live=live[live.week<=8]
        mapping = pd.DataFrame({"gsis_id":["p0","p0","p1"],"sleeper_id":["10","11","12"]})
        r = forecast(pd.concat([h,live]),report,mapping)
        self.assertNotIn("10",r["bySleeper"])
        self.assertIn("12",r["bySleeper"])
        p = r["bySleeper"]["12"]
        self.assertEqual(p["availability"],"UNVERIFIED")
        self.assertEqual(p["schedule"],"UNVERIFIED")
        self.assertEqual(r["targetWeek"],9)

    def test_missing_week_is_not_manufactured_as_zero(self):
        h = normalize(fixture())
        h = h[~((h.player_id=="p0")&(h.season==2025)&h.week.isin([6,7,8]))]
        f = feature_rows(h)
        self.assertTrue(f[(f.player_id=="p0")&(f.season==2025)&(f.week==9)].empty)

    def test_future_source_cutoff_and_undated_timestamp_rejected(self):
        h = fixture();report,_ = build(h)
        ids=pd.DataFrame({"gsis_id":["p0"],"sleeper_id":["10"]})
        with self.assertRaisesRegex(ValueError,"cutoff"):
            forecast(h,report,ids,season=2026)
        with self.assertRaisesRegex(ValueError,"timestamp"):
            forecast(h,report,ids,season=2025,as_of_week=8,source_generated_at="2026-11-04")

    def test_advanced_failure_in_promotion_gate_retains_simple(self):
        rows=[]
        for season,weeks in [(2024,range(4,19)),(2025,range(4,19)),(2026,range(4,9))]:
            for week in weeks:
                for i in range(5):
                    rows.append(dict(position="QB",season=season,week=week,actual=10,
                                     season_mean=12,recent4=13,opportunity_ridge=11,
                                     position_ridge=10 if season==2024 else 15))
        r=evaluate(pd.DataFrame(rows))["QB"]
        self.assertEqual(r["candidate_model"],"position_ridge")
        self.assertEqual(r["selected_model"],"opportunity_ridge")
        self.assertEqual(r["promotion_gate"],"ADVANCED_REJECTED_BASELINE_RETAINED")

    def test_deployment_baseline_does_not_rewrite_frozen_final_test(self):
        rows=[]
        for season,weeks in [(2024,range(4,19)),(2025,range(4,19)),(2026,range(4,9))]:
            for week in weeks:
                for i in range(5):
                    rows.append(dict(position="RB",season=season,week=week,actual=10,
                                     season_mean=13,recent4=14,opportunity_ridge=11,
                                     position_ridge=10 if season<2026 else 15))
        r=evaluate(pd.DataFrame(rows))["RB"]
        self.assertEqual(r["selected_model"],"position_ridge")
        self.assertEqual(r["final_test"]["selected_model"]["mae"],5)
        self.assertEqual(r["deployment_model"],"opportunity_ridge")
        self.assertEqual(r["deployment_status"],"PROSPECTIVE_VALIDATION_PENDING")
        self.assertIn("IN_SAMPLE_SELECTION",r["deployment_evaluation_label"])
        self.assertEqual(r["deployment_selection_partition"],"2026_W4_8")


if __name__ == "__main__":unittest.main()
