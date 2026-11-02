# Notebooks

The analyses, in the order they build on each other. Each notebook opens with its questions and
closes every section with what it shows; the logic lives in the `football_scouting` package, and
the notebooks call it. Only aggregated results are shown, as StatsBomb's terms require.

| Notebook | Question | What it found |
|---|---|---|
| [01 · Data exploration](01_data_exploration.ipynb) | What does the 2015/16 data look like before any model: minutes, reliability, leagues, market values, xG, event locations, the links between the two sources? | The Premier League recorded about three times the interceptions from 28 December 2015; finishing shows no skill over one season; Transfermarkt revalued players after Euro 2016, in July; 2,277 pool players linked across sources with at most about three wrong. |
| [02 · Player profiles](02_player_profiles.ipynb) | Which numbers describe a player, once possession, recording and small samples are accounted for? | Twelve statistics per position group, adjusted for possession as measured within players and shrunk by their reliability, forecast the rest of a season 21% to 28% better than the raw rates. |
| [03 · Possession value](03_possession_value.ipynb) | What are a player's passes and carries worth? | An expected-threat map that counts ball losses (the textbook map overstates threat by 46%) and an expected pass completion model (held-out AUC 0.883): completion as recorded mostly measures how easy a player's passes are. |
| [04 · Market value and the recruitment back-test](04_recruitment_backtest.ipynb) | What did the market pay for on 30 June 2016, and did the players it undervalued outgrow players of their age? | Shortlists of the most undervalued players under a €5M budget scored 72.9 three years on, against 48.3 for every player within the budget; the event-data profile added nothing detectable to that. |
| [05 · Role discovery](05_role_discovery.ipynb) | Which role does a player play, from what they do and where? | No discrete roles: style is a continuum, read on three or four named axes per group. The market priced no style beyond a player's numbers, and no axis predicts value growth. |
| [06 · Similarity search](06_similarity_search.ipynb) | Who plays like a given player, within a budget? | A player's two half-seasons find each other first 73% of the time among 60 to 156 players. Clubs' 2016/17 signings were no nearer the player who left than chance. |
| [07 · Team style](07_team_style.ipynb) | How does a team play, and does a signing fit it? | Two team style axes (direct to combination play, deep block to high press); players who changed team in January changed style as the new team's style predicts. Fit went with minutes only at clubs that kept their coach. |
| [08 · Recruitment case study](08_recruitment_case_study.ipynb) | AFC Bournemouth must replace Matt Ritchie on 30 June 2016: who to sign? | The shortlist did better than 99.8% of random picks from the same long list three years on; the recommendation, chosen by fit, was its one miss. One-page scouting reports in [`reports/scouting/`](../reports/scouting/). |

## Running them

The notebooks read the processed tables, so they need `make data` and `make model` first (see the
main [README](../README.md#reproduce)). `make notebooks` runs all eight in place, about 25 minutes
on a laptop; they are committed with their outputs, and the tests check that every one of them ran
top to bottom without errors or warnings. The figures in the main README are saved by the
notebooks themselves into [`reports/figures/`](../reports/figures/).
