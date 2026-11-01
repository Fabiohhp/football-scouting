# Decisions

Design and analysis decisions, newest last. Each entry: date, decision, reason (the evidence).

## 2026-10-06: Python 3.12, capped below 3.13

**Decision.** `requires-python = ">=3.12,<3.13"`; `.python-version` is 3.12.
**Reason.** socceraction 1.5.3 (an option for the possession value analysis) declares
`Python <3.13`, `numpy <2`, `pandas <3`; 3.12 is the newest version that keeps that option open.
The cap can be lifted if possession value is implemented without socceraction.

## 2026-10-06: `uv.lock` is the dependency pin

**Decision.** `pyproject.toml` declares lower bounds; `uv.lock` (committed) pins exact versions
and hashes; `make setup` runs `uv sync --locked`.
**Reason.** Reproducible environments without hand-maintaining `==` pins.

## 2026-10-06: Own downloader instead of statsbombpy for raw data

**Decision.** Raw StatsBomb JSON is fetched with a small `httpx` client (retries, cache, atomic
writes) from `raw.githubusercontent.com`, mirroring the open-data repo layout under
`data/raw/statsbomb/`.
**Reason.** The raw data is downloaded once and cached. statsbombpy returns parsed DataFrames
and does not keep the raw files; a small client keeps byte-identical raw files that can be
checked against the repo's blob sizes.

## 2026-10-06: Pin StatsBomb open-data to a commit SHA

**Decision.** Download from commit `4b73468fc5b0f1950f9f66fada70ad3a4f9327cb` (master on
2026-10-06), set in `config/pipeline.yaml` (`statsbomb.ref`).
**Reason.** StatsBomb re-releases files in place (Ligue 1 2015/16 `match_available` is
2026-05-12). Pinning makes the raw snapshot reproducible; moving to a newer commit is an
explicit, logged change.

## 2026-10-06: Bundesliga 2015/16 downloaded but excluded from the scouting pool

**Decision.** The 34 Bundesliga matches (competition 9, season 27) are downloaded but marked
`scouting_pool: false` and excluded from league-wide comparisons by default. The scouting pool
is Premier League, La Liga, Serie A and Ligue 1 (1,517 matches).
**Reason.** Verified 2026-10-06: every one of the 34 matches involves Bayer Leverkusen (18 teams
appear in total). Players from the other 17 clubs appear in only one or two matches, so their
per-90 numbers and percentiles would not be comparable with full-season players.

## 2026-10-06: Transfermarkt as gzipped CSVs, 7 tables

**Decision.** Download the dcaribou tables as gzipped CSVs rather than the 201 MB DuckDB file:
`players`, `player_valuations`, `transfers`, `clubs`, `appearances`, plus `competitions` and
`games`. Each download is recorded in `data/raw/transfermarkt/manifest.json` (size, sha256,
ETag, Last-Modified).
**Reason.** CSVs are smaller (65 MB) and transparent, and the project builds its own DuckDB
anyway. `competitions` decodes competition codes (`GB1`, ...) and `games` gives the season of
each appearance; both are needed to select 2015/16 Big 5 players. Upstream overwrites files in
place, so the manifest is the provenance record.

## 2026-10-06: Interim Parquet is a faithful copy of the raw JSON, converted with DuckDB

**Decision.** `data/interim/statsbomb/` holds one Parquet row per JSON array element, nested
objects kept as STRUCT/LIST, plus `match_id` / `competition_id` / `season_id`. The schema is
inferred over all files; types DuckDB auto-detects from strings (UUID, TIME, DATE, TIMESTAMP)
are kept as VARCHAR; fields typed JSON (all-null) are stored as JSON text; MAP inference is
off. Events and lineups are written per competition-season. A deep check
(`make validate-statsbomb`) compares every JSON key path, per-match row count and per-match xG
sum with the Parquet tables.
**Reason.** Cleaning and renaming belong to the processed layer, where they can be tested; the
interim layer must lose nothing. DuckDB converts 4.5 GB in about 30 s with bounded memory (peak
RSS about 4 GB with 4 threads); pandas or pyarrow would need the whole season in memory, and
`pyarrow.Table.from_pylist` drops keys absent from the first row.

## 2026-10-06: Deliverables: statistical notebooks and a README, no app

**Decision.** The deliverables are statistical scouting analyses in notebooks and a README
written for recruiters; there is no interactive app. The last phase packages the README
(findings and figures first), clean narrative notebooks, and tests and lint in CI.
**Reason.** The project's goal is statistical analysis for scouting, not a data or
visualisation app.

## 2026-10-07: Per-90 metrics use real time on the pitch

**Decision.** Minutes played are the real elapsed time a player was on the pitch, stoppage time
included, computed from the actual length of each period. "Per 90" means per 90 real minutes.
**Reason.** Matches last 95.2 minutes on average (90.0 to 105.6), so nominal minutes (capped at
90) would treat players in long and short matches differently.

## 2026-10-07: Seven position groups

**Decision.** StatsBomb's 24 positions map to 7 groups: Goalkeeper (GK); Centre-back (RCB, CB,
LCB); Full-back / wing-back (RB, LB, RWB, LWB); Central midfield (RDM, CDM, LDM, RCM, CM,
LCM); Attacking midfield (RAM, CAM, LAM); Wide midfield / winger (RM, LM, RW, LW); Centre-
forward (RCF, CF, LCF). A player's primary position and group are the ones with the most
minutes.
**Reason.** Each group is a role players are scouted within: left, right and central variants
of a role share a group, and wing-backs share one with full-backs. Finer groups would leave
too few players to compare (attacking midfield, the smallest, is merged with the wingers for
comparisons; see 2026-10-11).

## 2026-10-07: Minutes played: rules forced by the data

**Decision.** Minutes come from the lineup position stints converted to real time, with four
corrections, each found in the data and covered by a test:
1. A dismissal ends the player's time (420 dismissals; in 413 the lineup stint runs to the
   final whistle; no dismissed player has an on-ball event after the card).
2. A Substitution event ends the player's time, even if the lineup does not (players back from
   treatment and replaced at once stayed "on" until the final whistle; up to 81 extra minutes
   in a team-match).
3. Overlapping stints of the same player are trimmed so no time counts twice.
4. Starters are the players on the pitch at kick-off (two lineups label some starters'
   first stint "Tactical Shift"); this equals the Starting XI event for every team-match.
**Reason.** Per-90 metrics depend on it. Checks after the fixes: never more than 11 players
on the pitch; for 3,102 of 3,102 team-matches, 11 x match length = time played + time lost
to dismissals + recorded absences (within 30 s); only 15 of 5.4M player events fall outside
the player's time on the pitch.

## 2026-10-07: Processed model layout

**Decision.** `data/processed/statsbomb/` holds dimensions (competitions, matches, periods,
teams, players), minutes tables (player_matches, player_positions, player_seasons), `events`
with the common columns, and one wide table per event type (common columns + flattened
attributes), plus `defensive_actions` (a union of tackles, interceptions, blocks,
clearances, ball recoveries, fouls committed and 50/50s, with the raw outcome) and
`formations`. Missing boolean flags become false (the spec only publishes true flags);
`{id, name}` objects become the name, except player references (ids). Transfermarkt tables
are typed copies; `scouting.duckdb` holds one view per table.
**Reason.** Notebooks can query one table per question without re-parsing nested JSON;
which defensive actions count (e.g. for PPDA) is left to each analysis.

## 2026-10-07: StatsBomb <-> Transfermarkt linkage method and result

**Decision.** Matches are paired by league, date and score; each team takes the club paired
with all its matches (ties, which only occur for 2-match Bundesliga opponents, go to the most
similar club name; the code fails on any remaining ambiguity). Players are linked within each
team-season by games played in common (Jaccard) and name similarity (accents removed,
nicknames included), one-to-one, with confidence tiers. Links below high confidence are
checked one by one against the same evidence and the outcome recorded; three manual decisions
are in `config/player_match_overrides.csv` (two players with no 2015/16 Transfermarkt
appearances, one listed under another name).
**Reason.** Result: 1,551/1,551 matches, 98/98 teams, 2,522/2,522 player-seasons linked
(2,505 high-confidence players; the 1 medium and 4 low-confidence links are all correct).
Independent checks not used for matching: goals in the linked games agree exactly for 99.2% of
players (none differ by more than 1); nationality agrees for 98% (the rest are spelling
variants or dual nationals).

## 2026-10-07: Transfermarkt snapshot columns are outcome-only

**Decision.** Transfermarkt columns that describe the player or club at snapshot time (2026:
current club, current market value, highest value, contract, caps, agent, squad values) are
marked "Snapshot" in the data dictionary and must never be used as 2015/16 features.
**Reason.** They are future information for the back-test (leakage).

## 2026-10-10: Notebook tooling and the player-season unit for analyses

**Decision.** Notebooks use matplotlib (Okabe-Ito colours, a source line on every figure via
`football_scouting.plots`) and are executed with `make notebooks` (nbconvert, outputs saved in
the `.ipynb`). The unit for player analyses is one row per player in the scouting pool, with
minutes summed over pool clubs (`analysis.players.pool_player_seasons`); minutes outside the
pool are left out. `player_seasons.minutes_<group>` columns are 0, not NULL, when a player
has no minutes in a group (a data quality test checks they add up to `minutes`).
**Reason.** NULL group minutes made a NumPy argmax pick the wrong primary group (caught by
checking the notebook against an independent SQL count). Summing over clubs affects 103
players who moved mid-season.

## 2026-10-11: Who is compared, and within which groups (EDA section 1)

**Decision.** (1) Players are compared from 900 real minutes, or from 450 minutes if they were
under 23 on 30 June 2016. (2) Six comparison groups (`comparison_groups` in
`config/pipeline.yaml`): attacking midfield is merged with the wingers. (3) Percentiles are
computed over the four pool leagues together, not per league. (4) Minutes are summed over
clubs for mid-season movers. (5) Shinji Okazaki's missing Transfermarkt date of birth is filled
from Wikipedia (`config/date_of_birth_overrides.csv`).
**Reason.** Evidence in `notebooks/01_data_exploration.ipynb`, section 1:
- 900 minutes keeps 1,366 of 2,176 players (61-65% per league) but only 20% of under-21s.
- The share of players reaching 900 minutes rises through the early twenties: 23% at age 20,
  45% at 21, 55% at 22, 59% at 23 and 67-73% from 24. Under 23 is also football's usual
  young-player limit. The 450-minute rule adds 70 under-23 players to the 175 who pass 900.
