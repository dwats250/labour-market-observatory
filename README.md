# Labour Market Observatory

**Regional conditions and local job-search links.**

A small static dashboard showing official Statistics Canada labour-market conditions for the
**Vancouver Island and Coast economic region**, **British Columbia** and **Canada**. It also
links to current local job searches around Nanaimo, Parksville, Qualicum Beach, Ladysmith and
Duncan. It refreshes itself weekly and is designed to be left alone between visits.

## What it shows

| Measure | Table | Frequency |
|---|---|---|
| Employment, employment rate, unemployment rate | 14-10-0462-01 | Monthly, three-month moving average, not seasonally adjusted |
| Job vacancies, job vacancy rate | 14-10-0441-01 | Quarterly, not seasonally adjusted |

The page shows each current value with its change from the same period a year earlier.
Rates change in percentage points and counts in percent. Below that are charts of the last
24 months or 8 quarters, a full table of historical values, and a print button that uses the
browser's print / Save as PDF.

**Limitation.** This release does not collect job advertisements, so it cannot show changes in
advertised occupations, employers, skills or salaries. The official figures here are not a
substitute for those questions. Use the *Look locally* links to search current listings.

## How it works

```
config/series.json            series wanted, by published Statistics Canada label
src/collect.py                WDS fetch → validate → merge → data/ + report
src/build.py                  data/ → site/index.html (static, ~5 KB of JS)
data/official/*.json          canonical observations (the database)
data/status.json              last attempt / last successful check per dataset, revision log
reports/YYYY-Www.md           weekly reading copy (never parsed back)
.github/workflows/weekly.yml  collect → test → build → commit → deploy Pages
```

- **No hard-coded vector IDs.** On every run the collector reads the cube metadata from the
  Statistics Canada Web Data Service (WDS). It finds each member by its published label and
  builds the coordinate from those members. The vector ID, coordinate and labels it resolved
  are recorded in `data/official/*.json` and shown under *Sources and method*. If a configured
  label disappears, that dataset fails loudly and lists the labels that are available.
- **Bounded window.** Each run re-fetches the latest 36 months and 12 quarters. History older
  than that window is kept.
- **Revisions.** Observations are keyed by series and reference period. A changed value
  replaces the stored one, gets a new `lastChanged` time and is listed in that week's report.
  Unchanged values are never duplicated. Git history preserves every earlier retrieved
  version. These are *not* point-in-time vintages.
- **Suppression.** If a value is newly published as suppressed (`x`, `F` …), it replaces the
  earlier number and is shown as unavailable.
- **Failure isolation.** The two datasets are fetched independently, with timeouts and three
  bounded retries. A transport error, malformed payload or missing series keeps that
  dataset's last-good file and records `lastResult: failed`. The page then shows a
  degraded-status notice, and the workflow run fails *after* the page has deployed.
- **Overdue warning.** The visitor's browser compares each dataset's last successful check
  with the current time. After 14 days it shows *Collection check overdue*, so a stalled
  schedule is visible without a new deployment. Timestamps stay readable without JavaScript.
  An old quarterly reference period on its own is not treated as a failure, because vacancies
  are published about three months after each quarter.

Report week convention: **ISO week in America/Vancouver time** (e.g. `2026-W42`). A rerun in
the same week replaces that week's report. Internal timestamps are UTC.

## Local commands

Python 3.10+ standard library only. No install step.

```sh
python3 -m src.collect                         # fetch real data into data/ + write report
python3 -m src.build                           # build site/ from data/
python3 -m http.server -d site 8000            # preview at http://localhost:8000
python3 -m unittest discover -s tests -t .     # focused data/failure tests
python3 -m tests.preview                       # SAMPLE-labelled layout preview in preview/ (synthetic, never deploy)
```

## Operations

- **Schedule:** Saturdays 17:17 UTC (`.github/workflows/weekly.yml`). Pushes that change
  `src/`, `config/`, `tests/` or the workflow also run it and redeploy.
- **Manual refresh / recovery:** GitHub → *Actions* → *Weekly check* → *Run workflow* on
  `main`. Use this after a failed or skipped run. It re-fetches the whole bounded window, so
  missed weeks fill themselves in.
- **Pages:** *Settings → Pages → Build and deployment → Source: GitHub Actions*. The workflow
  deploys Pages itself. It does not rely on bot commits to trigger another build.
- **Permissions:** only `GITHUB_TOKEN`, with `contents: write` for the data commit and
  `pages: write` + `id-token: write` for the deploy. There are no personal tokens and no
  force pushes. If the branch moved during a run, the push is rejected and the run fails
  without overwriting anything. Re-run it.
- **Known GitHub behaviour:** scheduled runs can start late or occasionally be dropped under
  load. GitHub also disables scheduled workflows in public repositories after 60 days without
  repository activity. The weekly data and report commits count as activity. If the schedule
  is ever disabled, re-enable it on the Actions tab and run it manually. Either way, the
  dashboard's own overdue warning will show the gap.

## Data licence and attribution

Adapted from Statistics Canada, Tables 14-10-0462-01 and 14-10-0441-01 (reference periods as
shown on the page). This does not constitute an endorsement by Statistics Canada of this
product. The data are used under the
[Statistics Canada Open Licence](https://www.statcan.gc.ca/en/terms-conditions/open-licence).
See [docs/SOURCES.md](docs/SOURCES.md) for source decisions.

The code is MIT-licensed (see `LICENSE`). That licence does not cover the Statistics Canada
data.
