# Development notes

How the repository is organised, the commands that rebuild everything, the rules that keep the
back-test honest, and the data pitfalls found so far. Decisions and their evidence are in
[`DECISIONS.md`](DECISIONS.md); the status is in [`PROGRESS.md`](PROGRESS.md).

## Commands

```bash
make setup             # uv sync --locked (Python 3.12, pinned by uv.lock)
make lint              # ruff check + ruff format --check
make format            # ruff --fix + ruff format
make test              # unit tests (tests marked `network` or `data` are deselected)
make all               # data + model + dq
make data              # download, convert, validate, coverage report (idempotent)
make model             # build-tables, links, database, profiles, dictionary (~1.5 min)
make dq                # data quality tests on data/processed (pytest -m data)
make notebooks         # re-run every notebook in place (needs `make model`)
make verify-statsbomb  # StatsBomb coverage + size estimate (metadata only); writes inventory.csv
make download-statsbomb       # raw JSON -> data/raw/statsbomb/ (resumable, size-checked)
make download-transfermarkt   # gz CSVs -> data/raw/transfermarkt/ (+ manifest.json)
make convert-statsbomb        # raw JSON -> data/interim/statsbomb/*.parquet (FORCE=1 rebuilds)
make validate-statsbomb       # deep check Parquet vs raw JSON (key paths, counts, xG sums)
make coverage-report          # reports/coverage_report.md
make build-tables             # data/processed/{statsbomb,transfermarkt}/*.parquet
make links                    # data/processed/links/ (StatsBomb <-> Transfermarkt)
make database                 # data/processed/scouting.duckdb (views)
make profiles                 # data/processed/profiles/ (player profiles), then the views again
make dictionary               # docs/DATA_DICTIONARY.md (fails on undocumented columns)
```

Run a single script: `uv run python scripts/<name>.py`. Add a dependency: `uv add <pkg>`
(dev-only: `uv add --dev <pkg>`); `pyproject.toml` and `uv.lock` always change together.

## Layout and conventions

- Python 3.12 (capped `<3.13` for socceraction), `uv` for the environment, `uv.lock` pins exact
  versions. Ruff (line length 100) for lint and format, notebooks included; pytest for tests.
- Reusable logic in `src/football_scouting/`; thin entry points in `scripts/`, exposed as
  Makefile targets; `notebooks/` hold the analyses and import their logic from the package;
  `reports/figures/` holds the figures used by the README.
- All parameters (sources, pinned versions, competitions, seasons, position and comparison
  groups, who is compared, profiles, recording contexts, the xT map, back-test dates, paths,
  HTTP retry policy) come from `config/pipeline.yaml` via
  `football_scouting.config.load_config()`. No hard-coded IDs or paths in code.
- Pipeline steps are idempotent and resumable: cached downloads (`http.fetch_json_cached`),
  atomic writes (`.part` + rename), retries with exponential backoff, existing files skipped.
- Raw StatsBomb files mirror the open-data repo layout under `data/raw/statsbomb/`, downloaded
  from the commit SHA pinned in the config (`statsbomb.ref`), never from `master`.
- Data layers: `data/raw/` (as downloaded), `data/interim/` (a faithful Parquet copy of the raw
  JSON: nested STRUCT/LIST columns, strings kept as strings, no cleaning), `data/processed/`
  (the analytical model; `profiles/` is built from the other processed tables by
  `analysis.profiles`). Interim tables are queried with DuckDB, e.g.
  `read_parquet('data/interim/statsbomb/events/*.parquet')`, nested fields as
  `shot.statsbomb_xg`.
- DuckDB connections for big scans come from `statsbomb_parquet.connect()` (4 threads, 3 GB
  limit): the JSON conversion peaks at about 4 GB of memory.
- New processed columns must be described in `src/football_scouting/model/dictionary.yaml`
  (`make dictionary` fails otherwise).
- Tests that hit the network are marked `network`; tests on the processed data are marked
  `data` and run with `make dq`.

