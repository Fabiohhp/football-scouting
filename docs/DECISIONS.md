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