- Attacking midfield has 37 players at 900 minutes. Two merges were tested: AM + W, and
  AM + CM with W + CF. Players swap positions in both patterns. But on 15 per-90 actions AM is
  1.5 SD from W against 3.1 from CM, and 81% of attacking midfielders are closest to the
  winger profile. AM + W leaves the winger group's spread unchanged, while W + CF widens it
  (CF 2.45 -> 3.28).
- Within one league, goalkeepers (23-27) and centre-forwards (37-48) would carry percentile
  margins of +-13 to +-16 points at the 80th percentile, against +-8 or better pooled.

## 2026-10-11: Every player's rates are shrunk by measured reliability (EDA section 2)

**Decision.** Reliability is measured by random split halves (50 draws, outfield players with
1,800+ minutes, rates centred within comparison group x league) and summarised per metric by K
in r = M / (M + K). Every player's per-90 rates and ratios, not only young players', are
shrunk towards the comparison group's average with weight M / (M + K), metric by metric (M:
the player's minutes). Goals and dribble success rate are not used to rank players;
non-penalty xG stands in for goals.
**Reason.** At 900 minutes reliability ranges from 0.87 (passes) to 0.33 (goals) and 0.08
(dribble success). Non-penalty xG is 0.56 and key passes 0.50, so a minutes filter alone does
not make the main scouting numbers trustworthy, for regulars as much as for young players.
r = M / (M + K) fits the measured curves within 10% at every M. A chronological split was
rejected because it mixes noise with real change (form, injuries, coaches).
K is measured per statistic and comparison group from 2026-10-18.

## 2026-10-11: Defensive numbers are compared within recording context (EDA section 3)

**Decision.** Interceptions, pressures and clearances are compared only among players recorded
the same way. There are five recording contexts: La Liga, Serie A, Ligue 1, and the Premier
League before and from 28 December 2015. Within each comparison group, a player's counts in
each context are rescaled so that the context's group average equals the four-league group
average; a Premier League player's matches before and after the change are rescaled
separately. Percentiles are then computed over the four leagues together, as for every other
metric. Attacking and passing metrics are used as recorded.
**Reason.** From match week 19 the Premier League records about 3x the interceptions (+18%
pressures, +16% clearances) while other events stay flat, an abrupt change with no football
explanation. League explains 25% of players' interceptions within comparison group, 8% of
pressures and clearances, and at most 3% of any attacking or passing metric (0.4% of xG, goals
and passes). A multiplicative rescale matches a change that scales counts up. It also removes
real league differences in these three metrics (pressing intensity, for instance), which
cannot be told apart from recording.

## 2026-10-12: The club on a valuation is read from its name, not its id

**Decision.** A valuation's club is `player_valuations.current_club_name`
(`analysis.values.pool_valuations`); `current_club_id` and
`player_club_domestic_competition_id` are not used. The data dictionary says so.
**Reason.** For 2015/16 valuations of pool players, the id is the player's 2015/16 club only
62% of the time and often the snapshot (2026) club; the name is the exact 2015/16 club name for
85%, and the rest are spelling variants and reserve teams. Known moves confirm it (Higuaín,
Kanté, Stones, Pogba change name on the first valuation after their transfer). A data quality
test guards the name.

## 2026-10-13: The back-test's dates (EDA section 4)

**Decision** (`backtest` in `config/pipeline.yaml`):
- the market's view of a player is their value on **30 June 2016**, kept with its age, and is a
  feature like the 2015/16 numbers;
- value growth is measured from the value on **1 August 2016**, after every league's
  end-of-season revaluation; moves made in July 2016 are career outcomes;
- outcomes are read on **31 August 2017, 2018, 2019 and 2021** (+1, +2, +3, +5 years);
- a player with no valuation in the 12 months before a horizon is **no longer valued**, an
  outcome, not missing data.

**Reason.** Transfermarkt revalues league by league. On 30 June 2016 the median value was 142
days old, and the end-of-season revaluation came only on 13 July to 1 August 2016. That
revaluation follows the season just played: among players who stayed at their club, 48% of
those with 2,700+ minutes went up against 10% down. Measuring growth from 30 June would let a
model fed with the full season score on that catch-up. Values from 1 August alone are fresh but
already contain July's moves (415 players revalued at another club) and Euro 2016 (199 squad
players, +5% on average), which a club deciding in June could not see. Splitting the two dates
keeps what the club could see as the feature and starts the outcome after the catch-up.
Several horizons because players pay off at different speeds: five years on, the median
under-21 is worth 2.6 times their August 2016 value and the median 28 to 30-year-old a fifth.
31 August falls after every later summer's revaluation (late May to June; 25 August in 2020).
Five years is the longest contract a club could sign in 2016. 2020 is left out because on
8 April 2020 Transfermarkt cut 1,650 pool players at once (median -20%), and on 31 August 2020
56% of the players still valued carried that cut rather than a reading of the season. Players
who stop being valued are mostly older (median age 33 in 2016), but for young players it says
something about the career, so dropping them would flatter any model.

## 2026-10-14: How xG is used (EDA section 5)

**Decision.**
- Attacking output is measured with StatsBomb's non-penalty xG **as published**: no league
  adjustment and no recalibration. The back-test does not need an own xG model.
- **Finishing** (non-penalty goals minus xG per shot) is not used to rank players, like goals
  (2026-10-11).
- Player profiles show **shot volume** (non-penalty shots per 90) and **shot quality** (xG per
  shot) next to non-penalty xG per 90. Each is shrunk towards the comparison group's average
  with its own K: shots per 90 in minutes, xG per shot in shots (about 28), with weight
  n / (n + K) for a player with n shots.

**Reason.** Over the pool's 37,888 shots, non-penalty xG runs 4% below goals (3,569 goals from
3,433 xG, about 2.7 standard deviations). Every league sits between +2% and +6% and none differs
from the others beyond chance, so a league adjustment would correct nothing. The errors are by
kind of chance: direct free kicks score 1.6 times their xG, open-play shots under 0.06 xG score
15-18% less than predicted and chances of 0.1 to 0.4 score 10-13% more. An isotonic
recalibration per shot type, fitted on these shots, barely changes the order of non-penalty xG
per 90 within each comparison group (Spearman 0.995 to 0.998; 17 to 19 of the top 20 stay).
Finishing has a split-half reliability of 0.02 or less at 20 shots per half (K about 1,600
shots), while a regular centre-forward takes a median of 52 non-penalty shots a season. xG per
shot reaches r = 0.5 at about 28 shots and, within each group, is close to independent of shot
volume (Spearman -0.14 to +0.04): the two describe different ways to reach the same xG per 90.

## 2026-10-14: Pitch figures with mplsoccer

**Decision.** Figures on a pitch are drawn with mplsoccer (`pitch_type="statsbomb"`). numpy and
scipy, imported by the package, are declared as direct dependencies.
**Reason.** mplsoccer is the standard library for football pitch plots and reads StatsBomb's
120 x 80 coordinates as they are, including the inverted y axis (checked: left backs are drawn
on the left with play going upwards). The alternative, drawing the pitch by hand in
`football_scouting.plots`, would mean maintaining pitch geometry for no gain. numpy and scipy
were only installed through pandas and scikit-learn.

## 2026-10-17: Phase 3 scope and order

**Decision.** Phase 3 builds one notebook per analysis, in this order: (1) player profiles,
(2) possession value, (3) market value and the recruitment back-test, (4) role discovery,
(5) similarity search and replacements, (6) team style, (7) a recruitment case study, which
includes one-page scouting reports (HTML) for its shortlist. Possession value starts with
expected threat (xT), implemented in the package; VAEP is considered once the xT results are
in. There is no own xG model. The 2022 World Cup positional and tracking module is left as a
possible extension after Phase 4.
**Reason.** Profiles are the input of every later analysis. The back-test is the project's core
question and its riskiest analysis, so it comes as soon as its inputs exist; roles, similarity
and team style refine it. xT values passes, carries and dribbles from the event locations
alone; socceraction 1.5.3, the reference VAEP implementation, requires `numpy<2`, and with the
pinned numpy 2.5 the resolver falls back to socceraction 1.1.1 (2021). An own xG model would not
change the back-test: StatsBomb's xG is used as published, since recalibrating it barely changes
rankings within groups (2026-10-14). The tracking module needs new data (StatsBomb 360 and PFF
tracking) and does not feed the back-test.

## 2026-10-18: The player profiles (notebook 02, section 1)

**Decision.**
- Each outfield comparison group is read through **twelve statistics** (`profiles` in
  `config/pipeline.yaml`). Each is reliable within the group (split-half correlation of 0.4 or
  more at 900 minutes), no two correlate at 0.8 or more (Spearman, within the group), and
  together they cover what the role does. Goals, finishing and dribble success stay out
  (2026-10-11, 2026-10-14). Position descriptors (touch position, width, height of defensive
  actions) describe a role rather than how well it is played and are kept for role discovery.
- Progressive passes and carries follow **Wyscout's zones**: the ball ends at least 30 m closer
  to the centre of the goal within the own half, 15 m from the own half into the other, 10 m
  within the other half (on a 105 m pitch).
- **Fouls won and times dribbled past** are in no profile, and are not rescaled by league.
- **Counterpressures and pressures in the final third** are compared within recording context,
  like pressures (2026-10-11).
- **Shrinkage uses one K per statistic and comparison group**, measured within the group. This
  replaces the single K per statistic of 2026-10-11.

**Reason.**
- Progressive passes: FBref's 10-yard rule mostly re-counts passing volume (median Spearman
  with open-play passes 0.84 within group; the team explains 0.21 of it). Zones and 25% closer
  measure progress (0.60 and 0.62 with passes; team 0.08 and 0.09) and rank players almost the
  same way (0.91 to 0.98). All three are equally reliable (0.69 to 0.70 at 900 minutes), and
  for carries they agree (0.94 to 0.98). Zones is an industry standard and treats passes and
  carries alike.
