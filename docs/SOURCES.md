# Sources and access decisions

Decisions as of 14 October 2026. They are based on published terms, not on tests of
authenticated APIs or of how complete local listings are.

## Ingested

### Statistics Canada — Web Data Service (WDS)

- **14-10-0462-01** Labour force characteristics by economic region, three-month moving
  average, unadjusted for seasonality — https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1410046201
  - Measures: Employment, Employment rate, Unemployment rate
  - Population: total gender, 15 years and over (wherever those dimensions exist)
- **14-10-0441-01** Job vacancies, payroll employees, job vacancy rate, and average offered
  hourly wage by economic regions, quarterly, unadjusted for seasonality —
  https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1410044101
  - Measures: Job vacancies, Job vacancy rate
- Geographies: *Vancouver Island and Coast, British Columbia* (economic region), *British
  Columbia*, *Canada*.

Endpoints used (WDS user guide: https://www.statcan.gc.ca/en/developers/wds/user-guide):
`getCubeMetadata`, `getDataFromCubePidCoordAndLatestNPeriods` and `getCodeSets`. The code sets
supply the scalar, status, symbol and unit descriptions. A cached copy is used if a refresh
fails.

How the configured labels are matched is set out in `config/series.json`. The labels, vector
IDs and coordinates actually resolved are written to `data/official/*.json` on each successful
run.

Licence: [Statistics Canada Open Licence](https://www.statcan.gc.ca/en/terms-conditions/open-licence).
Required notice, as used on the page:

> Adapted from Statistics Canada, *[table name]*, *[reference date]*. This does not constitute
> an endorsement by Statistics Canada of this product.

Vacancy survey scope and quality: https://www150.statcan.gc.ca/n1/pub/75-514-g/75-514-g2024001-eng.htm

### Resolved series and verification (first live run, 14 October 2026)

These labels were resolved from WDS metadata by the Actions run of 14 Oct 2026 (17:07 UTC).

- **14-10-0462-01** has three dimensions: *Geography*, *Labour force characteristics* and
  *Statistics* (`Estimate` selected). It has **no gender or age dimension**, so the published
  totals are used as-is; the gender/age rules in the config only apply if such dimensions ever
  appear. Unit of measure is published as *Persons in thousands* (scalar *units*) for
  Employment and *Percent* for the rates.
- **14-10-0441-01** has two dimensions: *Geography* and *Statistics*. Units are *Number* and
  *Percent* (scalar *units*). Every value carries a quality grade (A–D). These are shown
  neutrally; `E` (use with caution) and `F`/`x`/`..` are shown as warnings.

| Series | Vector | Coordinate |
|---|---|---|
| Canada — Employment / Unemployment rate / Employment rate | v1642731724 / v1642731739 / v1642731745 | 1.3.1 / 1.8.1 / 1.10.1 |
| British Columbia — same | v1642733764 / v1642733779 / v1642733785 | 69.3.1 / 69.8.1 / 69.10.1 |
| Vancouver Island and Coast — same | v1642733794 / v1642733809 / v1642733815 | 70.3.1 / 70.8.1 / 70.10.1 |
| Canada — Job vacancies / Job vacancy rate | v1568395842 / v1568395844 | 1.1 / 1.4 |
| British Columbia — same | v1568395882 / v1568395884 | 11.1 / 11.4 |
| Vancouver Island and Coast — same | v1568396110 / v1568396112 | 80.1 / 80.4 |

Spot check: all 15 latest values were compared with Statistics Canada's own *download
selected data* CSV for each table, and every value, vector and unit matched. September 2026
(3-month average): Employment 21,274.7 / 2,949.0 / 455.1 thousand; unemployment rate 6.7 / 6.7
/ 5.8 %; employment rate 61.1 / 60.9 / 56.1 % (Canada / B.C. / VIC). Q2 2026: job vacancies
548,400 (A) / 89,810 (A) / 13,925 (B); vacancy rate 3.1 / 3.5 / 3.9 %. History available at
bootstrap: Oct 2023 – Sep 2026 (36 months) and Q3 2023 – Q2 2026 (12 quarters).

## Linked only (no collection)

| Source | Decision | Reason |
|---|---|---|
| Job Bank — https://www.jobbank.gc.ca/jobsearch/ | Link only | The job-seeker terms prohibit automated access. |
| WorkBC job search — https://www.workbc.ca/find-job/search-jobs | Link only | Permission to collect or republish was not established. Not assumed to be the same as Job Bank's terms. |
| CivicInfo BC careers — https://www.civicinfo.bc.ca/careers | Link only | RSS exists, but rights to keep and republish a public history were not established. Its terms reserve third-party rights. |
| WorkBC B.C. Labour Market Outlook — https://www.workbc.ca/labour-market/bc-labour-market-outlook | Labelled forecast link | A projection, not an observation. Not ingested. |

The links open each site's ordinary search page. No bookmarkable search URL with a location
filter was verified, so the page names the towns to type in instead of claiming a filter.

## Excluded

- **Adzuna API.** Its terms on ongoing use and aggregation, and its removal obligations on
  termination, are qualified. Permission to keep a permanent public archive was not established.
- **Individual employer or ATS feeds.** Out of scope.
