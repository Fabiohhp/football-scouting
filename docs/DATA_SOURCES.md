# Data sources

Two sources, no shared identifiers. Everything below was checked against the downloaded files
on 2026-10-06; the counts are reproduced by `make data` and summarized in
[`reports/coverage_report.md`](../reports/coverage_report.md).

## 1. StatsBomb Open Data (primary: on-pitch performance)

**What.** Event data exported from the StatsBomb Data API as JSON: every on-ball action with
location, outcome and player, StatsBomb xG and freeze frames on shots, plus lineups (with
positions played and their time windows), match metadata and the competitions list.

**Where.** [github.com/statsbomb/open-data](https://github.com/statsbomb/open-data), downloaded
from commit `4b73468fc5b0f1950f9f66fada70ad3a4f9327cb` (latest `master` on 2026-10-06) through
`raw.githubusercontent.com`. Raw files mirror the repo layout under `data/raw/statsbomb/`.
Format specifications are PDFs in the repo's `doc/` folder (Open Data Events v4.0.0, Lineups
v2.0.0, Matches v3.0.0, Competitions v2.0.0, 360 Frames v1.0.0).

**Coverage used: 2015/16, season_id 27.**

| League | competition_id | Matches | Teams | Events | Players who played |
|---|---|---|---|---|---|
| Premier League | 2 | 380 | 20 | 1,313,773 | 550 |
| La Liga | 11 | 380 | 20 | 1,295,354 | 539 |
| Serie A | 12 | 380 | 20 | 1,353,739 | 551 |
| Ligue 1 | 7 | 377 | 20 | 1,358,593 | 574 |
| 1. Bundesliga | 9 | 34 | 18 | 115,240 | 346 |

Raw size: 4.48 GB of JSON (events 4.45 GB, lineups 28 MB). Interim Parquet: 359 MB.
All matches have `match_status = available`, `data_version` 1.1.0 and shot / xy fidelity
version 2, except the two noted below.

**Known gaps and quirks.**
- **Bundesliga is a single-team sample**: the 34 matches are Bayer Leverkusen's. The other 17
  clubs appear once or twice each. Excluded from the scouting pool (see `DECISIONS.md`).
- **Ligue 1 has 377 of 380 matches.** Missing (home vs away): Bastia vs Gazélec Ajaccio,
  Saint-Étienne vs Paris Saint-Germain, Troyes vs Bordeaux. Those six teams have 37 matches.
  Transfermarkt has all 380 games, so these three can be identified there.
- **No 360 data** for any of these matches (`match_available_360` is null).
- Two matches have no `data_version` / `shot_fidelity_version` / `xy_fidelity_version` in their
  metadata: 3878540 (Serie A, Lazio vs Bologna, 2015-08-22) and 3900563 (Ligue 1, Guingamp vs
  Rennes, 2015-12-19).
- **Lineups include unused substitutes**, listed with an empty `positions` list. "Players who
  played" = at least one position. Squads per team-match range from 15 to 24 players.
- 10 (match, player) pairs have events but an empty `positions` list. To investigate in Phase 2
  (minutes played).
- `matches.home_team.home_team_group` / `away_team_group` are null in every match.
- StatsBomb re-releases files in place: `match_available` dates for these seasons range from
  2024-05-19 (Bundesliga) to 2026-05-12 (Ligue 1). Hence the pinned commit.
- **Recording differs between leagues and within the Premier League** (found 2026-10-11,
  `notebooks/01_data_exploration.ipynb` section 3). From 28 December 2015 (match week 19) the
  Premier League has about 3 times as many interceptions per match (median 11 -> 34), 18% more
  pressures and 16% more clearances, while passes, recoveries and duels stay flat. Across
  leagues, interceptions per team and match range from 10 (Serie A) to 16 (La Liga). No other
  event type in any league shifts by more than 8% between the two halves of the season.

