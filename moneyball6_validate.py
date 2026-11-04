#!/usr/bin/env python3
"""MONEYBALL 6.0 — auditoría de integridad y cobertura del feed avanzado.

No sustituye moneyball5_etl.py ni exige rutas/lesiones que el origen no publica.
Errores estructurales bloquean; cobertura incompleta produce advertencias.
Uso:
  python moneyball6_validate.py data/_MONEYBALL_FEED_2026.json.gz
  python moneyball6_validate.py data/_MONEYBALL_FEED_2026.json.gz --report data/moneyball6_quality.json
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import json
import math
from pathlib import Path
from typing import Any


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return date if date.tzinfo else None
    except ValueError:
        return None


def audit(feed: Any, max_age_hours: float = 48) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    metrics: dict[str, Any] = {}

    if not isinstance(feed, dict):
        return {"status": "FAIL", "errors": ["El feed no es un objeto JSON"],
                "warnings": [], "metrics": {}}

    if feed.get("schemaVersion") != 5:
        errors.append("schemaVersion esperado: 5")
    if feed.get("season") != 2026:
        errors.append("season esperado: 2026")

    first, through = feed.get("fromWeek"), feed.get("thruWeek")
    valid_weeks = (type(first) is int and type(through) is int
                   and 1 <= first <= through <= 18)
    if not valid_weeks:
        errors.append("Rango fromWeek/thruWeek inválido")

    generated = _timestamp(feed.get("generatedAt"))
    if generated is None:
        errors.append("generatedAt ausente, inválido o sin zona horaria")
    else:
        age = (datetime.now(timezone.utc) - generated.astimezone(timezone.utc)).total_seconds() / 3600
        metrics["ageHours"] = round(age, 2)
        if age < -1:
            errors.append("generatedAt en el futuro (más de una hora)")
        elif age > max_age_hours:
            warnings.append(f"Feed desactualizado: {age:.1f} horas")

    players = feed.get("bySleeper")
    if not isinstance(players, dict) or not players:
        errors.append("bySleeper ausente o vacío")
    else:
        player_count = 0
        row_count = 0
        snap_count = route_count = read_count = 0
        for sid, weekly in players.items():
            if not isinstance(sid, str) or not sid.isdigit():
                errors.append(f"Sleeper ID inválido: {str(sid)[:40]}")
                continue
            if not isinstance(weekly, list) or not weekly:
                errors.append(f"Sin registros semanales: {sid}")
                continue
            player_count += 1
            seen: set[int] = set()
            for row in weekly:
                row_count += 1
                if not isinstance(row, dict):
                    errors.append(f"Fila inválida: {sid}")
                    continue
                week = row.get("week")
                if type(week) is not int or (valid_weeks and not first <= week <= through):
                    errors.append(f"Semana inválida: {sid}/{week}")
                    continue
                if week in seen:
                    errors.append(f"Jugador-semana duplicado: {sid}/{week}")
                seen.add(week)
                for name in ("targets", "carries", "snaps", "routes", "firstReads",
                             "receptions", "teamSnaps", "teamDropbacks",
                             "redzoneCarries", "inside5Carries", "redzoneTargets",
                             "inside5Targets", "thirdDownTouches", "twoMinuteTouches",
                             "thirdDownOpportunities", "twoMinuteOpportunities"):
                    value = row.get(name)
                    if value is not None and (type(value) is not int or value < 0):
                        errors.append(f"{name} inválido: {sid}/{week}")
                for name in ("snapShare", "targetShare", "firstReadShare", "routeParticipation", "targetsPerRoute"):
                    value = row.get(name)
                    if value is not None and (isinstance(value, bool)
                                              or not isinstance(value, (int, float))
                                              or not math.isfinite(value)
                                              or not 0 <= value <= 1):
                        errors.append(f"{name} fuera de rango: {sid}/{week}")
                for name in ("ppr", "receivingAirYards", "airYardsShare", "wopr", "aDOT"):
                    value = row.get(name)
                    # Air yards and fantasy scores can legitimately be negative.
                    if value is not None and (isinstance(value, bool) or
                            not isinstance(value, (int, float)) or not math.isfinite(value)):
                        errors.append(f"{name} no finito/numerico: {sid}/{week}")
                if row.get("routes") is not None and row.get("teamDropbacks") is not None:
                    routes, drops = row["routes"], row["teamDropbacks"]
                    if type(routes) is int and type(drops) is int and routes > drops:
                        errors.append(f"Rutas mayores a dropbacks: {sid}/{week}")
                snap_count += row.get("snaps") is not None
                route_count += row.get("routes") is not None
                read_count += row.get("firstReads") is not None
        metrics.update(players=player_count, playerWeeks=row_count,
                       snapsPlayerWeeks=snap_count, routesPlayerWeeks=route_count,
                       firstReadsPlayerWeeks=read_count)
        if isinstance(feed.get("mappedPlayers"), int) and feed["mappedPlayers"] != player_count:
            errors.append("mappedPlayers no coincide con bySleeper")
        if route_count == 0:
            warnings.append("Sin rutas verificadas: no calcular TPRR ni route participation")
        if snap_count == 0:
            warnings.append("Sin snaps verificables")
        if read_count == 0:
            warnings.append("Sin first reads verificables")

    coverage = feed.get("coverage")
    if not isinstance(coverage, dict):
        errors.append("Objeto coverage ausente")
    elif valid_weeks:
        for key in ("boxWeeks", "snapWeeks", "pbpWeeks"):
            weeks = coverage.get(key)
            if not isinstance(weeks, list) or any(type(w) is not int or w < first or w > through for w in weeks):
                errors.append(f"coverage.{key} inválido")
            elif len(set(weeks)) != len(weeks):
                errors.append(f"coverage.{key} contiene duplicados")
            elif key == "boxWeeks" and through not in weeks:
                errors.append("Falta la última semana del box score")
            elif key != "boxWeeks" and len(weeks) < through - first + 1:
                warnings.append(f"{key} cubre {len(weeks)} de {through-first+1} semanas")
        routes_reported = coverage.get("routePlayerWeeks")
        if isinstance(routes_reported, int) and "routesPlayerWeeks" in metrics and routes_reported != metrics["routesPlayerWeeks"]:
            errors.append("routePlayerWeeks no coincide con los registros publicados")

    injuries = feed.get("injuriesBySleeper")
    if not isinstance(injuries, dict):
        errors.append("injuriesBySleeper debe ser un objeto")
    else:
        dated = total = 0
        for sid, records in injuries.items():
            if not isinstance(records, list):
                errors.append(f"Lesiones inválidas: {sid}")
                continue
            for record in records:
                total += 1
                if not isinstance(record, dict):
                    errors.append(f"Registro de lesión inválido: {sid}")
                    continue
                if _timestamp(record.get("dateModified")):
                    dated += 1
                elif record.get("dateVerified") is True:
                    errors.append(f"Lesión marcada verificable sin timestamp válido: {sid}")
        metrics["injuryReports"] = total
        metrics["injuryReportsDated"] = dated
        if total and dated < total:
            warnings.append(f"Lesiones sin fecha confiable: {total-dated}/{total}; no presentarlas como actuales")

    sources = feed.get("sources")
    if not isinstance(sources, dict):
        errors.append("Objeto sources ausente")
    else:
        for name, state in sources.items():
            if isinstance(state, str) and state.startswith("ERROR:"):
                warnings.append(f"Fuente opcional {name}: {state}")

    return {"status": "FAIL" if errors else "PASS_WITH_WARNINGS" if warnings else "PASS",
            "errors": errors[:100], "warnings": warnings, "metrics": metrics}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("feed", type=Path)
    parser.add_argument("--max-age-hours", type=float, default=48)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    opener = gzip.open if args.feed.suffix == ".gz" else open
    with opener(args.feed, "rt", encoding="utf-8") as f:
        payload = json.load(f)
    result = audit(payload, args.max_age_hours)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    raise SystemExit(1 if result["errors"] else 0)


if __name__ == "__main__":
    main()
