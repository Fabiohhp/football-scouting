"""Shared figure style for the notebooks and the README figures."""

from __future__ import annotations

import matplotlib as mpl
from matplotlib.figure import Figure

from football_scouting.config import Config

# Okabe-Ito: distinguishable with the common forms of colour blindness.
OKABE_ITO = ("#0072B2", "#E69F00", "#009E73", "#CC79A7", "#56B4E9", "#D55E00", "#000000")
GREY = "#8C8C8C"
CREDIT = "Data: StatsBomb Open Data (2015/16), Transfermarkt via dcaribou/transfermarkt-datasets"


def use_style() -> None:
    mpl.rcParams.update(
        {
            "figure.dpi": 110,
            "savefig.dpi": 200,
            "savefig.bbox": "tight",
            "font.size": 10,
            "axes.titlesize": 12,
            "axes.titleweight": "bold",
            "axes.titlelocation": "left",
            "axes.labelsize": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "axes.grid.axis": "y",
            "grid.color": "#E5E5E5",
            "grid.linewidth": 0.8,
            "legend.frameon": False,
        }
    )


def position_colors(cfg: Config) -> dict[str, str]:
    """{position group code: colour}, stable across notebooks."""
    return {g.code: OKABE_ITO[i % len(OKABE_ITO)] for i, g in enumerate(cfg.position_groups)}


def credit(fig: Figure, text: str = CREDIT) -> None:
    """Source line in the bottom-left corner (StatsBomb asks to be credited)."""
    fig.text(0.01, -0.02, text, fontsize=7.5, color=GREY, ha="left", va="top")