- The profiles: the least reliable statistic in each group sits at 0.41 to 0.50, the closest
  pair at 0.65 to 0.76. Among centre-backs, the share of aerial duels won (0.33; half of them
  win between 61% and 70%), interceptions (0.37) and blocks (0.19) fall below 0.4.
- Fouls won follow the league's refereeing: 12.0 per team and match in the Premier League, 15.9
  in Serie A (league partial η² 0.063 within comparison group). Times dribbled past follow the
  opposition's dribbling (0.061; 10.6 completed dribbles per team and match in the Premier
  League and La Liga, 8.4 and 8.8 in Serie A and Ligue 1). Dribblers tackled, the rate that
  would correct for the opposition, is noise in every group. A rescale would fix the level
  without making either number about the player.
- From match week 19 the Premier League records 14% more counterpressures and 21% more
  pressures in the final third per 90; no other league changes by more than 7%.
- Reliability differs widely between groups: at 900 minutes non-penalty xG per 90 is 0.66 among
  attacking midfielders and wingers and 0.18 among centre-backs (K about 470 and 4,000
  minutes), the share of aerial duels won 0.74 among centre-forwards and 0.33 among
  centre-backs. With the single K for xG (720 minutes), a centre-back with 2,700 minutes keeps
  79% of their own rate; with the centre-backs' K, 40%. Each group's K rests on fewer players
  (79 centre-forwards to 186 central midfielders with 900 minutes in both halves, against 702
  outfield players together), so it is less precise.

## 2026-10-18: The possession adjustment (notebook 02, section 2)

**Decision.**
- Possession is **time with the ball**: the time from each event to the next, within a half,
  goes to the team in possession, with gaps capped at 10 seconds. A player's possession is the
  team's share of that time while the player is on the pitch (`analysis.possession`).
- Every per-90 statistic in a profile is put on an even share of possession by its
  **elasticity, measured within players for each comparison group**: rate x (0.5 / share)^β,
  with the team's share for statistics made with the ball and the opponent's for those without
  it. Ratios (pass completion, ball losses per touch, xG per shot, aerial duels won) are used as
  recorded.
- **Full-backs' key passes** stay in the full-backs' profile.
- **Pass completion** stays as recorded. A completion over expected, which accounts for each
  pass's difficulty, is tested with the possession value model (notebook 03) and replaces it if
  it removes the team's part while staying reliable.

**Reason.**
- Time with the ball agrees with the share of passes (0.97 per match) and ranges from 39%
  (Carpi) to 65% (Barcelona) over the season. Season figures tie passing to possession (0.74 to
  0.84 among defenders and central midfielders) but cannot tell possession from the better
  players a team with the ball can afford. Within players (Poisson regression with a fixed
  effect per player), counts made with the ball grow faster than the time (progressive passes
  1.23 to 1.48), except forwards' (a centre-forward's passes 0.25); counts without the ball
  grow more slowly than the opponent's time (tackles 0.16 to 0.51, pressures 0.35 to 0.79); ball
  recoveries and centre-backs' aerial duels rise with the team's own possession. Leaving the
  player's own time on the ball out of the share changes the elasticities by a median of -0.05.
- Alternatives tested, by the median correlation with possession left after the adjustment,
  within comparison group (with the ball / without): none 0.33 / -0.08; in proportion to the
  time 0.12 / 0.29; measured elasticity 0.10 / 0.02. StatsBomb's PAdj (Knutson, 2014), which
  adjusts defensive counts only, turns them to 0.64: the team then explains 0.43 of them, and
  their rankings agree with the recorded ones at as little as 0.49. With the measured
  elasticity, the team's share of statistics made with the ball falls from 0.18 to 0.08 and the
  median reliability at 900 minutes from 0.74 to 0.72.
- On 31 players who changed teams during the season (median change in possession 5.3 points),
  the elasticities predict the size of the change in their rates (slope 0.97, 95% interval 0.50
  to 1.59); in proportion to the time 0.77, PAdj 0.18, its predicted changes about five times
  too large.
- Full-backs' key passes fall from 0.41 to 0.35 at 900 minutes once adjusted. They are the
  full-backs' main measure of chance creation; xA, the alternative, is 0.20. Shrinkage with the
  group's K weighs them by their reliability.
- Pass completion depends on the team even after possession (team share 0.41 to 0.60 among
  defenders and central midfielders, against 0.08 for the adjusted statistics made with the
  ball): it rewards safe passing in teams that keep the ball. A ratio gets no more chances from
  possession, so no possession adjustment applies; the difficulty of each pass does.

## 2026-10-18: The final profiles (notebook 02, section 3)

**Decision.**
- **Goalkeepers have no profile** and are left out of the back-test.
- Each profile statistic goes through four steps, in this order (`analysis.profiles`):
  - **recording context**: within each comparison group, a context's counts are multiplied so
    that its rate per 90 equals the group's rate over the four leagues, among the group's
    profiled players;
  - **possession**: per-90 statistics are adjusted by the group's elasticity (2026-10-18),
    fitted on the counts as recorded of the group's players with 900+ minutes;
  - **shrinkage** towards the group's mean of the adjusted values, weighted by minutes, with
    K per statistic and group measured on the adjusted values (split halves of 900 minutes,
    players with 1,800+ minutes). A ratio with no attempts takes the group's mean;
  - **percentiles**: the share of the group's profiled players at or below the player, ties
    sharing the average, reversed where a lower number is better.
- The profiles are **processed tables** (`make profiles`, part of `make model`):
  `data/processed/profiles/`, one row per player and statistic with each step, plus the
  elasticities, reliabilities and recording factors. Later analyses read them.
- Who is compared (2026-10-11) and the recording contexts (2026-10-11, 2026-10-18) are
  parameters in `config/pipeline.yaml` (`compared`, `recording`).

**Reason.**
- Goalkeepers: StatsBomb's open data has no post-shot xG, so shot-stopping cannot be judged
  without a model of its own, and the project builds no xG model (2026-10-17). A goalkeeper's
  other actions (claims, sweeping, distribution) do not make a recruitment judgement on their
  own.
- Shrinkage, tested on the 764 outfield players with 1,800+ minutes: each player's matches
  are dealt into two random halves, half the players keep only 450 minutes of the first, and
  the first half predicts the second (50 draws). With the group's K, the squared error falls by
  21% to 28% within groups (median over statistics), against 21% to 24% with one K for all
  outfield players. The group's K is better where reliability differs between groups:
  centre-forwards' aerial duels won (14 points of squared error), centre-backs' ball losses
  per touch (11), centre-forwards' xG per shot (8); elsewhere the two agree (median 0.3
  points), and it is never worse by more than 0.1. Without shrinkage, 450-minute players fill
  56% to 59% of the predicted top 10% though they are half the players; with it, 39% to 45%,
  and 1 to 2 points more of the predicted top 10% are in the second half's top quarter.
- Order of the steps: the recording factors and the possession adjustment both multiply
  counts; the elasticities, fitted within players, are the same on counts as recorded (the
  factors are constant within a context), so they match section 2. Recording context moves
  the percentiles of the statistics it touches by a median 8.6 points, possession 3.4,
  shrinkage 0.7 (3.3 for players under 23 with fewer than 900 minutes).
- Processed tables: every later notebook reads the same numbers, the build takes about 12
  seconds, and the rules are checked by data tests (each profiled player has their group's
  twelve statistics, shrunk values lie between the player's and the group's, adjusted values
  follow the elasticities).

## 2026-10-19: The expected threat map (notebook 03, section 1)

**Decision.**
- Possession value is credited by **expected threat** (xT; Karun Singh, 2018), implemented in
  `analysis.xt`. From each zone of the pitch a team shoots, moves the ball (a pass or a carry)
  or loses it; a zone's xT is the xG of its shots plus the xT of the zones its successful moves
  reach, each weighted by how often it happens. A move is credited with the xT it gains.
- **Open play only:** open-play passes (without injury clearances), carries and open-play shots.
  Set-piece deliveries and shots straight from set pieces are left out; what follows them in
  open play stays.
- **Ball losses count:** dispossessions, miscontrols and failed dribbles are actions that end
  the chain, like a failed pass.
- **Zones of 2.5 × 2.5 yards** (48 × 32).
- **One map** for both wings and all four leagues, **shots valued by their xG**.
- The grid, the losses and the shot value are parameters in `config/pipeline.yaml` (`xt`).

**Reason.**
- Every map was checked on matches it was not fitted on (20 random halves of the 1,517
  matches). Each action's observed outcome is the xG of the open-play shot its team's chain
  went on to take, where a chain ends at the opponent's next action on the ball, a set piece
  or the end of the half; skill is the share of a flat guess's squared error a map removes.
- Losses: the textbook model, with shots and moves only, overstates the outcomes by 46%. The
  107,792 dispossessions, miscontrols and failed dribbles it does not see hand the ball to the
  opponent or a set piece 80% to 93% of the time (a failed pass 99.6%), three quarters of them
  in the opponent's half. Counted, they bring the map to 13% below the outcomes and lift its
  held-out skill from 0.081 to 0.092 (16 × 12 zones), level with each zone's mean outcome
  (0.093). They halve xT in the own half (0.48 times) and barely change it in front of goal
  (0.89); the order of moves by credit hardly moves (Spearman 0.990).
