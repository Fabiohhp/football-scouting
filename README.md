# Football Scouting: a 2015/16 Recruitment Back-test

> **Status: work in progress (Phase 3: scouting analyses).** Findings and visuals will
> appear here once the analysis phases are complete.

Using only information available at the end of the 2015/16 season, which players would a
data-driven scouting system have recommended in the Big 5 European leagues, and how did their
careers and market values actually evolve afterwards? Because the season is closed, every
recommendation can be checked against what really happened.

## Key findings

_To be written after Phase 3._

## What this project shows

- **Data engineering**: an idempotent, config-driven pipeline from raw StatsBomb event JSON and
  Transfermarkt data to a documented Parquet + DuckDB analytical model.
- **Data quality**: automated tests (minutes played, goals vs. scores, referential integrity) and
  player entity resolution across providers that share no IDs.
- **Football analytics**: per-90 profiles shrunk by measured reliability, possession value
  (expected threat), role discovery, similarity search and team-style context.
- **Recruitment back-test**: features from 2015/16 only, outcomes from later seasons, kept
  strictly apart to avoid leakage.
- **Communication**: statistical analyses written up as notebooks for scouts and recruitment
  staff, with plain-language conclusions.

## Data

| Source | Use | Coverage |
|---|---|---|
| [StatsBomb Open Data](https://github.com/statsbomb/open-data) | Event data, xG, lineups | 2015/16 Premier League, La Liga, Serie A (380 matches each), Ligue 1 (377); Bundesliga (Bayer Leverkusen's 34 only). 5.4M events. |
| [Transfermarkt datasets (dcaribou)](https://github.com/dcaribou/transfermarkt-datasets) | Market values, careers | Valuations 2004 to 2026: 97.5% of 2015/16 players valued before the season's end, about 80% still valued five years later |

See [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md) for coverage, known gaps and terms, and
[`reports/coverage_report.md`](reports/coverage_report.md) for the full counts.

## Methodology

_To be written._

## Reproduce

Requirements: [uv](https://docs.astral.sh/uv/) and `make`.

```bash
make setup             # create the environment from uv.lock (Python 3.12)
make test              # run the test suite
make data              # download (~0.5 GB, ~4.5 GB on disk), convert, validate, report
make model             # analytical tables, StatsBomb <-> Transfermarkt links, DuckDB, dictionary
make dq                # data quality tests
```

The processed tables are documented in [`docs/DATA_DICTIONARY.md`](docs/DATA_DICTIONARY.md);
every command, the code conventions and the data pitfalls found so far are in
[`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md).

All pipeline parameters (competitions, seasons, source versions, paths) live in
[`config/pipeline.yaml`](config/pipeline.yaml). Data is written to `data/` and never committed.

## Project layout

```
config/      pipeline configuration
src/football_scouting/   reusable package (ingestion, modeling, metrics)
scripts/     pipeline entry points
notebooks/   exploration and storytelling (imports from src/)
reports/     figures and generated reports
tests/       pytest suite
docs/        decisions, progress, development notes, data sources, data dictionary
```

## Data attribution

Event data provided by [StatsBomb](https://statsbomb.com/) through its free
[open-data](https://github.com/statsbomb/open-data) repository. Market value and transfer data
from Transfermarkt via the [transfermarkt-datasets](https://github.com/dcaribou/transfermarkt-datasets)
project. Full terms in [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md).
