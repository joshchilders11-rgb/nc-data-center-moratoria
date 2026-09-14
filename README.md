# North Carolina Data Center Moratoria

A map of data center moratoria, bans, and related actions by North Carolina
counties, municipalities, and tribal governments — with a source for every
action, and with uncertain records marked as uncertain.

**[Open the interactive map →](data/nc_datacenter_moratoria.geojson)** · GitHub draws
it in the browser. Click any shape for its details.

<!-- stats:start -->
| As of 2026-08-29 | |
|---|---:|
| **Moratoria or bans in effect** | **42** |
| &nbsp;&nbsp;of which still need confirmation | 3 |
| &nbsp;&nbsp;county · municipal · tribal | 20 · 21 · 1 |
| Counties containing one | 34 of 100 |
| Adopted in August 2026 alone | 11 |
| Under consideration | 9 |
| Ended, declined, or replaced | 11 |
| &nbsp;&nbsp;of which chose permanent regulation instead | 7 |
| Checked, no action found | 72 |
| Records needing confirmation | 4 |
| Expiration dates estimated vs. printed in source | 30 vs. 12 |
<!-- stats:end -->

## Reading the map

| | Category |
|---|---|
| ![](https://img.shields.io/badge/%20-%20-B2182B?style=flat-square) | Moratorium or ban in effect |
| ![](https://img.shields.io/badge/%20-%20-8073AC?style=flat-square) | Under consideration — proposed, scheduled for a vote, or requested by residents |
| ![](https://img.shields.io/badge/%20-%20-758CA3?style=flat-square) | Ended, declined, or replaced by permanent regulation |
| ![](https://img.shields.io/badge/%20-%20-FFFFFF?style=flat-square) | Checked, no action found |

**Filled shapes** are county actions. **Heavy outlines** are city, town, or tribal
actions, so a county with no moratorium can still contain towns that have one —
Buncombe County has none, while Asheville and Woodfin both do.

**Black outlines** mark records that still need confirmation. Their popups say
what is missing.

## Before you quote a number

- **Status is as of August 29, 2026.** Moratoria are adopted, extended, and allowed
  to lapse within weeks. Check the source before relying on any single record.
- **Three of the 42 still need confirmation.** Quote 42 with that qualifier, or
  leave those three out and quote 39.
- **Most expiration dates are estimates.** Where a board said "twelve months",
  the calendar date is arithmetic. The map labels those dates *(estimated)*.
  Even a printed date can move: some moratoria end as soon as the ordinance work
  behind them is finished, and boards can vote to extend them.
- **34 counties counts land covered.** The Qualla Boundary spans five counties;
  counting it as a single jurisdiction gives 33.
- **This is an informative overlay.** It records what local governments have
  done. It does not assess whether any site is suitable, and it is not an
  exclusion filter.

## What's here

| File | |
|---|---|
| [`data/nc_data_center_moratoriums.csv`](data/nc_data_center_moratoriums.csv) | The research table — one row per jurisdiction, with dates, terms, rationale, confidence, and a source for each action. **The source of truth.** |
| [`data/nc_datacenter_moratoria.geojson`](data/nc_datacenter_moratoria.geojson) | The map layer, built from the table (WGS 84). |
| [`data/summary.json`](data/summary.json) | The counts above, recomputed on every build. |
| [`build/build_layer.py`](build/build_layer.py) | Joins the table to Census boundaries and writes the layer. |

## Rebuilding

```bash
pip install -r build/requirements.txt
python build/build_layer.py
```

Boundaries download from the U.S. Census Bureau on first run. Pushing a change to
the CSV rebuilds the layer, the summary, and the table at the top of this README
automatically.

Status is judged as of `RESEARCH_CUTOFF` in `build/build_layer.py`, not the day
the build runs. When you add newer research, move that date forward in the same
change; otherwise a moratorium adopted after it will show as ended. The notes
under *Before you quote a number* are written by hand and need updating too.

## How the records were built

Records were checked against agenda portals, adopted ordinances, and local
news, preferring primary government records where they could be retrieved. The
work corrected the source document it started from, which had attributed actions
by identically named counties in **Georgia, Florida, Texas, and Arkansas** to
North Carolina, and had labeled several city actions as county actions.

Every row carries a `confidence` rating for how well its dates are sourced, and a
`status` for whether the action happened at all. They measure different things:
a well-dated record can still be unconfirmed.

## Sources

- Jurisdiction records: the `source_url` column of the CSV.
- Boundaries: U.S. Census Bureau, 2021 cartographic boundary files (counties,
  places, and American Indian areas).

## License

Data in [`data/`](data/) is licensed under [CC BY 4.0](data/LICENSE.md): reuse it
freely, with credit. Code in [`build/`](build/) is licensed under [MIT](LICENSE).
Census boundary files are U.S. government works in the public domain.

**Suggested citation:** Childers, J. (2026). *North Carolina Data Center Moratoria*
[Data set]. https://github.com/joshchilders11-rgb/nc-data-center-moratoria

## Author

Josh Childers
