#!/usr/bin/env python3
"""MONEYBALL 5.0 — fuente ofensiva normalizada de NFL 2026.

Uso personal, solo datos públicos y con atribución. No descarga datos privados de Sleeper.
La salida JSON conserva NULL cuando la métrica no tiene cobertura.
Licencias: NFLverse CC-BY 4.0; FTN via nflverse CC-BY-SA 4.0.
Las rutas no se deducen: CSV opcional SOLO si posees derechos de automatización.

Instalar: pip install -r requirements.txt
Ejecutar: python moneyball5_etl.py --current-week 8 --output _MONEYBALL_FEED_2026.json
En producción omitir --current-week para obtener semana actual de Sleeper.
"""
from __future__ import annotations
import argparse
import gzip
import math
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any
import pandas as pd
import numpy as np
import requests

SEASON = 2026
ROOT = "https://github.com/nflverse/nflverse-data/releases/download/"
SOURCES = {
    "stats": ROOT + f"stats_player/stats_player_week_{SEASON}.csv",
    "snaps": ROOT + f"snap_counts/snap_counts_{SEASON}.parquet",
    "pbp": ROOT + f"pbp/play_by_play_{SEASON}.parquet",
    "ftn": ROOT + f"ftn_charting/ftn_charting_{SEASON}.parquet",
    "injury": ROOT + f"injuries/injuries_{SEASON}.parquet",
    "crosswalk": "https://raw.githubusercontent.com/dynastyprocess/data/master/files/db_playerids.csv",
    "state": "https://api.sleeper.app/v1/state/nfl",
}
ATTRIBUTIONS = {
    "nflverse": "https://nflreadr.nflverse.com/articles/nflverse_data_schedule.html — CC-BY 4.0",
    "FTN": "https://ftnfantasy.com/data vía nflverse — CC-BY-SA 4.0",
    "DynastyProcess": "https://github.com/dynastyprocess/data",
}

# Additive schema-5 migration: old consumers keep their keys, but those names
# never meant completed touches. A target includes an incomplete pass.
METRIC_DEFINITIONS = {
    "thirdDownOpportunities": {
        "definition": "Observed carries (excluding QB kneels) plus directed pass targets, including incompletions, on third down.",
        "scope": "Observed PBP opportunities; not touches, receptions, snaps or routes. Missing coverage remains null.",
    },
    "twoMinuteOpportunities": {
        "definition": "Observed carries (excluding QB kneels) plus directed pass targets, including incompletions, in Q2 or Q4 with 0 through 120 seconds remaining (inclusive).",
        "scope": "Clock-window proxy; not personnel participation or a verified two-minute offense designation. Missing coverage remains null.",
    },
    "thirdDownTouches": {"deprecated": True, "aliasOf": "thirdDownOpportunities",
                         "reason": "Legacy name includes incomplete targets; never interpret as completed touches."},
    "twoMinuteTouches": {"deprecated": True, "aliasOf": "twoMinuteOpportunities",
                         "reason": "Legacy name includes incomplete targets; never interpret as completed touches."},
}


def pull(url: str, dest: Path, hours: float = 6) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size and (datetime.now(timezone.utc).timestamp()-dest.stat().st_mtime) < hours*3600:
        return dest
    temp = dest.with_suffix(dest.suffix + ".tmp")
    with requests.get(url, timeout=(20, 180), stream=True, headers={"User-Agent": "MoneyballGM-Personal/5.0"}) as resp:
        resp.raise_for_status()
        with temp.open("wb") as f:
            for piece in resp.iter_content(chunk_size=1024*1024):
                if piece: f.write(piece)
    if temp.stat().st_size == 0:
        raise RuntimeError(f"Descarga vacía: {url}")
    temp.replace(dest)
    return dest


# Proyección de columnas antes de cargar Parquet: ahorro sustancial de RAM para
# play-by-play (contiene cientos de columnas que Moneyball no necesita).
PARQUET_FIELDS = {
    "snaps": ["pfr_player_id","season","week","offense_snaps","offense_pct","game_type"],
    "pbp": ["season","season_type","week","game_id","play_id","posteam",
            "rush_attempt","pass_attempt","yardline_100","rusher_player_id",
            "receiver_player_id","qb_kneel","down","qtr",
            "quarter_seconds_remaining","qb_dropback"],
    "ftn": ["nflverse_game_id","nflverse_play_id","read_thrown","season","week","season_type"],
    "injury": ["season","week","gsis_id","report_status","practice_status",
               "date_modified","report_date","practice_date","date","report_primary_injury"],
}

