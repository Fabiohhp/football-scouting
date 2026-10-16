# Progress

## Status

- **Phase 0, setup:** done (2026-10-06).
- **Phase 1, data collection:** done (2026-10-06).
- **Phase 2, data organisation and quality:** data model, minutes, linkage, quality tests and
  data dictionary done (2026-10-07). EDA notebook done: sections 1-3 (minutes and groups,
  reliability, league comparability) on 2026-10-11, section 4 (market values) on 2026-10-12,
  section 5 (shots and xG) on 2026-10-13, section 6 (event locations) on 2026-10-14, section 7
  (link quality) on 2026-10-15.

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

### Phase 2: EDA notebook `notebooks/01_data_exploration.ipynb` (2026-10-10 to 2026-10-15)
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
  still valued a year later, 79% five years later; raw value growth is mostly age, and 2020's
  values are mostly a flat COVID cut. New helpers `analysis.values`.
- Back-test dates decided: market view on 30 June 2016, growth from 1 August 2016, outcomes on
  31 August 2017, 2018, 2019 and 2021 (`backtest` in the config).
- Section 5, shots and xG: shot data complete (37,888 shots, all with xG). StatsBomb xG runs
  about 4% below goals, the same in every league; direct free kicks and chances of 0.1 to 0.4
  xG are under-predicted, open-play shots under 0.06 over-predicted, but recalibrating barely
  changes rankings within groups (Spearman >= 0.995). Finishing (goals minus xG per shot) shows
  no skill in one season; xG per shot (shot selection) is stable (K about 28 shots). Shot volume
  and quality are close to independent within groups (Spearman -0.14 to +0.04). New ratios
  `xg_per_shot` and `finishing`; split-half reliability can be measured in shots.
- xG decided: StatsBomb's non-penalty xG as published; finishing does not rank players;
  profiles show shot volume and shot quality (shrunk) next to xG per 90.
- Section 6, event locations: coordinates are a 0.1-yard grid within 120 x 80 in every league;
  the direction is as documented (set pieces at their spots, 99.5% of events recorded by both
  teams mirrored exactly); the end of the stadium a team attacks shifts on-ball actions by 2.5
  yards across, balanced over a season; each position group acts where it should;
  location-based numbers (entries into the final third and the box, progressive passes and
  carries, height of defensive actions) are on one scale across leagues and unaffected by the
  Premier League's recording change. New helpers `analysis.leagues`; pitch figures with
  mplsoccer.
- Section 7, link quality: games played and name each single the player out for 93.6% of the
  2,279 pool links, and one decides where the other ties. Goals, cards and minutes, never used
  to match, agree in 99.96%, 99.79% and 99.52% (within two minutes) of the 42,056 player-matches
  both sources record. On five independent checks, 98.4% of the best alternative candidates
  disagree on two or more; six links do, all right on inspection, so at most about 3 of 2,277
  links are wrong (95% confidence). Every Transfermarkt player in a pool game is linked back.
  Transfermarkt's appearances cover 14 first divisions: 21% of pool players were outside them in
  2016/17 and 32% in 2020/21, still valued with their club named. New helpers `analysis.links`;
  two new data quality tests.
- Data dictionary corrected: a valuation's `current_club_id` is often the player's 2026 club;
  the club name is the club at the valuation date (new data quality test). Transfermarkt's
  `position` and `sub_position` are the latest position, marked as snapshot columns.
- Decisions in `DECISIONS.md` (2026-10-11 to 2026-10-14).
- Bugs caught while checking the numbers: NULL group minutes in `player_seasons` (fixed at the
  source, new data test), a ratio computed after rescaling in the notebook (fixed). Okazaki's
  date of birth filled (new override file, unit and data tests).
- `docs/DEVELOPMENT.md`: commands, conventions, rules and data pitfalls.
- 58 unit tests, 27 data tests.

## Next

1. Phase 3: the order of the scouting analyses.

## Open questions

- How value growth is scored in the back-test: raw growth is mostly age (EDA section 4.6), so
  against players of the same age and comparison group; the exact baseline is a Phase 3
  choice.
- How careers are scored in the back-test: Transfermarkt's appearances cover 14 first
  divisions only (EDA section 7.4), so a fifth to a third of pool players have no games on
  record in a given later season while still valued; values, the club named on each valuation
  and games in covered leagues are the candidates, to be chosen in Phase 3.
- The meaning of `transfer_fee` 0 vs null (free, loan, unknown) is still unverified.
- Location-based numbers for player profiles (progressive passes and carries, entries into the
  final third and the box): EDA section 6 used simple versions of the usual definitions; the
  final definitions are a Phase 3 choice.
- Before publishing: register interest at statsbomb.com/resource-centre (StatsBomb asks this
  of open-data users) and add the StatsBomb logo from its Media Pack.
