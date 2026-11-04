#!/usr/bin/env python3
"""Position-specific PPR forecasts with chronological selection and held-out scoring.

NFL player statistics are retrospective revised snapshots. This is an event-time
backtest, not proof that each feature was published before historical kickoff.
All forecasts are CONDITIONAL ON A RECORDED GAME; absence is not modeled as zero.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

POSITIONS = ("QB", "RB", "WR", "TE")
MODELS = ("season_mean", "recent4", "opportunity_ridge", "position_ridge")
OPPS = {"QB": ["attempts", "carries"], "RB": ["carries", "targets"],
        "WR": ["targets"], "TE": ["targets"]}
STATS = ("attempts", "carries", "targets", "receptions", "passing_yards",
         "rushing_yards", "receiving_yards", "passing_tds", "rushing_tds", "receiving_tds")


def load_history(paths):
    frames = [pd.read_csv(p, low_memory=False) for p in paths]
    return normalize(pd.concat(frames, ignore_index=True))


def normalize(df):
    df = df.copy()
    aliases = {"passing_attempts": "attempts", "rushing_attempts": "carries",
               "passing_interceptions": "interceptions",
               "passing_touchdowns": "passing_tds", "rushing_touchdowns": "rushing_tds",
               "receiving_touchdowns": "receiving_tds"}
    for old, new in aliases.items():
        if old in df:
            df[new] = df[new].fillna(df[old]) if new in df else df[old]
    required = {"player_id", "position", "season", "week", "fantasy_points_ppr"}
    if not required.issubset(df):
        raise ValueError(f"Missing required columns: {sorted(required-set(df))}")
    if "season_type" in df:
        df = df[df.season_type == "REG"].copy()
    df = df[df.position.isin(POSITIONS)].copy()
    if df[list(required)].isna().any().any():
        raise ValueError("Null required player/week/outcome data")
    if df.duplicated(["player_id", "season", "week"]).any():
        raise ValueError("Duplicate player-season-week")
    for c in ["season", "week", "fantasy_points_ppr"]:
        df[c] = pd.to_numeric(df[c], errors="raise")
        if not np.isfinite(df[c]).all():
            raise ValueError(f"Nonfinite {c}")
    if not df.week.between(1, 18).all() or not (df.week % 1 == 0).all():
        raise ValueError("Invalid regular-season week")
    if not (df.season % 1 == 0).all():
        raise ValueError("Invalid season")
    for c in STATS:
        if c not in df:
            df[c] = np.nan
        df[c] = pd.to_numeric(df[c], errors="coerce")
        if np.isinf(df[c]).any():
            raise ValueError(f"Infinite source statistic {c}")
    df["player_id"] = df.player_id.astype(str)
    return df.sort_values(["season", "week", "player_id"]).reset_index(drop=True)


def feature_rows(history):
    """Build each row from strictly earlier weeks in the SAME NFL season."""
    rows = []
    for (_, season), group in history.groupby(["player_id", "season"], sort=False):
        prior = []
        for r in group.sort_values("week").to_dict("records"):
            if len(prior) >= 3 and r["week"]-prior[-1]["week"] <= 2:
                scores = [p["fantasy_points_ppr"] for p in prior]
                # Eligibility depends on prior information only, never current points.
                if np.mean(scores[-4:]) >= 5:
                    f = {"player_id": r["player_id"], "position": r["position"],
                         "season": int(season), "week": int(r["week"]),
                         "actual": float(r["fantasy_points_ppr"]),
                         "season_mean": float(np.mean(scores)),
                         "recent4": float(np.mean(scores[-4:])),
                         "recent2": float(np.mean(scores[-2:])),
                         "prior_games": len(prior), "feature_through_week": int(prior[-1]["week"])}
                    for c in STATS:
                        vals = [p[c] for p in prior[-4:] if pd.notna(p[c])]
                        f[c] = float(np.mean(vals)) if vals else np.nan
                    rows.append(f)
            prior.append(r)
    return pd.DataFrame(rows)


def columns(position, model):
    if model == "opportunity_ridge":
        return OPPS[position]
    return ["season_mean", "recent4", "recent2"] + OPPS[position] + {
        "QB": ["passing_yards", "rushing_yards", "passing_tds"],
        "RB": ["rushing_yards", "receiving_yards", "receptions", "rushing_tds"],
        "WR": ["receiving_yards", "receptions", "receiving_tds"],
        "TE": ["receiving_yards", "receptions", "receiving_tds"],
    }[position]


def ridge_predict(train, test, cols, penalty=30.0):
    """Training medians + missing flags; missing features never become observed zeros."""
    x = train[cols].to_numpy(dtype=float)
    t = test[cols].to_numpy(dtype=float)
    med = np.array([np.median(v[np.isfinite(v)]) if np.isfinite(v).any() else 0.0 for v in x.T])
    xmiss, tmiss = ~np.isfinite(x), ~np.isfinite(t)
    x, t = np.where(xmiss, med, x), np.where(tmiss, med, t)
    center, scale = x.mean(0), x.std(0)
    scale[scale < 1e-8] = 1
    x = np.column_stack([np.ones(len(x)), (x-center)/scale, xmiss.astype(float)])
    t = np.column_stack([np.ones(len(t)), (t-center)/scale, tmiss.astype(float)])
    reg = np.eye(x.shape[1])*penalty
    reg[0, 0] = 0
    beta = np.linalg.solve(x.T@x+reg, x.T@train.actual.to_numpy(dtype=float))
    return np.maximum(0, t@beta)


def walk_forward(features, minimum_train=60):
    if features.empty:
        raise ValueError("No eligible historical rows")
    out = []
    for (season, week), current in features.groupby(["season", "week"], sort=True):
        past = features[(features.season < season) | ((features.season == season) & (features.week < week))]
        for pos, test in current.groupby("position"):
            train = past[past.position == pos]
            if len(train) < minimum_train:
                continue
            predictions = {"season_mean": test.season_mean.to_numpy(), "recent4": test.recent4.to_numpy()}
            for name in MODELS[2:]:
                predictions[name] = ridge_predict(train, test, columns(pos, name))
            for i, r in enumerate(test.to_dict("records")):
                out.append({k: r[k] for k in ["player_id", "position", "season", "week", "actual", "feature_through_week"]}
                           | {m: float(v[i]) for m, v in predictions.items()})
    return pd.DataFrame(out)


def metrics(actual, predicted):
    a, p = np.asarray(actual, dtype=float), np.asarray(predicted, dtype=float)
    if not len(a):
        return {"n": 0, "mae": None, "rmse": None, "bias": None}
    d = p-a
    return {"n": len(d), "mae": round(float(np.mean(np.abs(d))), 5),
            "rmse": round(float(np.sqrt(np.mean(d*d))), 5), "bias": round(float(np.mean(d)), 5)}


def interval_radius(residuals, coverage=0.8):
    """Finite-sample split-conformal rank; temporal exchangeability is NOT assumed proven."""
    a = np.sort(np.abs(np.asarray(residuals, dtype=float)))
    if not len(a):
        raise ValueError("No calibration examples")
    rank = min(len(a), math.ceil((len(a)+1)*coverage))
    return float(a[rank-1])


def evaluate(predictions, selection_season=2024, test_season=2025, calibration_through_week=8,
             final_evaluation_season=2026, final_through_week=8):
    report = {}
    for pos in POSITIONS:
        p = predictions[predictions.position == pos]
        sel = p[p.season == selection_season]
        cal = p[(p.season == test_season) & (p.week <= calibration_through_week)]
        test = p[(p.season == test_season) & (p.week > calibration_through_week)]
        final = p[(p.season == final_evaluation_season)&(p.week <= final_through_week)]
        if min(len(sel), len(cal), len(test)) < 20:
            report[pos] = {"status": "INSUFFICIENT_DATA", "selection_n": len(sel), "calibration_n": len(cal), "test_n": len(test)}
            continue
        selection = {m: metrics(sel.actual, sel[m]) for m in MODELS}
        candidate = min(MODELS, key=lambda m: (selection[m]["mae"], MODELS.index(m)))
        simple = min(MODELS[:3], key=lambda m: (selection[m]["mae"],MODELS.index(m)))
        gate_metrics = {m: metrics(test.actual,test[m]) for m in MODELS}
        # 2025 is an explicit promotion validation gate, NOT the final test.
        rejected = candidate == "position_ridge" and gate_metrics[candidate]["mae"] >= gate_metrics[simple]["mae"]
        best = simple if rejected else candidate
        # Final 2026 results cannot change this frozen decision or interval radius.
        radius = interval_radius(cal.actual-cal[best])
        hit = np.abs(test.actual-test[best]) <= radius
        # Deployment can retain a better simple baseline after inspection, but
        # this creates a NEW policy with no untouched prospective test yet.
        deployment = best
        if len(final) >= 20:
            final_simple = min(MODELS[:3],key=lambda m:(metrics(final.actual,final[m])["mae"],MODELS.index(m)))
            if metrics(final.actual,final[final_simple])["mae"] < metrics(final.actual,final[best])["mae"]:
                deployment = final_simple
        deployment_radius = interval_radius(cal.actual-cal[deployment])
        report[pos] = {"status": "HELD_OUT_EVALUATED_CONDITIONAL_ON_OBSERVED_GAME",
                       "selected_model": best, "candidate_model": candidate,
                       "deployment_model":deployment,
                       "deployment_status":"PROSPECTIVE_VALIDATION_PENDING",
                       "deployment_selection_partition":f"{final_evaluation_season}_W4_{final_through_week}",
                       "deployment_interval80_radius":round(deployment_radius,5),
                       "deployment_interval80_selection_coverage":round(float((np.abs(final.actual-final[deployment])<=deployment_radius).mean()),5) if len(final) else None,
                       "deployment_evaluation_label":"IN_SAMPLE_SELECTION: selected after inspecting final partition; no untouched test for deployed policy",
                       "simple_baseline_preselected": simple,
                       "promotion_gate": "ADVANCED_REJECTED_BASELINE_RETAINED" if rejected else "CANDIDATE_RETAINED",
                       "selection": selection,
                       "calibration_n": len(cal), "interval80_radius": round(radius, 5),
                       "test": gate_metrics,
                       "test_label": "2025 SECOND_VALIDATION_DEPLOYMENT_GATE; not final test",
                       "test_interval80_coverage": round(float(hit.mean()), 5),
                       "final_test": {"season":final_evaluation_season,"through_week":final_through_week,
                                      "selected_model":metrics(final.actual,final[best]),
                                      "all_models":{m:metrics(final.actual,final[m]) for m in MODELS},
                                      "interval80_coverage":round(float((np.abs(final.actual-final[best])<=radius).mean()),5) if len(final) else None,
                                      "policy_frozen_before_this_partition":True},
                       "calibration_claim": "NOT_ESTABLISHED: temporal and availability shift remain",
                       "advanced_beats_recent4_on_test": bool(metrics(test.actual,test.position_ridge)["mae"] < metrics(test.actual,test.recent4)["mae"])}
    return report


def adjust_scoring(history, pass_int_points=-2.0):
    history = normalize(history)
    if not math.isfinite(pass_int_points):
        raise ValueError("Nonfinite interception scoring")
    if pass_int_points != -2:
        if "interceptions" not in history or history.interceptions.isna().any():
            raise ValueError("Interception adjustment requires observed interception counts")
        ints = pd.to_numeric(history.interceptions, errors="raise")
        if not np.isfinite(ints).all():
            raise ValueError("Nonfinite interception counts")
        history["fantasy_points_ppr"] = history.fantasy_points_ppr+(pass_int_points+2)*ints
    return history


def build(history, selection_season=2024, test_season=2025, calibration_through_week=8, pass_int_points=-2.0,
          final_evaluation_season=2026, final_through_week=8):
    if selection_season >= test_season or test_season >= final_evaluation_season or not 1 <= calibration_through_week <= 17:
        raise ValueError("Invalid chronological split")
    history = adjust_scoring(history, pass_int_points)
    features = feature_rows(history)
    predictions = walk_forward(features)
    if predictions.empty:
        raise ValueError("No walk-forward predictions")
    evaluated = evaluate(predictions, selection_season, test_season, calibration_through_week,final_evaluation_season,final_through_week)
    return {"schemaVersion": 80, "module": "position_ppr_forecast_validation",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "scoring": {"basis": "nflverse fantasy_points_ppr", "source_pass_int_points": -2,
                        "pass_int_points": pass_int_points,
                        "restriction": "Other custom scoring rules require separate reconciliation"},
            "positions": evaluated,
            "split": {"selection_season": selection_season, "calibration_season": test_season,
                      "calibration_through_week": calibration_through_week,
                      "second_validation_gate_weeks": list(range(calibration_through_week+1,19)),
                      "final_test_season":final_evaluation_season,"final_test_through_week":final_through_week,
                      "training": "expanding player-week observations strictly before each target week"},
            "sample": {"source_rows": len(history), "feature_rows": len(features), "predictions": len(predictions)},
            "limitations": ["Conditional on recorded games; unobserved absences are NOT zeros.",
                            "Eligibility requires >=3 prior same-season games, recent4 >=5 PPR and prior observation <=2 weeks ago.",
                            "Revised historical snapshots: publication-time availability is unproven.",
                            "No opponent, schedule, official practice, availability, market baseline, K or DST model.",
                            "Position ridge fixed penalty=30;2025 late-season validation gates promotion against simple baseline preselected in2024.",
                            "Final2026 W4-8 partition does not alter frozen production policy; retrospective revised snapshots are not a prospective trial.",
                            "Deployment may retain a better simple baseline selected using2026 W4-8; frozen-policy final_test remains unchanged and deployed policy needs prospective validation.",
                            "Symmetric 80% residual intervals are candidate predictive intervals, not guaranteed floors/ceilings.",
                            "No championship odds or trade acceptance probabilities."]}, predictions


def forecast(history, validation, crosswalk, season=2026, as_of_week=8,
             pass_int_points=-2.0, source_generated_at=None):
    """Forecast next numbered week, without asserting a scheduled/available game."""
    if not 1 <= as_of_week <= 17:
        raise ValueError("Invalid next-week forecast cutoff")
    if source_generated_at is not None:
        stamp = datetime.fromisoformat(source_generated_at.replace("Z","+00:00"))
        if stamp.tzinfo is None or stamp > datetime.now(timezone.utc):
            raise ValueError("Source timestamp must be timezone-aware and not future")
    if not ((history.season == season)&(history.week >= as_of_week)).any():
        raise ValueError("Forecast cutoff exceeds observed source week")
    history = adjust_scoring(history, pass_int_points)
    history = history[(history.season < season) | ((history.season == season) & (history.week <= as_of_week))]
    current = history[history.season == season].copy()
    if current.empty:
        raise ValueError("No current-season observed data")
    # Placeholder is only a request for features, never training truth.
    placeholder = current.sort_values("week").drop_duplicates("player_id",keep="last").copy()
    placeholder["week"] = as_of_week+1
    placeholder["fantasy_points_ppr"] = np.nan
    augmented = pd.concat([history,placeholder],ignore_index=True)
    all_features = feature_rows(augmented)
    requests = all_features[(all_features.season == season)&(all_features.week == as_of_week+1)]
    train = all_features[(all_features.season < season)|((all_features.season==season)&(all_features.week<=as_of_week))]
    # Mapping is accepted only when both directions are unique.
    ids = crosswalk[["gsis_id","sleeper_id"]].dropna().copy()
    ids["sleeper_id"] = ids.sleeper_id.astype(str).str.replace(r"\.0$","",regex=True)
    ids = ids.drop_duplicates()
    ids = ids[~ids.gsis_id.duplicated(keep=False)&~ids.sleeper_id.duplicated(keep=False)]
    mapping = dict(zip(ids.gsis_id,ids.sleeper_id))
    names = {}
    for r in current.to_dict("records"):
        names[r["player_id"]] = r.get("player_display_name") or r.get("player_name") or r["player_id"]
    by_sleeper = {}
    missing = []
    for pos, rows in requests.groupby("position"):
        audit = validation["positions"].get(pos,{})
        model = audit.get("deployment_model",audit.get("selected_model"))
        if not model:
            continue
        if model in MODELS[:2]:
            points = rows[model].to_numpy()
        else:
            points = ridge_predict(train[train.position == pos],rows,columns(pos,model))
        radius = audit.get("deployment_interval80_radius",audit["interval80_radius"])
        for r, point in zip(rows.to_dict("records"),points):
            sid = mapping.get(r["player_id"])
            if not sid or not sid.isdigit():
                missing.append(r["player_id"])
                continue
            by_sleeper[sid] = {"name": names[r["player_id"]], "position": pos,
                              "projection": round(float(point),4),
                              "interval80": {"lower": round(float(point)-radius,4), "upper": round(float(point)+radius,4)},
                              "model": model, "priorGames": r["prior_games"],
                              "lastObservedWeek": r["feature_through_week"],
                              "quality": "CONDITIONAL_ON_RECORDED_GAME", "availability": "UNVERIFIED",
                              "schedule": "UNVERIFIED", "calibration": "NOT_ESTABLISHED",
                              "deploymentStatus":audit.get("deployment_status","PROSPECTIVE_VALIDATION_PENDING"),
                              "evaluationBasis":audit.get("deployment_evaluation_label","IN_SAMPLE_SELECTION")}
    now = datetime.now(timezone.utc).isoformat()
    return {"schemaVersion":80,"season":season,"asOfWeek":as_of_week,"targetWeek":as_of_week+1,
            "generatedAt":now,"sourceGeneratedAt":source_generated_at or now,
            "sourceTimestampMeaning": "provided feed generation timestamp" if source_generated_at else "retrieval/build time, NOT NFL event/publication time",
            "bySleeper":by_sleeper,"validation":validation,"unmappedPlayers":missing,
            "scoring":validation["scoring"],
            "limitations":validation["limitations"]+[
                "Next numbered week; scheduled game and availability must be verified privately before lineup use.",
                "Intervals use 2025 calibration residuals, with no proof of exchangeability in 2026.",
                "Players with insufficient/recently missing history are omitted rather than assigned zero."]}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--history", type=Path, action="append", required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--predictions-output", type=Path)
    ap.add_argument("--selection-season", type=int, default=2024)
    ap.add_argument("--test-season", type=int, default=2025)
    ap.add_argument("--calibration-through-week", type=int, default=8)
    ap.add_argument("--pass-int-points", type=float, default=-2)
    ap.add_argument("--crosswalk", type=Path)
    ap.add_argument("--forecast-output", type=Path)
    ap.add_argument("--forecast-season", type=int, default=2026)
    ap.add_argument("--as-of-week", type=int, default=8)
    ap.add_argument("--source-generated-at")
    ap.add_argument("--final-evaluation-season",type=int,default=2026)
    ap.add_argument("--final-through-week",type=int,default=8)
    args = ap.parse_args()
    history = load_history(args.history)
    report, predictions = build(history, args.selection_season, args.test_season, args.calibration_through_week,args.pass_int_points,
                                args.final_evaluation_season,args.final_through_week)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.output.with_suffix(args.output.suffix+".tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2)+"\n")
    tmp.replace(args.output)
    if args.predictions_output:
        predictions.to_csv(args.predictions_output, index=False)
    if args.forecast_output:
        if not args.crosswalk:
            ap.error("--forecast-output requires --crosswalk")
        result = forecast(history,report,pd.read_csv(args.crosswalk,low_memory=False),args.forecast_season,
                          args.as_of_week,args.pass_int_points,args.source_generated_at)
        args.forecast_output.parent.mkdir(parents=True,exist_ok=True)
        tmp = Path(str(args.forecast_output)+".tmp")
        with gzip.open(tmp,"wt",encoding="utf-8") as f:
            json.dump(result,f,ensure_ascii=False,allow_nan=False,separators=(",",":"))
        tmp.replace(args.forecast_output)
    print(json.dumps(report["positions"], ensure_ascii=False))


if __name__ == "__main__":
    main()