## Notebooks

- `football_scouting.model.database.connect_readonly(load_config())` gives a DuckDB connection
  with every processed table as a view (Transfermarkt tables prefixed `tm_`).
- Helpers in `football_scouting.analysis`:
  - `players.pool_player_seasons`: one row per pool player, minutes summed over clubs, primary
    position group, comparison group, age on a given date;
  - `metrics.player_match_counts` and `metrics.rates`: event counts per player and match, then
    46 per-90 rates and ratios from any sum of rows, in seven `FAMILIES` (definitions in the
    module docstring; progressive passes and carries under three rules, `metrics.progressive`);
  - `reliability`: split-half reliability and the stabilisation constant K per metric, in
    minutes or, with `budget="shots"`, in shots for per-shot ratios, and of adjusted rates
    (`rate_fn`);
  - `possession.team_possession` and `possession.player_possession`: time with the ball per team
    and match, and each player's team's and opponent's time while on the pitch;
    `possession.elasticity`: how much a count depends on possession, within players (Poisson,
    a fixed effect per player); `possession.adjust_rates`: rates put on an even share;
  - `profiles`: the four steps of a profile (recording context, possession, shrinkage,
    percentiles), each a function (`recording_factors`, `rescale`, `possession_effects`,
    `adjusted_rates`, `reliability`, `shrink`, `percentiles`), and `build_profiles`, which
    chains them for `make profiles`; the functions take the processed profile tables back as
    arguments. Besides the `metrics` rates, a profile can hold two possession-value numbers
    (`VALUES`: `xt`, `completion_above_expected`): `value_sums` adds the sums behind them to
    the player-match counts, `profile_rates` turns sums into rates; `LABELS` and `FAMILY_OF`
    cover every statistic. `build_profiles(con, cfg, cfg.count_profiles)` rebuilds the
    profiles as chosen from the event counts (notebook 02), without them;
  - `xt`: expected threat. `load_actions` (open-play moves, shots and, optionally, ball
    losses), `fit` (the map on any grid), `value_at` and `move_credit` (the xT a move gains),
    `chain_outcomes` (the xG of the open-play shot each event's chain went on to take, to
    check a map on held-out matches), and `player_match_credit` and `credit_rates`: a player's
    xT per match and per 90 in three versions (`CREDITS`: gained, net, charged);
  - `xpass`: expected pass completion. `load_passes` (open-play passes with the features known
    when a pass is played, `FEATURES`, and the ones that leak its outcome, `LEAKS`),
    `next_opponent_action` (the check that an incomplete pass ends where it was cut out),
    `expected_completion` (each pass scored by a model fitted on other matches, `match_folds`),
    `player_match_passes` and `completion_rates` (completion, expected completion, completion
    above expected), `possession_slope` and `adjust_above_expected` (within players, on an even
    share of possession);
  - `values.pool_valuations` and `values.value_at`: Transfermarkt valuations of pool players
    and each player's value (and its age) on a date;
  - `leagues.eta_squared`, `leagues.league_effect` and `leagues.team_effect`: how much of a
    number the league explains, between team-matches and for players within comparison group,
    and how much the team explains beyond chance;
  - `links.statsbomb_games`, `links.transfermarkt_games` and `links.side_by_side`: each
    player-match's goals, cards and minutes (match clock) in both sources, lined up for any
    pairing of StatsBomb and Transfermarkt players (checks of the links).
- Figures use `football_scouting.plots`: `use_style()`, `position_colors(cfg)` and
  `credit(fig)` for the source line. Pitches are drawn with mplsoccer
  (`pitch_type="statsbomb"`).
- Players are compared within the six `comparison_groups` of the config, not the seven
  position groups, and read through the twelve statistics of their group's profile
  (`profiles` in the config; `replaced` records the three statistics possession value took
  the place of). Later analyses read the profiles from the processed tables
  (`profile_players`, `profile_values`: one row per player and statistic, as recorded,
  adjusted, shrunk and as a percentile), not from the raw rates.

