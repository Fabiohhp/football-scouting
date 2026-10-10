"""Write docs/DATA_DICTIONARY.md; fails if a processed column is not documented.

Usage: uv run python scripts/data_dictionary.py
"""

from __future__ import annotations

import sys

from football_scouting.config import PROJECT_ROOT, load_config
from football_scouting.model.dictionary import check, render


def main() -> int:
    cfg = load_config()
    problems = check(cfg)
    if problems:
        print("\n".join(problems))
        return 1
    out = PROJECT_ROOT / "docs" / "DATA_DICTIONARY.md"
    out.write_text(render(cfg), encoding="utf-8")
    print(f"Wrote {out.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
