"""
portfolio_metrics.py
--------------------
PHASE 3: portfolio performance engine.
PHASE 5: sector exposure and concentration.

WHAT: 1. Values each holding at the latest closing price.
      2. Calculates profit / loss, return % and portfolio weights.
      3. Builds the portfolio KPIs (total invested, current value, total P/L,
         best and worst holding).
      4. Groups the holdings by sector and measures concentration with the
         Herfindahl-Hirschman Index (HHI).
WHY:  Phase 2 only showed how much money went in. These numbers show what
      the SAMPLE / DEMO portfolio is worth now and how spread out it is.

Units: Return_Percentage, weights and HHI are DECIMALS (0.25 = 25%), like
the Phase 2 return columns, so Tableau can format them as percentages.
"""

import pandas as pd

from src.utils import SAMPLE_DATA_LABEL

HOLDINGS_COLUMNS = [
    "Ticker", "Company", "Sector", "Quantity", "Purchase_Date", "Purchase_Price",
    "Investment_Amount", "Latest_Date", "Latest_Close", "Current_Value",
    "Profit_Loss", "Return_Percentage", "Investment_Weight", "Portfolio_Weight", "Data_Label",
]

# HHI thresholds (decimal scale). These follow the common competition-policy
# bands of 1,500 and 2,500 on the 0-10,000 scale.
HHI_DIVERSIFIED_BELOW = 0.15
HHI_CONCENTRATED_ABOVE = 0.25


# ---------------------------------------------------------------------------
# Phase 3: value each holding
# ---------------------------------------------------------------------------
def latest_prices(market_df):
    """The last available Close for every ticker, with its date."""
    last = market_df.sort_values("Date").groupby("Ticker").tail(1)
    return last[["Ticker", "Date", "Close"]].rename(
        columns={"Date": "Latest_Date", "Close": "Latest_Close"})


def calculate_holdings(portfolio_df, market_df):
    """
    One row per holding:
        Current_Value     = Quantity x Latest_Close
        Profit_Loss       = Current_Value - Investment_Amount
        Return_Percentage = Profit_Loss / Investment_Amount        (decimal)
        Investment_Weight = Investment_Amount / total invested      (decimal)
        Portfolio_Weight  = Current_Value / total current value     (decimal)

    Uses the traded Close (what the shares would sell for today). Dividends
    received are not added, so this is the price-only P/L of the holdings.
    """
    prices = latest_prices(market_df)
    df = portfolio_df.merge(prices, on="Ticker", how="left", validate="one_to_one")
    missing = df.loc[df["Latest_Close"].isna(), "Ticker"].tolist()
    if missing:
        raise ValueError(f"No market price found for holdings: {missing}")

    df["Current_Value"] = df["Quantity"] * df["Latest_Close"]
    df["Profit_Loss"] = df["Current_Value"] - df["Investment_Amount"]
    df["Return_Percentage"] = df["Profit_Loss"] / df["Investment_Amount"]
    df["Investment_Weight"] = df["Investment_Amount"] / df["Investment_Amount"].sum()
    df["Portfolio_Weight"] = df["Current_Value"] / df["Current_Value"].sum()
    if "Data_Label" not in df.columns:
        df["Data_Label"] = SAMPLE_DATA_LABEL

    df = df[HOLDINGS_COLUMNS].sort_values("Current_Value", ascending=False)
    return df.reset_index(drop=True)


def portfolio_value_history(portfolio_df, market_df):
    """
    Daily value of the portfolio: sum of Quantity x Close on each trading day
    from the purchase date onward. Used for the benchmark comparison.
    """
    quantities = portfolio_df.set_index("Ticker")["Quantity"]
    start = pd.to_datetime(portfolio_df["Purchase_Date"]).max()
    prices = market_df[pd.to_datetime(market_df["Date"]) >= start]
    wide = prices.pivot(index="Date", columns="Ticker", values="Close")[quantities.index]
    if wide.isna().any().any():
        raise ValueError("A holding is missing a price on some trading days.")
    value = (wide * quantities).sum(axis=1)
    return value.rename("Portfolio_Value").reset_index()


# ---------------------------------------------------------------------------
# Phase 5: sector exposure and concentration
# ---------------------------------------------------------------------------
def herfindahl_index(weights):
    """HHI = sum of squared weights. 1/N for equal weights, 1.0 for one holding."""
    weights = pd.Series(weights, dtype=float)
    total = weights.sum()
    if total <= 0:
        raise ValueError("Weights must add up to more than zero.")
    weights = weights / total
    return float((weights ** 2).sum())


def concentration_label(hhi):
    if hhi < HHI_DIVERSIFIED_BELOW:
        return "Diversified"
    if hhi <= HHI_CONCENTRATED_ABOVE:
        return "Moderately concentrated"
    return "Concentrated"


def calculate_sector_exposure(holdings_df):
    """One row per sector: amount invested, current value, P/L and weight."""
    sectors = holdings_df.groupby("Sector", as_index=False).agg(
        Holdings=("Ticker", "count"),
        Investment_Amount=("Investment_Amount", "sum"),
        Current_Value=("Current_Value", "sum"),
        Profit_Loss=("Profit_Loss", "sum"),
    )
    sectors["Return_Percentage"] = sectors["Profit_Loss"] / sectors["Investment_Amount"]
    sectors["Sector_Weight"] = sectors["Current_Value"] / sectors["Current_Value"].sum()
    return sectors.sort_values("Sector_Weight", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Portfolio KPIs
# ---------------------------------------------------------------------------
def calculate_portfolio_summary(holdings_df, sector_df):
    """One-row table of portfolio KPIs (used for the dashboard KPI tiles)."""
    invested = holdings_df["Investment_Amount"].sum()
    current = holdings_df["Current_Value"].sum()
    best = holdings_df.loc[holdings_df["Return_Percentage"].idxmax()]
    worst = holdings_df.loc[holdings_df["Return_Percentage"].idxmin()]
    largest = holdings_df.loc[holdings_df["Portfolio_Weight"].idxmax()]
    hhi = herfindahl_index(holdings_df["Current_Value"])
    sector_hhi = herfindahl_index(sector_df["Current_Value"])
    return pd.DataFrame([{
        "Valuation_Date": holdings_df["Latest_Date"].max(),
        "Total_Investment": invested,
        "Current_Value": current,
        "Total_Profit_Loss": current - invested,
        "Portfolio_Return": current / invested - 1,
        "Number_Of_Holdings": len(holdings_df),
        "Number_Of_Sectors": holdings_df["Sector"].nunique(),
        "Best_Asset": best["Company"],
        "Best_Asset_Ticker": best["Ticker"],
        "Best_Asset_Return": best["Return_Percentage"],
        "Worst_Asset": worst["Company"],
        "Worst_Asset_Ticker": worst["Ticker"],
        "Worst_Asset_Return": worst["Return_Percentage"],
        "Largest_Holding": largest["Company"],
        "Largest_Holding_Weight": largest["Portfolio_Weight"],
        "HHI_Holdings": hhi,
        "Effective_Holdings": 1 / hhi,
        "HHI_Sectors": sector_hhi,
        "Concentration_Level": concentration_label(hhi),
        "Data_Label": SAMPLE_DATA_LABEL,
    }])
