import matplotlib.pyplot as plt

from football_scouting.plots import credit, save, use_style


def test_a_readme_figure_is_saved_the_same_without_the_software_version(tmp_config):
    use_style()
    fig, ax = plt.subplots()
    ax.plot([0, 1, 2], [1, 3, 2])
    credit(fig)
    path = tmp_config.paths.figures / "line.png"
    save(fig, "line", tmp_config)
    first = path.read_bytes()
    save(fig, "line", tmp_config)
    plt.close(fig)
    assert first.startswith(b"\x89PNG") and path.read_bytes() == first
    assert b"Matplotlib" not in first
