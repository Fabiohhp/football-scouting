from datetime import date

from football_scouting.analysis.style import NAMES
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


def test_backtest_outcomes_come_after_the_market_view():
    bt = load_config().backtest
    assert bt.market_view == date(2016, 6, 30) and bt.outcome_base == date(2016, 8, 1)
    assert all(h > bt.outcome_base for h in bt.horizons)
    assert date(2020, 8, 31) not in bt.horizons
    assert bt.primary_horizon == date(2019, 8, 31) and bt.age_bands[0] == 21
    assert bt.big_five == ("GB1", "ES1", "IT1", "FR1", "L1")


def test_compared_players_and_recording_contexts():
    cfg = load_config()
    assert (cfg.compared.minutes, cfg.compared.young_minutes, cfg.compared.young_age) == (
        900, 450, 23,
    )  # fmt: skip
    names = {c.competition_id: c.name for c in cfg.statsbomb.competitions}
    assert [(names[c.competition_id], c.since) for c in cfg.recording.changes] == [
        ("Premier League", date(2015, 12, 28))
    ]


def test_xt_grid_shot_value_and_credit():
    xt = load_config().xt
    assert (xt.nx, xt.ny, xt.losses, xt.shot_value, xt.credit) == (48, 32, True, "xg", "gained")
    assert 120 / xt.nx == 80 / xt.ny  # square zones


def test_count_profiles_put_back_what_possession_value_replaced():
    cfg = load_config()
    counted = cfg.count_profiles
    assert all(len(counted[g]) == len(ms) == 12 for g, ms in cfg.profiles.items())
    assert all("pass_completion" in ms for ms in counted.values())
    assert not {"xt", "completion_above_expected"} & {m for ms in counted.values() for m in ms}
    assert counted["CF"][4] == "passes_into_box" and counted["CM"][5] == "key_passes"


def test_role_descriptors_are_style_descriptors_in_family_order():
    cfg = load_config()
    roles = cfg.roles.descriptors
    assert list(roles) == list(cfg.profiles)
    assert all(list(ms) == [m for m in NAMES if m in ms] for ms in roles.values())
    assert [len(ms) for ms in roles.values()] == [9, 16, 21, 20, 19]
    # The left foot is a side, and pass length always stands for the share of long passes.
    assert not {"left_foot_share", "long_share"} & {m for ms in roles.values() for m in ms}
    assert [g for g, ms in roles.items() if "inside_foot_share" in ms] == ["AMW", "CF"]
    assert cfg.roles.axes == {"CB": 3, "FB": 3, "CM": 4, "AMW": 4, "CF": 3}
    assert cfg.roles.names["CB"][0] == ("Short passer", "Long passer")
    assert {g: len(ends) for g, ends in cfg.roles.names.items()} == cfg.roles.axes
