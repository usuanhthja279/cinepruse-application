#!/usr/bin/env python3
"""Build a conservative District selector label -> Indian state/UT reference.

Input is the public District selector snapshot and the official Census 2011
Location Code Directory workbook. Matching is exact after Unicode and spacing
normalization. Duplicate labels are preserved. Ambiguous or unmatched labels
are deliberately not guessed. This maps selector labels only; it must not be
used to assign cinema bookings or revenue to a state.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
import zipfile
from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent
ROSTER = ROOT / "district_movies_cities_2026-11-07.json"
WORKBOOK_URL = "https://censusindia.gov.in/nada/index.php/catalog/42648/download/46323/PC11_TV_DIR.xlsx"
CATALOG_URL = "https://censusindia.gov.in/nada/index.php/catalog/42648"
OUT = ROOT / "data" / "city_state_mapping_2026-11-07.csv"
PROVENANCE = ROOT / "data" / "city_state_mapping_2026-11-07.provenance.json"
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

# Stable names whose current spelling differs from the Census directory, plus
# the District NCR label whose New Delhi resolution the project owner verified.
CURATED = {
    "bengaluru": "Karnataka", "bangalore": "Karnataka",
    "hyderabad": "Telangana", "secunderabad": "Telangana",
    "mumbai": "Maharashtra", "mumbai greater": "Maharashtra",
    "leh": "Ladakh", "kargil": "Ladakh", "srinagar": "Jammu and Kashmir",
    "new delhi": "Delhi", "delhi ncr": "Delhi",
    # 2011 Census towns under the undivided Andhra Pradesh code whose 2011
    # district is now in Telangana. The workbook's state-level town rows do
    # not consistently retain a district code for these labels.
    "adilabad": "Telangana", "karimnagar": "Telangana", "khammam": "Telangana",
    "mahbubnagar": "Telangana", "medak": "Telangana", "nalgonda": "Telangana",
    "nizamabad": "Telangana", "rangareddy": "Telangana", "ranga reddy": "Telangana",
    "warangal": "Telangana",
}


def norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(c for c in value if not unicodedata.combining(c))
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def census_norm(value: str) -> str:
    # Town directory labels append municipality class and outgrowth text.
    # Exclude this suffix only on the source side, leaving selector labels
    # (including qualifiers such as "(West Bengal)") intact.
    value = re.sub(r"\s*\([^)]*\)\s*$", "", value)
    return norm(value)


def current_state(state_code: str, district: str) -> str | None:
    # Census 2011 Andhra Pradesh district codes: Telangana comprised the
    # following ten districts before the later administrative redistricting.
    telangana_district_codes = {"001", "007", "008", "009", "012", "013",
                                "014", "016", "018", "022"}
    d = district.strip().zfill(3)
    if state_code == "28" and d in telangana_district_codes:
        return "Telangana"
    if state_code == "28" and d == "000":
        # Some Census town rows are repeated only under the undivided state
        # heading, so current AP versus Telangana cannot be resolved there.
        return None
    code_map = {
        "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab",
        "04": "Chandigarh", "05": "Uttarakhand", "06": "Haryana",
        "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh",
        "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh",
        "13": "Nagaland", "14": "Manipur", "15": "Mizoram",
        "16": "Tripura", "17": "Meghalaya", "18": "Assam",
        "19": "West Bengal", "20": "Jharkhand", "21": "Odisha",
        "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
        "25": "Daman and Diu", "26": "Dadra and Nagar Haveli",
        "27": "Maharashtra", "28": "Andhra Pradesh", "29": "Karnataka",
        "30": "Goa", "31": "Lakshadweep", "32": "Kerala",
        "33": "Tamil Nadu", "34": "Puducherry", "35": "Andaman and Nicobar Islands",
        "36": "Telangana",
    }
    if state_code == "01" and d in {"003", "004"}:
        return "Ladakh"
    if state_code == "25":
        return "Dadra & Nagar Haveli and Daman & Diu"
    if state_code == "26":
        return "Dadra & Nagar Haveli and Daman & Diu"
    return code_map.get(state_code)


def xlsx_strings(zf: zipfile.ZipFile) -> list[str]:
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    return ["".join(t.text or "" for t in item.findall(".//m:t", NS))
            for item in root.findall("m:si", NS)]


def column_index(ref: str) -> int:
    letters = re.match(r"[A-Z]+", ref).group(0)
    value = 0
    for ch in letters:
        value = value * 26 + ord(ch) - 64
    return value - 1


def census_index(path: Path) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    candidates: dict[str, set[str]] = defaultdict(set)
    settlement_candidates: dict[str, set[str]] = defaultdict(set)
    with zipfile.ZipFile(path) as zf:
        shared = xlsx_strings(zf)
        sheet = ET.iterparse(zf.open("xl/worksheets/sheet1.xml"), events=("end",))
        for _, row in sheet:
            if row.tag.endswith("}row"):
                cells: dict[int, str] = {}
                for cell in row:
                    if not cell.tag.endswith("}c"):
                        continue
                    idx = column_index(cell.attrib.get("r", "A1"))
                    value = cell.find("m:v", NS)
                    if value is None or value.text is None:
                        continue
                    raw = value.text
                    cells[idx] = shared[int(raw)] if cell.attrib.get("t") == "s" else raw
                if cells and cells.get(0, "").strip().casefold() == "state code":
                    row.clear()
                    continue
                # Official directory columns: state, district, subdistrict,
                # town-village code, town-village name.
                if len(cells) >= 5:
                    state, district, loc_code, name = (cells.get(i, "").strip()
                                                        for i in (0, 1, 3, 4))
                    if (name and state.isdigit() and district.isdigit()
                            and loc_code.isdigit() and loc_code != "000000"):
                        state_name = current_state(state.zfill(2), district)
                        state_names = ({"Andhra Pradesh", "Telangana"}
                                       if state.zfill(2) == "28" and district.strip().zfill(3) == "000"
                                       else ({state_name} if state_name else set()))
                        if state_names:
                            key = census_norm(name)
                            settlement_candidates[key].update(state_names)
                            # Census town identifiers begin with 8. Prefer
                            # these over the broader settlement-name fallback.
                            if loc_code.startswith("8"):
                                candidates[key].update(state_names)
                row.clear()
    return candidates, settlement_candidates


def roster_rows(roster: dict) -> list[dict[str, str]]:
    rows = []
    for letter, group in roster["letters"].items():
        seen: dict[str, int] = defaultdict(int)
        for label in group["cities"]:
            seen[label] += 1
            rows.append({"letter": letter, "display_label": label,
                         "occurrence": str(seen[label])})
    return rows


def build(roster: dict, candidates: dict[str, set[str]],
          settlement_candidates: dict[str, set[str]] | None = None) -> tuple[list[dict[str, str]], dict]:
    settlement_candidates = settlement_candidates or {}
    output = []
    for row in roster_rows(roster):
        label = row["display_label"]
        found = sorted(candidates.get(norm(label), set()))
        used_settlement_fallback = False
        if not found:
            found = sorted(settlement_candidates.get(norm(label), set()))
            used_settlement_fallback = bool(found)
        curated = CURATED.get(norm(label))
        if curated:
            state, status, found = curated, "matched_curated_city_state", [curated]
            basis = "curated current city/state crosswalk; Delhi NCR uses project-owner-confirmed District New Delhi resolution"
        elif len(found) == 1:
            state, status = found[0], ("matched_exact_2011_settlement_name" if used_settlement_fallback
                                       else "matched_exact_2011_town_name")
            basis = ("exact normalized Census 2011 settlement name; town record absent" if used_settlement_fallback
                     else "exact normalized Census 2011 town name")
        elif found:
            state, status = "", "ambiguous_multiple_states"
            basis = "multiple Census 2011 town matches in different current states/UTs"
        else:
            state, status = "", "unmatched"
            basis = "no exact Census 2011 town-name match"
        output.append({**row, "state_or_ut": state, "mapping_status": status,
                       "candidate_states": "|".join(found), "source_year": "2011",
                       "mapping_basis": basis})
    counts: dict[str, int] = defaultdict(int)
    for row in output:
        counts[row["mapping_status"]] += 1
    summary = {"selector_labels": len(output), "status_counts": dict(sorted(counts.items())),
               "source_url": CATALOG_URL,
               "workbook_url": WORKBOOK_URL,
               "selector_source_url": roster.get("source_url"),
               "selector_capture_date": roster.get("captured_at_local"),
               "method": "Exact normalized Census 2011 town-name match, followed by a unique-state settlement-name fallback for labels absent from the town subset, plus explicitly labeled current-spelling, Telangana split, and owner-confirmed selector aliases; duplicate selector entries retained; no fuzzy matching.",
               "limitation": "This is a city-selector coverage reference, not a cinema-to-state map. Never aggregate bookings or revenue by this field. Census 2011 names and boundaries may differ from current administrative geography; ambiguous and unmatched entries remain unassigned."}
    return output, summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbook", type=Path, required=True,
                        help="Downloaded official Census 2011 Location Code Directory XLSX")
    parser.add_argument("--roster", type=Path, default=ROSTER)
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--provenance", type=Path, default=PROVENANCE)
    args = parser.parse_args()
    roster = json.loads(args.roster.read_text(encoding="utf-8"))
    town_index, settlement_index = census_index(args.workbook)
    rows, provenance = build(roster, town_index, settlement_index)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    args.provenance.write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(provenance, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
