# Progress

## Status

- **Phase 0, setup:** done (2026-10-06).
- **Phase 1, data collection:** done (2026-10-06).
- **Phase 2, data organisation and quality:** data model, minutes, linkage, quality tests and
  data dictionary done (2026-10-07). EDA notebook done: sections 1-3 (minutes and groups,
  reliability, league comparability) on 2026-10-11, section 4 (market values) on 2026-10-12,
  section 5 (shots and xG) on 2026-10-13, section 6 (event locations) on 2026-10-14, section 7
  (link quality) on 2026-10-15.
- **Phase 3, scouting analyses:** started 2026-10-17 (scope and order in `DECISIONS.md`).
  Player profiles: section 1 on 2026-10-17, sections 2 (possession) and 3 (the profiles) on
  2026-10-18. Possession value: section 1 (the xT map) and section 2 (a player's xT: how to count
  it, possession, what it adds to the profiles) on 2026-10-19, section 3 (expected pass
  completion) and section 4.1 (candidates for the profiles) on 2026-10-23, section 4.2 (the
  profiles with possession value) on 2026-10-24. Market value and the recruitment back-test:
  section 1 (what the market paid for) on 2026-10-24, sections 2 (what happened next), 3 (the
  back-test) and 4 (shortlists) on 2026-10-25.

Phase plan:
- Phase 2: analytical data model, minutes, positions, entity resolution, data quality, data
  dictionary, EDA notebook.
- Phase 3: statistical scouting analyses as notebooks, in order: player profiles, possession
  value (xT), market value and the recruitment back-test, role discovery, similarity search and
  replacements, team style, a recruitment case study with scouting reports.
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

### Phase 3: Player profiles `notebooks/02_player_profiles.ipynb` (from 2026-10-17)
- Section 1, which numbers describe a player: 46 candidate statistics in seven families
  (`analysis.metrics`), among them xA, long passes, switches, through balls, aerial duels,
  counterpressures, ball losses per touch and progressive passes and carries under three rules.
  Reliability at 900 minutes measured within each comparison group: it depends on the group (xG
  per 90 0.66 among attacking midfielders and wingers, 0.18 among centre-backs; aerial duels won
  0.74 among centre-forwards, 0.33 among centre-backs); cross completion, dribble success,
  dribblers tackled and finishing are noise in every group. Fouls won and times dribbled past
  carry league gaps (refereeing, opposition); the team explains passing volume (0.48) and pass
  completion (0.38) most. Progressive passes: the 10-yard rule mostly re-counts passing volume
  (Spearman 0.84 with passes, team share 0.21); zones and 25% closer measure progress (0.60,
  0.08). Twelve statistics per group, none correlated at 0.8 or more with another.
- Decided (`DECISIONS.md`, 2026-10-18): twelve statistics per group (`profiles` in the
  config), Wyscout's zones for progressive passes and carries, fouls won and times dribbled past
  left out, counterpressures and pressures in the final third within recording context, and
  shrinkage with one K per statistic and comparison group.
