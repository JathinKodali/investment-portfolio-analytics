"""
data_cleaning.py
----------------
PHASE 1: clean and validate the raw data.

WHAT: Fixes data types, removes duplicates and impossible values, checks
      that every ticker has one company and one sector, and writes a short
      data-quality summary.
WHY:  Return and portfolio calculations are only as good as the data behind
      them. One duplicated day or a negative price would distort every
      return calculated after it.

Rule followed throughout: we never invent prices. Rows that cannot be
trusted are removed and counted in the quality report instead.
"""

from datetime import datetime

import pandas as pd

from src.data_loader import MARKET_COLUMNS
from src.utils import (
    CURRENCY,
    DATA_QUALITY_REPORT_FILE,
    STOCK_INFO,
    format_date_range,
)

PRICE_COLUMNS = ["Open", "High", "Low", "Close", "Adjusted_Close"]
TEXT_COLUMNS = ["Ticker", "Company", "Sector"]

PORTFOLIO_REQUIRED_COLUMNS = ["Ticker", "Quantity", "Purchase_Price", "Purchase_Date"]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def check_required_columns(df, required, dataset_name):
    """Stop early with a clear message if an expected column is missing."""
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"{dataset_name} is missing required columns: {missing}")


def tidy_text_columns(df, columns):
    """Remove stray spaces and make tickers upper-case (' aapl' -> 'AAPL')."""
    for col in columns:
        if col in df.columns:
            df[col] = df[col].astype("string").str.strip()
            df[col] = df[col].replace("", pd.NA)
    if "Ticker" in df.columns:
        df["Ticker"] = df["Ticker"].str.upper()
    return df


def most_common_value(values):
    """Return the most frequent non-empty value (used to fix naming conflicts)."""
    values = values.dropna()
    return values.mode().iloc[0] if not values.empty else pd.NA


