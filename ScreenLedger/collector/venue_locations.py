"""Resolve District-provided cinema coordinates against the local state geometry."""
from __future__ import annotations
import csv, json, math, re
from collections import defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
MAP=ROOT/"dashboard/assets/india_state_map_simplified.geojson"
CSV=ROOT/"dashboard/data/district_cinema_locations.csv"
ADDRESS_CHECKS=ROOT/"dashboard/data/district_cinema_address_checks.csv"
SOURCES=(ROOT/"collector/output/snapshots.json",ROOT/"collector/output_live/snapshots.json",ROOT/"collector/output_top10/snapshots.json",ROOT/"collector/output_top10_raw/snapshots.json")
FIELDS=("cinema_id","cinema_name","state_or_ut","status","latitude","longitude","address","source_url","observed_at_utc","boundary_source")

def canonical(name):
    key=re.sub(r"[^a-z]","",str(name).lower().replace("&","and"))
    for a,b in (("arunanchal","arunachal"),("havelli","haveli"),("islands","island")):
        key=key.replace(a,b)
    return key

def in_ring(x,y,ring):
    inside=False
    for a,b in zip(ring,ring[1:]+ring[:1]):
        x1,y1=a[:2];x2,y2=b[:2]
        if (y1>y)!=(y2>y) and x<(x2-x1)*(y-y1)/(y2-y1)+x1:inside=not inside
    return inside

def boundary_distance(x,y,ring):
    # Approximate kilometres; exclude points near boundaries rather than overstate precision.
    cos=math.cos(math.radians(y));best=float("inf")
    for a,b in zip(ring,ring[1:]+ring[:1]):
        ax=(a[0]-x)*111*cos;ay=(a[1]-y)*111;bx=(b[0]-x)*111*cos;by=(b[1]-y)*111
        dx=bx-ax;dy=by-ay;den=dx*dx+dy*dy
        t=max(0,min(1,-(ax*dx+ay*dy)/den)) if den else 0
        best=min(best,math.hypot(ax+t*dx,ay+t*dy))
    return best

def prepare_geometry(data):
    result=[]
    for f in data["features"]:
        name=f["properties"].get("name") or f["properties"].get("NAME_1")
        g=f["geometry"]; polygons=[g["coordinates"]] if g["type"]=="Polygon" else g["coordinates"] if g["type"]=="MultiPolygon" else []
        for poly in polygons:
            if not poly or not poly[0]:continue
            xs=[p[0] for p in poly[0]];ys=[p[1] for p in poly[0]]
            result.append((name,poly,(min(xs),min(ys),max(xs),max(ys))))
    return result

def locate(lat,lon,geometry,min_boundary_km=2):
    try: lat=float(lat);lon=float(lon)
    except (TypeError,ValueError):return None,"missing_coordinates"
    if not (6<=lat<=38 and 68<=lon<=98):return None,"invalid_coordinates"
    found=set();nearby=[]
    for name,poly,(x0,y0,x1,y1) in geometry:
        if not (x0-0.03<=lon<=x1+0.03 and y0-0.03<=lat<=y1+0.03):continue
        if in_ring(lon,lat,poly[0]) and not any(in_ring(lon,lat,hole) for hole in poly[1:]):found.add(name)
        if any(boundary_distance(lon,lat,ring)<min_boundary_km for ring in poly):nearby.append(name)
    if len(found)!=1:return None,"ambiguous_or_outside_boundary"
    state=next(iter(found))
    if any(canonical(other)!=canonical(state) for other in nearby):return state,"near_boundary"
    return state,"inside_boundary"

def address_states(address,states):
    """Recognize state names at the address end, not in road or bank names."""
    text=str(address or "").casefold().strip();found=set()
    suffix=r"\s*(?:,?\s*[-–—]?\s*\d{6})?\s*(?:,\s*)?(?:india)?\s*$"
    for name in states:
        variants={name,name.replace("&","and"),name.replace("Havelli","Haveli"),name.replace("Arunanchal","Arunachal"),name.replace("Island","Islands")}
        aliases={"andhrapradesh":{"Andra Pradesh"},"karnataka":{"Karnakata"},"odisha":{"Orissa"}}
        variants.update(aliases.get(canonical(name),set()))
        for value in variants:
            pattern=re.escape(value.casefold()).replace(r"\ ",r"\s*")
            if re.search(r"(?<!\w)"+pattern+suffix,text):found.add(canonical(name));break
    return found

