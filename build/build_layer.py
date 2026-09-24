#!/usr/bin/env python
"""
Build the North Carolina data center moratoria layer from the research table.

    python build/build_layer.py

Reads   data/nc_data_center_moratoriums.csv    (research table, as of BASE_RESEARCH_DATE)
        data/research_updates.csv              (later research, applied on top)
Writes  data/nc_datacenter_moratoria.geojson   (map layer, styled for GitHub's viewer)
        data/summary.json                      (headline counts, recomputed every build)

Boundaries come from the U.S. Census Bureau 2021 cartographic boundary files and
are downloaded on first run. The two CSVs are the source of truth; the GeoJSON
is derived from them and should never be edited by hand.

The layer records what local governments have decided about new data centers.
It says nothing about where data centers exist or are planned.
"""

from __future__ import annotations

import json
import sys
import urllib.request
import zipfile
from datetime import date, datetime
from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "data" / "nc_data_center_moratoriums.csv"
UPDATES = ROOT / "data" / "research_updates.csv"
GEOJSON = ROOT / "data" / "nc_datacenter_moratoria.geojson"
SUMMARY = ROOT / "data" / "summary.json"
CACHE = ROOT / "build" / ".cache"

# The research table is a snapshot as of BASE_RESEARCH_DATE. Each row of
# research_updates.csv is a complete record from later research that replaces
# the table's row for that jurisdiction, or adds one the table lacks. Status is
# evaluated as of STATUS_AS_OF, the date of the latest statewide check, not the
# day the build runs, so the published snapshot is internally consistent.
BASE_RESEARCH_DATE = date(2026, 8, 29)
STATUS_AS_OF = date(2026, 9, 24)
UPDATE_COLUMNS = ["update_kind", "researched_on", "change_summary",
                  "needs_confirmation", "expiration_note"]

CENSUS = {
    "county": "https://www2.census.gov/geo/tiger/GENZ2021/shp/cb_2021_us_county_20m.zip",
    "place": "https://www2.census.gov/geo/tiger/GENZ2021/shp/cb_2021_37_place_500k.zip",
    "tribal": "https://www2.census.gov/geo/tiger/GENZ2021/shp/cb_2021_us_aiannh_500k.zip",
}
NC_FIPS = "37"
INCORPORATED_LSAD = {"25", "43", "47"}   # city, town, village (excludes CDPs)
QUALLA_GEOID = "0990"                     # Eastern Cherokee Reservation (Qualla Boundary)

# --- What each status means for whether a restriction is in force ------------
IN_FORCE_UNTIL_EXPIRY, IN_FORCE_INDEFINITE, ENDED = "until_expiry", "indefinite", "ended"
NEVER, UNDETERMINED = "never", "undetermined"
STATUS_MEANING = {
    "adopted": IN_FORCE_UNTIL_EXPIRY,
    "permanent_ban": IN_FORCE_INDEFINITE,
    "expired_superseded": ENDED,
    "expired_unverified": UNDETERMINED,   # term ran out; renewal unknown
    "adopted_unverified": UNDETERMINED,
    "unverified": UNDETERMINED,
    "regulated_no_moratorium": NEVER,     # chose regulation instead
    "none": NEVER, "rejected": NEVER, "deferred": NEVER, "studying": NEVER,
    "proposed": NEVER, "pending_vote": NEVER, "pending_second_reading": NEVER,
    "citizen_request": NEVER,
}

IN_EFFECT = "Moratorium or ban in effect"
CONSIDERING = "Under consideration"
ENDED_CAT = "Ended, declined, or replaced"
NO_ACTION = "No action found"
UNDER_CONSIDERATION = {"proposed", "pending_vote", "pending_second_reading",
                       "studying", "citizen_request", "deferred"}
DECLINED_OR_ENDED = {"rejected", "regulated_no_moratorium", "expired_superseded",
                     "expired_unverified"}
ASSERTS_ADOPTION = {"adopted", "permanent_ban", "adopted_unverified"}