- Grid: held-out skill rises with finer zones down to 2.5 yards (0.102, against 0.092 at the
  textbook's 16 × 12; gain over 4-yard zones +0.0034, 95% range +0.0022 to +0.0043) and stops
  at 2 yards (+0.0004, range -0.0004 to +0.0013). At 2.5 yards a move's credit correlates at
  0.988 between the maps of two halves of the matches.
- One map: a zone differs from its mirror image across the pitch by 4.0% of the mean xT, less
  than the maps of two halves of the matches (5.8%). Each league's own map credits moves like
  the pooled map as closely as random sets of 380 matches do (0.989 to 0.991). Its level
  differs beyond chance in La Liga (+5.9%) and Ligue 1 (-5.9%; random sets -2.8% to +3.2%):
  from the same zones their chains lead to more or less xG, which comes with the players who
  carry them on. A league's own map would credit a pass with the forwards who receive it.
- Shot value: goals give the same map 2% higher (credits agree at 0.990) but noisier between
  halves (0.948 against 0.988 with xG).

## 2026-10-19: A player's xT (notebook 03, section 2.1)

**Decision.**
- A player's xT per 90 is the **xT gained** by their successful open-play passes and carries:
  each move's gain on the map, xT(end) - xT(start), with a move to a zone worth less counting
  0, like a failed pass. Ball losses are not charged. Passes and carries are kept as its two
  parts (`analysis.xt.player_match_credit` and `credit_rates`; `xt.credit` in
  `config/pipeline.yaml`).
- Alternatives tested: **net** xT (Singh's player xT: gains less the xT that moves backwards
  give up) and **charged** xT (net, less the xT of the zone where a pass failed or the ball was
  lost).

**Reason.**
- Reliability at 900 minutes (50 random split halves, players with 1,800+ minutes, rates
  centred within league), by comparison group: gained 0.55 to 0.75 (K of 306 to 746 minutes),
  net 0.50 to 0.71 (360 to 905), charged 0.30 to 0.54 (779 to 2,062; below the profiles' 0.4
  among centre-backs and full-backs).
- Gained and net rank players almost the same (Spearman 0.97 to 0.99, 0.91 among
  centre-forwards). They part on moves backwards, which give back a median of 20% of the xT a
  centre-back gains, 32% of a central midfielder's and 48% of a centre-forward's. Net xT sinks
  the forwards who hold the ball up and lay it off (Lukaku from the 66th percentile of
  centre-forwards to the 27th, Benteke from the 52nd to the 13th; Fellaini from the 32nd to the
  1st among central midfielders): the map values zones, not the pressure a lay-off escapes.
- Charged: what a player gives away rises with what they make (Spearman 0.27 to 0.68 between
  net xT and the xT given away), so the difference cancels much of what tells players apart.
  The risk side is read in the profiles through pass completion and ball losses per touch.

## 2026-10-19: A player's xT and possession (notebook 03, section 2.2)

**Decision.**
- xT gained per 90 is put on an even share of possession by its **elasticity**, measured within
  players in each comparison group: rate x (0.5 / share)^elasticity, with the team's share of
  possession while the player is on the pitch, as the profiles' per-90 statistics are
  (2026-10-18). Alternatives tested: no adjustment, and in proportion to the time with the ball.
- The four leagues stay on one scale: no rescale by league.

**Reason.**
- Within players (Poisson regression with a fixed effect per player, players with 900+
  minutes), xT gained grows faster than the time with the ball among defenders and central
  midfielders (elasticity 1.50 to 1.81), about in proportion among attacking midfielders and
  wingers (0.95) and half as fast among centre-forwards (0.47). Leaving the player's own time on
  the ball out of the share lowers the elasticities by about 0.1.
- As recorded, xT gained correlates with possession at 0.24 to 0.47 within group, and the team
  explains 17% to 33% of it beyond chance. After the measured elasticity: correlation -0.03 to
  0.19, team share at most 0.18, reliability at 900 minutes 0.49 to 0.69 (0.55 to 0.75 as
  recorded). In proportion to the time leaves 0.16 to 0.24 among defenders and central
  midfielders and takes out more than the within-player effect among centre-forwards (0.04
  against 0.14).
- Leagues: once the group is known, the league explains 1.3% of the variation of adjusted xT
  (0.8% as recorded; 0.6% with leagues shuffled), against 6% for fouls won and times dribbled
  past, which the profiles also leave as recorded.


## 2026-10-23: Expected pass completion (notebook 03, section 3)

**Decision.**
- A pass's expected completion (xPass) comes from **gradient-boosted trees** on what is known
  when the pass is played: where it starts, its direction, height and body part, pressure,
  whether it is a cross, a through ball or a cut-back, whether it follows an aerial duel won, a
  recovery or an interception, and the phase of play (`analysis.xpass`). Who passes (role,
  team, league) is left out.
- **Not used: the end location, the length and the switch flag**, which give the outcome away.
- Every pass is scored by a model fitted on other matches (matches dealt at random into five
  folds).
- A player's **completion above expected** (completions less expected completions, per pass) is
  put on an even share of possession by how much it rises with the team's share within players
  in the comparison group: less slope x (share - 0.5), with the share while the player is on the
  pitch. The alternative tested: as it comes.

**Reason.**
- An incomplete pass ends where the opponent cut it out: 99.7% of 172,096 incomplete passes end
  within 2 yards of the opponent's next action that can end a pass (9.3% of completed ones).
  Switches are flagged only when the ball crossed 40 yards, the 10,032 incomplete ones included.
  With the end location the held-out AUC rises from 0.88 to 0.92 by learning where passes were
  cut out.
- Held out, on 1,317,164 open-play passes: log loss 0.343 (0.533 for the average, 0.388 for a
  logistic regression on start, direction, height and pressure), Brier score 0.108, AUC 0.883.
  Calibrated across the whole range and in every league (completed over expected 0.994 to
  1.006).
- Completion as recorded mostly measures the ease of a player's passes (Spearman 0.90 to 0.95
  with their mean expected completion, within group); completion above expected takes most of
  it out (0.20 to 0.50) and stays reliable (0.47 to 0.63 at 900 minutes).
- The match still shows in completion above expected: teams complete three to four points more
  than expected in the matches where they have most of the ball, and within players it rises
  0.8 to 1.3 points per 10 points of the team's share (weighted least squares with a fixed
  effect per player). On an even share its correlation with possession falls from 0.30-0.46 to
  0.13-0.19 and the team's share from 0.11-0.35 to 0.07-0.20, at 0.03 to 0.10 of reliability
  (0.40 to 0.60; centre-backs 0.399); the order of players hardly changes (0.95 to 0.99). The
  same within-player rule puts the profiles' per-90 statistics on an even share (2026-10-18).

## 2026-10-24: Possession value in the profiles (notebook 03, section 4)

**Decision.**
- **Completion above expected**, on an even share of possession (2026-10-23), takes the place of
  pass completion in all five outfield profiles.
- **xT gained per 90** (2026-10-19) takes the place of completed passes into the box among
  centre-forwards and of key passes among central midfielders. The other profiles keep their
  statistics.
- Both go through the profiles' four steps (`analysis.profiles`): no recording context;
  possession by the group's elasticity (xT) or slope within players (completion above
  expected); shrinkage by the group's K; percentiles within the group. `make profiles` fits the
  xT map and the expected completion model on the pool's matches (about a minute, against 12
  seconds). This revises the profiles of 2026-10-18; the config keeps what each number replaced
  (`replaced`), so that the analyses made on the earlier profiles can be reproduced.
- The ease of a player's passes (their mean expected completion) is a style, left for role
  discovery with the position descriptors.

**Reason.**
- Each swap was judged within the group, on players with 900+ minutes: the reliability at 900
  minutes, the strongest correlation with the eleven statistics left, and what it adds to them
  (the reliability of the part they do not predict, and how much of that part the team explains
  beyond chance).
- Pass completion as recorded is the steadier number (0.79 to 0.87 against 0.40 to 0.60 at 900
  minutes; what it adds to the other eleven 0.40 to 0.53 against 0.24 to 0.45), but it measures
  the ease of the passes a player chooses (Spearman 0.90 to 0.95) and, among defenders, the
  team: 0.38 of what it adds among centre-backs and 0.23 among full-backs, against 0.13 and 0.09
  for completion above expected. The profiles compare how well a role is played. Alternatives
  tested: keeping pass completion; completion above expected everywhere but among centre-backs,
  where it sits at 0.399, on the profiles' limit. Shrinkage weighs it there by K = 1,356 minutes
  (207 for pass completion).
- xT in place of completed passes into the box among centre-forwards: reliability 0.64 against
  0.44, what it adds 0.30 against 0.13 (closest of the rest: dribbles, 0.55). In place of key
  passes among central midfielders: 0.66 against 0.53, what it adds 0.29 against 0.26, with less
  of the team in it (0.02 against 0.13); the narrowest of the three, as key passes are the more
  direct count for a scout. Elsewhere xT adds less than any statistic of chance creation,
  passing or carrying it could replace; among full-backs it would correlate at 0.87 with passes
  into the box.
- The revised profiles keep the rules: no pair at 0.8 or more (closest 0.63 to 0.74, as before)
  and the same families (xT counted in chance creation: it values a move by the chance the
  possession goes on to reach). Percentiles in completion above expected follow those in pass
  completion at 0.49 to 0.70 (Spearman), and a fifth to a third of players move 25 points or
  more; xT follows the statistics it replaces at 0.73 and 0.74.
- The processed tables reproduce sections 2.2 and 3.2 of notebook 03 (largest difference 6e-17).

## 2026-10-24: No VAEP before the back-test

**Decision.** The back-test (notebook 04) reads the profiles of 2026-10-24, with xT and
completion above expected; VAEP is not added. It is reconsidered if the back-test shows the
profiles missing something that explains how players' careers went.
**Reason.** xT, the possession-value number that credits passes and carries, mostly repeats the
profiles: the group's twelve statistics predict 67% to 87% of it out of sample, and the part
they miss is mostly noise (reliability -0.02 to 0.28 at 900 minutes; notebook 03, section 2.3).
It took the place of a statistic in two profiles only, narrowly among central midfielders
(section 4.1). VAEP would also value defensive actions and set pieces, but it is a second model
to validate (the chances of scoring and conceding within the next actions), and socceraction's
reference implementation, 1.5.3, requires numpy < 2 (2026-10-17).

## 2026-10-24: The market's view of a player (notebook 04, section 1)

**Decision.**
- The market's view of a profiled player (their Transfermarkt value on 30 June 2016) is
  modelled on the log scale, one comparison group at a time, by a ridge regression
  (`analysis.market.value_model`) on what a club could see: age (through a cubic spline),
  minutes, league, the team's goal difference per match in its league (weighted by the player's
  minutes for players who changed teams), and the twelve profile statistics, shrunk and
  standardised within the group.
- Models are judged out of sample with ten folds that keep a team's players together, over 20
  random splits of the teams; intervals come from resampling whole teams.
