from football_scouting.ingest.statsbomb import check_fixtures, teams_in_every_match


def _match(home: str, away: str) -> dict:
    return {"home_team": {"home_team_name": home}, "away_team": {"away_team_name": away}}


def _round_robin(teams: list[str]) -> list[dict]:
    return [_match(h, a) for h in teams for a in teams if h != a]


def test_complete_round_robin_has_no_gaps():
    check = check_fixtures(_round_robin(["A", "B", "C"]))
    assert check.teams == {"A", "B", "C"}
    assert check.missing == ()
    assert check.duplicated == ()


def test_missing_and_duplicated_fixtures_are_reported_with_home_away_order():
    matches = [m for m in _round_robin(["A", "B", "C"]) if (m != _match("C", "A"))]
    matches.append(_match("A", "B"))
    check = check_fixtures(matches)
    assert check.missing == (("C", "A"),)
    assert check.duplicated == (("A", "B"),)


def test_teams_in_every_match_identifies_single_team_sample():
    matches = [_match("Leverkusen", "X"), _match("Y", "Leverkusen"), _match("Leverkusen", "Z")]
    assert teams_in_every_match(matches) == {"Leverkusen"}
    assert teams_in_every_match(_round_robin(["A", "B", "C"])) == set()
    assert teams_in_every_match([]) == set()