## Rules that protect the analysis

- **No data in git.** `data/` is ignored, as are `*.parquet` and `*.duckdb`. StatsBomb's terms
  forbid redistributing the data, so notebooks show aggregated results only (no dumps of event
  tables), and published work credits StatsBomb with its logo (see
  [`DATA_SOURCES.md`](DATA_SOURCES.md)).
- **No leakage.** Features use 2015/16 information only. Outcomes (later market values,
  transfers, careers) live in separate tables and are never joined into feature code.
  Transfermarkt snapshot columns (current club and value, highest value, contract, caps,
  agent, positions, squad values) describe 2026 and are outcomes only.
- **Every claim about the data is checked against the files**, with counts: what a field
  means, what a table covers, how many rows a rule affects.

## Data pitfalls found so far

StatsBomb:
- Bundesliga 2015/16 (competition 9, season 27) is **Bayer Leverkusen's 34 matches only**:
  outside the scouting pool (`scouting_pool: false`).
- Ligue 1 2015/16 has 377 of 380 matches (missing: Bastia vs Gazélec Ajaccio, Saint-Étienne vs
  Paris Saint-Germain, Troyes vs Bordeaux); those six teams have 37 matches.
- Matches 3878540 (Serie A, Lazio vs Bologna) and 3900563 (Ligue 1, Guingamp vs Rennes) have no
  `data_version` / `shot_fidelity_version` / `xy_fidelity_version`; their shots and locations
  look like the rest (EDA sections 5 and 6).
- Event dicts have heterogeneous keys: `pyarrow.Table.from_pylist` infers the schema from the
  **first row only** and silently drops columns. Infer over all rows (`pa.array(rows)`) or pass
  an explicit schema.
- **Lineups include unused substitutes** (empty `positions` list); a player played if they have
  at least one position.
- **Lineups do not close stints at exits**: dismissals (413 of 420) and some substitutions after
  a "Player On" leave the player on until the final whistle. `model/minutes.py` ends time at
  the first exit; never compute minutes from lineups directly.
- Lineup `from` / `to` and event `minute` / `second` are the match clock (45:00 at the start of
  the second half), not real time: use `match_seconds` / `start_seconds`. Event `timestamp`
  restarts every period. Cards (Bad Behaviour) can come after the whistle.
- Names contain escaped apostrophes ("N''Golo"); the processed tables undo it.
- **Recording changes.** From 2015-12-28 (match week 19) the Premier League records about 3x
  the interceptions, 18% more pressures and 16% more clearances; interceptions also differ
  about 1.6x between leagues. Never compare raw interceptions, pressures or clearances across
  leagues or across that date; counterpressures (+14%) and pressures in the final third (+21%)
  change with pressures. Attacking and passing numbers share one scale (league partial
  η² <= 0.03).
- **Reliability.** Goals and dribble success are mostly noise over one season; non-penalty xG
  needs about 1,700 minutes for r = 0.7. Finishing (goals minus xG per shot) shows no skill in
  one season (K about 1,600 shots); xG per shot is stable (K about 28 shots). Reliability
  depends on the comparison group: at 900 minutes xG per 90 is 0.66 among attacking midfielders
  and wingers, 0.18 among centre-backs. Shrink with K per metric and comparison group
  (`analysis.reliability`).
- **Contests.** An aerial duel is won on the winner's action (`aerial_won` on a pass,
  clearance, shot or miscontrol) and lost as a Duel of type Aerial Lost: equal counts in every
  match. Every completed dribble leaves a Dribbled Past event for the defender. Fouls won follow
  the league's refereeing (Serie A a third more per match than the Premier League), and times
  dribbled past the opposition's dribbling (more in the Premier League and La Liga).
