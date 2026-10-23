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