# Records whose ACTION could not be confirmed against a primary source. These are
# outlined in black on the map. The list follows the corrections log's
# definition of record, minus Northampton County (see below). A jurisdiction in
# research_updates.csv takes its flag from that file's needs_confirmation
# column instead, so later research can raise or clear a flag.
NEEDS_CONFIRMATION = {
    "Clay County": "Adoption date, and whether the ban is permanent or temporary, are both "
                   "unconfirmed. The ordinance PDFs are image-only scans.",
    "Town of Bailey": "The entire record rests on a single tracker entry, with no news "
                      "coverage anywhere.",
    "City of Kings Mountain": "An extension passed on 2026-08-25, so the moratorium did not "
                              "lapse, but the extension's length and new end date are unknown.",
    "Watauga County": "No primary government record could be retrieved. Rests on two news "
                      "sources and a tracker.",
}
# The action is confirmed; only the end date is uncertain. Not outlined, since
# the date is already labelled as estimated.
EXPIRATION_UNCONFIRMED = {
    "Northampton County": "Adoption, the 32-month term and the unanimous vote are confirmed. "
                          "The end date is not: the term was changed on the floor.",
}

COLORS = {IN_EFFECT: "#B2182B", CONSIDERING: "#8073AC", ENDED_CAT: "#758CA3"}
LEVEL_LABEL = {"county": "County", "municipal": "Municipality", "tribal": "Tribal nation"}


def parse_date(value):
    if value is None or pd.isna(value):
        return None
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def in_effect(row, as_of: date):
    """True / False / None. None means the data cannot say, and is never guessed."""
    meaning = STATUS_MEANING.get(row["status"])
    if meaning is None:
        sys.exit(f"Unrecognized status '{row['status']}' for {row['jurisdiction']}. "
                 "Add it to STATUS_MEANING before building.")
    if meaning in (NEVER, ENDED):
        return False
    if meaning == UNDETERMINED:
        return None
    start = parse_date(row["effective_date"]) or parse_date(row["adopted_date"])
    if start is None:
        return None
    if as_of < start:
        return False
    if meaning == IN_FORCE_INDEFINITE:
        return True
    raw = row["expiration_date"]
    if not pd.isna(raw) and "indefinite" in str(raw).lower():
        return True
    end = parse_date(raw)
    if end is None:
        return None
    return as_of <= end


def category(status: str, active) -> str:
    # Status decides the bucket first: a proposal that never took effect is
    # "not in force", but it is still under consideration, not ended.
    if status == "none":
        return NO_ACTION
    if status in UNDER_CONSIDERATION:
        return CONSIDERING
    if status in DECLINED_OR_ENDED:
        return ENDED_CAT
    if status in ASSERTS_ADOPTION:
        return ENDED_CAT if active is False else IN_EFFECT
    return CONSIDERING


def load_records() -> pd.DataFrame:
    """The research table with research_updates.csv applied."""
    base = pd.read_csv(CSV, dtype="string", keep_default_na=True).dropna(how="all")
    print(f"Read {len(base)} records from {CSV.name}")
    blank = {c: pd.Series(pd.NA, index=base.index, dtype="string") for c in UPDATE_COLUMNS}
    if not UPDATES.exists():
        return base.assign(**blank)

    upd = pd.read_csv(UPDATES, dtype="string", keep_default_na=True).dropna(how="all")
    missing = [c for c in [*base.columns, *UPDATE_COLUMNS] if c not in upd.columns]
    if missing:
        sys.exit(f"{UPDATES.name} is missing columns: {', '.join(missing)}")
    problems = [f"{n}: listed more than once"
                for n in upd.loc[upd["jurisdiction"].duplicated(), "jurisdiction"]]
    known = set(base["jurisdiction"])
    for _, r in upd.iterrows():
        name, kind = r["jurisdiction"], r["update_kind"]
        if kind == "revised" and name not in known:
            problems.append(f"{name}: marked revised, but {CSV.name} has no such record")
        elif kind == "new" and name in known:
            problems.append(f"{name}: marked new, but {CSV.name} already has it")
        elif kind not in ("new", "revised"):
            problems.append(f"{name}: update_kind must be 'new' or 'revised', not '{kind}'")
        when = parse_date(r["researched_on"])
        if when is None or when > STATUS_AS_OF:
            problems.append(f"{name}: researched_on '{r['researched_on']}' is missing or later "
                            f"than STATUS_AS_OF ({STATUS_AS_OF}); move STATUS_AS_OF forward")
        if pd.isna(r["change_summary"]):
            problems.append(f"{name}: change_summary is empty")
    if problems:
        sys.exit(f"Refusing to build. Problems in {UPDATES.name}:\n  " + "\n  ".join(problems))

    kept = base[~base["jurisdiction"].isin(upd["jurisdiction"])].assign(**blank)
    merged = pd.concat([kept, upd[[*base.columns, *UPDATE_COLUMNS]]], ignore_index=True)
    kinds = upd["update_kind"].value_counts()
    print(f"Applied {len(upd)} updates from {UPDATES.name} "
          f"({kinds.get('revised', 0)} revised, {kinds.get('new', 0)} new)")
    return merged