- **Possession.** An event's `possession_team_id` is the team in control, also on the
  opponent's events; a recovery, tackle or interception often starts the acting team's
  possession (77% of ball recoveries, 42% of tackles and 34% of interceptions are recorded in
  it).
  Whether an action was made with or without the ball follows from its type, not its possession
  team. Time with the ball: gaps between events capped at 10 seconds (`analysis.possession`).
  Who has the ball next: after an incomplete open-play pass the opponent (or a set piece) acts
  next 99.6% of the time; after a dispossession 80%, a failed dribble 83%, a miscontrol 93%.
- **Locations.** A 0.1-yard grid from 0.1 to 120.0 and 0.1 to 80.0; the acting team attacks
  towards x = 120 with y = 0 on its left, and the same spot seen by the other team is
  (120.1 - x, 80.1 - y). Set-piece spots (kick-offs at x = 60 or 61, goal kicks at 6 or 7) give
  away the end of the stadium a team attacks; towards one end on-ball actions sit 2.5 yards
  further right. Season numbers balance the two ends, single halves do not. Location-based
  numbers share one scale across leagues.
- **Pass ends.** An incomplete pass ends where the opponent cut it out (99.7% within 2 yards of
  the opponent's next interception, recovery, clearance, block or goalkeeper action, when it
  comes within three events), not where it was aimed: its end location and length give the
  outcome away (ground passes: median 15.6 yards completed, 12.7 incomplete). The switch flag is
  set only when the ball crossed 40 yards, completed or not. Crosses, through balls and
  cut-backs are flagged on incomplete passes too.
- **xG.** Every penalty has xG 0.7835 and most have no freeze frame; shots straight from a
  corner sit at the xG floor (0.00018). Non-penalty xG runs about 4% below goals in every
  league; direct free kicks score 1.6 times their xG, open-play shots under 0.06 xG score less
  than predicted and chances of 0.1 to 0.4 more. Rankings within a comparison group barely
  change when xG is recalibrated, so xG is used as published.

Transfermarkt:
- **`transfers` is survivorship-biased**: no records for players whose `players.last_season` is
  before 2020, and only 38% of 2015/16 -> 2016/17 club changes have a record. Use `appearances`
  and the club on each valuation for careers.
- `games.season` 2015 means 2015/16. Competition codes: GB1, ES1, IT1, FR1, L1. `appearances`
  only contains players who played.
- **`appearances` covers 14 first divisions** (the pool leagues, Bundesliga, Eredivisie,
  Portugal, Turkey, Belgium, Russia, Greece, Scotland, Ukraine, Denmark), their cups and
  European competitions. A player elsewhere has no games on record but is still valued with
  the club named: 21% of pool players in 2016/17 (mostly relegated clubs), 32% in 2020/21.
  Never read "no appearances" as "no career".
- Valuations are irregular in time: "value at date X" is the latest valuation on or before X,
  and its age is kept. 520 transfers are future-dated (up to 2030).
- **Valuations come in league batches**: on 30 June 2016 most values date from January or
  February; the end-of-season revaluation came on 13 July to 1 August 2016, after Euro 2016
  and with July's transfers already in. The back-test reads the market's view on 30 June 2016
  and growth from 1 August 2016 (`backtest` in the config); later values are outcomes only.
- **8 April 2020: a flat COVID cut** of almost every value (1,650 pool players, median -20%);
  on 31 August 2020 most values are still that cut. Raw value growth is mostly age: compare a
  player's growth with players of the same age.
- **`player_valuations.current_club_id` (and `player_club_domestic_competition_id`) is often
  the player's 2026 club**, not the club at the valuation date. Use `current_club_name`.
- Missing dates of birth are filled only from `config/date_of_birth_overrides.csv` (with a
  source); the build fails if an override would replace an existing date.
- Name and coverage gaps handled by hand in `config/player_match_overrides.csv`: Markel
  Susaeta and Rushian Hepburn-Murphy have no 2015/16 appearances; Assane Gnoukouri is listed
  as "Alassane Traoré".