**Terms of use** ([`LICENSE.pdf`](https://github.com/statsbomb/open-data/blob/master/LICENSE.pdf),
"StatsBomb Public Data User Agreement", last updated 8 September 2023, plus the repo README):
- Free to use for research and analysis; analysis and conclusions may be shared publicly.
- **Attribution is required**: any published analysis must name StatsBomb as the data source
  and carry the StatsBomb logo (README "Terms & Conditions"; agreement clause 1.4). Logos:
  [StatsBomb Media Pack](https://statsbomb.com/media-pack/), or `img/` in the repo.
- **No redistribution** of the data to third parties (clause 1.2.1). Consequences here: raw,
  interim and processed data are never committed, and published notebooks and the README show
  only aggregated results, never dumps of event-level data.
- No commercial exploitation of the data or derived analysis (clause 1.2.2).
- StatsBomb asks users to register their interest at
  [statsbomb.com/resource-centre](https://www.statsbomb.com/resource-centre) (clause 2.2).
- Provided "as is", with no warranty of accuracy or completeness.

## 2. Transfermarkt datasets by dcaribou (secondary: market values and careers)

**What.** Tables built from [transfermarkt.co.uk](https://www.transfermarkt.co.uk/) by the
[transfermarkt-datasets](https://github.com/dcaribou/transfermarkt-datasets) project. We use 7
of its tables, as gzipped CSVs: `players`, `player_valuations`, `transfers`, `clubs`,
`appearances`, plus `competitions` (decodes competition codes such as `GB1`) and `games` (the
season of each appearance).

**Where.** `https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data/<table>.csv.gz`, stored as
downloaded under `data/raw/transfermarkt/`. All files were published on 2026-09-05
(`Last-Modified`). Upstream overwrites files in place, so `data/raw/transfermarkt/manifest.json`
records each file's size, sha256, ETag and Last-Modified. According to the project README,
updates are paused: `games` ends 2026-07-06, `appearances` 2026-06-28, `player_valuations`
2026-06-12.

**Coverage verified.**

| Table | Rows | Range |
|---|---|---|
| players | 50,149 | |
| player_valuations | 656,301 | 2000-01-20 to 2026-06-12 (sparse before 2004) |
| transfers | 175,165 | 1993-07-01 to 2030-06-30 |
| clubs | 796 | |
| appearances | 1,894,350 | |
| competitions | 65 | |
| games | 88,958 | seasons 2005 to 2025 |

- `games.season` 2015 = 2015/16 (first game 2015-08-08, last 2016-05-17 in the Premier League).
- 2015/16 games: 380 in each of GB1, ES1, IT1, FR1; 306 in L1 (full Bundesliga).
- `appearances` lists only players who played (3 of 1.9M rows have 0 minutes).
- **Player counts agree with StatsBomb.** Players who played in 2015/16, Transfermarkt vs
  StatsBomb: Premier League 549 vs 550, La Liga 538 vs 539, Serie A 551 vs 551, Ligue 1 575 vs
  574; the four leagues together 2,175 vs 2,176. This is a good sign for entity resolution.
- For those 2,175 players: all are in `players`, 2,174 have a date of birth, 2,120 (97.5%)
  have a market valuation on or before 2016-06-30 (95.3% within the previous 6 months), and
  valuations continue in later seasons (2016/17: 97.4% of players valued; 2018/19: 89.2%;
  2020/21: 79.7%).

**Known gaps and quirks.**
- **`transfers` is survivorship-biased.** No player whose `players.last_season` is before 2020
  has any transfer record (14,153 players in the snapshot; 935 of our 2,175). Even for the
  others, only 61.6% have one. Of the 583 pool players whose main club changed between 2015/16
  and 2016/17, only 38.1% have a matching transfer record (e.g. Higuaín's 2016 move to
  Juventus is missing). Career moves need `appearances` and the club on each valuation.
- 520 transfers are dated after the snapshot's last game (up to 2030-06-30): announced future
  moves.
- `transfers.transfer_fee` is present on most rows, but the meaning of 0 vs null (free, loan,
  unknown) is not yet verified.
- Valuations are irregular in time (a few per player per year), so "value at date X" means "the
  latest valuation on or before X" and its age must be tracked.

**License and attribution.** The dataset repository is licensed CC0-1.0. The data itself comes
from transfermarkt.com, and we credit Transfermarkt as the original source alongside the
dataset. This is a non-commercial portfolio project.

## Attribution text (README, notebooks, reports)

> Event data: StatsBomb Open Data (statsbomb.com), shown with the StatsBomb logo. Market
> values, transfers and careers: Transfermarkt (transfermarkt.com), via the
> transfermarkt-datasets project by dcaribou (CC0-1.0).