- A player's gap is the model's out-of-sample value less their value, on the log scale, in two
  versions: within team (the model above) and across teams (without the team's strength).

**Reason.**
- Age, minutes and league explain 29% to 43% of the variation in log value, the team's goal
  difference 62% to 73%, and the profile then adds at most 0.03 (0.12 to 0.25 without the team).
  Goal difference per match explains more than points per match (0.60 to 0.70), as it also
  counts the margin of each result. Boosted trees on the same columns explain less (0.57 to 0.64
  against 0.64 to 0.74, in four settings), so the regression's straight lines miss nothing that
  matters, and they can be read: what the market paid per year of age, per 900 minutes, per half
  a goal of goal difference, per league and per standard deviation of each statistic.
- Teams are held out because teammates share their team's status: with a teammate in the
  training folds, the model would learn a player's value from the team.
- The gap within team is unrelated to the team's strength (Spearman -0.02 to -0.15), the gap
  across teams mostly measures it (-0.46 to -0.57). Both say something the value did not: among
  the 866 players revalued at the same club between 30 June and 1 August 2016, after the season,
  the gap within team agrees with the revaluation at 0.32 (across teams 0.26, minutes alone
  0.24), and the tenth with the largest gap went up 42%. That catch-up is outside the back-test,
  which measures growth from 1 August (2026-10-13).

## 2026-10-24: The gap the back-test reads first (notebook 04, section 1.6)

**Decision.**
- The back-test reads the gap within team first, and the gap across teams as a check. Both
  are fixed before any outcome is looked at.
- Picking players by their team's weakness alone, without their numbers, is one of the
  back-test's baselines.
- The shortlists (section 4) leave out the players of the strongest teams, besides keeping to a
  budget.

**Reason.**
- Under a budget the two gaps find equally cheap players. Among players valued at €5M or less,
  the ten largest gaps of each group cost a median of €0.6M to €2M either way, and the two lists
  share 4 to 8 of their ten names.
- They differ on where the players play. The list across teams takes half its players (25 of
  50) from the weakest fifth of teams, where 28% of the players under the ceiling play. The
  list within team spreads over the five fifths (6 to 13 players each).
- The gap across teams mostly measures the team's strength (Spearman -0.46 to -0.57), so a rule
  that picked weak teams' regulars without their numbers would make much the same list. Reading
  it first would test whether the market's discount for weak teams was too steep, which the
  baseline tests directly, rather than whether the profile finds players.
- The gap within team agrees more with Transfermarkt's revaluation after the season (0.32
  against 0.26).
- A budget misses whether a player was for sale. Of the five largest gaps within team per group
  under €5M, 8 of 25 play for the strongest fifth of teams, where 6% of the players under the
  ceiling play. Among them are prospects at Arsenal and Manchester City, a reserve at Real
  Madrid and Leicester City's champions still on February values, players strong teams do not
  sell at their market value.

## 2026-10-25: How outcomes are scored (notebook 04, section 2)

**Decision** (`backtest` in `config/pipeline.yaml`, `analysis.outcomes`):
- A player's value growth at a horizon (log of their value then over their value on 1 August
  2016) is scored as a **percentile among the profiled players of the same age band**: two-year
  bands from 21 to 32 on 30 June 2016, under 21 and 33 and over open. Players no longer valued
  tie at the bottom of their band. Growth above an age curve is the check.
- The back-test reads the score **three years on (31 August 2019) first**; one, two and five
  years on support it.
- **Careers are secondary outcomes**, read from Transfermarkt's appearances in the season that
  ended before each horizon: league minutes in the big five (900 or more: a regular), minutes
  in the Champions League, and the league played most in (the big five, another covered league,
  none of the covered leagues, or no longer valued).
- Both are fixed before any prediction is checked against them; section 2 reads neither the gaps
  nor the profiles.

**Reason.**
- Raw growth is mostly age: age explains 24% to 43% of it out of sample, and three years on the
  median player under 21 is worth 2.7 times their August 2016 value, the median player aged 31
  or 32 a quarter. Within the bands the score is neutral to age by construction and barely
  depends on position (48 to 52 on average) or league (45 to 54).
- A percentile places the players no longer valued (8% of them three years on, 19% five years
  on, mostly veterans) without inventing a value for them, and resists outliers. Growth above an
  age curve, which would need a floor value for them, ranks the players still valued almost
  alike (Spearman 0.93 to 0.98).
- Three years on comes before the COVID cut of 8 April 2020, with 92% of the players still
  valued and the young near their peak growth; one year on, age explains least (24%) and the
  score correlates only 0.55 with the score three years on, and five years on a fifth of the
  players are no longer valued.
- Value growth follows careers: big five regulars score 59 to 70, the rest 36 to 42, and the
  score correlates 0.45 to 0.54 with big five league minutes, so it is a fair primary outcome.
- The league comes from the minutes, not the club named on the value: valuations name clubs by
  their short name and can predate a move. The club named on 31 August matches the league of the
  season that starts then for 78% to 81% of players who played; the club named on 30 June, the
  season just ended, for 96% to 97%. Players with no league minutes in the covered leagues were
  rarely at a covered club (4% to 7%): mostly at clubs in a lower division that season, or never
  in the covered leagues on record.

## 2026-10-25: How the back-test is judged (notebook 04, section 3)

**Decision** (fixed before any result was seen):
- The system's ranking is the gap within team, out of sample (section 1). Its pick is the top
  10% of each comparison group (133 players); rows tied at the edge of a pick share the places
  left (`analysis.backtest.pick_weights`).
- The pick is judged by its players' mean score three years on (section 2); one, two and five
  years on and the careers support it.
- Baselines pick as many players per group by rules that need no profile: the most minutes in
  2015/16, the cheapest on 30 June 2016, the youngest, and the weakest teams' players (team goal
  difference per match, most minutes first). Checks: the gap across teams, and the gap of the
  value model without the profile.
- Intervals (90%) come from 200 resamples of whole 2015/16 teams, each pick made afresh;
  differences between rankings are read on the same resamples.

**Reason.**
- A pick of the top of each group is how a ranking would be used: a shortlist per position, not
  an ordering of every player. A tenth keeps 18 to 32 players per group; a larger pick would
  dilute the top of the ranking, a smaller one widen the intervals.
- The mean score answers the recruitment question directly: how the chosen players did against
  players of their age. The whole ranking's Spearman correlation is reported beside it.
- Each baseline is a rule a club could have followed with the same information. The weakest
  teams' rule tests the bet the gap across teams makes (section 1.6), and the model without the
  profile tests what the twelve statistics add.
- Teammates share their team's fortunes (promotion, relegation, a sale of the squad), so players
  are not independent; resampling whole teams keeps that in the intervals.

## 2026-10-25: The shortlists (notebook 04, section 4)

**Decision** (fixed before the shortlists' outcomes were looked at):
- A shortlist takes the five largest gaps within team of each comparison group (25 players)
  among the players valued at €5M or less on 30 June 2016, leaving out the players of the
  strongest fifth of teams by goal difference per match (`analysis.backtest.pick_weights` with a
  set number of places).
- The gap within team alone ranks the shortlists; each player's minutes in 2015/16 are shown
  beside it.
- The shortlists are judged as the back-test: the mean score three years on, against every
  player within the budget and the shortlists of the gap without the profile and of the most
  minutes, with 90% intervals from 200 resamples of whole teams. Budgets of €2M and €10M, ten
  players per group and the other horizons are checks.

**Reason.**
- The budget is the ceiling the gap was chosen under (section 1.6). Strong teams do not sell
  their prospects and regulars at their market value: 8 of the 25 largest gaps within team under
  the ceiling played for the strongest fifth of teams (Iwobi, Iheanacho, Nacho, Albrighton and
  Wes Morgan among them).
- The gap and minutes together scored best in the back-test (section 3.3: the 16 players in both
  picks scored 76, either alone about 60), but that was found after the results and no later
  season is left to test it on. It stays a finding; the shortlists keep the system as fixed.
- Five players per group is a list a scout can follow up player by player; ten per group is the
  check.

## 2026-10-28: The descriptors a style is read from (notebook 05, section 1)

Revised 2026-10-29: descriptors read from the matches in a player's own position (entry below).

**Decision.**
- Style within each outfield comparison group is read from **style descriptors**
  (`analysis.style`), not from the profile's twelve statistics: shares and places rather than
  volumes (where a player touches the ball and defends, what they do with the ball, how they
  pass, with which foot, how they defend). The profile judges how well a player plays their role.
- Each descriptor is read from the matches a player spent at least half of in a position of
  their comparison group, and put on an **even share of possession** by its slope within players:
  a weighted least-squares slope on the team's share of the ball with a fixed effect per player,
  fitted per comparison group on players with 900+ such minutes (`style.possession_slopes`,
  `style.adjust`). Counts recorded differently by league or date are first rescaled by recording
  context, as in the profiles.
- Each group keeps the descriptors that are reliable within the group (0.5 or more at 900
  minutes, on an even share), that the team explains less than 0.4 of beyond chance, and that do
  not correlate at 0.8 or more with a more reliable one (Spearman, players with 900+ minutes). The
  share of passes with the left foot is left out, and so is the share with the inside foot where
  the flank a player is put on, given their foot, explains half of it or more, except among
  attacking midfielders and wingers. This gives 9 descriptors for centre-backs, 16 for full-backs,
  21 for central midfielders, 20 for attacking midfielders and wingers and 19 for centre-forwards
  (`roles.descriptors` in `config/pipeline.yaml`).
- Descriptors that did not stay with the players who changed team (the height of defensive
  actions, clearances and blocks, tackles per defensive action) are kept where they pass the
  rules.

**Reason.**
- The descriptors are at least as reliable as the profiles' statistics (median 0.62 to 0.80 at
  900 minutes by group, against 0.61 to 0.71; the same among centre-backs and centre-forwards)
  and add what the profile lacks: the foot follows no profile statistic above 0.42 (Spearman),
  the spreads of a player's touches and the shares of forward and backward passes none above
  0.56. A role taken from the profile would make ranking players within it circular. Alternative
  tested: the profile itself. Its first principal component (22% to 33% of the variation) already
  sets two ways of playing each position against each other and barely follows the team's goal
  difference (0.02 to 0.28) or the player's market value (0.02 to 0.37), so roles from the
  profile would not simply split good players from weak ones; the descriptors are preferred for
  what they add and to keep the profile independent of the role.
