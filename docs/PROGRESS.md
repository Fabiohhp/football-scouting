# Progress

## Status

- **Phase 0, setup:** done (2026-10-06).
- **Phase 1, data collection:** done (2026-10-06).
- **Phase 2, data organisation and quality:** data model, minutes, linkage, quality tests and
  data dictionary done (2026-10-07). EDA notebook in progress: sections 1-3 (minutes and
  groups, reliability, league comparability) done on 2026-10-11, section 4 (market values) on
  2026-10-12.

Phase plan:
- Phase 2: analytical data model, minutes, positions, entity resolution, data quality, data
  dictionary, EDA notebook.
- Phase 3: statistical scouting analyses as notebooks (candidates: player profiles, an own xG
  model, possession value, role discovery, similarity search, market value and the
  recruitment back-test, team style, scouting reports, a recruitment case study).
- Phase 4: README for recruiters (findings and figures first), clean narrative notebooks, CI.

## Done

### Phase 0: Setup (2026-10-06)
- Repository structure, `uv` environment (Python 3.12, `uv.lock`), `.gitignore`, ruff + pytest
  config, Makefile, `config/pipeline.yaml`, README skeleton, `docs/`.

### Phase 1: Data collection (2026-10-06)
- `make verify-statsbomb`: competitions file and match lists verified; all counts as expected
  (380/380/380/377 + 34 Leverkusen-only Bundesliga matches). Download size estimated first.
- `make data` runs the whole phase, idempotently (a second run downloads nothing):
  - `download-statsbomb`: 3,102 files (events + lineups for 1,551 matches), 4,481 MB, each
    size-checked against the GitHub blob size. No 360 files exist for these matches.
  - `download-transfermarkt`: 7 gzipped CSV tables, 65 MB, with a provenance manifest.
  - `convert-statsbomb`: interim Parquet (359 MB): competitions, matches, lineups and events
    (5,436,699 rows) per competition-season. Integrity checks: index 1..n per match, unique
    event ids, 2 lineup rows per match, no orphan match ids.
  - `validate-statsbomb`: independent re-read of every raw file; key paths, row counts and xG
    sums all match the Parquet tables.
  - `coverage-report`: `reports/coverage_report.md`.
- `docs/DATA_SOURCES.md`: coverage, gaps, terms and attribution for both sources.
- Main findings:
  - StatsBomb and Transfermarkt agree on players who played in 2015/16 (2,176 vs 2,175 in
    the four pool leagues).
  - 97.5% of those Transfermarkt players have a valuation on or before 2016-06-30.
  - **Transfermarkt `transfers` is survivorship-biased** (no records at all for players with
    `last_season` before 2020; only 38% of 2015/16 -> 2016/17 club changes have a transfer
    record). Careers can be derived from `appearances` and the club on each valuation.
- 16 tests (config, fixture checks, downloader skip/size-check/atomicity with a mock HTTP
  transport, Transfermarkt manifest idempotency, JSON -> Parquet fidelity on sample files).

### Phase 2: Data organisation and quality (2026-10-07)
- Choices: real time on the pitch for minutes; 7 position groups; entity resolution on
  evidence (see `DECISIONS.md`, 2026-10-07).
- `make model`: processed tables (`build-tables`), Transfermarkt links (`links`), DuckDB
  views (`database`), `docs/DATA_DICTIONARY.md` (`dictionary`). ~20 s from the interim layer.
- Minutes: four data problems found and fixed (dismissals and substitutions not closing
  lineup stints, overlapping stints, starters mislabelled).
- Linkage: 100% of matches, teams and players who played; 2,505 high-confidence players,
  1 medium, 4 low (all checked and correct), 3 manual. Review file:
  `data/processed/links/player_match_review.csv`.
- `make dq`: 19 data quality tests (goals vs scores, starters vs Starting XI, never more than
  11 on the pitch, team time explained, events within time on the pitch, referential
  integrity, one-to-one links, every column documented). 38 unit tests in `make test`.

### Phase 2: EDA notebook `notebooks/01_data_exploration.ipynb` (2026-10-10 to 2026-10-12)
- Section 1, minutes and sample size: 2,176 pool players; 1,366 at 900 real minutes. Grouping
  test (AM + W chosen over AM + CM / W + CF), within-league sample test (percentiles pooled),
  age limit for the 450-minute rule (under 23).
- Section 2, reliability: split-half reliability for 17 metrics, K per metric
  (`analysis.reliability`); xG 0.56 and key passes 0.50 at 900 minutes; goals and dribble
  success mostly noise. Every player's rates will be shrunk by K.
- Section 3, leagues: attacking and passing numbers comparable across leagues; **Premier
  League recording change from 2015-12-28** (interceptions x3, pressures +18%, clearances
  +16%) and league differences in interceptions. Defensive numbers will be compared within
  five recording contexts.
- Section 4, market values: Transfermarkt revalues league by league; on 30 June 2016 values
  are about five months old, and the end-of-season revaluation (13 July to 1 August 2016)
  follows minutes played and already contains July's moves and Euro 2016. 97% of players are
  still valued a year later, 79% five years later. New helpers `analysis.values`.
- Data dictionary corrected: a valuation's `current_club_id` is often the player's 2026 club;
  the club name is the club at the valuation date (new data quality test).
- Decisions in `DECISIONS.md` (2026-10-11, 2026-10-12).
- Bugs caught while checking the numbers: NULL group minutes in `player_seasons` (fixed at the
  source, new data test), a ratio computed after rescaling in the notebook (fixed). Okazaki's
  date of birth filled (new override file, unit and data tests).
- `docs/DEVELOPMENT.md`: commands, conventions, rules and data pitfalls.
- 51 unit tests, 25 data tests.

## Next

1. The back-test cutoff (see open questions), then the remaining EDA analyses, one at a time:
   shots and xG, spatial checks, link quality.
2. Phase 3: the order of the scouting analyses.

## Open questions

- The back-test cutoff. The value on 30 June 2016 is what a club could see that summer but lags
  the season (median 142 days old); values from 1 August 2016 are fresh but contain July's
  moves and Euro 2016. Candidate rule: 30 June value as the market's view (feature), growth
  measured from 1 August 2016 (EDA section 4).
- How players no longer valued enter the back-test (an outcome, not missing data).
- The meaning of `transfer_fee` 0 vs null (free, loan, unknown) is still unverified.
- The two matches without fidelity metadata (3878540, 3900563) look normal in the checks so
  far.
- Before publishing: register interest at statsbomb.com/resource-centre (StatsBomb asks this
  of open-data users) and add the StatsBomb logo from its Media Pack.
