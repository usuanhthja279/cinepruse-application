#!/usr/bin/env python3
"""Check a local NWIC archive against a separately downloaded official ZIP and sample the simplified geometry."""
import argparse,hashlib,json,math,zipfile
from pathlib import Path
from fetch_and_embed_soi_map import walk_points

ROOT=Path(__file__).resolve().parent

def sha(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):h.update(chunk)
    return h.hexdigest()

def verify(local,official,simplified):
    local_hash=sha(local);official_hash=sha(official)
    if local_hash!=official_hash:raise ValueError("Local archive does not match the downloaded official archive")
    with zipfile.ZipFile(local) as z:
        source=json.loads(z.read("state_NWIC.GeoJSON"))
    if "7755" not in str(source.get("crs",{})):raise ValueError("Unexpected source CRS")
    simple=json.loads(simplified.read_text(encoding="utf8"))
    source_by_code={f["properties"]["state"]:f for f in source["features"]}
    a=6378137.0;f=1/298.257223563;e=math.sqrt(2*f-f*f)
    p0,p1,p2=map(math.radians,(24,12.472955,35.1728044444444));l0=math.radians(80)
    def m(p):return math.cos(p)/math.sqrt(1-e*e*math.sin(p)**2)
    def t(p):return math.tan(math.pi/4-p/2)/((1-e*math.sin(p))/(1+e*math.sin(p)))**(e/2)
    n=math.log(m(p1)/m(p2))/math.log(t(p1)/t(p2));F=m(p1)/(n*t(p1)**n);rho0=a*F*t(p0)**n
    def project(lon,lat):
        p=math.radians(lat);theta=n*(math.radians(lon)-l0);rho=a*F*t(p)**n
        return 4_000_000+rho*math.sin(theta),4_000_000+rho0-rho*math.cos(theta)
    results=[]
    for feature in simple["features"]:
        code=feature["properties"]["state_code"]
        if code not in source_by_code:raise ValueError(f"Missing source state code: {code}")
        raw=source_by_code[code];grid={(round(x/100),round(y/100)) for x,y in walk_points(raw["geometry"]["coordinates"])}
        pts=list(walk_points(feature["geometry"]["coordinates"]));step=max(1,len(pts)//100);sample=pts[::step][:100];matched=0
        for lon,lat in sample:
            x,y=project(lon,lat);gx,gy=round(x/100),round(y/100)
            matched+=any((gx+i,gy+j) in grid for i in (-1,0,1) for j in (-1,0,1))
        results.append({"state_code":code,"sampled":len(sample),"matched":matched})
    if len(results)!=36 or any(x["matched"]!=x["sampled"] for x in results):raise ValueError("Simplified geometry sample does not fully match source within grid tolerance")
    return {"local_archive_sha256":local_hash,"official_archive_sha256":official_hash,"archive_match":True,
            "feature_count":len(results),"sampled_points":sum(x["sampled"] for x in results),"matching_points":sum(x["matched"] for x in results),
            "sampling_method":"At most 100 evenly spaced simplified vertices per state; projected to EPSG:7755 and compared to official vertices in adjacent 100 metre grid cells.",
            "limitation":"Sampling does not prove every boundary vertex or replace a human visual comparison with the official political map.","states":results}

def main():
    p=argparse.ArgumentParser();p.add_argument("--official-archive",type=Path,required=True);p.add_argument("--local-archive",type=Path,default=ROOT/"state_nwic_geojson.zip");p.add_argument("--simplified",type=Path,default=ROOT/"assets/india_state_map_simplified.geojson");p.add_argument("--output",type=Path);a=p.parse_args();result=verify(a.local_archive,a.official_archive,a.simplified);text=json.dumps(result,indent=2,ensure_ascii=False)
    if a.output:a.output.write_text(text+"\n",encoding="utf8")
    print(text)
if __name__=="__main__":main()
