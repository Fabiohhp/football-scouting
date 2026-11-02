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
  back-test) and 4 (shortlists) on 2026-10-25. Role discovery: section 1 (which numbers
  describe a role) on 2026-10-27 and 2026-10-28, section 2 (roles or a continuum) on
  2026-10-28; both read again from a player's own position on 2026-10-29; sections 3 (names and
  portraits of the style axes) and 4 (styles, the market and the back-test) on 2026-10-29, then
  the style as processed tables. Similarity search: section 1 (how alike) on 2026-10-29,
  sections 2 (what similarity follows) and 3 (replacements) on 2026-10-30. Team style: sections 1
  (how a team plays), 2 (team style axes) and 3 (players within teams) on 2026-10-30, sections 4
  (fit) and 5 (against which opponents, an addendum) on 2026-10-31. Recruitment case study: the
  scenario and its rules, sections 1 (the vacancy), 2 (the long list), 3 (the shortlist) and 4
  (the recommendation and the scouting reports) on 2026-11-01, section 5 (what happened) on
  2026-11-02.

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

### Phase 3: Role discovery `notebooks/05_role_discovery.ipynb` (from 2026-10-27)
- Section 1, which numbers describe a role: 27 candidate descriptors in five families
  (`analysis.style`), shares and places rather than volumes (where a player touches the ball,
  what they do with it, how they pass, with which foot, how they defend), for the 1,335 profiled
  players, counts rescaled by recording context, read from the matches each player spent mainly
  in a position of their group (88% of player-matches, 91% of minutes; 1,176 regulars) with
  spreads measured within each match. They are at least as stable as the profiles' statistics
  (median reliability at 900 minutes 0.62 to 0.80 by group, against 0.61 to 0.71; the same for
  centre-backs and centre-forwards); the foot a player passes with is fixed (0.99 to 1.00).
  Within players, ten more points of possession raise touches by 2.3 to 3.8 yards and defensive
  actions by 3.6 to 5.9; on an even share by these slopes, places and pressing no longer follow
  possession, at no cost in reliability (median change -0.002). Where defenders play and how they
  pass stays partly the team's: centre-backs' and full-backs' touch height, pass ease and high
  passes, centre-backs' spreads and aerial duels keep a team share of 0.40 to 0.52. The 22
  players who changed team in January kept about three quarters of the correlation their
  numbers' reliability allowed: foot, carrying, passing length and crossing moved with them, the
  height of their defensive actions, clearances and tackles did not. Pass length and long passes
  (0.92 to 0.97) and pass ease and high passes (-0.81 to -0.92) repeat each other; shares of
  actions follow the profile's counts per 90 (dribbles 0.90 to 0.96, tackles 0.84 to 0.90),
  places, passing shape and foot are new. The profile's first principal component sets two ways
  of playing each position against each other (passers against aerial defenders among
  centre-backs) and barely follows the team's goal difference (0.02 to 0.28) or market value
  (0.02 to 0.37).
- Section 1.5, the descriptors chosen (`DECISIONS.md`, 2026-10-28 and 2026-10-29): style is read
  from the descriptors, not the profile, on an even share of possession; each group keeps those
  reliable at 0.5 or more, with a team share under 0.4 and no pair at 0.8 or more, the left foot
  left out as a side and the inside foot too where the flank explains half of it (centre-backs,
  full-backs, central midfielders: R² 0.68 to 0.88): 9 for centre-backs, 16 for full-backs, 21
  for central midfielders, 20 for attacking midfielders and wingers, 19 for centre-forwards
  (`roles.descriptors` in the config).
- Deployment (2026-10-29): read over whole seasons, three of the first version's 18 axes
  measured how a player was deployed (centre-backs' high-and-wide axis followed minutes outside
  centre-back at 0.54; two axes followed time on both flanks at 0.64 and 0.66). Reading each
  player's matches in their group's positions, spreads within match and the inside foot as a
  side removed it (at most 0.35).
