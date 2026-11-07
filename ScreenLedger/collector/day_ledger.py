"""As-of day ledger and source-backed cinema geography."""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timezone
from venue_locations import load_locations

def day_ledger(conn, day, movie_id):
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
    locations=load_locations(conn)
    names_by_cinema=defaultdict(set)
    for r in rows:
        d=dict(r); key=(d["cinema_id"] or "").strip() or "name:"+(d["cinema_name"] or "")
        names_by_cinema[key].add(d["cinema_name"] or "")
    mappings={};mapping_report=[]
    for key,names in names_by_cinema.items():
        loc=locations.get(key,{})
        state=loc.get("state_or_ut") or None
        mappings[key]=state
        mapping_report.append({"cinema_id":key,"cinema_names":" | ".join(sorted(names)),
            "state_or_ut":state or "", "candidate_states":"", "matched_city_names":"",
            "status":loc.get("status","unmatched"),
            "source":"District venue coordinates or researched venue address" if state else "No sufficiently reliable cinema location",
            "source_url":loc.get("source_url",""),"address":loc.get("address",""),
            "secondary_source_url":loc.get("secondary_source_url",""),"notes":loc.get("notes",""),
            "latitude":loc.get("latitude",""),"longitude":loc.get("longitude",""),
            "observed_at_utc":loc.get("observed_at_utc","")})
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
            "mapping_method":"District-provided cinema coordinates compared to project-supplied state geometry, with address cross-check when available; near-boundary and conflicting locations excluded",
            "mapped_cinemas":sum(v is not None for v in mappings.values()),"unmapped_cinemas":sum(v is None for v in mappings.values()),
            "cinema_mapping":sorted(mapping_report,key=lambda x:(x["status"],x["cinema_names"])),
            "first_observation_utc":oldest,"last_observation_utc":newest,"missing_revenue_sessions":missing_amount,
            "missing_inventory_sessions":missing_inventory,"started_sessions_without_5min_capture":stale_pre_show,
            "complete_day_verified":False}
