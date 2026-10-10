from football_scouting.config import PROJECT_ROOT, load_config


def test_config_loads_and_resolves_paths():
    cfg = load_config()
    assert cfg.paths.raw == PROJECT_ROOT / "data" / "raw"
    assert cfg.statsbomb.raw_base_url.startswith("https://raw.githubusercontent.com/")


def test_configured_competitions_are_unique_2015_16_pairs():
    cfg = load_config()
    pairs = [(c.competition_id, c.season_id) for c in cfg.statsbomb.competitions]
    assert len(pairs) == len(set(pairs)) == 5
    assert {s for _, s in pairs} == {27}


def test_bundesliga_sample_is_excluded_from_scouting_pool():
    cfg = load_config()
    pool = {c.name for c in cfg.statsbomb.competitions if c.scouting_pool}
    assert pool == {"Premier League", "La Liga", "Serie A", "Ligue 1"}


def test_comparison_groups_cover_each_position_group_once():
    cfg = load_config()
    mapping = cfg.comparison_group_of()
    assert sorted(mapping) == sorted(g.code for g in cfg.position_groups)
    assert mapping["AM"] == mapping["W"] == "AMW"
