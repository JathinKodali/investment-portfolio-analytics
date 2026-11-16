"""
data_loader.py
--------------
PHASE 1: collect and load the raw data.

WHAT: 1. Downloads daily stock prices from Yahoo Finance (optional).
      2. Loads the saved raw market data CSV.
      3. Loads the portfolio file, or creates a clearly labelled SAMPLE
         portfolio when no portfolio file exists.
WHY:  Every later calculation needs a reliable copy of the raw data saved
      on disk, so the analysis can be re-run without downloading again.
"""

import json
from datetime import datetime, timezone

import pandas as pd

from src.utils import (
    END_DATE,
    RAW_MARKET_FILE,
    RAW_PORTFOLIO_FILE,
    SAMPLE_DATA_LABEL,
    SAMPLE_QUANTITIES,
    START_DATE,
    STOCK_INFO,
    save_csv,
)

MANIFEST_FILE = RAW_MARKET_FILE.parent / "source_manifest.json"

# Column order used for the raw market dataset.
MARKET_COLUMNS = [
    "Date", "Ticker", "Company", "Sector",
    "Open", "High", "Low", "Close", "Adjusted_Close", "Volume",
]

PORTFOLIO_COLUMNS = [
    "Ticker", "Company", "Sector", "Quantity", "Purchase_Price",
    "Investment_Amount", "Purchase_Date", "Data_Label",
]


# ---------------------------------------------------------------------------
# 1. Download market data (only needed when refreshing the raw data)
# ---------------------------------------------------------------------------
def download_market_data(tickers=None, start=START_DATE, end=END_DATE):
    """
    Download daily prices for each ticker from Yahoo Finance.

    Needs the optional 'yfinance' package (pip install yfinance).
    The source repository excludes downloaded data. Run this for the initial
    acquisition or to refresh the locally saved prices.
    """
    # Imported here so the rest of the project works without yfinance.
    try:
        import yfinance as yf
    except ImportError as error:
        raise ImportError(
            "Downloading needs the 'yfinance' package. Install it with:\n"
            "    pip install yfinance\n"
            "or use a previously acquired CSV in data/raw/."
        ) from error

    tickers = tickers or list(STOCK_INFO)

    # yfinance treats the end date as EXCLUSIVE, so add one day to include it.
    end_exclusive = (pd.Timestamp(end) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

    # auto_adjust=False keeps both the traded Close and the Adjusted Close.
    wide = yf.download(
        tickers, start=start, end=end_exclusive, auto_adjust=False,
        group_by="ticker", progress=False, threads=False,
    )
    if wide.empty:
        raise RuntimeError("No data was downloaded. Check the tickers and dates.")

    # The download is "wide" (one block of columns per ticker).
    # Convert it to a "long" table: one row per ticker per day.
    frames = []
    for ticker in tickers:
        one_stock = wide[ticker].dropna(how="all").reset_index()
        one_stock["Ticker"] = ticker
        frames.append(one_stock)
    long = pd.concat(frames, ignore_index=True)

    long = long.rename(columns={"Adj Close": "Adjusted_Close"})
    long["Company"] = long["Ticker"].map(lambda t: STOCK_INFO[t]["Company"])
    long["Sector"] = long["Ticker"].map(lambda t: STOCK_INFO[t]["Sector"])

    # If the source has no adjusted price, fall back to Close.
    if "Adjusted_Close" not in long.columns:
        long["Adjusted_Close"] = long["Close"]

    return long[MARKET_COLUMNS]


def save_raw_market_data(market_df):
    """
    Save downloaded prices to data/raw/ so we never need to re-download,
    plus a small 'manifest' recording where and when the data came from.
    """
    save_csv(market_df, RAW_MARKET_FILE)

    manifest = {
        "market_data": "REAL daily stock prices downloaded from Yahoo Finance (yfinance)",
        "portfolio_data": f"{SAMPLE_DATA_LABEL}: demo quantities, purchase prices taken from real closes",
        "retrieved_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "currency": "USD",
        "requested_period": {"start": START_DATE, "end": END_DATE},
        "rows_per_ticker": market_df.groupby("Ticker").size().to_dict(),
    }
    MANIFEST_FILE.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"  Saved: data/raw/{MANIFEST_FILE.name}")


# ---------------------------------------------------------------------------
# 2. Load the raw market data
# ---------------------------------------------------------------------------
def load_market_data(path=RAW_MARKET_FILE):
    """
    Read the raw market data CSV.

    If the file has no Adjusted_Close column, Close is used instead
    (as required by the project brief), and a note is printed.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"Raw market data not found at {path}.\n"
            "Run:  python main.py --download   to download it."
        )

    market_df = pd.read_csv(path)

    if "Adjusted_Close" not in market_df.columns:
        print("  Note: Adjusted_Close not found, so Close is used in its place.")
        market_df["Adjusted_Close"] = market_df["Close"]

    return market_df


# ---------------------------------------------------------------------------
# 3. Load or create the portfolio
# ---------------------------------------------------------------------------
def create_sample_portfolio(market_df, quantities=None):
    """
    Build a SAMPLE / DEMO portfolio from real market prices.

    Assumption: each stock is bought on its first trading day in the dataset.
    - Quantity        -> taken from SAMPLE_QUANTITIES (demo values)
    - Purchase_Price  -> the REAL closing price on that purchase date
    - Investment_Amount = Quantity x Purchase_Price
    """
    quantities = quantities or SAMPLE_QUANTITIES

    prices = market_df.copy()
    prices["Date"] = pd.to_datetime(prices["Date"])
    prices = prices.sort_values(["Ticker", "Date"])

    rows = []
    for ticker, quantity in quantities.items():
        stock_prices = prices[prices["Ticker"] == ticker]
        if stock_prices.empty:
            print(f"  Warning: {ticker} has no market data, so it is skipped.")
            continue

        first_day = stock_prices.iloc[0]  # first trading day available
        purchase_price = float(first_day["Close"])
        rows.append({
            "Ticker": ticker,
            "Company": first_day["Company"],
            "Sector": first_day["Sector"],
            "Quantity": quantity,
            "Purchase_Price": purchase_price,
            "Investment_Amount": quantity * purchase_price,
            "Purchase_Date": first_day["Date"],
            "Data_Label": SAMPLE_DATA_LABEL,
        })

    return pd.DataFrame(rows, columns=PORTFOLIO_COLUMNS)


def load_portfolio_data(market_df, path=RAW_PORTFOLIO_FILE):
    """
    Load the portfolio file. If it does not exist yet, create the sample
    portfolio, save it to data/raw/, and return it.
    """
    if path.exists():
        return pd.read_csv(path)

    print("  No portfolio file found, so a SAMPLE / DEMO portfolio is created.")
    portfolio_df = create_sample_portfolio(market_df)
    save_csv(portfolio_df, path)
    return portfolio_df
