#!/usr/bin/env python3
"""Download Government of India/NWIC Survey of India state GeoJSON; validate; embed.

Usage:
  python fetch_and_embed_soi_map.py
  python fetch_and_embed_soi_map.py --archive state_nwic_geojson.zip

All geometries originate from the supplied government archive; no replacement polygons.
Requires only Python 3.10+ standard library and an internet connection for auto download.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request
import zipfile

SOURCE = "https://nwdp.nwic.gov.in/dataset/dd960900-34cc-4486-a95c-83200d2f2c7b/resource/f039e721-132c-4a24-9e5e-07af03064b4d/download/state_nwic_geojson.zip"
DATASET_PAGE = "https://nwdp.nwic.gov.in/dataset/state-boundary"
SOI_REFERENCE = "https://surveyofindia.gov.in/pages/political-map-of-india"
ARCHIVE = "state_nwic_geojson_original.zip"
OUTPUT = "index.html"
EXPECTED = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal", "Andaman and Nicobar Islands", "Chandigarh", "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Jammu and Kashmir", "Ladakh", "Lakshadweep", "Puducherry"
]
PREFIX = "<!-- BEGIN VALIDATED SOI GEOMETRY (not automatically cartographically approved) -->"
SUFFIX = "<!-- END VALIDATED SOI GEOMETRY -->"
NORMALIZED = {re.sub(r"[^a-z0-9]", "", n.lower()): n for n in EXPECTED}
ALIASES = {
    "an": "Andaman and Nicobar Islands", "ar": "Arunachal Pradesh",
    "dh": "Dadra and Nagar Haveli and Daman and Diu",
    "jammukashmir": "Jammu and Kashmir",
    "jammukashmirut": "Jammu and Kashmir",
    "jammuandkashmirut": "Jammu and Kashmir",
    "theunionterritoryofjammuandkashmir": "Jammu and Kashmir",
    "nctdelhi": "Delhi", "delhinct": "Delhi", "newdelhi": "Delhi", "nationalcapitalterritoryofdelhi": "Delhi",
    "orissa": "Odisha", "uttaranchal": "Uttarakhand", "pondicherry": "Puducherry",
    "andamannicobarislands": "Andaman and Nicobar Islands",
    "andamanandnicobar": "Andaman and Nicobar Islands",
    "andamanandnicobarisland": "Andaman and Nicobar Islands",
    "theandamanandnicobarislands": "Andaman and Nicobar Islands",
    "dadraandnagarhaveli": "Dadra and Nagar Haveli and Daman and Diu",
    "damananddiu": "Dadra and Nagar Haveli and Daman and Diu",
    "dadraandnagarhavelianddamananddiu": "Dadra and Nagar Haveli and Daman and Diu",
    "laccadive": "Lakshadweep", "laccadiveislands": "Lakshadweep"
}
FIELDS = ["STNAME", "STNAME_SH", "ST_NAME", "STATE_NAME", "STATENAME", "STATE_UT_NAME", "STATE_UT", "STATE", "STNM", "NAME", "NAME_EN", "state_name_english"]


def canonical(value: object) -> str | None:
    if value is None or not str(value).strip():
        return None
    value = str(value).strip()
    key = re.sub(r"[^a-z0-9]", "", value.lower())
    return NORMALIZED.get(key) or ALIASES.get(key)


def state_name(props: dict) -> str | None:
    keys = {re.sub(r"[^a-z0-9]", "", str(k).lower()): v for k, v in props.items()}
    for key in FIELDS:
        norm = re.sub(r"[^a-z0-9]", "", key.lower())
        if norm in keys:
            v = canonical(keys[norm])
            if v:
                return v
    return None


def walk_points(obj):
    if isinstance(obj, (list, tuple)):
        if len(obj) >= 2 and isinstance(obj[0], (int, float)) and isinstance(obj[1], (int, float)):
            yield float(obj[0]), float(obj[1])
        else:
            for item in obj:
                yield from walk_points(item)


def transform_coordinates(obj, transform):
    """Recursively transform GeoJSON positions while preserving extra dimensions."""
    if isinstance(obj, (list, tuple)):
        if len(obj) >= 2 and isinstance(obj[0], (int, float)) and isinstance(obj[1], (int, float)):
            lon, lat = transform(float(obj[0]), float(obj[1]))
            return [lon, lat, *obj[2:]]
        return [transform_coordinates(item, transform) for item in obj]
    return obj


def india_nsf_lcc_to_wgs84(easting: float, northing: float) -> tuple[float, float]:
    """EPSG:7755 WGS 84 / India NSF LCC inverse projection (metres to degrees)."""
    a = 6378137.0
    inv_f = 298.257223563
    f = 1 / inv_f
    e = math.sqrt(2 * f - f * f)
    phi0 = math.radians(24.0)
    phi1 = math.radians(12.472955)
    phi2 = math.radians(35.1728044444444)
    lam0 = math.radians(80.0)

    def m(phi):
        return math.cos(phi) / math.sqrt(1 - e * e * math.sin(phi) ** 2)

    def t(phi):
        sin_phi = math.sin(phi)
        return math.tan(math.pi / 4 - phi / 2) / ((1 - e * sin_phi) / (1 + e * sin_phi)) ** (e / 2)

    n = math.log(m(phi1) / m(phi2)) / math.log(t(phi1) / t(phi2))
    F = m(phi1) / (n * t(phi1) ** n)
    rho0 = a * F * t(phi0) ** n
    dx, dy = easting - 4_000_000.0, northing - 4_000_000.0
    rho = math.copysign(math.hypot(dx, rho0 - dy), n)
    theta = math.atan2(dx, rho0 - dy)
    target_t = (rho / (a * F)) ** (1 / n)
    phi = math.pi / 2 - 2 * math.atan(target_t)
    for _ in range(12):
        sin_phi = math.sin(phi)
        next_phi = math.pi / 2 - 2 * math.atan(target_t * ((1 - e * sin_phi) / (1 + e * sin_phi)) ** (e / 2))
        if abs(next_phi - phi) < 1e-13:
            phi = next_phi
            break
        phi = next_phi
    return math.degrees(lam0 + theta / n), math.degrees(phi)


def validate_json(doc: dict):
    if not isinstance(doc, dict) or doc.get("type") != "FeatureCollection":
        raise ValueError("The government archive does not contain a GeoJSON FeatureCollection.")
    feats = doc.get("features")
    if not isinstance(feats, list):
        raise ValueError("No features[] array in GeoJSON.")
    by_name = {}
    unmatched = []
    crs_name = (((doc.get("crs") or {}).get("properties") or {}).get("name") or "").upper()
    epsg7755 = "EPSG::7755" in crs_name or "EPSG:7755" in crs_name
    for feat in feats:
        if feat.get("type") != "Feature":
            continue
        geom = feat.get("geometry") or {}
        if geom.get("type") not in ("Polygon", "MultiPolygon"):
            continue
        name = state_name(feat.get("properties") or {})
        if not name:
            unmatched.append(feat.get("properties") or {})
            continue
        pts = list(walk_points(geom.get("coordinates", [])))
        if len(pts) < 4 or not all(math.isfinite(a) and math.isfinite(b) for a,b in pts):
            raise ValueError(f"Invalid or empty polygon coordinates for {name}.")
        # WGS84 degrees, EPSG:7755 India NSF LCC, or Web Mercator meters.
        deg = max(abs(a) for a,b in pts) <= 180 and max(abs(b) for a,b in pts) <= 90
        projected = 500_000 < max(abs(a) for a,b in pts) < 30_000_000
        if epsg7755:
            transform = india_nsf_lcc_to_wgs84
            geom = dict(geom)
            geom["coordinates"] = transform_coordinates(geom.get("coordinates", []), transform)
            new = dict(feat)
            new["geometry"] = geom
            pts = list(walk_points(geom["coordinates"]))
        elif not (deg or projected):
            raise ValueError(f"Unknown coordinate reference system for {name}; use WGS84 or Web Mercator.")
        else:
            new = dict(feat)
        if projected and not epsg7755:
            def to_ll(a, b):
                lon = math.degrees(a / 6378137.0)
                lat = math.degrees(2 * math.atan(math.exp(b / 6378137.0)) - math.pi/2)
                return lon, lat
            pts = [to_ll(a, b) for a, b in pts]
        lonlo = min(a for a,b in pts)
        lonhi = max(a for a,b in pts)
        latlo = min(b for a,b in pts)
        lathi = max(b for a,b in pts)
        if not (65 < lonlo < 99 and 67 < lonhi < 101 and 5 < latlo < 39 and 6 < lathi < 40):
            raise ValueError(f"Coordinates outside expected India extent for {name}: {lonlo:.2f},{latlo:.2f} to {lonhi:.2f},{lathi:.2f}.")
        new["properties"] = dict(feat.get("properties") or {})
        new["properties"]["SCREENLEDGER_STATE_NAME"] = name
        by_name.setdefault(name, []).append((new,(lonlo,latlo,lonhi,lathi)))
    missing = [s for s in EXPECTED if s not in by_name]
    if missing:
        candidates = [list(x.items())[:5] for x in unmatched[:4]]
        raise ValueError(f"Missing official polygon names: {missing}. Unknown name samples: {candidates}. No guessed geometry was inserted.")
    # This is only a sanity test, NOT a definitive territorial-boundary verification.
    # The 2026 official political map is the reference for formal visual QA.
    bounds = {n: (min(b[0] for _,b in fs), min(b[1] for _,b in fs), max(b[2] for _,b in fs), max(b[3] for _,b in fs)) for n,fs in by_name.items()}
    if bounds["Ladakh"][3] < 35 or bounds["Jammu and Kashmir"][3] < 34:
        raise ValueError("The northern outlines appear truncated; manual Survey of India verification required.")
    selected = [f for group in by_name.values() for f,b in group]
    return {"type":"FeatureCollection", "features":selected}, {"feature_count":len(selected), "state_count":len(by_name), "north_bounds":{s:bounds[s] for s in ("Jammu and Kashmir","Ladakh")}, "unmatched_count":len(unmatched)}


def fetch(url: str, destination: Path):
    req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0 (compatible; ScreenLedger-research/1.0)", "Accept": "application/zip,application/octet-stream,*/*"})
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            if getattr(response, "status", 200) != 200:
                raise ValueError(f"Government portal returned HTTP {response.status}")
            data = response.read(90 * 1024 * 1024 + 1)
    except (urllib.error.URLError, TimeoutError) as err:
        raise RuntimeError(f"Government ZIP download failed: {err}. Open {DATASET_PAGE} in your browser, download 'state_NWIC_GeoJSON.zip' and rerun with --archive PATH.") from err
    if len(data) > 90 * 1024 * 1024:
        raise ValueError("Archive is unexpectedly larger than 90MB.")
    if not data.startswith(b"PK"):
        raise ValueError("Government endpoint returned non-ZIP content (possibly portal error/login).")
    destination.write_bytes(data)
    return data


def extract_archive(raw: bytes):
    from io import BytesIO
    with zipfile.ZipFile(BytesIO(raw)) as z:
        candidates = [i for i in z.infolist() if i.filename.lower().endswith((".geojson", ".json")) and not i.is_dir()]
        candidates.sort(key=lambda x: (not x.filename.lower().endswith(".geojson"), -x.file_size))
        if not candidates:
            raise ValueError("Official ZIP has no .geojson/.json entry. Inspect the original ZIP instead of substituting a map.")
        for i in candidates:
            if i.file_size > 140 * 1024 * 1024:
                continue
            try:
                doc = json.loads(z.read(i))
                if isinstance(doc, dict) and doc.get("type") == "FeatureCollection":
                    return doc, i.filename
            except (ValueError, UnicodeDecodeError):
                continue
        raise ValueError("No valid GeoJSON FeatureCollection found inside official ZIP.")


def embed(base: str, geojson: dict, metadata: dict):
    # Strip any previous embedded geometry and inject once, before the last app script.
    base = re.sub(re.escape(PREFIX) + r".*?" + re.escape(SUFFIX), "", base, flags=re.S)
    anchor = "// Initial view: complete state index; never draw or label an unsourced silhouette as an official map."
    if anchor not in base:
        raise RuntimeError("Expected dashboard v3 map loader not found in index.html; refusing unsafe modification.")
    source_block = (PREFIX + '\n<script id="screenledgerOfficialGeo" type="application/json">' + json.dumps(geojson, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/") + "</script>\n" + SUFFIX + '\n')
    # Position JSON data before the JS map loader script. Existing page has two sequential scripts.
    loader_header = "<script>\n(() => {\nconst SOURCE_STATE="
    # Fallback to precise substring in v3 source.
    if loader_header not in base:
        loader_header = "<script>\n(() => {\nconst SOURCE_STATE"
    if loader_header not in base:
        # If app starts after a different wrapper, place JSON before last script tag.
        pos = base.rfind("<script>")
        if pos < 0:raise RuntimeError("No main dashboard <script> found")
        base = base[:pos] + source_block + base[pos:]
    else:
        base = base.replace(loader_header, source_block + loader_header, 1)
    init = """const savedGeo=document.getElementById('screenledgerOfficialGeo');