def confirmation_note(row):
    """Why a record still needs confirmation, or None. Updated records carry
    their own flag; the rest keep the table's."""
    if not pd.isna(row["update_kind"]):
        return None if pd.isna(row["needs_confirmation"]) else str(row["needs_confirmation"])
    return NEEDS_CONFIRMATION.get(str(row["jurisdiction"]))


def expiration_note(row):
    if not pd.isna(row["update_kind"]):
        return None if pd.isna(row["expiration_note"]) else str(row["expiration_note"])
    return EXPIRATION_UNCONFIRMED.get(str(row["jurisdiction"]))


def boundaries(kind: str) -> gpd.GeoDataFrame:
    CACHE.mkdir(parents=True, exist_ok=True)
    url = CENSUS[kind]
    zpath = CACHE / Path(url).name
    if not zpath.exists():
        print(f"  downloading {zpath.name}")
        urllib.request.urlretrieve(url, zpath)
    with zipfile.ZipFile(zpath) as z:
        shp = next(n for n in z.namelist() if n.endswith(".shp"))
    return gpd.read_file(f"zip://{zpath}!{shp}")


def match_geometry(rows: pd.DataFrame) -> gpd.GeoSeries:
    counties = boundaries("county")
    counties = counties[counties["STATEFP"] == NC_FIPS]
    places = boundaries("place")
    places = places[places["LSAD"].isin(INCORPORATED_LSAD)]
    tribal = boundaries("tribal")
    tribal = tribal[tribal["GEOID"] == QUALLA_GEOID]

    geoms, missing = [], []
    for _, r in rows.iterrows():
        level, name = r["level"], str(r["jurisdiction"])
        if level == "county":
            hit = counties[counties["NAME"].str.casefold() == str(r["county"]).casefold()]
        elif level == "municipal":
            key = name
            for prefix in ("City of ", "Town of ", "Village of "):
                key = key.removeprefix(prefix)
            hit = places[places["NAME"].str.casefold() == key.casefold()]
        elif level == "tribal":
            hit = tribal
        else:
            sys.exit(f"Unrecognized level '{level}' for {name}.")
        if len(hit) != 1:
            missing.append(f"{name} ({level}): {len(hit)} boundary matches")
            geoms.append(None)
        else:
            geoms.append(hit.geometry.iloc[0])
    if missing:
        sys.exit("Boundary matching failed; refusing to publish a partial layer:\n  "
                 + "\n  ".join(missing))
    return gpd.GeoSeries(geoms, crs=counties.crs, index=rows.index)


def style(level: str, cat: str, flagged: bool) -> dict:
    """simplestyle-spec properties, which GitHub's GeoJSON viewer draws."""
    if cat == NO_ACTION:
        return {"fill": "#FFFFFF", "fill-opacity": 0, "stroke": "#B0B8C0",
                "stroke-width": 0.6, "stroke-opacity": 1}
    color = COLORS[cat]
    if level == "county":
        s = {"fill": color, "fill-opacity": 0.45, "stroke": "#FFFFFF", "stroke-width": 1}
    else:
        s = {"fill": color, "fill-opacity": 0.15, "stroke": color, "stroke-width": 2.5}
    if flagged:
        s.update({"stroke": "#111111", "stroke-width": 3.5})
    s["stroke-opacity"] = 1
    return s