- Section 2, possession: time with the ball (gaps between events capped at 10 s) agrees with
  the share of passes (0.97 per match); teams range from 39% (Carpi) to 65% (Barcelona) over the
  season. Season figures tie the statistics made with the ball to possession (open-play passes
  0.74 to 0.84 among defenders and central midfielders) but cannot tell possession from the
  players a team with the ball can afford, so the dependence is measured within players
  (Poisson with a fixed effect per player): counts with the ball grow faster than the team's
  time with it (progressive passes 1.23 to 1.48), except forwards'; counts without the ball
  grow more slowly than the opponent's time (tackles 0.16 to 0.51); recoveries and
  centre-backs' aerial duels rise with the team's own possession. Adjusting by these
  elasticities takes possession out of both kinds (median correlation 0.10 and 0.02) at a small
  cost in reliability (one statistic below 0.4: full-backs' key passes, 0.35); in proportion to
  the time, and StatsBomb's PAdj far more, overshoot on defensive counts. On 31 players who
  changed teams, the elasticities predict the right size of change (slope 0.97, 95% interval
  0.50 to 1.59), PAdj changes five times too large. Pass completion, not adjusted, still
  depends on the team (team share 0.41 to 0.60 among defenders and central midfielders).
- Decided (`DECISIONS.md`, 2026-10-18): possession as time with the ball; each per-90 statistic
  adjusted by its group's measured elasticity, ratios as recorded; full-backs' key passes kept;
  pass completion as recorded until an expected completion is tested with the possession value
  model.
- Section 3, the profiles: 1,335 outfield players (69 through the under-23 rule) read through
  their group's twelve statistics after recording context, possession and shrinkage, as
  percentiles within the group. Recording context moves the percentiles of the statistics it
  touches the most (a median 8.6 points), possession 3.4, shrinkage 0.7 (3.3 for players under
  23 with fewer than 900 minutes). On players with 1,800+ minutes, part of a season shrunk by
  the group's K forecasts the rest 21% to 28% better (squared error); the group's K beats one K
  where reliability differs between groups (centre-forwards' aerial duels won, centre-backs'
  ball losses per touch). Shrinkage barely changes the order of players, but 450-minute players
  fill 39% to 45% of the predicted top 10% instead of 56% to 59%, where they are half the
  players. Five example profiles (pizza charts) and the top five of each group read like the
  players (Kanté first in tackles and interceptions).
- Decided (`DECISIONS.md`, 2026-10-18): goalkeepers have no profile and are left out of the
  back-test; the four steps and their details; the profiles as processed tables
  (`make profiles`, part of `make model`); who is compared and the recording contexts in the
  config (`compared`, `recording`). Three statistics were later replaced by possession-value
  numbers (notebook 03, section 4.2); the notebook builds and reads the profiles as chosen here
  (`Config.count_profiles`).
- New helpers: `metrics.FAMILIES`, `metrics.progressive`, `leagues.team_effect`,
  `analysis.possession`, `analysis.profiles`; `reliability.split_half_reliability` takes a rate
  function. New processed tables `profile_players`, `profile_values`, `profile_statistics` and
  `profile_recording`. 78 unit tests, 34 data tests (new: progressive rules, team effect against
  chance, profiles name known statistics, possession time on toy matches, the within-player
  elasticity against a confounded simulation, the new counts reconcile with the event tables,
  aerial duels won equal lost in every match, possession time adds up between teams and
  players, the profile steps on toy data, the processed profiles follow their rules).

### Phase 3: Possession value `notebooks/03_possession_value.ipynb` (from 2026-10-19)
- Section 1, the xT map: expected threat from 2,577,884 open-play actions (passes, carries,
  shots, ball losses), checked on held-out matches against the xG each action's chain went on
  to reach (`analysis.xt.chain_outcomes`). The textbook model (shots and moves) overstates it by
  46%; dispossessions, miscontrols and failed dribbles, which hand the ball over 80% to 93% of
  the time, bring it to 13% below and lift held-out skill from 0.081 to 0.092, level with each
  zone's mean outcome, halving the worth of the build-up against the final third. Skill rises
  with finer zones down to 2.5 yards and stops at 2. Both wings match within noise; the leagues
  share the map's shape, with La Liga's chains reaching 5.9% more xG from the same zones and
  Ligue 1's 5.9% less; shots valued by goals give the same map with more noise. xT: 0.004 at
  the centre spot, 0.046 at the edge of the box, 0.118 on the penalty spot.
- Section 2.1, a player's xT: three ways of counting the credit of a player's passes and
  carries per 90, among 1,335 outfield players with a profile. xT gained (moves to a zone worth
  less count 0) is the most reliable in every group (0.55 to 0.75 at 900 minutes), net xT
  (Singh's, moves backwards counted against) slightly less (0.50 to 0.71) and ranks players
  almost the same (0.91 to 0.99), but sinks forwards who lay the ball off; charging failed passes
  and ball losses halves the reliability (0.30 to 0.54), as what players give away rises with
  what they make. The median full-back gains more than the median central midfielder; carries
  bring 18% of a centre-back's xT and 48% of a centre-forward's.
- Section 2.2, possession and the team: within players, xT gained grows faster than the time
  with the ball among defenders and central midfielders (elasticity 1.50 to 1.81), half as fast
  among centre-forwards (0.47). Adjusted by the measured elasticity, its correlation with
  possession falls from 0.24-0.47 to -0.03-0.19 and the team's share from 0.17-0.33 to at most
  0.18, at 0.03 to 0.07 of reliability. The league explains 1.3% of it within group.
- Section 2.3, what xT adds to the profiles: the group's twelve profile statistics predict 67% to
  87% of xT gained out of sample, through progressive passes and carries, passes into the box and
  key passes. The part they miss has a reliability of -0.02 to 0.28 at 900 minutes, below what
  almost every profile statistic adds to the other eleven (median 0.40 to 0.46). Among
  full-backs xT correlates with completed passes into the box at 0.87, past the profiles' limit
  of 0.8, and is more reliable (0.49 against 0.40 at 900 minutes).
- Section 3, expected pass completion: gradient-boosted trees on what is known when a pass is
  played, every pass scored by a model fitted on other matches (held-out AUC 0.883, log loss
  0.343 against 0.533 for the average; calibrated in every league). End locations are left out:
  an incomplete pass ends where it was cut out. Completion as recorded mostly measures the ease
  of a player's passes (Spearman 0.90 to 0.95 with their mean expected completion); completion
  above expected takes it out and stays reliable (0.47 to 0.63 at 900 minutes), with less of the
  team (team share 0.11 to 0.35 against 0.14 to 0.61). It still rises with possession within
  players (0.8 to 1.3 points per 10 points of the team's share); on an even share its
  correlation with possession falls from 0.30-0.46 to 0.13-0.19, at 0.03 to 0.10 of reliability
  (0.40 to 0.60).
- Section 4.1, candidates for the profiles: each swap judged on reliability, the strongest
  correlation with the eleven statistics left, and the reliability and team share of what it
  adds to them. Pass completion as recorded is steadier than completion above expected (0.79 to
  0.87 against 0.40 to 0.60 at 900 minutes; what it adds 0.40 to 0.53 against 0.24 to 0.45) but
  measures the ease of a player's passes and, among defenders, the team (0.38 and 0.23 of what it
  adds, against 0.13 and 0.09). xT adds more than the statistic it replaces among
  centre-forwards, in place of completed passes into the box (0.30 against 0.13), and narrowly
  among central midfielders, in place of key passes (0.29 against 0.26); it repeats the other
  groups' profiles.
- Section 4.2, the profiles with possession value: completion above expected in place of pass
  completion in every group, xT in place of completed passes into the box (centre-forwards) and
  key passes (central midfielders), built by `make profiles` through the four steps. The tables
  reproduce sections 2.2 and 3.2 (largest difference 6e-17). The rules hold (closest pair 0.63
  to 0.74, the same families); completion above expected is the least reliable statistic of
  three profiles (centre-backs 0.399) and is shrunk harder than pass completion (K of 595 to
  1,356 minutes against 135 to 244), xT less than the statistics it replaces (471 and 509
  against 792 and 1,137). Percentiles move: Spearman 0.49 to 0.70 between pass completion and
  completion above expected, a fifth to a third of players by 25 points or more (Stones from the
  95th percentile of centre-backs to the 56th, Kanté from the 52nd to the 90th of central
  midfielders); 0.73 and 0.74 for xT.
- Decided (`DECISIONS.md`, 2026-10-19): open play only, ball losses counted, zones of 2.5
  yards, one map for all four leagues, shots valued by their xG; a player's xT is the xT gained
  by their successful passes and carries (`xt` in the config), put on an even share of
  possession by its elasticity within the comparison group; the four leagues on one scale.
  2026-10-23: the expected pass completion model (boosted trees, end locations and the switch
  flag left out, every pass scored by a model fitted on other matches); completion above
  expected put on an even share of possession by its within-player slope. 2026-10-24:
  completion above expected in place of pass completion in every profile, xT in place of
  completed passes into the box (centre-forwards) and key passes (central midfielders); the
  ease of a player's passes left for role discovery; no VAEP before the back-test.
- New helpers `analysis.xt` and `analysis.xpass`; `analysis.profiles` builds the possession-value
  numbers (`value_sums`, `profile_rates`, `possession_effects`). 93 unit tests, 42 data tests
  (new: the map
  solved by hand on two zones, chains broken by the opponent, set pieces and the half, a
  player's credit in the three versions, folds that keep matches together, passes scored only
  by models that never saw their match, the within-player possession slope; the actions and
  passes reconcile with the event tables, every action has a chain outcome, the map peaks in
  front of goal and mirrors, players' credit adds up to the moves, incomplete passes end where
  they were cut out, switches are flagged only when the ball crossed, the possession-value
  numbers in the profiles on toy data, the profiles as chosen from the event counts, the
  processed completion above expected follows its slope).

### Phase 3: Market value and the recruitment back-test `notebooks/04_recruitment_backtest.ipynb` (from 2026-10-24)
- Section 1, what the market paid for: the 1,335 profiled players' Transfermarkt values on 30
  June 2016, mostly winter values (a median 142 days old; one in eight, almost all the Euro 2016
  squads, set after the season). A ridge regression of log value per comparison group, judged
  with teams held out: age, minutes and league explain 29% to 43%, the team's goal difference per
  match (better than points) takes it to 62% to 73%, and the twelve profile statistics then add
  at most 0.03 (0.12 to 0.25 without the team); boosted trees do worse (0.57 to 0.64). Other
  things equal, values peak at 22 or 23 (27 to 28 for central midfielders) and halve by 32;
  ten more full matches add 16% to 49%, half a goal of goal difference per match 45% to 51%; La
  Liga and Serie A pay a half to two thirds of the Premier League's price, Ligue 1 a third.
  Within the profile the market paid for attacking output and the ball (xG, xT, dribbles, long
  passes, completion above expected; at most a quarter more per standard deviation), nothing
  for tackles, interceptions or pressures. The gap between the model and the value, within team
  (unrelated to the team's strength) or across teams (mostly the team's strength, -0.46 to
  -0.57), agrees with Transfermarkt's own revaluation after the season (0.32 and 0.26; minutes
  alone 0.24): young players breaking through at strong teams, Leicester's champions still on
  February values, veterans; across teams, small clubs' regulars. Under a €5M ceiling the two
  gaps' lists cost the same; the list across teams takes half its players from the weakest fifth
  of teams, the list within team spreads over all five, a fifth of it at the strongest teams.
- Decided (`DECISIONS.md`, 2026-10-24): the value model, its checks with teams held out, and
  the two gaps; the back-test reads the gap within team first, keeps the gap across teams as a
  check, tests picking by the team's weakness alone as a baseline, and the shortlists leave out
  the strongest teams' players.
- Section 2, what happened next, scored before any prediction is checked: values on 1 August
  2016 against values one, two, three and five years on (92% of the profiled players still
  valued three years on, 81% five years on). Age explains 24% to 43% of value growth (players
  under 21 worth 2.7 times as much three years on, aged 31 or 32 a quarter), so growth is scored
  as a percentile within two-year age bands, players no longer valued at the bottom; the score
  ranks the players still valued like growth above an age curve (0.93 to 0.98) and barely
  depends on position or league (45 to 54). Players no longer valued are mostly veterans (83%
  of those 33 and over five years on) and rarely come back. Careers from the appearances: 79% of
  the players were in the big five one year on, 42% five years on (64% of those under 23);
  regulars in the big five score 59 to 70 on value growth, the rest 36 to 42.
- Section 3, the back-test, judged as fixed before the results: the top 10% of each group by the
  gap within team (133 players) rank on average at the 63rd percentile of their age band three
  years on (90% interval 56 to 68), 12 points above all players, and at 60 to 64 at every
  horizon. The players with the most minutes in 2015/16 do as well (61.7) with a different
  list (16 players shared); the model without the profile picks 99 of the same players and
  scores 61.3, so the twelve statistics add nothing detectable. Cheap or young players alone are
  close to average (53.4, 52.1), the weakest teams' regulars below it (47.3). The gap and
  minutes are independent and add up (about 15 points of score each from the bottom of the
  group to the top; the 16 players in both picks score 76). The gap's players kept careers
  typical for their age: their values caught up with their numbers.
- Decided (`DECISIONS.md`, 2026-10-25): value growth scored within age bands, the back-test read
  three years on first, careers as secondary outcomes, a player's level read from their
  appearances; how the back-test is judged (the pick, the baselines, the checks, the intervals).
- Section 4, shortlists: the five largest gaps within team of each group among the 808 players
  valued at €5M or less on 30 June 2016 outside the strongest fifth of teams. The 25 players were
  young (a median 24.5), cheap (a median €0.6M) and mostly short of minutes (8 at their group's
  median or more). Three years on they rank on average at the 73rd percentile of their age band
  (72.9, 90% interval 60.8 to 81.8), 24.6 points above all players within the budget (13.1 to
  32.6), at budgets of €2M to €10M, with five or ten players per group (67.7 to 74.0) and at
  every horizon (65.1 to 75.7); in Transfermarkt values, €21.9M on 30 June 2016 and €188.2M
  three years on (all players within the budget: 1.6 times). The gap without the profile
  scores the same (72.6); the most-minutes shortlist 65.6 (the gap ahead by 7.3, -7.3 to 19.2).
  Thirteen players scored 90 or more (Diop, Pellegrini, Piccini, Skhiri, Inglese, Wanderson,
  Josef Martínez among them), six under 50, four of them attackers, two with teams relegated in
  May 2016. The players of the 12 relegated teams score 45.3 three years on, the others 51.2.
  The score counts growth after Transfermarkt's revaluation of July 2016, which had already
  raised the shortlisted players' values by a median 1.67 times.
- Decided (`DECISIONS.md`, 2026-10-25): the shortlists' budget, the players left out, their
  length, and the gap within team alone as their ranking (minutes shown beside it).
- New helpers `analysis.market`, `analysis.outcomes` and `analysis.backtest`; new back-test
  settings in the config (`primary_horizon`, `age_bands`, `big_five`, `regular_minutes`,
  `champions_league`). 112 unit tests, 49 data tests (new: picks of the top share or a set
  number of each group, ties at the edge, rankings by several keys, picks made afresh on resamples; team strength on toy matches, profiles standardised within group,
  folds and resamples that keep teams together, out-of-fold predictions never from a model that
  saw the team, a model read one column at a time, value growth until a player is no longer
  valued, age bands, scores within groups, excess growth, careers read from the season before
  each horizon, club names linked through the players; every profiled player has a team and a
  value on the market view, team strength adds up over each match, every profiled player has an
  outcome at every horizon, players no longer valued score lowest in their band, levels follow
  the minutes, club names find their clubs, one league per club and season).

## Next

1. Role discovery (`notebooks/05_role_discovery.ipynb`): roles within each comparison group
   from the profiles, named, and checked for stability.

## Open questions

- Team style (Phase 3): whether a line-up can be fitted to the opponent from one season, for
  instance a midfielder who intercepts more against teams that risk their passes. A team's risk
  can be read from the ease of its passes (mean expected completion, notebook 03); whether a
  player's defensive counts rise against riskier opponents more than other players' would be
  measured within players and recording context, and checked for reliability.
- How the back-test treats short samples: shrunk values rank players with few minutes
  conservatively (450-minute players fill 39% to 45% of a group's predicted top 10% where they
  are half the players), which is right on average but can bury a young player with strong
  numbers. Ranking young players also by an optimistic bound is a back-test choice.
- The meaning of `transfer_fee` 0 vs null (free, loan, unknown) is still unverified.
- Before publishing: register interest at statsbomb.com/resource-centre (StatsBomb asks this
  of open-data users) and add the StatsBomb logo from its Media Pack.
