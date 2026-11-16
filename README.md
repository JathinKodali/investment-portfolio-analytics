# Investment Portfolio Analytics

A Python and Tableau project for analysing stock returns, portfolio performance, risk, diversification and savings goals. The portfolio uses clearly labelled sample quantities; the market data is acquired separately.

## Four Tableau dashboards

| Dashboard | What it shows |
| --- | --- |
| Market Overview | Stock prices, return comparisons, Stock selection and date filters |
| Portfolio Performance | Holdings, profit/loss, sector exposure, concentration and an S&P 500 comparison |
| Risk & Return | Annualised return, volatility, Sharpe ratio and maximum drawdown |
| Goal Simulator | Lump-sum and monthly savings projections, target progress and required monthly contributions |

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py --download
python tableau/build_workbook.py
python -m pytest
```

Open `tableau/Investment_Portfolio_Analytics.twbx` in Tableau Desktop or Tableau Public Edition. The builder packages the generated data as Hyper extracts. Consult [the Tableau guide](docs/tableau_guide.md) for controls and dashboard details. A fresh rebuild has been checked locally; interactive verification of that rebuilt workbook is still pending.

The first pipeline run needs internet access to acquire prices using yfinance. Later runs can use `python main.py` with the saved CSVs. The source repository excludes downloaded prices, generated CSVs, workbooks and personal coursework reports. Those files are produced locally; no packaged workbook download is promised in this initial source publication.

The existing 51 Python tests use fixtures and do not need live market downloads. They were last run successfully on 17 November 2026.

## Data and assumptions

- Market universe: AAPL, CAT, JNJ, JPM, PG and XOM, plus the S&P 500 benchmark.
- Configured period: 1 January 2025 through 30 September 2026. Settings are in `src/utils.py`.
- Prices are acquired from Yahoo Finance using yfinance; acquisition writes a source manifest. Refreshed data may differ from earlier project results.
- Portfolio quantities are sample/demo inputs. Purchase prices use each stock's first available close.
- Stock-market and portfolio values are in USD. The separate savings simulator uses INR without currency conversion.
- Daily stock returns use adjusted close; holdings profit/loss is price-only.
- Risk groups are relative to this small stock universe. The savings model assumes a constant return.

See [the savings model](docs/goal_simulator_concept.md) for formulas and edge cases.

## Source layout

```text
src/          data loading, cleaning, market/portfolio/risk metrics and goal maths
tests/        fixture-based Python tests
tableau/      workbook builder and workbook utility
notebooks/    exploratory analysis
docs/         Tableau and goal simulator guides
main.py       pipeline entry point
```

This is an educational analytics project. Historical performance and constant-return projections do not establish future outcomes.