- Section 2, roles or a continuum (`DECISIONS.md`, 2026-10-28 and 2026-10-29): the descriptors,
  shrunk by their reliability, show no discrete roles. Gaussian mixtures of 2 to 7 roles under a
  rule fixed beforehand (lowest BIC, every role at least 10% of the regulars, refits on random
  halves reproducing it at an adjusted Rand index of 0.6): no mixture is reproduced in any group
  (two roles at most 0.57, central midfielders; three or more at most 0.44). Style is read
  instead on varimax-rotated principal components: three axes for centre-backs, full-backs and
  centre-forwards, four for central midfielders and attacking midfielders and wingers (parallel
  analysis, then reliability 0.7 and congruence 0.85 averaged over 20,000 random halves: over
  fewer the mean moved enough to decide centre-forwards' fourth axis, 0.845 ± 0.001, by
  chance), reliable at 0.72 to 0.89, congruence 0.86 to 0.99, 52% to 66% of the variation. The
  recorded positions are told apart at a balanced accuracy of 0.57 to 0.75 and place players on
  only three axes; the team explains up to 0.48 of an axis (full-backs who attack the box), most
  under a quarter; long-passing axes lean against possession (-0.28 to -0.34).
- Section 3, names and portraits (`DECISIONS.md`, 2026-10-29): each axis is named by its two
  ends (for instance deep pivot ↔ advanced midfielder, inside forward ↔ touchline winger, target
  man ↔ mobile forward, ball-carrier ↔ direct passer among centre-backs), checked against the
  players at either end (1,800 minutes or more), the recorded medians of the bottom and top
  deciles and where they touch the ball (`style.touch_map`, each match mirrored to the player's
  side). Seven axes move 14% to 35% of touches between their ends (two random groups of
  regulars: 4% to 6%); the other ten, 7% to 12%, set apart how players pass, carry and defend,
  and three of them are no further apart on a touch map than random groups. 94% of centre-backs'
  touches in the opposition box come after a corner or a free kick, and the ends of two axes
  differ in who takes the set pieces.
- Section 4, styles, the market and the back-test (`DECISIONS.md`, 2026-10-29): the market priced
  no style beyond a player's numbers and context (the axes lower notebook 04's out-of-sample R²
  by 0.001 to 0.009; no axis follows the gap within team beyond ±0.10), and no correlation with
  growth three years on passes Holm's correction over the 34 (10,000 resamples of teams).
  Centre-forwards who lay the ball off grew less than those who pass it forward (-0.21, Holm
  0.16), steadily across horizons and beside minutes and the gap. The 25 shortlisted players
  have no style in common (10 at an end of an axis, about 13 by chance).
- New helpers `analysis.style` and `analysis.roles`; `metrics.TOUCH` (the touch condition,
  shared); `roles` in the config. 126 unit tests, 54 data tests (new: descriptors as shares and
  places, spreads as standard deviations within matches, the share of a match spent in the
  player's group, touch maps mirrored to the same side in each match, defensive shares built from rescaled parts, possession slopes within players
  against a confounded simulation; the style sums reconcile with the event tables, descriptors
  stay in range, spreads within matches are at most the season's, every match played has its
  group share; roles: shrinkage, a mixture finding separated roles numbered by height, parallel
  analysis against shuffled data, varimax at the best rotation, axis scores standardised and
  uncorrelated, congruence of clear axes).
- The style as processed tables (`DECISIONS.md`, 2026-10-29): `make profiles` builds
  `style_values`, `style_descriptors`, `style_axes`, `style_loadings`, `style_scores` and
  `style_recording` (`roles.build_style`; the names of the axes' ends are `roles.names` in the
  config), and notebook 05 checks them against its own fit. 57 data tests (new: every profiled
  player has their group's descriptors and axes, shrunk descriptors lie between the player and
  the group, scores are standardised and uncorrelated among the regulars with the loadings as
  their correlations).

### Phase 3: Similarity search `notebooks/06_similarity_search.ipynb` (from 2026-10-29)
- Section 1, how alike: a distance is judged by whether it finds a player again in the other
  half of their season (matches dealt alternately in date order; 576 players with 900 minutes or
  more in their group's positions in each half, each half placed on the season's terms). Style
  axes and profile together, each block of equal weight, find the player's own half first 59% of
  the time (chance 0.9%), the profile alone 43%, the axes alone 25%. Whitening the profile block
  (Mahalanobis) costs 6.4 points (-9.2 to -3.8), so the Euclidean distance is kept by the rule
  fixed beforehand. The style descriptors in place of the axes reach 73% (70% to 76%), more in
  every group, and the search uses them: style descriptors and profile, equal weight, Euclidean.
  The axes stay to describe how two players are alike. The 22 players who changed team in
  January are found again across their two clubs half as often as across alternating halves
  (34% against 64% with the descriptors, 25% against 50% with the axes).