def main() -> None:
    df = load_records()

    df["_active"] = [in_effect(r, STATUS_AS_OF) for _, r in df.iterrows()]
    df["_category"] = [category(s, a) for s, a in zip(df["status"], df["_active"])]
    # Kept as an explicit boolean: a column built from None and strings turns the
    # None into NaN, and NaN is truthy, which would flag every record.
    notes = [confirmation_note(r) for _, r in df.iterrows()]
    df["_flagged"] = [n is not None for n in notes]
    df["_flag_note"] = [n or "" for n in notes]
    geometry = match_geometry(df)

    features = []
    for idx, r in df.iterrows():
        name, level, cat = str(r["jurisdiction"]), str(r["level"]), r["_category"]
        flagged = bool(r["_flagged"])
        props = {"name": name, "level": LEVEL_LABEL[level],
                 "county": None if level == "tribal" else str(r["county"]),
                 "category": cat}
        if flagged:
            props["needs_confirmation"] = "yes"
            props["confirmation_note"] = str(r["_flag_note"])
        if not pd.isna(r["update_kind"]):
            props["updated"] = str(r["researched_on"])
            props["update_note"] = str(r["change_summary"])
        props["status"] = str(r["status"])
        for key, col in (("covers", "covers"), ("duration", "duration_label"),
                         ("adopted", "adopted_date")):
            if not pd.isna(r[col]):
                props[key] = str(r[col])
        end = parse_date(r["expiration_date"])
        if end:
            estimated = str(r["expiration_is_inferred"]).upper() == "TRUE"
            props["expires"] = f"{end.isoformat()} (estimated)" if estimated else end.isoformat()
        elif cat == IN_EFFECT:
            # Three different situations, which a single "no end date" phrase
            # would blur: a ban meant to be permanent, a pause set to run
            # indefinitely, and a record whose end date is simply unknown.
            raw = "" if pd.isna(r["expiration_date"]) else str(r["expiration_date"]).lower()
            if r["status"] == "permanent_ban":
                props["expires"] = "Permanent ban, no end date"
            elif "indefinite" in raw or str(r["duration_label"]).lower() == "indefinite":
                props["expires"] = "Indefinite, no end date set"
            else:
                props["expires"] = "End date unknown"
        note = expiration_note(r)
        if note:
            props["expiration_note"] = note
        props["confidence"] = str(r["confidence"])
        if not pd.isna(r["source_url"]):
            props["source"] = str(r["source_url"])
        props.update(style(level, cat, flagged))
        features.append((idx, level, flagged, name, props))

    # Draw order: counties beneath municipalities and the tribal nation, and
    # outlined records above their unflagged neighbors.
    order = {"county": 0, "municipal": 1, "tribal": 2}
    features.sort(key=lambda f: (order[f[1]], f[2], f[3]))

    layer = gpd.GeoDataFrame(
        [f[4] for f in features],
        geometry=[geometry.loc[f[0]] for f in features],
        crs=geometry.crs,
    ).to_crs("EPSG:4326")
    projected = layer.to_crs("EPSG:32119")
    tolerance = [50 if lvl == "County" else 10 for lvl in layer["level"]]
    layer["geometry"] = gpd.GeoSeries(
        [g.simplify(t, preserve_topology=True) for g, t in zip(projected.geometry, tolerance)],
        crs="EPSG:32119",
    ).to_crs("EPSG:4326")

    collection = json.loads(layer.to_json(drop_id=True, na="drop"))

    def rounded(value):
        if isinstance(value, float):
            return round(value, 5)
        if isinstance(value, list):
            return [rounded(v) for v in value]
        return value

    for f in collection["features"]:
        f["geometry"]["coordinates"] = rounded(f["geometry"]["coordinates"])

    counts = df["_category"].value_counts()
    effect = df[df["_category"] == IN_EFFECT]
    counties_in_effect = set(effect.loc[effect["level"] != "tribal", "county"])
    if (effect["level"] == "tribal").any():
        counties_in_effect |= {"Cherokee", "Graham", "Haywood", "Jackson", "Swain"}
    eii = df["expiration_is_inferred"].str.upper()
    adopted = effect["adopted_date"].fillna("")
    summary = {
        "status_as_of": STATUS_AS_OF.isoformat(),
        "base_research_as_of": BASE_RESEARCH_DATE.isoformat(),
        "records": len(df),
        "records_updated_after_base_research": int(df["update_kind"].notna().sum()),
        "by_category": {c: int(counts.get(c, 0)) for c in (IN_EFFECT, CONSIDERING, ENDED_CAT, NO_ACTION)},
        "in_effect_by_level": {k: int(v) for k, v in effect["level"].value_counts().items()},
        # Counted as "needing confirmation" rather than "confirmed": a record that is
        # not flagged is sourced, but not necessarily to a primary government record.
        "in_effect_needing_confirmation": int(effect["_flagged"].sum()),
        "needs_confirmation": int(df["_flagged"].sum()),
        "counties_containing_a_moratorium_in_effect": len(counties_in_effect),
        "expiration_dates_printed_in_source": int((eii == "FALSE").sum()),
        "expiration_dates_estimated": int((eii == "TRUE").sum()),
        "chose_regulation_instead": int((df["status"] == "regulated_no_moratorium").sum()),
        "adopted_in_august_2026": int(adopted.str.startswith("2026-08").sum()),
        "adopted_after_base_research": int((adopted > BASE_RESEARCH_DATE.isoformat()).sum()),
    }
    collection = {
        "type": "FeatureCollection",
        "metadata": {
            "title": "North Carolina data center moratoria",
            "status_as_of": STATUS_AS_OF.isoformat(),
            "base_research_as_of": BASE_RESEARCH_DATE.isoformat(),
            "note": "Records what local governments have decided about new data centers; "
                    "it says nothing about where data centers exist or are planned. Estimated "
                    "expiration dates are labelled '(estimated)'. Records outlined in black "
                    "need confirmation against a primary source. Records changed by research "
                    "after the base table carry 'updated' and 'update_note'.",
            "source_tables": ["data/nc_data_center_moratoriums.csv", "data/research_updates.csv"],
            "boundaries": "U.S. Census Bureau, 2021 cartographic boundary files",
        },
        "features": collection["features"],
    }
    readme = ROOT / "README.md"
    if readme.exists():
        text = readme.read_text(encoding="utf-8")
        start, end = "<!-- stats:start -->", "<!-- stats:end -->"
        if start in text and end in text:
            by = summary["by_category"]
            lv = summary["in_effect_by_level"]
            block = "\n".join([
                start,
                f"| As of {summary['status_as_of']} | |",
                "|---|---:|",
                f"| **Moratoria or bans in effect** | **{by[IN_EFFECT]}** |",
                f"| &nbsp;&nbsp;of which still need confirmation | {summary['in_effect_needing_confirmation']} |",
                f"| &nbsp;&nbsp;county / municipal / tribal | {lv.get('county', 0)} / {lv.get('municipal', 0)} / {lv.get('tribal', 0)} |",
                f"| Counties containing one | {summary['counties_containing_a_moratorium_in_effect']} of 100 |",
                f"| Adopted in August 2026 alone | {summary['adopted_in_august_2026']} |",
                f"| Adopted after {summary['base_research_as_of']} | {summary['adopted_after_base_research']} |",
                f"| Under consideration | {by[CONSIDERING]} |",
                f"| Ended, declined, or replaced | {by[ENDED_CAT]} |",
                f"| &nbsp;&nbsp;of which chose permanent regulation instead | {summary['chose_regulation_instead']} |",
                f"| Checked, no action found | {by[NO_ACTION]} |",
                f"| Records needing confirmation | {summary['needs_confirmation']} |",
                f"| Expiration dates estimated vs. printed in source | {summary['expiration_dates_estimated']} vs. {summary['expiration_dates_printed_in_source']} |",
                f"| Records changed by research after {summary['base_research_as_of']} | {summary['records_updated_after_base_research']} |",
                end,
            ])
            head, rest = text.split(start, 1)
            readme.write_text(head + block + rest.split(end, 1)[1], encoding="utf-8")

    GEOJSON.write_text(json.dumps(collection, ensure_ascii=False, separators=(",", ":")) + "\n",
                       encoding="utf-8")
    SUMMARY.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"Wrote {GEOJSON.relative_to(ROOT)} ({GEOJSON.stat().st_size / 1024:.0f} KB, "
          f"{len(collection['features'])} features)")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