if(savedGeo){
 try{const obj=JSON.parse(savedGeo.textContent);const fs=extractFeatures(obj);const names=new Set(fs.map(f=>featureName(f)).filter(Boolean));
 if(names.size!==36 || !names.has('Jammu and Kashmir') || !names.has('Ladakh'))throw new Error('Missing states/UTs');
 app.stateGeo=fs;app.geoSource='user-provided NWIC/Survey of India archive (see provenance)';
 get('geoStatus').textContent='Loaded '+fs.length+' government-sourced state features. Downloaded archive SHA-256: '+savedGeo.dataset.sha256+'. Political border verification remains required.';
 }catch(err){get('geoStatus').textContent='Embedded geometry was rejected: '+err.message;}
}
"""
    script_tag = '<script id="screenledgerOfficialGeo" type="application/json">'
    base = base.replace(script_tag, '<script id="screenledgerOfficialGeo" data-sha256="' + metadata["archive_sha256"] + '" type="application/json">', 1)
    base = base.replace(anchor, init + anchor, 1)
    # Make source status less confusing while no geometry present.
    base = base.replace('Official boundary geometry required</b>', 'Official boundary data not yet embedded</b>')
    return base


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, help='Previously downloaded Government of India state ZIP (no internet required)')
    parser.add_argument('--template', type=Path, default=Path(__file__).with_name('index.html'))
    parser.add_argument('--output', type=Path, default=Path(__file__).with_name(OUTPUT))
    args = parser.parse_args()
    archive = args.archive or Path(__file__).with_name(ARCHIVE)
    archive_retrieved_from_url = not archive.exists() and args.archive is None
    if not archive.exists():
        print('Downloading government-hosted Survey of India state geometry from NWIC...')
        raw = fetch(SOURCE, archive)
    else:
        raw = archive.read_bytes()
    checksum = hashlib.sha256(raw).hexdigest()
    doc, entry = extract_archive(raw)
    clean, audit = validate_json(doc)
    template = args.template.read_text(encoding='utf-8')
    audit.update({"declared_source_url":SOURCE,"acquisition_method":"downloaded_directly_from_government_url" if archive_retrieved_from_url else "local_supplied_archive_unverified_origin","dataset_page":DATASET_PAGE,"cartographic_reference":SOI_REFERENCE,"archive_file":archive.name,"archive_sha256":checksum,"zip_entry":entry,"run_utc":dt.datetime.now(dt.timezone.utc).isoformat(),"verified_2026_border_against_political_map":False,"redistribution_rights_verified":False,"origin_certified_by_this_tool":archive_retrieved_from_url})
    html = embed(template, clean, audit)
    args.output.write_text(html, encoding='utf-8')
    auditfile = args.output.with_name('soi_geometry_provenance.json')
    auditfile.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"Embedded {audit['feature_count']} polygon features, covering {audit['state_count']} states/UTs into {args.output}")
    print(f"Archive SHA-256: {checksum}")
    print(f"Audit: {auditfile}")
    print('IMPORTANT: geographic QA against SoI political map and redistribution terms are NOT yet approved.')

if __name__ == '__main__':
    try: main()
    except Exception as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        sys.exit(1)