- Section 2, what similarity follows: among a regular's five nearest regulars (1,176 players),
  teammates come up 2.6 times as often as by chance (2.9% against 1.1%; 14% of the lists of five
  hold one), through the descriptors (2.7 times) more than the profile (1.75); the same league
  1.28 times, the same line 1.29 times (central midfielders 75% against 53%), the same side 1.06
  times. Short samples drawn from the tested players' halves: top 5 92% on a full half, 90% at
  900 minutes, 79% at 450, 67% at 270; at 450 minutes 0.88 of the top 5 at 900, so young players
  with 450 to 899 minutes join the candidates by the rule fixed beforehand. A short sample comes
  in more of the other players' lists of five than a full half (7.4 at 450 minutes, 9.8 at 270,
  against 5), so young players are listed apart from the regulars.
- Section 3, replacements: the search as a function (`similarity.similar`): two lists (1,176
  regulars, 84 young players), teammates left out, filters by age, league, market value on 30
  June 2016, foot (left-footed from half of the passes; 908 candidates under 30%, 300 over 70%)
  and side; each candidate with the style axis ends shared with the player and the profile
  statistics furthest apart. Examples: the most valuable regular of each group who changed club
  for 2016/17 (David Luiz, Šime Vrsaljko, Paul Pogba, Memphis Depay, Gonzalo Higuaín). Their
  nearest regulars are worth a median of €2M to €25M beside €13M to €70M; four of the six nearest
  to Vrsaljko, a right-back, play on the left, so side is a filter. What clubs did: in 195 pairs
  of a regular who left and a player of their group their club signed for 2016/17 (137 regulars,
  58 clubs), the player signed sits at a mean share of 0.50 of the list (0.46 to 0.54 over 2,000
  resamples of clubs), 8% in the nearest tenth (4% to 12%) against 10%: where chance puts them,
  with the descriptors alone (0.49) or the profile alone (0.51), in every group. Nor by position:
  the same line 0.98 times as often as by chance (0.83 to 1.14), the same side 0.94 times
  (full-backs 51% against 50%). By market value the players signed come early (a mean share of
  0.37, 0.33 to 0.41; 16% in the nearest tenth): the pairs follow the club's price level more
  than the player who left, so they cannot tell whether clubs replace a player by style.