def read_small_parquet(key: str, path: Path) -> pd.DataFrame:
    import pyarrow.parquet as pq
    available=set(pq.ParquetFile(path).schema.names)
    selected=[col for col in PARQUET_FIELDS[key] if col in available]
    return pd.read_parquet(path,columns=selected)


def json_native(value: Any) -> Any:
    """Convierte escalares pandas/NumPy a JSON válido sin fabricar cifras.

    Mantiene ``None`` para datos ausentes. No serializa estructuras desconocidas
    como cadenas, porque ocultaría errores en el esquema del feed.
    """
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, dict):
        return {str(json_native(k)): json_native(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_native(v) for v in value]
    if isinstance(value, np.generic):
        return json_native(value.item())
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def load_source(key: str, cache: Path, optional: bool = False) -> pd.DataFrame | None:
    suffix = ".csv" if key in ("stats", "crosswalk") else ".parquet"
    try:
        file = pull(SOURCES[key], cache / (key + suffix))
        return pd.read_csv(file, low_memory=False, dtype=str if key=="crosswalk" else None) if suffix==".csv" else read_small_parquet(key,file)
    except Exception as exc:
        if optional:
            print(f"FUENTE OPCIONAL {key} NO VERIFICADA: {exc}")
            return None
        raise RuntimeError(f"Fuente requerida {key} falló: {exc}") from exc


def have(df: pd.DataFrame, required: list[str], label: str) -> None:
    missing = set(required)-set(df.columns)
    if missing:
        raise ValueError(f"{label}: columnas faltantes {sorted(missing)}")


def gsis_id(x: Any) -> str | None:
    if pd.isna(x): return None
    s = str(x).strip()
    return s if len(s)==10 and s.startswith("00-") and s[3:].isdigit() else None


def text_id(x: Any) -> str | None:
    if pd.isna(x): return None
    s = str(x).strip()
    return s if s.isdigit() and 2 <= len(s) <= 9 else None


def clean_rate(x: Any) -> float | None:
    """PFR offense_pct puede expresarse 0.61 o 61.0; nunca inventar cero."""
    if pd.isna(x) or x == "": return None
    n=float(x)
    if n>1 and n<=100: n/=100
    return round(n,5) if 0<=n<=1 else None


def nint(x: Any) -> int | None:
    if pd.isna(x) or x == "": return None
    try:
        v=float(x)
        if not (v.is_integer() and -1_000_000_000 < v < 1_000_000_000): return None
        return int(v)
    except (ValueError, TypeError, OverflowError): return None


def load_identity(cross: pd.DataFrame) -> tuple[dict[str,str],dict[str,str],dict[str,Any]]:
    have(cross,["gsis_id","sleeper_id"],"DynastyProcess")
    # No fuzzy matching. Duplicados inconsistentes quedan fuera.
    gs: dict[str,set[str]] = {}
    pfr: dict[str,set[str]] = {}
    pfr_col="pfr_id" if "pfr_id" in cross.columns else None
    for x in cross.itertuples(index=False):
        row=x._asdict()
        sid=text_id(row.get("sleeper_id"))
        if not sid: continue
        g=gsis_id(row.get("gsis_id"))
        if g: gs.setdefault(g,set()).add(sid)
        p=row.get(pfr_col) if pfr_col else None
        if p and not pd.isna(p): pfr.setdefault(str(p).strip(),set()).add(sid)
    # La ambigüedad inversa (un Sleeper ID asociado a dos jugadores físicos)
    # también es peligrosa: jamás sumar sus estadísticas bajo un solo jugador.
    g_candidates={k:next(iter(v)) for k,v in gs.items() if len(v)==1}
    p_candidates={k:next(iter(v)) for k,v in pfr.items() if len(v)==1}
    inverse:dict[str,set[str]]={}
    for g,sid in g_candidates.items(): inverse.setdefault(sid,set()).add(g)
    bad_sid={sid for sid,vals in inverse.items() if len(vals)>1}
    clean_g={k:v for k,v in g_candidates.items() if v not in bad_sid}
    clean_p={k:v for k,v in p_candidates.items() if v not in bad_sid}
    return clean_g,clean_p,{"gsisMapped":len(clean_g),"pfrMapped":len(clean_p),
                            "ambiguousGSIS":sum(len(v)>1 for v in gs.values()),
                            "ambiguousPFR":sum(len(v)>1 for v in pfr.values()),
                            "ambiguousSleeper":len(bad_sid)}


def stats_index(stats: pd.DataFrame,gsis_to_sid: dict[str,str],through: int) -> tuple[dict[tuple[str,int],dict],set[tuple[str,int]]]:
    have(stats,["player_id","season","week","season_type","targets","carries"],"stats")
    s=stats[(pd.to_numeric(stats.season,errors="coerce")==SEASON) &
        (pd.to_numeric(stats.week,errors="coerce").between(1,through)) &
        (stats.season_type.astype(str).str.upper()=="REG")].copy()
    if s.empty: raise ValueError("No hay estadísticas semanales REG de la temporada")
    s["sid"]=s.player_id.map(lambda x:gsis_to_sid.get(gsis_id(x)))
    s=s[s.sid.notna()].copy()
    s["week"]=pd.to_numeric(s.week).astype(int)
    out={}
    for (sid,w),g in s.groupby(["sid","week"]):
        # En semana con trade pueden surgir dos filas; sumar counts, no sumar shares.
        target=pd.to_numeric(g.targets,errors="coerce").sum(min_count=1)
        carry=pd.to_numeric(g.carries,errors="coerce").sum(min_count=1)
        score=(pd.to_numeric(g.fantasy_points_ppr,errors="coerce").sum(min_count=1)
                 if "fantasy_points_ppr" in g.columns else float("nan"))
        target_share=(pd.to_numeric(g.target_share,errors="coerce").iloc[0]
            if "target_share" in g.columns and len(g)==1 else float("nan"))
        def sum_number(col: str) -> float | None:
            if col not in g.columns: return None
            z=pd.to_numeric(g[col],errors="coerce").sum(min_count=1)
            return float(z) if pd.notna(z) else None
        def single_rate(col: str) -> float | None:
            if col not in g.columns or len(g)!=1:return None
            z=pd.to_numeric(g[col],errors="coerce").iloc[0]
            return float(z) if pd.notna(z) else None
        air=sum_number("receiving_air_yards")
        t=nint(target)
        air_share=single_rate("air_yards_share")
        out[(str(sid),int(w))]={"targets":t,
                "carries":nint(carry),"receptions":nint(sum_number("receptions")),
                "ppr":float(score) if pd.notna(score) else None,
                "targetShare":float(target_share) if pd.notna(target_share) else None,
                "receivingAirYards":air,"airYardsShare":air_share,
                "wopr":single_rate("wopr"),
                "aDOT":round(air/t,4) if air is not None and t is not None and t>0 else None}
    return out,set(out)


def build_snap_index(snaps: pd.DataFrame | None,pfr_to_sid: dict[str,str],through:int) -> dict[tuple[str,int],dict]:
    if snaps is None:return {}
    have(snaps,["pfr_player_id","season","week","offense_snaps","offense_pct","game_type"],"snaps")
    s=snaps[(pd.to_numeric(snaps.season,errors="coerce")==SEASON)&
      (pd.to_numeric(snaps.week,errors="coerce").between(1,through))&
      (snaps.game_type.astype(str).str.upper()=="REG")].copy()
    s["sid"]=s.pfr_player_id.map(lambda x:pfr_to_sid.get(str(x).strip()))
    s=s[s.sid.notna()]
    out={}
    for (sid,w),g in s.groupby(["sid","week"]):
        snaps_num=pd.to_numeric(g.offense_snaps,errors="coerce").sum(min_count=1)
        pcts=[clean_rate(x) for x in g.offense_pct]
        pcts=[x for x in pcts if x is not None]
        # Un jugador tradeado no tiene share único sin snap totals por equipo.
        out[(str(sid),int(w))]={"snaps":nint(snaps_num),"snapShare":pcts[0] if len(g)==1 and len(pcts)==1 else None}
    return out


def pbp_index(pbp:pd.DataFrame | None,gsis_to_sid:dict[str,str],through:int):
    """Uso por PBP de jugadas observadas. Nunca mide rutas ni snaps individuales."""
    if pbp is None:return {},{},{}
    cols=["season","season_type","week","game_id","play_id","posteam","rush_attempt","pass_attempt",
          "yardline_100","rusher_player_id","receiver_player_id"]
    have(pbp,cols,"PBP")
    s=pbp[(pd.to_numeric(pbp.season,errors="coerce")==SEASON)&
      (pd.to_numeric(pbp.week,errors="coerce").between(1,through))&
      (pbp.season_type.astype(str).str.upper()=="REG")].copy()
    s["week"]=pd.to_numeric(s.week).astype(int)
    s["play_int"]=pd.to_numeric(s.play_id,errors="coerce").astype("Int64")
    s=s[s.game_id.notna() & s.play_int.notna()].copy()
    # Si un play aparece dos veces, evitar duplicar oportunidades premium.
    # Las filas con el mismo ID pero actores distintos son datos contradictorios,
    # por lo que se invalida el PBP opcional en lugar de elegir un actor arbitrario.
    if s.duplicated(["game_id","play_int"]).any():
        check=s.loc[s.duplicated(["game_id","play_int"],keep=False)]
        for _, part in check.groupby(["game_id","play_int"]):
            for col in ["posteam","rusher_player_id","receiver_player_id","rush_attempt","pass_attempt"]:
                if part[col].fillna("<NULL>").astype(str).nunique()>1:
                    raise ValueError("PBP contradictorio para mismo game_id/play_id")
        s=s.drop_duplicates(["game_id","play_int"]).copy()
    rz=pd.to_numeric(s.yardline_100,errors="coerce")
    s["redzone"]=rz.between(1,20,inclusive="both")
    s["inside5"]=rz.between(1,5,inclusive="both")
    s["rush"]=pd.to_numeric(s.rush_attempt,errors="coerce").eq(1)
    s["pas"]=pd.to_numeric(s.pass_attempt,errors="coerce").eq(1)
    if "qb_kneel" in s.columns:s["rush"] &= ~pd.to_numeric(s.qb_kneel,errors="coerce").eq(1)
    # Team / week PBP presence: no zero if missing team-game coverage.
    teams=set((int(w),str(t)) for w,t in zip(s.week,s.posteam) if pd.notna(t))
    players:dict[tuple[str,int],dict] = {}
    def acc(g,w,key):
        sid=gsis_to_sid.get(gsis_id(g));
        if sid is None:return
        k=(sid,int(w)); rec=players.setdefault(k,{"redzoneCarries":None,"inside5Carries":None,
           "redzoneTargets":None,"inside5Targets":None,"thirdDownTouches":None,
           "twoMinuteTouches":None})
        rec[key]=(rec[key] or 0)+1
    for r in s.loc[s.rush & s.redzone,["rusher_player_id","week","inside5"]].itertuples(index=False):
        acc(r.rusher_player_id,r.week,"redzoneCarries")
        if r.inside5:acc(r.rusher_player_id,r.week,"inside5Carries")
    for r in s.loc[s.pas & s.redzone & s.receiver_player_id.notna(),
                   ["receiver_player_id","week","inside5"]].itertuples(index=False):
        acc(r.receiver_player_id,r.week,"redzoneTargets")
        if r.inside5:acc(r.receiver_player_id,r.week,"inside5Targets")
    # Terceros downs y últimos 120 s de Q2/Q4 como oportunidades observadas,
    # NO participación en snaps, ni rutas, ni cobertura del personal sobre el campo.
    down=pd.to_numeric(s["down"],errors="coerce") if "down" in s.columns else pd.Series(False,index=s.index)
    qtr=pd.to_numeric(s["qtr"],errors="coerce") if "qtr" in s.columns else pd.Series(False,index=s.index)
    sec=pd.to_numeric(s["quarter_seconds_remaining"],errors="coerce") if "quarter_seconds_remaining" in s.columns else pd.Series(float("nan"),index=s.index)
    third=down.eq(3) if "down" in s.columns else pd.Series(False,index=s.index)
    two=qtr.isin([2,4]) & sec.between(0,120) if "qtr" in s.columns and "quarter_seconds_remaining" in s.columns else pd.Series(False,index=s.index)
    for i,r in s.loc[(s.rush| (s.pas & s.receiver_player_id.notna())) & (third|two)].iterrows():
        ident=r.rusher_player_id if r.rush else r.receiver_player_id
        if bool(third.loc[i]):acc(ident,r.week,"thirdDownTouches")
        if bool(two.loc[i]):acc(ident,r.week,"twoMinuteTouches")
    # Team dropbacks: only count verified qb_dropback=1; no inferred routes.
    drops={}
    if "qb_dropback" in s.columns:
        x=s[pd.to_numeric(s.qb_dropback,errors="coerce").eq(1)].groupby(["week","posteam"]).size()
        drops={(int(w),str(t)):int(n) for (w,t),n in x.items()}
    for rec in players.values():
        rec["thirdDownOpportunities"] = rec["thirdDownTouches"]
        rec["twoMinuteOpportunities"] = rec["twoMinuteTouches"]
    return players,teams,{"drops":drops,"pbp":s}


def first_reads(ftn:pd.DataFrame | None,pbp_ctx:dict,gsis_to_sid:dict[str,str],through:int):
    """FTN read_thrown='0' es la primera lectura según el diccionario de origen.

    Cobertura calculada en TODOS los pases dirigidos, no solo los first reads.
    Un receptor con targets chartados y 0 first reads debe conservar el cero.
    Si la cobertura del equipo es <85%, no se afirma ningún cero.
    """
    if ftn is None or not pbp_ctx or "pbp" not in pbp_ctx:return {},{}
    have(ftn,["nflverse_game_id","nflverse_play_id","read_thrown","season","week"],"FTN")
    p=pbp_ctx["pbp"]
    f=ftn[(pd.to_numeric(ftn.season,errors="coerce")==SEASON)&
       (pd.to_numeric(ftn.week,errors="coerce").between(1,through))].copy()
    if "season_type" in f.columns:
        f=f[f.season_type.astype(str).str.upper()=="REG"]
    f["play_int"]=pd.to_numeric(f.nflverse_play_id,errors="coerce").astype("Int64")
    f=f.dropna(subset=["nflverse_game_id","play_int"]).drop_duplicates(["nflverse_game_id","play_int"],keep=False)
    f=f[["nflverse_game_id","play_int","read_thrown"]].rename(columns={"nflverse_game_id":"game_id"})
    q=p.loc[p.pas & p.receiver_player_id.notna(),["week","game_id","play_int","posteam","receiver_player_id"]].copy()
    if q.empty:return {},{}
    m=q.merge(f,on=["game_id","play_int"],how="left",validate="many_to_one")
    codes={"0","1","2","CHK","DES","SD"}
    m["readCode"]=m.read_thrown.astype(str).str.strip().str.upper()
    m["charted"]=m.readCode.isin(codes)
    coverage=m.groupby(["week","posteam"]).charted.mean().to_dict()
    observed=m[m.charted].copy()
    first=observed[observed.readCode=="0"]
    denom=first.groupby(["week","posteam"]).size().to_dict()
    counts=first.groupby(["week","posteam","receiver_player_id"]).size().to_dict()
    out={};team_full={}
    for (w,t),ratio in coverage.items():
        if ratio<.85 or denom.get((w,t),0)<=0:continue
        team_full[(int(w),str(t))]=int(denom[(w,t)])
    # Un receptor tradeado en la misma semana puede pertenecer a dos equipos:
    # sumar numeradores Y denominadores de los equipos que lo dirigieron.
    for (w,t,g),rows in observed.groupby(["week","posteam","receiver_player_id"]):
        if (int(w),str(t)) not in team_full:continue
        sid=gsis_to_sid.get(gsis_id(g))
        if not sid:continue
        n=int(counts.get((w,t,g),0))
        k=(sid,int(w));rec=out.setdefault(k,{"firstReads":0,"firstReadShare":None,"_denom":0})
        rec["firstReads"]+=n
        rec["_denom"]+=team_full[(int(w),str(t))]
    for rec in out.values():
        denominator=rec.pop("_denom")
        rec["firstReadShare"]=rec["firstReads"]/denominator if denominator else None
    return out,team_full


def optional_routes(file: Path | None, through:int) -> dict[tuple[str,int],dict]:
    """Importar SÓLO CSV exportable por contrato; no scraping.
    Columnas: season,week,sleeper_id,routes,team_dropbacks,source,license_ok.
    """
    if not file:return {}
    f=pd.read_csv(file,dtype={"sleeper_id":str})
    have(f,["season","week","sleeper_id","routes","team_dropbacks","source","license_ok"],"Routes")
    if not f.license_ok.astype(str).str.lower().isin(["true","1","yes"]).all():
        raise ValueError("El proveedor no está autorizado explícitamente para automatización")
    out={}
    for r in f.to_dict("records"):
        if int(r["season"])!=SEASON or not 1<=int(r["week"])<=through:continue
        sid=text_id(r["sleeper_id"]); routes=nint(r["routes"]);d=nint(r["team_dropbacks"])
        if not sid or routes is None or d is None or routes>d or d<1:continue
        key=(sid,int(r["week"]))
        if key in out: raise ValueError("Rutas duplicadas para jugador-semana (posible trade ambiguo): "+str(key))
        out[key]={"routes":routes,"teamDropbacks":d,"routeParticipation":routes/d,
                  "sourceRoutes":str(r["source"])}
    return out


def make_feed(cross:pd.DataFrame,stats:pd.DataFrame,snaps:pd.DataFrame|None,
              pbp:pd.DataFrame|None,ftn:pd.DataFrame|None,inj:pd.DataFrame|None,
              through:int,routes:pd.DataFrame|None=None) -> dict:
    g,p,ids=load_identity(cross)
    box,players=stats_index(stats,g,through)
    # Cada fuente OPCIONAL se analiza separadamente. Un cambio de esquema en FTN,
    # PFR o PBP jamás debe impedir que el feed básico se publique.
    errors={}
    def optional(label,fun,default):
        try:return fun()
        except Exception as exc:
            errors[label]=f"{type(exc).__name__}: {exc}"
            print(f"FUENTE OPCIONAL {label} FALLÓ: {errors[label]}")
            return default
    snaps_idx=optional("snaps",lambda:build_snap_index(snaps,p,through),{})
    usage,team_coverage,ctx=optional("pbp",lambda:pbp_index(pbp,g,through),({},{},{}))
    ftn_idx,team_first=optional("ftn",lambda:first_reads(ftn,ctx,g,through),({},{}))
    route_idx={}
    if routes is not None:
        # Tests can supply route DataFrame through an in-memory adapter.
        for r in routes.to_dict("records"):
            sid=text_id(r.get("sleeper_id"));w=nint(r.get("week"));rv=nint(r.get("routes"));dv=nint(r.get("team_dropbacks"))
            if int(r.get("season",SEASON))!=SEASON or w is None or w>through:continue
            if str(r.get("license_ok","")).lower() not in ("true","1","yes"):
                raise ValueError("Routes without license_ok=true")
            if sid and dv and rv is not None:
                if rv>dv or rv<0 or dv<1:
                    raise ValueError("Rutas no pueden superar team_dropbacks: "+str((sid,w)))
                if (sid,w) in route_idx:
                    raise ValueError("Rutas duplicadas: "+str((sid,w)))
                route_idx[(sid,w)]={"routes":rv,"teamDropbacks":dv,
                                  "routeParticipation":rv/dv,"sourceRoutes":str(r.get("source",""))}
    keys=set(box)|set(snaps_idx)|set(usage)|set(ftn_idx)|set(route_idx)
    by={}
    for sid,w in sorted(keys,key=lambda k:(int(k[0]),k[1])):
        base={"week":w,"snaps":None,"snapShare":None,"teamSnaps":None,"routes":None,
              "targets":None,"carries":None,"receptions":None,"ppr":None,"targetShare":None,
              "receivingAirYards":None,"airYardsShare":None,"wopr":None,"aDOT":None,
              "teamDropbacks":None,"routeParticipation":None,"targetsPerRoute":None,
              "redzoneCarries":None,"inside5Carries":None,"redzoneTargets":None,
              "inside5Targets":None,"firstReads":None,"firstReadShare":None,
              "thirdDownTouches":None,"twoMinuteTouches":None,
              "thirdDownOpportunities":None,"twoMinuteOpportunities":None}
        for source in (box,snaps_idx,usage,ftn_idx,route_idx):
            base.update(source.get((sid,w),{}))
        # Source coverage: zero is meaningful only when team has charted plays and player appeared.
        if (sid,w) in players and ctx.get("pbp") is not None:
            # A precise player-team join is unavailable in box summary after trades;
            # do not synthesize red-zone zero when player not involved in PBP.
            pass
        if base["routes"] is not None and box.get((sid,w),{}).get("targets") is not None and base["routes"]>0:
            base["targetsPerRoute"]=round(box[(sid,w)]["targets"]/base["routes"],5)
        by.setdefault(sid,[]).append(base)
    if len(by)<100:raise ValueError("Cobertura insuficiente de mapeo GSIS/Sleeper (<100)")
    if not any(w==through for _,w in box):raise ValueError(f"Semana {through} no disponible en stats")
    for sid,weekly in by.items():
        for row in weekly:
            if row['targets'] is not None and row['targets']<0:raise ValueError('Targets negativos: '+sid)
            if row['carries'] is not None and row['carries']<0:raise ValueError('Carries negativos: '+sid)
            if row['routes'] is not None and row['targets'] is not None and row['routes']>0 and row['targets']>row['routes']:
                # Se observan más targets que rutas, normalmente fuente incompleta o
                # definiciones distintas: conservar el conteo, NO publicar TPRR.
                row['targetsPerRoute']=None
    injuries_by={}
    def build_injury():
        out={}
        if inj is None:return out
        req=["season","week","gsis_id","report_status","practice_status"]
        have(inj,req,"Injuries")
        # nflverse puede modificar el nombre de la fecha entre releases.
        # Sin fecha verificada publicamos registros como parciales, no como noticias frescas.
        date_column=next((name for name in
                          ("date_modified","report_date","practice_date","date")
                          if name in inj.columns),None)
        injury_rows=inj[(pd.to_numeric(inj.season,errors="coerce")==SEASON)&
           (pd.to_numeric(inj.week,errors="coerce").between(1,through+1))].copy()
        injury_rows["sid"]=injury_rows.gsis_id.map(lambda v:g.get(gsis_id(v)))
        sort_cols=["sid","week"]+([date_column] if date_column else [])
        injury_rows=injury_rows[injury_rows.sid.notna()].sort_values(sort_cols,kind="mergesort")
        for sid,part in injury_rows.groupby("sid"):
            rows=[]
            for r in part.tail(8).to_dict("records"):
                raw_date=r.get(date_column) if date_column else None
                valid_date=(str(raw_date) if raw_date is not None and pd.notna(raw_date) else None)
                rows.append({"week":nint(r.get("week")),"dateModified":valid_date,
                    "practiceStatus":str(r.get("practice_status") or ""),
                    "reportStatus":str(r.get("report_status") or ""),
                    "primaryInjury":str(r.get("report_primary_injury") or ""),
                    "dateVerified":bool(valid_date)})
            out[str(sid)]=rows
        return out
    injuries_by=optional("injuries",build_injury,{})
    injury_has_dates=bool(inj is not None and any(x in inj.columns for x in
                       ("date_modified","report_date","practice_date","date")))
    # Una fuente que aporta algunos partidos no implica cobertura de TODA la temporada.
    box_weeks={w for _,w in box}
    snap_weeks={w for _,w in snaps_idx}
    pbp_weeks=set(ctx['pbp']['week'].astype(int).unique()) if ctx and 'pbp' in ctx else set()
    src={"snaps":("PARCIAL; semanas "+','.join(map(str,sorted(snap_weeks))) if snaps_idx else "NO DISPONIBLE"),
         "pbp":("PARCIAL; semanas "+','.join(map(str,sorted(pbp_weeks))) if pbp_weeks else "NO DISPONIBLE"),
         "ftn":"PARCIAL (por cobertura del partido)" if ftn_idx else "NO DISPONIBLE",
         "routes":"AUTORIZADO" if route_idx else "NO DISPONIBLE: proveedor con permiso requerido",
         "injuries":("DISPONIBLE" if injury_has_dates else
                     "PARCIAL: sin fecha de publicación verificable")
                     if injuries_by and "injuries" not in errors else "NO DISPONIBLE"}
    src.update({k:"ERROR: "+v for k,v in errors.items()})
    coverage={"boxWeeks":sorted(box_weeks),"snapWeeks":sorted(snap_weeks),
              "pbpWeeks":sorted(pbp_weeks),"ftnMappedPlayerWeeks":len(ftn_idx),
              "routePlayerWeeks":len(route_idx)}
    return {"schemaVersion":5,"season":SEASON,"generatedAt":datetime.now(timezone.utc).isoformat(),
            "fromWeek":1,"thruWeek":through,"mappedPlayers":len(by),
            "sources":src,"coverage":coverage,"identity":ids,"attribution":ATTRIBUTIONS,
            "metricDefinitions":METRIC_DEFINITIONS,
            "sourceUrls":SOURCES,
            "bySleeper":by,"injuriesBySleeper":injuries_by}


def main() -> None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--current-week",type=int,default=None,help="NFL semana actual; se incluyen sólo semanas anteriores")
    ap.add_argument("--output",default="_MONEYBALL_FEED_2026.json")
    ap.add_argument("--cache-dir",default=".mb5-cache")
    ap.add_argument("--routes-csv",default="",help="CSV opcional con permiso de exportación/automatización")
    a=ap.parse_args()
    if a.current_week is None:
        r=requests.get(SOURCES["state"],timeout=20,headers={"User-Agent":"MoneyballGM-Personal/5.0"});r.raise_for_status()
        state=r.json();week=int(state.get("week") or state.get("leg"))
    else:week=a.current_week
    if not 2<=week<=19:raise ValueError("Semana NFL inválida (requiere al menos una semana completa)")
    through=min(18,week-1)
    cache=Path(a.cache_dir)
    cross=load_source("crosswalk",cache)
    stats=load_source("stats",cache)
    snaps=load_source("snaps",cache,optional=True)
    pbp=load_source("pbp",cache,optional=True)
    ftn=load_source("ftn",cache,optional=True)
    inj=load_source("injury",cache,optional=True)
    route=None
    if a.routes_csv:
        route_file=Path(a.routes_csv)
        if not route_file.is_file(): raise FileNotFoundError(route_file)
        route=pd.read_csv(route_file,dtype={"sleeper_id":str})
    feed=make_feed(cross,stats,snaps,pbp,ftn,inj,through,route)
    target=Path(a.output);target.parent.mkdir(parents=True,exist_ok=True)
    tmp=target.with_suffix(target.suffix+".tmp")
    # pandas/numpy producen np.int64 (por ejemplo en coverage.pbpWeeks), que
    # json.dumps estándar no sabe codificar. Conservar nulos; no cambiar datos.
    feed=json_native(feed)
    # Quality gate 6.0: los errores estructurales impiden reemplazar el último
    # feed válido. La falta de datos opcionales se reporta, no se inventa.
    from moneyball6_validate import audit
    quality = audit(feed)
    if quality["errors"]:
        raise RuntimeError("MONEYBALL6_QUALITY_FAIL " + json.dumps(
            quality["errors"], ensure_ascii=False))
    print("MONEYBALL6_QUALITY", json.dumps(
        {"status": quality["status"], "warnings": quality["warnings"],
         "metrics": quality["metrics"]}, ensure_ascii=False))
    tmp.write_text(json.dumps(feed,ensure_ascii=False,separators=(",",":"),allow_nan=False),encoding="utf-8")
    tmp.replace(target)
    # Publicar versión gzip adicional: GitHub Raw y Apps Script leen el archivo
    # comprimido para no superar cuotas cuando crezca el histórico de temporada.
    gz=Path(str(target)+".gz")
    gz_tmp=Path(str(gz)+".tmp")
    with gzip.open(gz_tmp,"wb",compresslevel=6) as f:
        f.write(target.read_bytes())
    gz_tmp.replace(gz)
    print("MONEYBALL5_FEED_GZIP",gz,"bytes",gz.stat().st_size)
    print("MONEYBALL5_FEED_OK",target,"jugadores",feed["mappedPlayers"],"hasta semana",through)
    print("Fuentes:",json.dumps(feed["sources"],ensure_ascii=False))

if __name__=="__main__":main()
