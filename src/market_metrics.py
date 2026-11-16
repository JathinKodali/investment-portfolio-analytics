"""
market_metrics.py
-----------------
PHASE 2: basic market analytics.

WHAT: Calculates, for every stock and every day:
        - Daily_Return            (decimal, 0.025 = 2.5%)
        - Cumulative_Return       (decimal, growth since the first day)
        - Price_Change            (USD, today's Close - yesterday's Close)
        - Price_Change_Percentage (PERCENT, 2.5 = 2.5%)
      and prepares the Tableau files for the Phase 2 worksheets.
WHY:  Raw prices cannot be compared across stocks (a $300 stock vs a $100
      stock). Returns put every stock on the same scale.

Units are kept explicit to avoid mixing decimals and percentages:
  *_Return columns are DECIMALS, *_Percentage columns are PERCENTS.
"""

import pandas as pd

from src.utils import TABLEAU_ALLOCATION_FILE, TABLEAU_MARKET_FILE, save_csv

# Which price is used for returns.
# Adjusted_Close corrects for dividends and stock splits, so a dividend
# payout or a 2-for-1 split is not mistaken for a price fall. If the data has
# no adjusted price, data_loader.py copies Close into this column.
RETURN_PRICE_COLUMN = "Adjusted_Close"

TABLEAU_MARKET_COLUMNS = [
    "Date", "Ticker", "Company", "Sector",
    "Open", "High", "Low", "Close", "Adjusted_Close", "Volume",
    "Daily_Return", "Cumulative_Return", "Price_Change", "Price_Change_Percentage",
]

TABLEAU_ALLOCATION_COLUMNS = [
    "Ticker", "Company", "Sector", "Quantity", "Purchase_Price",
    "Purchase_Date", "Investment_Amount", "Data_Label",
]


# ---------------------------------------------------------------------------
# Return calculations
# ---------------------------------------------------------------------------
def add_daily_return(df, price_column=RETURN_PRICE_COLUMN):
    """
    Daily Return = (Today's price - Previous day's price) / Previous day's price

    Calculated separately for each ticker, so the first day of one stock is
    never compared with the last day of another. The first day of each stock
    has no previous price, so its Daily_Return is left blank (NaN).
    """
    df = df.sort_values(["Ticker", "Date"]).copy()
    df["Daily_Return"] = df.groupby("Ticker")[price_column].pct_change(fill_method=None)
    return df


def add_cumulative_return(df):
    """
    Cumulative Return = Product of (1 + Daily Return) - 1

    Compounding the daily returns shows how much 1 dollar invested on the
    first day would have grown. Example: 0.40 means +40% since the start.
    The first day counts as 0% growth (nothing has happened yet).
    """
    df = df.copy()
    growth_factor = 1 + df["Daily_Return"].fillna(0)
    df["Cumulative_Return"] = growth_factor.groupby(df["Ticker"]).cumprod() - 1
    return df


def add_price_change(df):
    """
    Price_Change            = Close - Previous Close           (in USD)
    Price_Change_Percentage = Price_Change / Previous Close x 100 (in %)

    These use the traded Close price (the price shown on the trend chart),
    so they are 'price-only' moves. Daily_Return also includes dividends.
    """
    df = df.sort_values(["Ticker", "Date"]).copy()
    previous_close = df.groupby("Ticker")["Close"].shift(1)
    df["Price_Change"] = df["Close"] - previous_close
    df["Price_Change_Percentage"] = df["Price_Change"] / previous_close * 100
    return df


def calculate_market_metrics(clean_market_df):
    """Run all Phase 2 calculations in the correct order."""
    df = add_daily_return(clean_market_df)
    df = add_cumulative_return(df)
    df = add_price_change(df)
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Summary for the console and for outputs/
# ---------------------------------------------------------------------------
def summarise_stock_performance(market_df):
    """
    One row per stock: start and end prices and the return over the full
    period. Used to check the numbers before building Tableau charts.
    """
    rows = []
    for ticker, stock in market_df.sort_values("Date").groupby("Ticker"):
        first, last = stock.iloc[0], stock.iloc[-1]
        rows.append({
            "Ticker": ticker,
            "Company": first["Company"],
            "Sector": first["Sector"],
            "Start_Date": first["Date"],
            "End_Date": last["Date"],
            "Trading_Days": len(stock),
            "Start_Close": first["Close"],
            "End_Close": last["Close"],
            # Price-only change over the whole period, in percent.
            "Period_Price_Change_Percentage": (last["Close"] / first["Close"] - 1) * 100,
            # Total return including dividends, as a decimal.
            "Cumulative_Return": last["Cumulative_Return"],
            "Best_Daily_Return": stock["Daily_Return"].max(),
            "Worst_Daily_Return": stock["Daily_Return"].min(),
        })
    summary = pd.DataFrame(rows).sort_values("Cumulative_Return", ascending=False)
    return summary.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Tableau-ready datasets
# ---------------------------------------------------------------------------
def build_tableau_market_data(market_df):
    """Select and round the columns used by the Tableau market worksheets."""
    df = market_df[TABLEAU_MARKET_COLUMNS].copy()
    df[["Daily_Return", "Cumulative_Return"]] = df[["Daily_Return", "Cumulative_Return"]].round(8)
    df[["Price_Change", "Price_Change_Percentage"]] = df[["Price_Change", "Price_Change_Percentage"]].round(4)
    return df.sort_values(["Ticker", "Date"]).reset_index(drop=True)


def build_tableau_allocation_data(clean_portfolio_df):
    """
    Holdings for the Portfolio Allocation chart (amount invested per company).
    Phase 3 will replace this with tableau_portfolio_holdings.csv, which adds
    current value and profit/loss.
    """
    return clean_portfolio_df[TABLEAU_ALLOCATION_COLUMNS].copy()


def validate_tableau_market_data(df):
    """
    Check the Tableau market file before saving it. Returns a list of
    problems (an empty list means the file is ready).
    """
    problems = []
    missing_columns = [c for c in TABLEAU_MARKET_COLUMNS if c not in df.columns]
    if missing_columns:
        problems.append(f"Missing columns: {missing_columns}")
    if any(str(c).startswith("Unnamed") for c in df.columns):
        problems.append("Unexpected index column")
    if df.duplicated(["Ticker", "Date"]).any():
        problems.append("Duplicate Ticker + Date rows")

    # Blanks are only expected on each stock's first day (no previous price).
    first_day = df["Date"] == df.groupby("Ticker")["Date"].transform("min")
    for col in ["Daily_Return", "Price_Change", "Price_Change_Percentage"]:
        unexpected_blanks = df.loc[~first_day, col].isna().sum()
        if unexpected_blanks:
            problems.append(f"{col} has {unexpected_blanks} unexpected blanks")
    other_columns = [c for c in TABLEAU_MARKET_COLUMNS
                     if c not in ("Daily_Return", "Price_Change", "Price_Change_Percentage")]
    if df[other_columns].isna().any().any():
        problems.append("Blank values in price / name columns")

    # The first-day cumulative return must be exactly 0.
    if (df.loc[first_day, "Cumulative_Return"].abs() > 1e-12).any():
        problems.append("Cumulative_Return does not start at 0")
    return problems


def export_tableau_files(tableau_market_df, tableau_allocation_df):
    """Write the two Phase 2 Tableau files to data/tableau/."""
    save_csv(tableau_market_df, TABLEAU_MARKET_FILE)
    save_csv(tableau_allocation_df, TABLEAU_ALLOCATION_FILE)
