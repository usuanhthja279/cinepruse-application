"""As-of day ledger and transparent, name-based cinema geography candidates."""
from __future__ import annotations
import csv
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

MAPPING_PATH = Path(__file__).resolve().parents[1] / "dashboard/data/city_state_mapping_2026-11-07.csv"
ALLOWED = {"matched_exact_2011_town_name", "matched_exact_2011_settlement_name", "matched_curated_city_state"}

def city_candidates(path=MAPPING_PATH):
    candidates = defaultdict(set)
    unresolved = set()
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            name = row["display_label"].strip().casefold()
            state = row["state_or_ut"].strip()
            if name and len(name) >= 4:
                if state and row["mapping_status"] in ALLOWED:
                    candidates[name].add(state)
                else:
                    unresolved.add(name)
    return {name: next(iter(states)) for name, states in candidates.items() if len(states) == 1 and name not in unresolved}

def cinema_state_candidates(name, candidates, pattern=None):
    if not candidates:
        return set()
    text = (name or "").casefold()
    pattern = pattern or re.compile(r"(?<![\w])(?:" + "|".join(re.escape(c) for c in sorted(candidates, key=len, reverse=True)) + r")(?![\w])")
    return {candidates[match.group()] for match in pattern.finditer(text)}

def cinema_state(name, candidates, pattern=None):
    # A venue label is not proof of physical location. Expose this as a candidate.
    found = cinema_state_candidates(name, candidates, pattern)
    return next(iter(found)) if len(found) == 1 else None

def day_ledger(conn, day, movie_id, mapping_path=MAPPING_PATH):
    now = datetime.now(timezone.utc).isoformat()
    rows = conn.execute("""WITH ranked AS (
        SELECT o.session_key,o.show_datetime_ist,o.cinema_id,o.cinema_name,
               o.total_seats,o.available_seats,o.unavailable_seats,
               o.estimated_gross_inr,o.pricing_complete,c.observed_at_utc,
               ROW_NUMBER() OVER (PARTITION BY o.session_key
                   ORDER BY c.observed_at_utc DESC,c.id DESC) AS rn
        FROM observations o JOIN captures c ON c.id=o.capture_id
        WHERE o.movie_id=? AND c.movie_id=? AND c.status='ok'
          AND substr(o.show_datetime_ist,1,10)=?
          AND (c.service_date_ist=? OR c.service_date_ist IS NULL)
          AND datetime(c.observed_at_utc)<=datetime(?)
          AND datetime(c.observed_at_utc)<=datetime(o.show_datetime_ist)
    ) SELECT * FROM ranked WHERE rn=1""", (movie_id,movie_id,day.isoformat(),day.isoformat(),now)).fetchall()
    candidates=city_candidates(mapping_path)
    pattern = re.compile(r"(?<![\w])(?:" + "|".join(re.escape(c) for c in sorted(candidates, key=len, reverse=True)) + r")(?![\w])") if candidates else None
    # Multiple names for the same cinema must agree; never allocate a conflict.
    names_by_cinema=defaultdict(set)
    for r in rows:
        d=dict(r); key=(d["cinema_id"] or "").strip() or "name:"+(d["cinema_name"] or "")
        names_by_cinema[key].add(d["cinema_name"] or "")
    mappings={}; mapping_report=[]
    for key,names in names_by_cinema.items():
        possible=set().union(*(cinema_state_candidates(name,candidates,pattern) for name in names))
        mappings[key]=next(iter(possible)) if len(possible)==1 else None
        matched=sorted({m.group() for name in names for m in pattern.finditer(name.casefold())}) if pattern else []
        mapping_report.append({"cinema_id":key,"cinema_names":" | ".join(sorted(names)),
                               "state_or_ut":mappings[key] or "", "candidate_states":" | ".join(sorted(possible)),
                               "matched_city_names":" | ".join(matched),
                               "status":"inferred" if len(possible)==1 else ("ambiguous" if possible else "unmatched"),
                               "source":"venue name and Census-derived District city selector mapping"})
    totals={"unique_sessions":0,"total_seats":0,"available_seats":0,"booked_plus_blocked_seats":0,"confirmed_revenue_inr":0.0,"pricing_incomplete_sessions":0}
    states=defaultdict(lambda:{"unique_sessions":0,"booked_plus_blocked_seats":0,"confirmed_revenue_inr":0.0,"pricing_incomplete_sessions":0,"cinemas":set()})
    unresolved={"unique_sessions":0,"booked_plus_blocked_seats":0,"confirmed_revenue_inr":0.0,"pricing_incomplete_sessions":0,"cinemas":set()}
    oldest=None; newest=None; missing_amount=0; missing_inventory=0; stale_pre_show=0
    for r in rows:
        d=dict(r); name=d["cinema_name"] or ""; key=(d["cinema_id"] or "").strip() or "name:"+name
        group=states[mappings[key]] if mappings[key] else unresolved
        revenue=d["estimated_gross_inr"]
        incomplete=not bool(d["pricing_complete"]) or revenue is None
        totals["unique_sessions"]+=1
        for field in ("total_seats","available_seats"):
            totals[field]+=d[field] or 0
        if d["unavailable_seats"] is None: missing_inventory+=1
        tickets=d["unavailable_seats"] or 0
        totals["booked_plus_blocked_seats"]+=tickets
        totals["confirmed_revenue_inr"]+=revenue or 0
        totals["pricing_incomplete_sessions"]+=int(incomplete)
        group["unique_sessions"]+=1;group["booked_plus_blocked_seats"]+=tickets
        group["confirmed_revenue_inr"]+=revenue or 0;group["pricing_incomplete_sessions"]+=int(incomplete);group["cinemas"].add(key)
        if revenue is None: missing_amount+=1
        t=d["observed_at_utc"]
        try:
            observed=datetime.fromisoformat(t); starts=datetime.fromisoformat(d["show_datetime_ist"])
            if starts<=datetime.now(timezone.utc) and (starts-observed).total_seconds()>300: stale_pre_show+=1
        except (TypeError,ValueError):
            pass
        oldest=min(oldest,t) if oldest else t; newest=max(newest,t) if newest else t
    def export(item):
        return {**item,"cinemas":len(item["cinemas"])}
    return {"service_date":day.isoformat(),"as_of_utc":now,"basis":"latest observed before show start per session across all successful captures",
            "totals":totals,"states":{name:export(item) for name,item in states.items()},"unresolved":export(unresolved),
            "mapping_method":"candidate only: uniquely state-mapped city name appears in cinema name",
            "mapped_cinemas":sum(v is not None for v in mappings.values()),"unmapped_cinemas":sum(v is None for v in mappings.values()),
            "cinema_mapping":sorted(mapping_report,key=lambda x:(x["status"],x["cinema_names"])),
            "first_observation_utc":oldest,"last_observation_utc":newest,"missing_revenue_sessions":missing_amount,
            "missing_inventory_sessions":missing_inventory,"started_sessions_without_5min_capture":stale_pre_show,
            "complete_day_verified":False}