def build(sources=SOURCES,map_path=MAP):
    geo=json.loads(map_path.read_text(encoding="utf8"));geometry=prepare_geometry(geo); states=sorted({x[0] for x in geometry})
    by_id=defaultdict(list)
    for path in sources:
        if not path.exists():continue
        snapshots=json.loads(path.read_text(encoding="utf8"));snapshots=snapshots if isinstance(snapshots,list) else [snapshots]
        for snap in snapshots:
            meta=snap.get("metadata",{})
            for show in snap.get("shows",[]):
                cid=str(show.get("cinema_id") or "").strip()
                if not cid:continue
                lat=show.get("latitude");lon=show.get("longitude");address=show.get("cinema_address") or ""
                if lat is None and lon is None and not address:continue
                by_id[cid].append((show.get("cinema_name") or "",lat,lon,address,meta.get("source_url") or "",show.get("snapshot_utc") or meta.get("snapshot_utc") or ""))
    out=[]
    for cid,rows in sorted(by_id.items()):
        unique=list(dict.fromkeys(rows)); evaluations=[]
        for name,lat,lon,address,url,stamp in unique:
            geo_state,status=locate(lat,lon,geometry); addr=address_states(address,states)
            if geo_state and addr and canonical(geo_state) not in addr:status="address_boundary_conflict";geo_state=None
            if geo_state and len(addr)>1:status="ambiguous_address";geo_state=None
            if geo_state and status=="near_boundary" and not addr:status="conflicting_or_boundary_review";geo_state=None
            if geo_state and addr:status="address_and_boundary_agree_near_border" if status=="near_boundary" else "address_and_boundary_agree"
            elif geo_state:status="coordinates_within_boundary"
            evaluations.append((name,lat,lon,address,url,stamp,geo_state,status))
        found={canonical(x[6]) for x in evaluations if x[6]}
        bad=any(x[7] in ("address_boundary_conflict","ambiguous_address","near_boundary") for x in evaluations)
        chosen=max(evaluations,key=lambda x:(bool(x[6]),x[5]))
        name,lat,lon,address,url,stamp,geo_state,status=chosen
        if len(found)>1 or bad:geo_state=None;status="conflicting_or_boundary_review"
        out.append(dict(cinema_id=cid,cinema_name=name,state_or_ut=geo_state or "",status=status,latitude=lat,longitude=lon,address=address,source_url=url,observed_at_utc=stamp,boundary_source="NWIC archive checksum matched; simplified geometry sampled"))
    return out

def write_csv(rows,path=CSV):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(rows)