- New helpers: `analysis.similarity` (blocks of the space, coordinates, a player's nearest
  players, a player's own rank, the lists a candidate comes in, the search's space and the
  search, axis ends and profile gaps), `outcomes.season_clubs` (the club a player played most for
  in each season), `profiles.match_counts`, `profiles.towards` and `profiles.place`,
  `roles.style_matches` and `roles.place` (any set of a player's matches on the season's terms).
  146 unit tests (new: shrinkage towards a given mean, blocks of total variance 1 whitened or not,
  blocks weighing the same, a player's own rank with or without a sample in its place, nearest
  players, the lists a candidate comes in, the search's values and space, the search's lists and
  filters, axis ends and what two players share, profile gaps, a player's club by season).

### Phase 3: Team style `notebooks/07_team_style.ipynb` (from 2026-10-30)
- Section 1, how a team plays: fourteen numbers for each of the 80 teams (PPDA, the height of
  defensive actions, final-third pressures and counterpressures per pressure, possession, field
  tilt, passes per possession, tempo, yards gained per completed pass, long balls from the back
  and from goal kicks, wide entries, crosses, pass ease), with tackles, interceptions, fouls,
  clearances and pressures rescaled within recording context. As recorded, Premier League PPDA
  goes from 15.8 before match week 19 to 12.7 after; on one scale 12.9 and 12.4. Every number is
  reliable over a season (split-half, stepped up: 0.81 to 0.97); the league explains 0.00 to 0.19
  of each. By the rule fixed beforehand (reliability 0.7 or more; of two at Spearman 0.8 or more,
  the more reliable), ten are kept: tempo, field tilt, passes per possession and possession go,
  pass ease standing for the possession game. Most follow strength (points per match: possession
  +0.63, the height of defensive actions +0.63, PPDA -0.48); wide entries least (-0.30).
- Section 2, team style axes: by the rule of notebook 05, two varimax-rotated axes of the ten
  numbers, 68% of their variation: direct to combination play (pass ease and counterpressing
  against yards per pass, long balls, crosses and wide entries) and deep block to high press (the
  height of defensive actions, final-third pressing, PPDA). Reliable over a season (0.95 and
  0.85) and found again in half the teams (congruence 0.98); the second eigenvalue is on the line
  of parallel analysis (1.525 against 1.522 over 200 shuffles, 1.524 over 10,000). Both follow
  strength (Spearman with points +0.44 and +0.52); Leicester City are the only direct team among
  the twelve with the most points. Pass networks of four teams, in their most used formation.
  The numbers, the number of axes and the names of their ends are `team_style` in the config.
- Section 3, players within teams (1,106 regulars who played for one team all season, the team's
  scores without the player's own actions): on an even share of possession the team explains a
  median 0.04 (central midfielders) to 0.27 (full-backs) of a style descriptor beyond chance, the
  two team axes 0.01 to 0.05 of it (14% to 63% of the team's part). What follows the team is how
  the ball is moved: at direct teams longer and higher passes, more aerial duels and crosses
  (correlations to -0.53). The press shows only as recorded (the height of defensive actions +0.34
  to +0.40); the even-share adjustment takes it out, possession going with the press (+0.67). The
  22 players who changed team in January changed style as the team axes predict: slope 1.00
  (0.46 to 1.44) over descriptors and 1.02 (0.47 to 1.69) over style axes, against 0.45 and 0.61
  for shuffled team changes.
- Section 4, fit (204 profiled players who changed club for 2016/17, to 64 clubs still in their
  league): a club's style in a position read from all its players of the group together, a
  player's fit as the share of the other clubs further from them than the new club, after the
  change the team axes predict. One-team regulars fit their own club without them at a mean 0.63
  (0.5 an average club); the signings fit their new club at 0.50 (0.46 to 0.55). Fit and the share
  of the new club's league minutes in 2016/17, with value against the club's regulars, age,
  minutes and group: +0.08 (-0.04 to +0.19) over all signings; +0.24 (0.10 to 0.39; 0.3% of
  10,000 shuffles of the new clubs) at the 37 of 64 clubs that kept their coach, -0.12 (-0.29 to
  +0.03) at the others, a gap of 0.36 (0.15 to 0.58). Steady without the predicted change, as
  recorded and with the step in team strength as a control (+0.20 to +0.24 with the same coach).
  The coach split was added during the analysis and is reported beside the result over all
  signings, to be tested again on another season.
- Section 5, against which opponents (an addendum; the 764 profiled players with 1,800 minutes or
  more): a player's response to the opponent's style is a profile statistic against the upper
  half of their team's opponents on a team style axis or pass ease less against the lower half,
  the opponent's style read without its matches against the player's team. Over 180 responses the
  split-half reliability over a season is a median -0.05 to +0.05 by group, the highest 0.32
  (attacking midfielders' and wingers' tackles against a high press), 13 above chance where 9
  would be by chance; the same halves give the players' levels 0.81 to 0.86. The opponent moves
  every player's numbers alike (82 of 180 mean responses clear of 0; centre-backs about a standard
  deviation more aerial duels and clearances against direct teams), not some players' more: no
  line-up can be picked by a player's own response with one season of data.
- New helpers: `analysis.teams` (each player's own counts per match and the team-match sums built
  from them with the opponent's, a team without a player, the team numbers, recording factors and
  rescaling for teams, split-half reliability across teams of the numbers or of any function of
  them, pass networks between the positions of a team's most used formation, a player's fit to a
  club as a rank among the clubs); in `analysis.outcomes`, a player's club in the first half of a
  season, their share of a club's league minutes and each club's coach across two seasons. 156
  unit tests (new: the team numbers, rescaling that keeps a context's heights, reliability of
  stable differences, position codes, a team without a player's own counts, the team style in the
  config, fit as a rank, first-half clubs, league shares, coaches) and 66 data tests (new: both
  teams of every pool match, the opponent's counts, team counts that add up the players', player
  rows in their team's matches, a team without all its players, every team's numbers in range, a
  pass network's eleven positions, one first-half club per player, coaches across seasons).

### Phase 3: Recruitment case study `notebooks/08_recruitment_case_study.ipynb` (from 2026-11-01)
- The scenario and its rules, set before any list of candidates was drawn up (`DECISIONS.md`,
  2026-11-01): AFC Bournemouth replacing Matt Ritchie, sold to Newcastle United on 1 July 2016 for
  €12M, decided on 30 June 2016. Of the 12 clubs placed 6th to 16th that lost a regular wide player
  with 55% or more of their league minutes that summer, the one with the league's smallest squad,
  a coach who stayed, the fee on record and a profiled signing for the role (Jordon Ibe). Budget:
  the fee over what Premier League clubs paid against market value the summer before, the last
  one known on 30 June 2016; candidates 27 or under, on the right, outside the strongest fifth of
  teams; the shortlist by the gap within team in the nearer half of the long list; the
  recommendation by fit to Bournemouth's style.
- Section 1, the vacancy: Bournemouth 16th of 20 (42 points, goal difference -22) with the
  league's smallest squad by market value (€89M on 30 June 2016, median €163M), Eddie Howe in the
  last match of 2015/16 and the first of 2016/17. Ritchie, 26, 87% of the club's league minutes,
  almost all at right midfield, two passes in three with the left foot, €6M. High percentiles for
  ball security (90), pressures and shots (69), passes into the box (66); low for dribbles (5),
  xG per shot (8), progressive carries and key passes (10); a link player, forward passer and
  touchline winger on the style axes. Bournemouth: middle of the direct-to-combination axis, 6th
  of 20 towards the high press, few yards per pass (14th percentile of 80), many wide entries
  (91st); their wide players together cover the flank's length, stay wide, defend deep and rarely
  enter the box, as Ritchie did. The club's three other profiled wide players played on the left.
- Section 2, the long list: summer transfers are dated from 1 July, so the budget comes from the
  summer of 2015 (Premier League clubs paid a median of 1.53 times the market value, 37 profiled
  transfers; 1.25 to 1.33 elsewhere): a ceiling of €7.85M of market value. The check: in 2016 the
  Premier League's ratio rose to 1.99 (a ceiling of €6.04M, Ritchie's own value) while the other
  leagues' fell. 276 candidates outside Bournemouth, 114 on the right, 80 of them 27 or under, 45
  within the budget, 42 outside the strongest fifth (34 regulars, 8 young players); the side costs
  the most (11 of the 14 regulars nearer Ritchie than the first on the long list play elsewhere).
  Nearest: Adrien Thomasson (Nantes, €2.5M, 1.31 from Ritchie, the 15th nearest of 249 regulars),
  Ludovic Blas (Guingamp) among the young players; the nearer halves (17 regulars to Santi Mina, 4
  young players) go to the shortlist. Most candidates lose the ball more often than Ritchie. A
  caveat: Jesse Lingard (Manchester United, €5M) passes the rule on teams that do not sell.
- Section 3, the shortlist: the five largest gaps within team (`market.gap`) of the 21 players in
  the nearer halves: Ludovic Blas (Guingamp, 18, €0.3M against the model's €1.1M), Adri Embarba
  (Rayo Vallecano, €1.0M against €2.7M), Lorenzo Pasciuti (Carpi, €1.3M against €3.0M), Jesse
  Lingard (Manchester United, €5.0M against €9.8M) and Suso (Genoa, €3.3M against €5.3M), the 77th
  to 98th percentile of the group's gaps; Thomasson, the nearest regular, is sixth. The nearer half
  is valued close to its numbers (the model a median 1.05 times the market), the further half below
  them (1.44). Fit to Bournemouth (`teams.fit_distances` and `fit`, reproducing notebook 07's fit of
  its 52 signings of the group exactly): a median of 0.34 on the long list, 0.54 in the nearer
  half; on the shortlist from 0.24 (Suso) to 0.92 (Pasciuti).
- Shared code moved to the package for the case study, the notebooks that used it calling it now
  with their outputs unchanged: `market.gap` (notebook 04's gap, reproduced exactly);
  `similarity.search_players`, `main_positions` and `line` (notebook 06's candidate rows); and
  `teams.team_seasons`, `style_axes`, `scores_without`, `whole_season_team`, `style_slopes` and
  `fit_distances` (notebook 07's team seasons and fit). 163 unit tests (new: the gap, lines and
  main positions, scores without a player, one-team players, slopes on the team axes, fit
  distances) and 72 data tests (new: the search's rows for every profiled player, lists by minutes
  and age, team seasons that add up, the team axes as configured, teams without one player).
- Section 4, the recommendation and the scouting reports: Lorenzo Pasciuti fits Bournemouth's style
  best of the five (0.92; Embarba 0.79, Blas 0.64, Lingard 0.32, Suso 0.24), is the nearest regular
  of the five to Ritchie and shares all three of Ritchie's axis ends. Against Ritchie: the same ball
  security (99th percentile, Ritchie 90th), more crossing and passes into the box, touches further
  up the flank; no shooting (shots and xG at the bottom of the group) and less pressing. Jordon Ibe,
  the player the club signed, is 29th of the long list's 34 regulars (further half, fit 0.30);
  Ritchie's fit to Bournemouth without Ritchie is 0.94. One-page HTML reports (`make reports`,
  `reports/scouting/`) for the shortlist, Ritchie and Ibe as of 30 June 2016, with an index:
  profile pizza and table against Ritchie, strengths and weaknesses (80th percentile or above, 20th
  or below, at most three each), touch and shot maps, style axes, value against the model, fit,
  nearest regulars and rule-based notes; single files with inline SVG, rebuilt byte for byte.
- The case study's steps moved to the package (`analysis.recruitment`, the scenario as
  `case_study` in the config), sections 1 to 3 calling them with their outputs unchanged, so that
  `make reports` needs no notebook; `reports` draws the pages (jinja2 templates in
  `src/football_scouting/templates/`). 177 unit tests (new: the filters step by step, each list's
  nearer half, the shortlist and the recommendation, team fifths, the ceiling, the case study in
  the config, strengths and weaknesses, units, file names, SVG that rebuilds the same, the
  figures, a player's role, the templates) and 78 data tests (new: the budget from the summer
  before, every rule on the long list, the shortlist and the recommendation, the club's signing,
  styles read back as stored, the reports written for every player).
- Section 5, what happened (outcomes as in notebook 04: growth score within the age band at the
  four horizons, three years on read first; league minutes; the club named on the valuation).
  Three years on, four of the five shortlisted players stood at the 79th percentile of their age
  band or above, all regulars in the big five: Lingard 96 (Manchester United, €40M), Suso 91 (AC
  Milan, €40M), Embarba 79 (Rayo Vallecano, back in La Liga) and Blas 79 (Guingamp). Pasciuti, the
  recommendation, stayed at Carpi outside the covered leagues (€1.4M on 1 August 2016, €0.6M in
  2019; 20th percentile). The shortlist's mean, 72.8, against a median 37.3 for every pick of five
  from the nearer half (20,349 picks, `backtest.chance`): 0.2% did as well, at most 1.7% at any
  horizon. The long list grew less than the group (nearer half 37.6, further half 41.3, the
  group's 305 profiled players 52.0). Ordered by fit the shortlist came out almost in reverse
  (Pasciuti last, Lingard and Suso first). Jordon Ibe, the club's signing: 31%, 59% and 23% of
  Bournemouth's league minutes from 2016/17 to 2018/19, 19th percentile three years on, 4th five
  years on (€0.8M at Derby County); Pasciuti 26th and Ibe 29th of the long list's 42. Ritchie: 82nd
  percentile (€12M, Newcastle United). 178 unit tests (new: every pick's mean) and 78 data tests.

## Next

1. Phase 4: the README for recruiters (findings and figures first), clean narrative notebooks, CI.

## Open questions

- How the back-test treats short samples: shrunk values rank players with few minutes
  conservatively (450-minute players fill 39% to 45% of a group's predicted top 10% where they
  are half the players), which is right on average but can bury a young player with strong
  numbers. Ranking young players also by an optimistic bound is a back-test choice.
- Centre-forwards who lay the ball off grew less in value than those who pass it forward
  (Spearman -0.21 three years on, short of Holm's correction over 34 correlations, steady from
  two to five years on and beside minutes and the gap). Whether it reflects how clubs judge
  forwards or chance needs players it was not found on, from another season; the case study,
  of a winger, does not test it.
- Fit and minutes: signings played more where they fitted only at clubs that kept their coach
  (notebook 07, section 4), a split added during the analysis. Testing it on another season's
  signings needs event data beyond 2015/16.
- Fit as the case study's last step: the shortlisted player who fitted Bournemouth best had the
  worst career of the five, and the two who fitted least the best (notebook 08, section 5). Value
  growth is not what fit was chosen for and none of the five joined the club, so one case cannot
  say whether fit should decide among a shortlist or only be shown beside it; other clubs and
  seasons would.
- The meaning of `transfer_fee` 0 vs null (free, loan, unknown) is still unverified.
- Before publishing: register interest at statsbomb.com/resource-centre (StatsBomb asks this
  of open-data users) and add the StatsBomb logo from its Media Pack (the notebooks' figures and
  the scouting reports credit StatsBomb in text only).
