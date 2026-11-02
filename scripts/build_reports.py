"""Scouting reports of the recruitment case study (reports/scouting/).

One HTML page for each shortlisted player, the player the club replaced and the players of their
group it signed, all as of the back-test's market view, and an index page: the case study of
`case_study` in the config (`analysis.recruitment.case_study`), written by
`reports.write_reports`. Needs `make model`.

Usage: uv run python scripts/build_reports.py
"""

from __future__ import annotations

import sys

from football_scouting.analysis.recruitment import case_study, signings
from football_scouting.config import PROJECT_ROOT, load_config
from football_scouting.model.database import connect_readonly
from football_scouting.reports import write_reports


def main() -> int:
    cfg = load_config()
    with connect_readonly(cfg) as con:
        case = case_study(con, cfg)
        signed = signings(con, case, cfg.backtest.market_view.year)
        paths = write_reports(con, cfg, case, signed)
    for path in paths:
        print(f"{path.relative_to(PROJECT_ROOT)}: {path.stat().st_size / 1024:,.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