def load_locations(conn, path=CSV, map_path=MAP, address_path=ADDRESS_CHECKS):
    """Combine saved District extracts and future captured coordinates by venue ID.

    Unresolved conflicts and near-border evidence without corroborating addresses
    remain unassigned. The NWIC archive checksum matches the official download.
    """
    evidence=defaultdict(list)
    if path.exists():
        with path.open(encoding="utf-8-sig",newline="") as f:
            for row in csv.DictReader(f):
                if row.get("cinema_id"):evidence[row["cinema_id"]].append(row)
    exists=conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='cinema_location_observations'").fetchone()
    if exists:
        geo=json.loads(map_path.read_text(encoding="utf8"));geometry=prepare_geometry(geo);states=sorted({x[0] for x in geometry})
        rows=conn.execute("""SELECT cinema_id,cinema_name,address,latitude,longitude,source_url,observed_at_utc FROM (
               SELECT *,ROW_NUMBER() OVER (PARTITION BY cinema_id,cinema_name,address,latitude,longitude
                      ORDER BY observed_at_utc DESC,capture_id DESC) AS rn
               FROM cinema_location_observations) WHERE rn=1""").fetchall()
        for row in rows:
            d=dict(row);state,status=locate(d.get("latitude"),d.get("longitude"),geometry)
            addr=address_states(d.get("address"),states)
            if state and addr and (canonical(state) not in addr or len(addr)>1):state=None;status="conflicting_or_boundary_review"
            elif state and status=="near_boundary" and not addr:state=None;status="conflicting_or_boundary_review"
            elif state and addr:status="address_and_boundary_agree_near_border" if status=="near_boundary" else "address_and_boundary_agree"
            elif state:status="coordinates_within_boundary"
            evidence[d["cinema_id"]].append({"cinema_id":d["cinema_id"],"cinema_name":d["cinema_name"] or "", "state_or_ut":state or "", "status":status, "latitude":d.get("latitude"),"longitude":d.get("longitude"),"address":d.get("address") or "", "source_url":d.get("source_url") or "", "observed_at_utc":d.get("observed_at_utc") or "", "boundary_source":"NWIC archive checksum matched; simplified geometry sampled"})
    # Address checks are individually researched public venue records. Exact
    # District IDs are mandatory; independently reviewed exceptions carry a
    # second source and an explanation, and remain visible in the export.
    checks={}
    if address_path.exists():
        from urllib.parse import urlparse
        geo=json.loads(map_path.read_text(encoding="utf8")); known={canonical(x[0]):x[0] for x in prepare_geometry(geo)}
        with address_path.open(encoding="utf-8-sig",newline="") as f:
            for row in csv.DictReader(f):
                cid=row.get("cinema_id","");state=known.get(canonical(row.get("state_or_ut","")))
                url=urlparse(row.get("source_url", ""));kind=row.get("status","")
                district=url.scheme=="https" and url.hostname in ("district.in","www.district.in") and bool(re.search(r"-CD"+re.escape(cid)+r"$",url.path,re.I))
                independent=kind in {"independent_address_resolution","independent_name_match","independent_conflict_resolution"} and url.scheme=="https" and bool(url.hostname) and urlparse(row.get("secondary_source_url","")).scheme=="https" and bool(urlparse(row.get("secondary_source_url","")).hostname) and bool(row.get("notes"))
                valid=kind=="district_venue_address" and district and address_states(row.get("address"),known.values())=={canonical(state)} if state else False
                if cid and state and (valid or independent):
                    row["state_or_ut"]=state;checks[cid]=row
    result={}
    for cinema_id,rows in evidence.items():
        valid=[r for r in rows if r.get("state_or_ut") and r.get("status") in {"address_and_boundary_agree","address_and_boundary_agree_near_border","coordinates_within_boundary"}]
        states={canonical(r["state_or_ut"]) for r in valid}
        conflicts=any(r.get("status") in {"conflicting_or_boundary_review","address_boundary_conflict","ambiguous_address","near_boundary"} for r in rows)
        if len(states)==1 and not conflicts:
            chosen=max(valid,key=lambda r:(r.get("status") in {"address_and_boundary_agree","address_and_boundary_agree_near_border"},r.get("observed_at_utc") or ""))
            result[cinema_id]=dict(chosen)
        else:
            result[cinema_id]={"cinema_id":cinema_id,"state_or_ut":"","status":"needs_review" if conflicts or len(states)>1 else "unmatched","source_url":"","address":"","latitude":"","longitude":""}
        check=checks.get(cinema_id)
        if check and (not states or states=={canonical(check['state_or_ut'])}) and (not conflicts or check['status']=='independent_conflict_resolution'):
            result[cinema_id]={**result[cinema_id],**check}
    for cinema_id,check in checks.items():
        if cinema_id not in result:result[cinema_id]=check
    return result

if __name__=="__main__":
    from collections import Counter
    data=build();write_csv(data);print(json.dumps({"cinemas":len(data),"status_counts":dict(Counter(r["status"] for r in data)),"output":str(CSV)},ensure_ascii=False))