# ---------------------------------------------------------------------------
# Market data cleaning
# ---------------------------------------------------------------------------
def clean_market_data(raw_df):
    """
    Clean the daily market data.

    Returns
    -------
    clean_df : DataFrame  -> cleaned data, sorted by Ticker and Date
    report   : dict       -> what was found and fixed (for the quality summary)
    """
    df = raw_df.copy()
    report = {"rows_before": len(df)}

    # Adjusted_Close is optional in the brief: fall back to Close if absent.
    if "Adjusted_Close" not in df.columns and "Close" in df.columns:
        df["Adjusted_Close"] = df["Close"]
    check_required_columns(df, MARKET_COLUMNS, "Market data")

    # Step 1 - Tidy text so 'aapl ' and 'AAPL' count as the same ticker.
    df = tidy_text_columns(df, TEXT_COLUMNS)

    # Step 2 - Convert Date to a real date. Unreadable dates become NaT
    # and are removed, because a price without a date cannot be analysed.
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    report["invalid_dates_removed"] = int(df["Date"].isna().sum())
    df = df.dropna(subset=["Date"])

    # Step 3 - Make sure number columns really contain numbers.
    # Text such as "n/a" becomes NaN so it can be handled in Step 5.
    for col in PRICE_COLUMNS + ["Volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Step 4 - Remove duplicates.
    # (a) identical rows, (b) the same ticker on the same date twice.
    before = len(df)
    df = df.drop_duplicates()
    report["exact_duplicates_removed"] = before - len(df)

    before = len(df)
    df = df.sort_values(["Ticker", "Date"])
    df = df.drop_duplicates(subset=["Ticker", "Date"], keep="last")
    report["ticker_date_duplicates_removed"] = before - len(df)

    # Step 5 - Handle missing values.
    # Adjusted_Close can safely fall back to Close (the brief allows this).
    missing_adjusted = df["Adjusted_Close"].isna() & df["Close"].notna()
    report["adjusted_close_filled_from_close"] = int(missing_adjusted.sum())
    df.loc[missing_adjusted, "Adjusted_Close"] = df.loc[missing_adjusted, "Close"]

    # Missing Open/High/Low/Close cannot be filled without inventing prices,
    # so those rows are removed.
    before = len(df)
    df = df.dropna(subset=PRICE_COLUMNS)
    report["rows_missing_prices_removed"] = before - len(df)
    report["missing_volume_values"] = int(df["Volume"].isna().sum())

    # Step 6 - Remove impossible values.
    # A share price cannot be zero or negative, and volume cannot be negative.
    before = len(df)
    df = df[(df[PRICE_COLUMNS] > 0).all(axis=1)]
    report["non_positive_prices_removed"] = before - len(df)

    before = len(df)
    df = df[~(df["Volume"] < 0)]
    report["negative_volume_removed"] = before - len(df)

    # The day's High can never be below the day's Low.
    before = len(df)
    df = df[df["High"] >= df["Low"]]
    report["high_below_low_removed"] = before - len(df)

    # Open/Close slightly outside High/Low can happen in vendor data, so we
    # only count these as warnings instead of deleting real trading days.
    outside_range = (
        (df[["Open", "Close"]].max(axis=1) > df["High"] + 0.01)
        | (df[["Open", "Close"]].min(axis=1) < df["Low"] - 0.01)
    )
    report["ohlc_range_warnings"] = int(outside_range.sum())

    # Step 7 - Ticker consistency: each ticker must map to ONE company and
    # ONE sector. Fill gaps from the reference list in utils.py first.
    df["Company"] = df["Company"].fillna(
        df["Ticker"].map(lambda t: STOCK_INFO.get(t, {}).get("Company")))
    df["Sector"] = df["Sector"].fillna(
        df["Ticker"].map(lambda t: STOCK_INFO.get(t, {}).get("Sector")))

    conflicts = []
    for col in ["Company", "Sector"]:
        names_per_ticker = df.groupby("Ticker")[col].nunique()
        for ticker in names_per_ticker[names_per_ticker > 1].index:
            conflicts.append(f"{ticker} had several {col} values")
            fixed_value = most_common_value(df.loc[df["Ticker"] == ticker, col])
            df.loc[df["Ticker"] == ticker, col] = fixed_value
    report["ticker_conflicts_fixed"] = conflicts

    report["unknown_tickers"] = sorted(set(df["Ticker"]) - set(STOCK_INFO))
    report["missing_sectors"] = sorted(df.loc[df["Sector"].isna(), "Ticker"].unique())
    df["Sector"] = df["Sector"].fillna("Unknown")
    df["Company"] = df["Company"].fillna(df["Ticker"])

    # Step 8 - Remove floating-point noise from the download
    # (e.g. 243.8500061035156 -> 243.85).
    df[PRICE_COLUMNS] = df[PRICE_COLUMNS].round(4)
    df["Volume"] = df["Volume"].astype("Int64")

    # Step 9 - Check that every stock has a price on every trading day.
    all_dates = df["Date"].nunique()
    days_per_stock = df.groupby("Ticker")["Date"].nunique()
    report["stocks_with_missing_days"] = {
        ticker: int(all_dates - days)
        for ticker, days in days_per_stock.items() if days < all_dates
    }

    # Final tidy: consistent column order, sorted by Ticker then Date.
    df = df[MARKET_COLUMNS].sort_values(["Ticker", "Date"]).reset_index(drop=True)
    for col in TEXT_COLUMNS:
        df[col] = df[col].astype(str)

    report["rows_after"] = len(df)
    report["missing_values_after"] = int(df[MARKET_COLUMNS].isna().sum().sum())
    return df, report


# ---------------------------------------------------------------------------
# Portfolio data cleaning
# ---------------------------------------------------------------------------
def clean_portfolio_data(raw_df, clean_market_df):
    """
    Clean the portfolio holdings and recalculate Investment_Amount.

    Company and Sector are taken from the cleaned market data so both
    datasets always use exactly the same names (needed to link them in
    Tableau and in Phase 3).
    """
    df = raw_df.copy()
    report = {"rows_before": len(df)}
    check_required_columns(df, PORTFOLIO_REQUIRED_COLUMNS, "Portfolio data")

    for col in ["Company", "Sector", "Data_Label"]:
        if col not in df.columns:
            df[col] = pd.NA
    df = tidy_text_columns(df, TEXT_COLUMNS + ["Data_Label"])

    df["Purchase_Date"] = pd.to_datetime(df["Purchase_Date"], errors="coerce")
    for col in ["Quantity", "Purchase_Price", "Investment_Amount"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    before = len(df)
    df = df.drop_duplicates()
    report["duplicates_removed"] = before - len(df)

    # A holding needs a positive quantity, a positive price and a date.
    valid = (df["Quantity"] > 0) & (df["Purchase_Price"] > 0) & df["Purchase_Date"].notna()
    report["invalid_rows_removed"] = int((~valid).sum())
    df = df[valid].copy()

    # Investment_Amount = Quantity x Purchase_Price (always recalculated so
    # it can never disagree with the quantity and price columns).
    new_amount = df["Quantity"] * df["Purchase_Price"]
    if "Investment_Amount" in df.columns:
        mismatch = (df["Investment_Amount"] - new_amount).abs() > 0.01
        report["investment_amount_corrected"] = int(mismatch.sum())
    else:
        report["investment_amount_corrected"] = 0
    df["Investment_Amount"] = new_amount

    # Use the market data's Company and Sector names for every ticker.
    names = clean_market_df.drop_duplicates("Ticker").set_index("Ticker")
    df["Company"] = df["Ticker"].map(names["Company"]).fillna(df["Company"])
    df["Sector"] = df["Ticker"].map(names["Sector"]).fillna(df["Sector"])

    # Holdings with no market prices cannot be valued later (Phase 3).
    report["tickers_without_market_data"] = sorted(set(df["Ticker"]) - set(names.index))
    report["missing_sectors"] = sorted(df.loc[df["Sector"].isna(), "Ticker"].unique())
    df["Sector"] = df["Sector"].fillna("Unknown")
    df["Company"] = df["Company"].fillna(df["Ticker"])

    # A portfolio file supplied without a label is treated as user data.
    df["Data_Label"] = df["Data_Label"].fillna("USER PROVIDED DATA")

    df["Purchase_Price"] = df["Purchase_Price"].round(4)
    df["Investment_Amount"] = df["Investment_Amount"].round(2)
    df["Quantity"] = df["Quantity"].astype(int)

    columns = ["Ticker", "Company", "Sector", "Quantity", "Purchase_Price",
               "Investment_Amount", "Purchase_Date", "Data_Label"]
    df = df[columns].sort_values("Ticker").reset_index(drop=True)
    for col in TEXT_COLUMNS + ["Data_Label"]:
        df[col] = df[col].astype(str)

    report["rows_after"] = len(df)
    report["missing_values_after"] = int(df.isna().sum().sum())
    return df, report


# ---------------------------------------------------------------------------
# Phase 1 validation output
# ---------------------------------------------------------------------------
def print_dataset_overview(df, dataset_name, date_column="Date"):
    """Print shape, columns, missing values, stocks, date range and sectors."""
    print(f"\n--- {dataset_name} ---")
    print(f"Dataset shape     : {df.shape[0]:,} rows x {df.shape[1]} columns")
    print(f"Column names      : {', '.join(df.columns)}")

    missing = df.isna().sum()
    missing = missing[missing > 0]
    print(f"Missing values    : {'none' if missing.empty else missing.to_dict()}")

    print(f"Number of stocks  : {df['Ticker'].nunique()} ({', '.join(sorted(df['Ticker'].unique()))})")
    if date_column in df.columns:
        print(f"Date range        : {format_date_range(df[date_column])}")
    print(f"Sectors           : {', '.join(sorted(df['Sector'].unique()))}")


def build_quality_report(market_report, portfolio_report, market_df, portfolio_df):
    """
    Turn the cleaning reports into a short, readable data-quality summary.
    Returns the text so it can be printed and saved.
    """
    warnings = []
    if market_report["stocks_with_missing_days"]:
        warnings.append(f"Some stocks miss trading days: {market_report['stocks_with_missing_days']}")
    if market_report["ohlc_range_warnings"]:
        warnings.append(f"{market_report['ohlc_range_warnings']} rows have Open/Close outside High-Low")
    if market_report["missing_volume_values"]:
        warnings.append(f"{market_report['missing_volume_values']} rows have no Volume")
    if market_report["unknown_tickers"]:
        warnings.append(f"Tickers not in the reference list: {market_report['unknown_tickers']}")
    if portfolio_report["tickers_without_market_data"]:
        warnings.append(f"Holdings without market prices: {portfolio_report['tickers_without_market_data']}")
    for label, report in [("Market", market_report), ("Portfolio", portfolio_report)]:
        if report["missing_sectors"]:
            warnings.append(f"{label}: missing sectors for {report['missing_sectors']}")

    days_per_stock = market_df.groupby("Ticker")["Date"].nunique()
    labels = ", ".join(sorted(portfolio_df["Data_Label"].unique()))

    lines = [
        "DATA QUALITY SUMMARY - PHASE 1",
        f"Generated: {datetime.now():%Y-%m-%d %H:%M}",
        "",
        "MARKET DATA (data/raw/market_data_raw.csv -> data/processed/clean_market_data.csv)",
        "  Source                         : Yahoo Finance daily prices (real market data)",
        f"  Currency                       : {CURRENCY}",
        f"  Rows before / after cleaning   : {market_report['rows_before']:,} / {market_report['rows_after']:,}",
        f"  Stocks                         : {market_df['Ticker'].nunique()} ({', '.join(sorted(market_df['Ticker'].unique()))})",
        f"  Sectors                        : {market_df['Sector'].nunique()} ({', '.join(sorted(market_df['Sector'].unique()))})",
        f"  Date range                     : {format_date_range(market_df['Date'])}",
        f"  Trading days per stock         : {days_per_stock.min()} to {days_per_stock.max()}",
        f"  Invalid dates removed          : {market_report['invalid_dates_removed']}",
        f"  Exact duplicate rows removed   : {market_report['exact_duplicates_removed']}",
        f"  Duplicate Ticker+Date removed  : {market_report['ticker_date_duplicates_removed']}",
        f"  Rows with missing prices removed: {market_report['rows_missing_prices_removed']}",
        f"  Adjusted_Close filled from Close: {market_report['adjusted_close_filled_from_close']}",
        f"  Zero/negative prices removed   : {market_report['non_positive_prices_removed']}",
        f"  Negative volume removed        : {market_report['negative_volume_removed']}",
        f"  High below Low removed         : {market_report['high_below_low_removed']}",
        f"  Ticker name conflicts fixed    : {len(market_report['ticker_conflicts_fixed'])}",
        f"  Missing values after cleaning  : {market_report['missing_values_after']}",
        "",
        "PORTFOLIO DATA (data/raw/sample_portfolio.csv -> data/processed/clean_portfolio_data.csv)",
        f"  Data label                     : {labels}",
        f"  Holdings before / after        : {portfolio_report['rows_before']} / {portfolio_report['rows_after']}",
        f"  Duplicates removed             : {portfolio_report['duplicates_removed']}",
        f"  Invalid rows removed           : {portfolio_report['invalid_rows_removed']}",
        f"  Investment_Amount corrected    : {portfolio_report['investment_amount_corrected']}",
        f"  Total amount invested          : {portfolio_df['Investment_Amount'].sum():,.2f} {CURRENCY}",
        f"  Missing values after cleaning  : {portfolio_report['missing_values_after']}",
        "",
        "RESULT: " + ("PASSED - no warnings" if not warnings
                      else f"PASSED WITH {len(warnings)} WARNING(S)"),
    ]
    lines += [f"  - {warning}" for warning in warnings]
    return "\n".join(lines)


def save_quality_report(report_text, path=DATA_QUALITY_REPORT_FILE):
    """Save the data-quality summary as a text file in outputs/."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report_text + "\n", encoding="utf-8")