- Possession: within players, ten more points of possession raise touches by 2.3 to 3.8 yards and
  defensive actions by 3.6 to 5.9 yards, and add 3 to 4 counterpressures per 100 pressures. On an
  even share, the heights, clearances and blocks, counterpressures and final-third pressures no
  longer follow the team's possession (at most 0.24 in absolute value, from 0.15 to 0.55), and
  the median reliability changes by -0.002.
- Reliability 0.5: the split-half correlation at 900 minutes is the share of the differences
  between players at that sample that is real, and 900 minutes is where players are compared
  from. In a principal component analysis every standardised descriptor weighs the same, so a
  noisy one adds chance to the axes. The rule leaves out through balls (outside attacking
  midfielders and wingers), counterpressures, tackles per defensive action (among centre-backs,
  attacking midfielders and wingers and centre-forwards), final-third pressures (outside central
  midfielders and centre-forwards), switches among centre-forwards (0.49), and among centre-backs
  dribbles and shots per touch and crosses per pass (0.36, 0.45, 0.33), the height of their
  defensive actions (0.39) and their clearances and blocks (0.48).
- The team's share, 0.4: the descriptors left out are at 0.40 to 0.52, and no other passes 0.39.
  They are how defenders pass (pass ease and high passes among centre-backs, 0.47 and 0.48, and
  full-backs, 0.49 and 0.44; pass ease among central midfielders, 0.41), centre-backs' aerial
  duels per touch (0.52), and where defenders play (centre-backs' touch height and spreads, 0.40
  to 0.43; full-backs' touch height, 0.50, width, 0.41, and forward passes, 0.42): how a team
  builds its play, how high its line stands and how opponents attack it. Pass completion, which
  left the profiles as a team number, stood at 0.41 to 0.60 among defenders and central
  midfielders (2026-10-18).
- Pairs at 0.8, the profiles' limit: pass length and the share of long passes (0.92 to 0.97 in
  every group), pass ease and high passes (0.81 and 0.82 among attacking midfielders and wingers
  and centre-forwards), passes and dribbles per touch among attacking midfielders and wingers
  (0.83), touch width and the spread across the pitch among centre-forwards (0.94).
- The left foot (reliability 0.99 to 1.00) says which side a player plays: a left-footed and a
  right-footed full-back can play the same role on opposite flanks. It is left to the similarity
  search. The inside foot says the same where a player is put on a flank: the flank of the other
  foot explains it at R² 0.88 among centre-backs, 0.81 among full-backs and 0.68 among central
  midfielders. Among attacking midfielders and wingers (0.80) the side of the other foot is the
  role itself, the inverted winger who cuts inside; among centre-forwards the flank explains none
  of it (0.03).
- Players who changed team kept a median 0.76 of the correlation their descriptors' reliability
  allowed, on an even share: their foot, carrying, passing length and crossing moved with them;
  the height of their defensive actions (-0.31), their clearances and blocks (-0.37) and their
  tackles did not. They are 22 (6 central midfielders, 5 attacking midfielders and wingers, 5
  centre-forwards, 4 centre-backs, 2 full-backs) with wide intervals. How much of each axis the
  team explains is measured on the axes (section 2).

## 2026-10-28: Style axes rather than roles (notebook 05, section 2)

Revised 2026-10-29: fitted again on the descriptors read from a player's own position, the
congruence averaged over 20,000 halves (entry below).

**Decision.**
- Within each outfield comparison group, a player's style is read as scores on **style axes**,
  not as membership of discrete roles: varimax-rotated principal components of the group's
  descriptors (`roles.descriptors`, on an even share of possession, shrunk towards the group's
  mean with K = 900 (1 - r) / r per descriptor and group, as the profiles are), fitted on the
  group's regulars (900+ minutes in the group's positions); every profiled player is scored
  (`analysis.roles`).
- The number of axes follows a rule fixed before any axis was read: start from the components
  whose eigenvalue stands above the 95th percentile of 200 shuffles of the descriptors (parallel
  analysis), and drop the last axis until every axis has a split-half reliability of 0.7 or more
  at 900 minutes and a mean Tucker congruence of 0.85 or more with the axes fitted on random
  halves of the regulars, averaged over 20,000 halves. This keeps three axes for centre-backs,
  full-backs and centre-forwards and four for central midfielders and for attacking midfielders
  and wingers (`roles.axes` in `config/pipeline.yaml`).
- The positions StatsBomb records are a check, not an input.

**Reason.**
- Roles as groups were tested first, under a rule fixed beforehand: Gaussian mixtures of 2 to 7
  roles on the principal components holding 80% of the descriptors' variation, with full, shared
  or diagonal covariance; the lowest BIC among the mixtures in which every role is the main role
  of at least 10% of the regulars and that refits on random halves of the regulars reproduce (a
  mean adjusted Rand index of 0.6 or more over 50 halves). In every group the lowest BIC is a
  two-role mixture with diagonal covariance, 16 to 46 points better than one component, and none
  is reproduced (0.09 to 0.57, central midfielders the closest); no mixture of three roles or
  more reaches more than 0.44. Roles that change with the players fitted would name noise.
