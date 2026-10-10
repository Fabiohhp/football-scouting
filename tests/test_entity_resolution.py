import pandas as pd
import pytest

from football_scouting.model.entity_resolution import (
    assign,
    confidence_tier,
    name_similarity,
    normalize_name,
    pick_clubs,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("N'Golo Kanté", "n golo kante"),
        ("Uroš Đurđević", "uros durdevic"),  # vs. "Djurdjevic": similarity 0.93
        ("Martin Ødegaard", "martin odegaard"),
        ("Paul-José M'Poku", "paul jose m poku"),
        (None, ""),
    ],
)
def test_normalize_name(raw, expected):
    assert normalize_name(raw) == expected


def test_name_similarity_uses_the_best_variant():
    # Full legal name vs. display name: the StatsBomb nickname carries the match.
    assert name_similarity(["Francisco Román Alarcón Suárez", "Isco"], ["Isco"]) == 1.0
    assert name_similarity(["Sergio Busquets i Burgos"], ["Sergio Busquets"]) == 1.0
    assert name_similarity(["Javier Hernández Balcázar"], ["Chicharito"]) < 0.5
    assert name_similarity([None], ["Isco"]) == 0.0


def test_confidence_tiers():
    assert confidence_tier(games=1.0, name=1.0, margin=0.5) == "high"
    assert confidence_tier(games=1.0, name=1.0, margin=0.08) == "medium"
    assert confidence_tier(games=1.0, name=0.3, margin=0.4) == "low"


def _votes(rows):
    cols = [
        "competition_id",
        "season_id",
        "team_id",
        "team_name",
        "matches",
        "club_id",
        "club_name",
        "votes",
    ]
    return pd.DataFrame(rows, columns=cols)


def test_pick_clubs_breaks_ties_by_name():
    votes = _votes(
        [
            (9, 27, 184, "Eintracht Frankfurt", 2, 99, "Hannover 96", 2),
            (9, 27, 184, "Eintracht Frankfurt", 2, 24, "Eintracht Frankfurt", 2),
        ]
    )
    best = pick_clubs(votes)
    assert best.loc[0, "club_id"] == 24
    assert best.loc[0, "runner_up_votes"] == 2


def test_pick_clubs_rejects_unsupported_or_duplicate_links():
    with pytest.raises(ValueError, match="do not all support"):
        pick_clubs(_votes([(2, 27, 1, "Arsenal", 38, 11, "Arsenal FC", 37)]))
    with pytest.raises(ValueError, match="two StatsBomb teams"):
        pick_clubs(
            _votes(
                [
                    (2, 27, 1, "Arsenal", 1, 11, "Arsenal FC", 1),
                    (2, 27, 2, "Chelsea", 1, 11, "Arsenal FC", 1),
                ]
            )
        )


def test_assign_is_one_to_one_and_best_first():
    scored = pd.DataFrame(
        [
            # sb, tm, score: sb 1 prefers tm 10; sb 2 also likes tm 10 but must take tm 20.
            (1, 10, 0.95, 1.0, 1.0),
            (1, 20, 0.30, 0.2, 0.4),
            (2, 10, 0.60, 0.5, 0.75),
            (2, 20, 0.90, 1.0, 0.75),
        ],
        columns=["sb_player_id", "tm_player_id", "score", "games_jaccard", "name_similarity"],
    ).assign(team_id=7, competition_id=2, season_id=27)
    out = assign(scored).set_index("sb_player_id")
    assert out.loc[1, "tm_player_id"] == 10 and out.loc[2, "tm_player_id"] == 20
    assert out.loc[1, "margin"] == pytest.approx(0.65)
    assert out["tm_player_id"].is_unique
