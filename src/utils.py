"""
utils.py
--------
Shared settings and small helper functions used by every phase.

WHAT: File paths, the list of stocks we analyse, the sample-portfolio
      quantities, and helpers for printing and saving CSV files.
WHY:  Keeping these in one place means a change (for example, adding a new
      stock) only has to be made once.
"""

from pathlib import Path

import pandas as pd


# ---------------------------------------------------------------------------
# Folder and file paths
# ---------------------------------------------------------------------------
# PROJECT_ROOT is the "investment-portfolio-analytics" folder. Building every
# path from it means the code works no matter where it is run from.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"              # data exactly as collected
PROCESSED_DIR = DATA_DIR / "processed"  # cleaned data
TABLEAU_DIR = DATA_DIR / "tableau"      # final files that Tableau reads
OUTPUTS_DIR = PROJECT_ROOT / "outputs"  # reports and summaries

# Raw input files
RAW_MARKET_FILE = RAW_DIR / "market_data_raw.csv"
RAW_PORTFOLIO_FILE = RAW_DIR / "sample_portfolio.csv"

# Phase 1 outputs
CLEAN_MARKET_FILE = PROCESSED_DIR / "clean_market_data.csv"
CLEAN_PORTFOLIO_FILE = PROCESSED_DIR / "clean_portfolio_data.csv"
DATA_QUALITY_REPORT_FILE = OUTPUTS_DIR / "data_quality_report.txt"

# Phase 2 outputs
TABLEAU_MARKET_FILE = TABLEAU_DIR / "tableau_market_data.csv"
TABLEAU_ALLOCATION_FILE = TABLEAU_DIR / "tableau_portfolio_allocation.csv"
STOCK_PERFORMANCE_FILE = OUTPUTS_DIR / "phase2_stock_performance_summary.csv"


# ---------------------------------------------------------------------------
# Market data settings
# ---------------------------------------------------------------------------
# The stocks we track. Company names and sectors are stored here because the
# price download only gives us prices, not company details.
# One stock per sector keeps the sample diversified across the economy.
STOCK_INFO = {
    "AAPL": {"Company": "Apple Inc.", "Sector": "Technology"},
    "CAT": {"Company": "Caterpillar Inc.", "Sector": "Industrials"},
    "JNJ": {"Company": "Johnson & Johnson", "Sector": "Healthcare"},
    "JPM": {"Company": "JPMorgan Chase & Co.", "Sector": "Financials"},
    "PG": {"Company": "The Procter & Gamble Company", "Sector": "Consumer Staples"},
    "XOM": {"Company": "Exxon Mobil Corporation", "Sector": "Energy"},
}

# Period of market data to collect (both dates inclusive).
START_DATE = "2025-01-01"
END_DATE = "2026-09-30"

# All prices in this dataset are US stock prices.
CURRENCY = "USD"


# ---------------------------------------------------------------------------
# Sample portfolio settings  (SAMPLE / DEMO DATA)
# ---------------------------------------------------------------------------
# We do not have a real investor's holdings, so we create a clearly labelled
# demo portfolio. Only the QUANTITIES are made up. Purchase prices are taken
# from the real closing price on the purchase date, so no prices are invented.
SAMPLE_DATA_LABEL = "SAMPLE / DEMO DATA"
SAMPLE_QUANTITIES = {
    "AAPL": 18,
    "CAT": 8,
    "JNJ": 15,
    "JPM": 14,
    "PG": 13,
    "XOM": 22,
}


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------
def print_header(title):
    """Print a clear section header so the console output is easy to follow."""
    line = "=" * 70
    print(f"\n{line}\n{title}\n{line}")


def save_csv(df, path):
    """
    Save a DataFrame as a Tableau-friendly CSV file.

    - index=False: no extra unnamed index column in Tableau.
    - date_format: every date is written the same way (YYYY-MM-DD).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, date_format="%Y-%m-%d")
    print(f"  Saved: {path.relative_to(PROJECT_ROOT)}  ({len(df):,} rows)")


def format_date_range(dates):
    """Return a readable date range such as '02 Jan 2025 to 30 Sep 2026'."""
    dates = pd.to_datetime(dates)
    return f"{dates.min():%d %b %Y} to {dates.max():%d %b %Y}"


# ---------------------------------------------------------------------------
# Phase 3-6 settings and outputs
# ---------------------------------------------------------------------------
# Benchmark used in Phase 6: the S&P 500 index (Yahoo Finance symbol ^GSPC).
BENCHMARK_TICKER = "^GSPC"
BENCHMARK_NAME = "S&P 500"
RAW_BENCHMARK_FILE = RAW_DIR / "benchmark_raw.csv"

# Trading days in a year, used to annualise daily returns and volatility.
TRADING_DAYS_PER_YEAR = 252

# Annual risk-free rate used in the Sharpe ratio (approximate yield on
# 3-month US Treasury bills during 2025-2026). An assumption, not data.
RISK_FREE_RATE = 0.04

TABLEAU_HOLDINGS_FILE = TABLEAU_DIR / "tableau_portfolio_holdings.csv"
TABLEAU_SUMMARY_FILE = TABLEAU_DIR / "tableau_portfolio_summary.csv"
TABLEAU_SECTOR_FILE = TABLEAU_DIR / "tableau_sector_exposure.csv"
TABLEAU_RISK_FILE = TABLEAU_DIR / "tableau_risk_return.csv"
TABLEAU_BENCHMARK_FILE = TABLEAU_DIR / "tableau_benchmark_comparison.csv"
TABLEAU_GOAL_PROJECTION_FILE = TABLEAU_DIR / "tableau_goal_projection.csv"
TABLEAU_GOAL_SCAFFOLD_FILE = TABLEAU_DIR / "tableau_goal_scaffold.csv"
FINAL_SUMMARY_FILE = OUTPUTS_DIR / "final_project_summary.txt"

# Default Goal Simulator inputs (Phases 7-12), in Indian rupees.
GOAL_DEFAULTS = {
    "initial_investment": 200_000,
    "monthly_investment": 5_000,
    "target_amount": 1_000_000,
    "annual_return_pct": 12.0,
    "years": 5,
}
# Longest period the Tableau simulator can show (rows in the scaffold).
GOAL_MAX_YEARS = 40
