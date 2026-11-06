#!/usr/bin/env python3
"""Normalize city catalogs from user-saved, authorized District exports or HTML.

No network access. SEO links are a PARTIAL discoverable subset, not a full city roster.
"""
from __future__ import annotations
import argparse
import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from bs4 import BeautifulSoup

from district_extractor import slugify_city

FIELDS = ["name", "slug", "city_id", "state", "latitude", "longitude", "source",
          "source_path", "confidence", "checked_at_utc"]
CITY_CONTAINER = {"cities", "citylist", "city_list", "popularcities", "othercities", "supportedcities",
                  "availablecities", "moviecities", "cityoptions", "city_options"}
CITY_NAME = ("name", "cityName", "city_name", "label", "city", "displayName", "display_name")
CITY_SLUG = ("slug", "citySlug", "city_slug", "urlSlug", "url_slug", "key", "code")
CITY_ID = ("cityId", "city_id", "id", "locationId", "location_id")
CITY_STATE = ("state", "stateName", "state_name")


def first(obj: dict, keys: tuple[str, ...]):
    for key in keys:
        if obj.get(key) not in (None, ""):
            return obj[key]
    return None


def normalize_name(value) -> str | None:
    if not isinstance(value, str):
        return None
    name = re.sub(r"\s+", " ", value).strip()
    return name if 1 < len(name) <= 100 else None


def parse_object(obj: dict, where: str, now: str) -> dict | None:
    name = normalize_name(first(obj, CITY_NAME))
    slug_raw = first(obj, CITY_SLUG)
    if not name and isinstance(slug_raw, str):
        name = slug_raw.replace("-", " ").title()
    if not name:
        return None
    slug = slugify_city(str(slug_raw or name))
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
        return None
    # Exclude nested cinema, region, and metadata objects by requiring city-list context.
    # If the source supplies only names, the slug is inferred and not verified.
    return {
        "name": name, "slug": slug, "city_id": str(first(obj, CITY_ID) or ""),
        "state": str(first(obj, CITY_STATE) or ""),
        "latitude": first(obj, ("latitude", "lat")) or "",
        "longitude": first(obj, ("longitude", "lng", "lon")) or "",
        "source": "saved_json_city_catalog", "source_path": where,
        "confidence": "source_slug" if slug_raw else "inferred_slug",
        "checked_at_utc": now,
    }


def extract_catalog_from_json(obj, now: str) -> list[dict]:
    found = []

    def visit(value, path: str, in_city_container: bool = False):
        if isinstance(value, dict):
            if in_city_container:
                row = parse_object(value, path, now)
                if row is not None:
                    found.append(row)
                    return
            for key, nested in value.items():
                # Deliberately avoid treating every movie session's cityName as a city catalog.
                listed = key.lower().replace("-", "_") in CITY_CONTAINER or key.lower() in CITY_CONTAINER
                visit(nested, f"{path}.{key}", listed)
        elif isinstance(value, list):
            for i, nested in enumerate(value):
                if in_city_container and isinstance(nested, str):
                    name = normalize_name(nested)
                    if name:
                        found.append({"name": name, "slug": slugify_city(name), "city_id": "",
                                      "state": "", "latitude": "", "longitude": "",
                                      "source": "saved_json_city_catalog", "source_path": f"{path}[{i}]",
                                      "confidence": "inferred_slug", "checked_at_utc": now})
                else:
                    visit(nested, f"{path}[{i}]", in_city_container)
    visit(obj, "root", isinstance(obj, list))
    return found


def extract_city_links(html: str, now: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    found = []
    for a in soup.find_all("a", href=True):
        parsed = urlparse(a["href"])
        if parsed.hostname and parsed.hostname not in ("www.district.in", "district.in"):
            continue
        m = re.fullmatch(r"/movies/([a-z0-9-]+)-movie-tickets/?", parsed.path, re.I)
        if not m:
            continue
        slug = m.group(1).lower()
        name = normalize_name(a.get_text(" ", strip=True)) or slug.replace("-", " ").title()
        found.append({"name": name, "slug": slug, "city_id": "", "state": "",
                      "latitude": "", "longitude": "", "source": "page_seo_city_link",
                      "source_path": a["href"], "confidence": "source_slug", "checked_at_utc": now})
    for node in soup.select('script[type="application/json"],script[type="application/ld+json"]'):
        if not node.string:
            continue
        try:
            found.extend(extract_catalog_from_json(json.loads(node.string), now))
        except json.JSONDecodeError:
            continue
    return found


def extract_catalog(source_file: Path) -> list[dict]:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    content = source_file.read_text(encoding="utf-8-sig")
    if source_file.suffix.lower() == ".csv":
        with source_file.open(encoding="utf-8-sig", newline="") as f:
            data = {"cities": list(csv.DictReader(f))}
        return extract_catalog_from_json(data, now)
    if source_file.suffix.lower() == ".json":
        return extract_catalog_from_json(json.loads(content), now)
    return extract_city_links(content, now)


def save_catalog(rows: list[dict], output: Path, source_name: str) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    unique: dict[str, dict] = {}
    for row in rows:
        slug = row["slug"]
        existing = unique.get(slug)
        if not existing or (existing["confidence"] == "inferred_slug" and row["confidence"] == "source_slug"):
            unique[slug] = row
    catalog = sorted(unique.values(), key=lambda x: (x["name"].lower(), x["slug"]))
    with (output / "cities_discovered.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(catalog)
    (output / "cities_discovered.json").write_text(json.dumps(catalog, indent=2, ensure_ascii=False), encoding="utf-8")
    report = {"source_file": source_name, "discovered": len(rows), "unique_cities": len(catalog),
              "source_slugs": sum(r["confidence"] == "source_slug" for r in catalog),
              "inferred_slugs": sum(r["confidence"] == "inferred_slug" for r in catalog),
              "complete_official_roster_verified": False,
              "note": "Saved-file discovery only. A page's links or exported subset cannot prove all supported District cities were captured. Obtain a complete authorized official catalog with total count for verification."}
    (output / "city_discovery_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main():
    p = argparse.ArgumentParser(description="Discover District cities from saved HTML, JSON, or CSV (offline only)")
    p.add_argument("--source-file", required=True, type=Path)
    p.add_argument("--out", type=Path, default=Path("city_catalog_output"))
    args = p.parse_args()
    r = save_catalog(extract_catalog(args.source_file), args.out, str(args.source_file))
    print(json.dumps(r, indent=2))

if __name__ == "__main__":
    main()
