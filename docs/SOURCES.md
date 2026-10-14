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