- The axes are reliable (0.72 to 0.89 at 900 minutes, against a median of 0.61 to 0.71 for the
  profiles' statistics), found again in half the players (congruence 0.86 to 0.99), and hold 52%
  to 66% of the descriptors' variation. Each gathers a few descriptors, so it can be named, and
  scores on axes suit a similarity search.
- Axes left out: a fourth for centre-backs and for full-backs (reliability 0.62 and 0.64), a
  fifth and a fourth for centre-forwards (congruence 0.818 and 0.845 ± 0.001).
- 20,000 halves: the congruence is a mean over random halves, first planned over 50.
  Centre-forwards' fourth axis showed that such a mean moves from one sample of halves to the
  next by more than an axis on the line can bear: from 0.77 to 0.90 over 50 halves, from 0.835 to
  0.855 over 1,000. The first 50 halves kept it (0.86), a check over 1,000 left it out (0.837),
  another 1,000 kept it (0.854). Over 20,000 halves the mean is 0.845 ± 0.001, so the axis is
  left out by the rule's own threshold rather than by the sample of halves. Every other count is
  the same over 50, 1,000 or 20,000 halves.
- Alternative considered: archetypes (each player a mix of pure types at the edges of the cloud),
  closer to a scout's vocabulary, but the extremes are the noisiest players and the types would
  face the stability test the mixtures failed.
- Recorded positions: the descriptors tell them apart at a balanced accuracy of 0.57 to 0.75,
  and a position places players clearly on only three axes (the position explains 0.18 to 0.41
  of them, at most 0.08 of the others). They describe the formation more than the style.

## 2026-10-29: Style read from a player's own position (notebook 05, sections 1 and 2)

**Decision.**
- A player's style descriptors are read only from the matches they spent at least half of in a
  position of their comparison group (`style.group_share`, `style.IN_GROUP`): 88% of the
  profiled players' player-matches and 91% of their minutes. The regulars the axes are fitted on
  are the players with 900 such minutes or more (1,176; 1,266 counting every match).
- The spreads of a player's touches along and across the pitch are measured within each match
  and pooled over matches, not over the season's touches.
- The share of passes with the inside foot is left out of a group where the flank a player is put
  on, given their foot, explains half of it or more, except among attacking midfielders and
  wingers.
- The rules of 2026-10-28 are unchanged and were applied again; their outcome is in the two
  entries above.

**Reason.**
- The first version read each player's whole season. Before the axes were named, their ends were
  checked against how each player was deployed, and three of 18 axes measured deployment rather
  than style. Centre-backs' first axis (touches high and wide, crosses) followed the share of a
  player's minutes outside centre-back at a Spearman correlation of 0.54, and 78% of its top
  tenth had spent more than a fifth of their minutes elsewhere, mostly at full-back.
  Centre-backs' fourth and full-backs' third axes followed the share of minutes on the less-used
  flank (0.64 and 0.66): 67% and 69% of their top tenth had played on both flanks, none of their
  bottom tenth. A season's spread of touches across the pitch grows when a player changes flank
  between matches, and the inside foot was explained by the flank of the other foot at R² 0.80
  to 0.87 among centre-backs, full-backs and attacking midfielders and wingers (0.65 among
  central midfielders, 0.12 among centre-forwards).
- Read from their own position, no axis follows deployment beyond 0.35 (Spearman, section 2.3),
  and centre-backs' sides are no longer told apart (balanced accuracy 0.57, chance 0.50). The
  first version's split of centre-backs into two roles (57 who touched the ball higher and wider)
  was that same minority and is gone.
- What changes: centre-backs keep 9 descriptors rather than 15 (their touch height and spreads
  are the team's, 0.40 to 0.43; their crosses are no longer reliable, 0.33, as a centre-back
  crosses when played at full-back), full-backs 16 rather than 20 (touch height, width and
  forward passes are the team's), attacking midfielders and wingers 20 rather than 22,
  centre-forwards 19 rather than 20. The median reliability of centre-backs' descriptors falls
  from 0.71 to 0.62: part of what told them apart was where else they played. The axes become
  three for centre-backs, full-backs and centre-forwards and four for central midfielders and
  attacking midfielders and wingers (first version: four for centre-backs, full-backs and central
  midfielders, three for the others), and no group keeps a mixture of roles (first version:
  central midfielders and centre-backs).
- Half a match: each match is read in the role a player mostly played in it; the 9% of minutes
  left out are matches spent mainly in another group's positions.
- The inside foot stays among attacking midfielders and wingers (R² 0.80): there the side of the
  other foot is the role itself, and their third axis sets the inverted winger who cuts inside
  and plays through balls against the winger who stays wide and crosses. Among centre-forwards
  the flank explains none of it (0.03).

## 2026-10-29: Names of the style axes (notebook 05, section 3)

**Decision.**
- Each style axis is named by its two ends, low and high (`roles.names` in the config):
  - centre-backs: short passer ↔ long passer; ball-carrier ↔ direct passer; central ↔ wide;
  - full-backs: dribbler ↔ box defender; holds position ↔ gets into the box; short passer and
    presser ↔ long passer;
  - central midfielders: deep pivot ↔ advanced midfielder; short passer and presser ↔ long
    passer; ground passer ↔ aerial presence; ball-carrier ↔ forward passer;
  - attacking midfielders and wingers: link player ↔ final-third attacker; lay-off runner ↔
    forward passer; inside forward ↔ touchline winger; ball-carrier ↔ aerial presence;
  - centre-forwards: target man ↔ mobile forward; deep-lying forward ↔ penalty-box striker;
    forward passer ↔ lay-off forward.
- A name is read from the axis's loadings and checked against three portraits of its ends: the
  three lowest and highest scores among players with 1,800 minutes or more in their group's
  positions, the recorded medians of the descriptors loading most on it in the bottom and top
  deciles of the regulars, and where those deciles touch the ball (`style.touch_map`: each
  player counting once, every match mirrored so that the player's touches lean to the same side,
  touches counted as in the descriptors, set pieces included).
- The notebook checks that the descriptor loading most on each axis is the one its name was read
  from: a refit that reorders or flips the axes fails instead of mislabelling them.

**Reason.**
- Loadings alone would have misnamed three axes. 94% of centre-backs' touches in the opposition
  box come after a corner or a free kick, so their second axis sets carrying the ball out against
  passing it on at once and forward, and attacking set pieces, not reaching the box in play.
  Centre-backs keep no clearance or aerial descriptor (section 1.5), so "stopper" would claim
  more than the axis measures. Centre-forwards' forward passing on their
  third axis is not flick-ons (14% of forward passes headed at the low end, 9% at the high end).
- Set pieces in the portraits: the ends of central midfielders' third axis and of attacking
  midfielders' and wingers' second differ in who takes corners and free kicks (4 and 6 times as
  many per touch at one end as at the other), which the names' descriptions say.
- Examples from 1,800 minutes: their scores owe least to the shrinkage towards the group's mean.
- Mirroring each match: a side is not a style (section 1.5). Unmirrored, a decile's left- and
  right-sided players cancel out; mirrored by season, a player who changed flank would still show
  on both sides.
- Numbers beside the maps: on three axes (central midfielders' second, attacking midfielders'
  and wingers' fourth, centre-forwards' third) the two ends' touch maps are no further apart than
  two random groups of regulars (95th percentile), and centre-backs' first is barely beyond it;
  a heat map alone would not show them.

## 2026-10-29: Styles against the market and the back-test (notebook 05, section 4)

**Decision.**
- Style is read against the market and the outcomes, not added to the back-test: the axes are
  set against the gap within team and the growth score three years on of notebook 04, and the
  shortlists are placed on them. The back-test's rankings, fixed before any outcome was read,
  stay as they are.
- The 34 correlations (17 axes, the gap and growth) are judged together under Holm's correction
  at a 10% familywise error, with p-values from 10,000 resamples of whole teams (twice the share
  of resamples on the other side of zero).

**Reason.**
- A ranking that used style after its link with growth had been read would be fitted to the
  outcomes it is judged on.
- Read one at a time at 10%, 34 correlations would turn up about three leads by chance; Holm's
  correction keeps the chance of any false lead among them at 10%.
- 10,000 resamples: Holm's smallest threshold is 0.10 / 34, about 0.003, and a p-value read from
  resamples is only as fine as their number. Over 2,000 the strongest correlation (centre-
  forwards' third axis with growth) read p = 0.002 and passed (Holm 0.07); over 10,000 it reads
  0.0046 and does not (Holm 0.16). As with the congruence of the axes, a decision at a threshold
  needs the estimate precise at the threshold.
- Outcome: no correlation passes. The axes add nothing to the model of the value on 30 June 2016
  (out-of-sample R² 0.001 to 0.009 lower), none follows the gap beyond ±0.10, and the shortlists
  have no style in common (10 of 25 at an end of an axis, about 13 by chance). Centre-forwards
  who lay the ball off grew less than those who pass it forward (-0.21, steady from two to five
  years on and beside minutes and the gap): an open question for the case study.

## 2026-10-29: The style as processed tables

**Decision.**
- `make profiles` also builds every profiled player's style (`roles.build_style`), with the
  config's descriptors, axes and names (`roles`):
  - `style_values`: each descriptor as recorded, on an even share and shrunk;
  - `style_descriptors`: the slopes, reliabilities and K behind them, and the regulars' mean and
    standard deviation the axes are standardised by;
  - `style_axes` (with the names of their ends), `style_loadings` (loadings and weights) and
    `style_scores`;
  - `style_recording`: the recording-context factors of the matches the style is read from.
- Notebook 05 still fits the axes step by step, and checks that the tables hold the same scores
  and shrunk descriptors.

**Reason.**
- The similarity search, team style and the scouting reports read players through their style
  axes. Refitting them in each notebook would take minutes, and could drift from notebook 05.
- The factors, slopes, K and standardisation are kept so that any set of a player's matches (a
  half season, the matches at one club) can be placed on the same axes (`roles.place`).

## 2026-10-29: How alike: the distance of the similarity search (notebook 06, section 1)

**Decision.**
- Players are compared within their comparison group by the Euclidean distance across two blocks
  of equal weight (`analysis.similarity`):
  - style: the shrunk style descriptors (`style_values`);
  - profile: the twelve shrunk statistics of the group's profile (`profile_values`).
- Each block is standardised over the group's regulars (900 minutes or more in its positions)
  and scaled to a total variance of 1, so that its weight does not depend on its number of
  columns. Neither block is whitened.
- The style axes are not part of the distance; they describe how two players are alike, by the
  names of their ends.

**Reason.**
- The test: each player's matches dealt alternately, in date order, into two halves; 576
  players with 900 minutes or more in their group's positions in each half, each half placed on
  the season's terms (`profiles.place`, `roles.place`). A distance is judged by how often a
  player's other half is the nearest of every tested player's (top 1, both ways round; 0.9% by
  chance).
- The rule fixed beforehand chose between the axes and the profile with the profile block
  whitened (a Mahalanobis distance) or not: whitened, the top 1 falls by 6.4 points (-9.2 to
  -3.8, 2,000 resamples of players within group), so neither block is whitened. Whitening gives
  the profile's small directions, mostly noise over half a season, as much weight as its main
  ones.
- The descriptors in place of the axes, a reference in that rule, find the player again 73% of
  the time (70% to 76%) against 59% (56% to 62%), more in every group (centre-backs 58% against
  43%, full-backs 70% against 54%, central midfielders 79% against 64%, attacking midfielders
  and wingers 88% against 75%, centre-forwards 78% against 71%), and across clubs for the 22
  players who changed team in January (34% against 25%). The three or four axes keep what a
  group's players share; what they leave of the descriptors is less shared but as stable.
- Each block alone does worse: the profile 43%, the axes 25%.

## 2026-10-30: What similarity follows (notebook 06, section 2)

**Decision.**
- The search's distance stays as chosen in section 1: teammates, league, line and side are not
  taken out of it. The replacements show each candidate's team and league; side and foot are
  filters.
- Candidates are the group's regulars (900 minutes or more in its positions) and, by a rule fixed
  beforehand, young players (under 23 on 30 June 2016) with 450 to 899 minutes in the group's
  positions. The young players are shown in a list of their own beside the regulars', each with
  their minutes.

**Reason.**
- Among a regular's five nearest regulars, teammates come up 2.6 times as often as by chance
  (2.9% against 1.1%; 2.2 to 3.2 over 2,000 resamples of whole teams), through the descriptors
  (2.7 times) more than the profile (1.75): a team's way of playing shows in its players' style.
  Taking the team out would also take out the system a club may want to find again, and 86% of
  the lists of five hold no teammate. The same league comes up 1.28 times as often as by chance,
  the same line 1.29 times (central midfielders 75% against 53%), the same side 1.06 times: a
  style does not say which side a player plays on.
- The rule: from the tested players' halves (section 1), matches drawn until they reach 270, 450,
  675 or 900 minutes in the group's positions (20 draws, each half in turn). The top 5, both ways
  round, is 92% on a full half, 90% at 900 minutes, 79% at 450 and 67% at 270; at 450 minutes it
  is 0.88 of what it is at 900 (0.87 to 0.89), above the half the rule asks for.
- A list of their own: shrunk towards the group's mean, a short sample comes in more of the other
  players' lists of five than a full half does (7.4 at 450 minutes, 9.8 at 270, against 5).
  Mixed with the regulars, young players would take about half as many places again as their
  style warrants.

## 2026-10-30: The search and what it explains (notebook 06, section 3)

**Decision.**
- The search (`similarity.similar`) lists a player's nearest candidates by the distance of section
  1, the regulars and the young players in lists of their own. The player's teammates (anyone who
  played for one of their teams in 2015/16) are left out unless asked for.
- Filters: age, league, market value on 30 June 2016 (the back-test's market view), foot and side.
  A player is left-footed when half or more of their passes played with either foot in their
  group's positions are with the left; their side is that of the position they spent most time in
  among their group's positions (none in the centre).
- Each candidate comes with the ends of the style axes both players stand at (the bottom or top
  third of the group's regulars on the axis), by name, and the profile statistics the candidate is
  furthest above and below the player on, in percentile points within the group.
- Examples, by a rule fixed beforehand: in each group, the regular with the highest market value
  on 30 June 2016 who changed club for 2016/17 (the club played the most minutes for in
  Transfermarkt's appearances), with a budget of half their value.

**Reason.**
- A club looks for a replacement outside its squad; teammates also come up more often than chance
  (section 2).
- The foot's share is bimodal: of the 1,260 candidates, 908 play under 30% of their passes with
  the left foot and 300 over 70%, 52 in between, so a cut at half sorts almost every player.
- Side has to be a filter: the style is read the same way from both flanks (notebook 05), and the
  nearest regulars to a right-back include left-backs (four of the six nearest to Šime Vrsaljko).
- The axes name how two players are alike in a few words (notebook 05); the descriptors behind
  the distance are too many to read. Percentiles put the profile's statistics on one scale.
- The rule for the examples keeps the choice of players from the results. A budget of half the
  player's value leaves out none to two of the five nearest regulars: the nearest are worth far
  less than the players who left (a median of €2M to €25M beside €13M to €70M).

## 2026-10-30: How a team plays: the team numbers (notebook 07, section 1)

**Decision.**
- A team's play is read through ten numbers over its league season (`analysis.teams`): PPDA, the
  height of defensive actions, final-third pressures and counterpressures per pressure, yards
  gained per completed pass, long passes from the own third, long goal kicks (40 yards or more),
  wide entries into the final third, crosses per final-third pass and pass ease (the mean expected
  completion of its open-play passes).
- Tackles, interceptions, fouls, clearances and pressures are rescaled within recording context
  (each league, and the Premier League before and from match week 19), the location sums of their
  events following them, so that each context keeps the heights of its actions.
- The numbers are not adjusted for a team's strength.

**Reason.**
- Fourteen candidates were judged by a rule fixed beforehand: a split-half reliability over a
  season of 0.7 or more (random halves of each team's matches, centred within the league, 200
  draws, stepped up by Spearman-Brown), and of two numbers at a Spearman correlation of 0.8 or
  more across the 80 teams, the more reliable kept. All fourteen are reliable (0.81 to 0.97); the
  rule drops tempo (passes per possession, 0.93), field tilt (possession, 0.89), passes per
  possession (pass ease, 0.89) and possession (pass ease, 0.84). Pass ease stands for the
  possession game: the teams that keep the ball play the safer passes.
- As recorded, Premier League PPDA goes from 15.8 before match week 19 to 12.7 after it, with
  interceptions recorded about three times as often; on one scale, 12.9 and 12.4. La Liga goes
  from 11.6 to 12.7.
- Goal kicks are bimodal: 21% under 40 yards (median 24), 79% at 40 or more (median 65), 4%
  between 35 and 45.
- Most numbers follow points per match (possession +0.63, the height of defensive actions +0.63,
  PPDA -0.48), but a signing plays in the team's style whatever its cause, so the style is kept as
  it is and its correlation with strength is shown beside it.

## 2026-10-30: Team style axes (notebook 07, section 2)

**Decision.**
- Teams are read on two style axes: varimax-rotated principal components of the ten team numbers,
  standardised across the 80 teams (`team_style` in the config). Their ends: 1. Direct to
  Combination play, 2. Deep block to High press, named from the numbers that load most on each
  axis and the teams at each end.
- The second axis is kept although its eigenvalue sits on the line of shuffled data.

**Reason.**
- The rule of notebook 05, fixed before any axis was read: start from the components above the
  95th percentile of 200 shuffles of the numbers (parallel analysis), and drop the last axis while
  any has a split-half reliability under 0.7 over a season (random halves of each team's matches,
  centred within the league, 200 draws) or a mean Tucker congruence under 0.85 with the axes
  fitted on random halves of the teams (20,000 halves). Two components stand above chance; both
  axes are reliable (0.95 and 0.85) and found again in half the teams (0.981 and 0.978); together
  they hold 68% of the variation.
- The second eigenvalue, 1.525, is on the line: 1.522 for shuffled data over 200 shuffles, 1.524
  over 10,000. It is kept because it is reliable and reproducible and reads clearly, and because
  after a first component as strong as this one (5.3) parallel analysis is conservative for the
  next.
- Axis 1: pass ease (+0.88) and counterpressing (+0.58) against yards gained per pass (-0.77),
  long balls from the back (-0.76), crosses (-0.74), long goal kicks (-0.59) and wide entries
  (-0.55); Eibar, Caen and Frosinone at one end, Paris Saint-Germain, Empoli and Nice at the
  other. Axis 2: the height of defensive actions (+0.88), final-third pressures (+0.87) and
  counterpressing (+0.68) against PPDA (-0.82); Angers, Aston Villa and Troyes at one end, Lyon,
  Barcelona and Napoli at the other.
- The scores follow points per match (Spearman +0.44 and +0.52) and are not adjusted for strength,
  as the numbers are not (section 1).

## 2026-10-30: Players within teams (notebook 07, section 3)

**Decision.**
- When a player's style is set against their team's, the team's scores on the team style axes are
  computed without the player's own actions (`teams.player_match_sums` and `teams.without`).
- A player's style at a new team is predicted from the team style axes: each descriptor and style
  axis moves by its slopes on the team's two scores, fitted on the regulars who played for one
  team all season, times the change in the team's scores. Section 4 reads a signing's style at
  the new club this way.
- The team's part is read on descriptors not shrunk (`recorded` and `adjusted` in
  `style_values`), both as recorded and on an even share of possession.

**Reason.**
- A regular plays a median 3% to 7% of their team's open-play passes, and centre-backs 9% of its
  long balls from the back: left in, the player's own style would be credited to the team. Taken
  out, the scores change little (correlations of 0.99 and 0.97 with the team's own), so the
  correction is cheap and the results do not hang on it.
- The 22 players who changed team in January (450 minutes or more at each) changed style as the
  slopes predict: a slope of 1.00 (0.46 to 1.44 over 2,000 resamples of the players) of the
  change observed on the change predicted over their descriptors and 1.02 (0.47 to 1.69) over
  their style axes, against 0.45 and 0.61 for the 95th percentile of 10,000 shuffles of the team
  changes; leaving any one player out keeps it between 0.88 and 1.17. A slope of 0 would have
  meant that the link between a team's style and its players' is all in whom it picks.
- Shrinkage pulls a player towards the group's mean by their minutes, not their team, so it would
  understate how far teams set their players apart. On an even share the team explains a median
  0.04 to 0.27 of a descriptor beyond chance and the team axes 0.01 to 0.05 (14% to 63% of the
  team's part); as recorded, 0.06 to 0.26 and 0.03 to 0.10.
- On an even share no descriptor follows the deep block to high press axis by more than 0.22; as
  recorded the height of defensive actions follows it (+0.34 to +0.40 outside the centre-backs and
  centre-forwards). Possession goes with the press across the teams (Spearman +0.67), so the even
  share also takes out the height a team's press gives its players. The search keeps the even
  share, which compares players whatever their team's possession; section 4 measures fit both
  ways.

## 2026-10-31: Fit to a club's style (notebook 07, section 4)

**Decision.**
- A club's style in a position is read from all its players of the comparison group together:
  their 2015/16 matches in the group's positions summed and read on the season's terms (the style
  descriptors on an even share of possession, pulled towards the group's mean), with the player
  being measured left out.
- A player's fit to a club is a rank (`teams.fit`): the share of the other clubs, all but the old
  and the new, further from the player than the new club, in the search's descriptor block
  (notebook 06), after the change the team style axes predict (section 3).
- A signing's club for 2016/17 is the club they played most minutes for from July to December in
  Transfermarkt's appearances, or else the club their last summer transfer went to
  (`outcomes.first_half_clubs`); the outcome is their share of that club's league minutes
  (`outcomes.league_share`).
- Fit's effect on minutes is reported over all signings and split by whether the club kept its
  coach from the last league match of 2015/16 to the first of 2016/17 (`outcomes.coaches`). The
  split is named in the notebook as added during the analysis.

**Reason.**
- A rank and not the distance itself: a player near the group's mean is near every club, so the
  distance mixes how typical a player is with how well they fit. The distance to the nearest
  player of the club was set aside: a club with more players in the position would look like a
  better fit, and more players in the position also means more competition for minutes.
- The measure tells a club's style apart: the 1,106 regulars who played for one team all season
  fit their own club, without them, at a mean 0.63 (0.56 for central midfielders to 0.68 for
  full-backs), against 0.5 for an average club. The 204 signings fit their new club at a mean 0.50
  (0.46 to 0.55 over 2,000 resamples of the clubs): clubs did not sign for fit.
- Signings: appearances name 200 of the 204 clubs; summer transfers the other 4 (Transfermarkt's
  transfers are survivorship-biased, so they are the fallback). The club named on a valuation was
  tried as a further fallback and added nobody. Adem Ljajić and Iago Falqué are left out: their
  new club, Torino, played no attacking midfielder or winger in 2015/16.
- The coach: a club's 2015/16 style is its coach's as much as its players', and Transfermarkt's
  games name the coach of each match. With value against the club's regulars, age, minutes and
  group held equal, the slope of the share of minutes on fit is +0.08 over all signings (−0.04 to
  +0.19, within chance: 12% of 10,000 shuffles of the new clubs within group at or above it);
  +0.24 (0.10 to 0.39; 0.3% of shuffles) at the 37 of 64 clubs that kept their coach and −0.12
  (−0.29 to +0.03) at the others, a gap of 0.36 (0.15 to 0.58; 0.2% of shuffles). With the same
  coach the slope stays between +0.20 and +0.24 without the predicted change, as recorded, and with
  the step in team strength as a further control. As the split was not set out beforehand, the
  result over all signings is reported beside it, and the split is the result to test again on
  another season.

## 2026-10-31: Line-ups against the opponent's style (notebook 07, section 5)

**Decision.**
- A player's response to the opponent's style is read within the player: a profile statistic from
  their matches against the upper half of their team's 19 opponents on a team style axis or on
  pass ease, less the same against the lower half (the median opponent left out), on the profile's
  terms and not shrunk. The opponent's style is read from its matches against the other teams.
- Players are not picked by their response to an opponent: no response is reliable enough over a
  season. What the opponent does to every player of a group is reported beside it.

**Reason.**
- Over 180 responses (the twelve profile statistics of five groups, against three sides of the
  opponent's style) and the 764 profiled players with 1,800 minutes or more, the split-half
  reliability over a season (200 draws, stepped up) is a median −0.05 to +0.05 by group. The
  highest, attacking midfielders' and wingers' tackles against a high press, is 0.32, which would
  take about five seasons to reach 0.7, the bar of the team numbers and the style axes. Thirteen
  responses are above the 95th percentile of 200 shuffles of the opponents' halves, where about
  nine would be by chance. The same halves give the players' levels a median reliability of 0.81
  to 0.86, so the halves hold enough matches to tell players apart.
- A team's shared answer to an opponent counts as each of its players', so these reliabilities
  are an upper bound for a player's own.
- Halves of the opponents rather than a slope: every profile statistic, ratios included, is read
  from summed matches by the profile's own functions (`profiles.place`), and each player meets
  nine opponents on each side (14 to 16 matches, the median by group).
- Leaving out the opponent's two matches against the player's team changes its style little
  (correlations of 0.995 to 0.999 with the season's) and takes the player's own team out of it.
