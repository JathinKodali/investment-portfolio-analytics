"""
risk_metrics.py
---------------
PHASE 4: risk and volatility analysis.
PHASE 6: benchmark comparison against the S&P 500.
PHASE 13 (optional metrics): Sharpe ratio and maximum drawdown.

WHAT: For each stock (and the S&P 500 for reference):
        Annualized_Return     = average Daily_Return x 252
        Annualized_Volatility = standard deviation of Daily_Return x sqrt(252)
        Sharpe_Ratio          = (Annualized_Return - risk-free rate) / Annualized_Volatility
        Max_Drawdown          = largest fall from a previous peak (negative decimal)
      Stocks are put into Low / Medium / High risk groups by volatility
      terciles (data-driven thresholds, so 2 stocks per group here).
      The portfolio and the S&P 500 are both indexed to 100 on the purchase
      date so their growth can be compared on one chart.
WHY:  Return alone does not show how bumpy the ride was. Volatility and
      drawdown show the risk taken to earn that return.
"""

import numpy as np
import pandas as pd

from src.utils import (
    BENCHMARK_NAME,
    BENCHMARK_TICKER,
    RAW_BENCHMARK_FILE,
    RISK_FREE_RATE,
    TRADING_DAYS_PER_YEAR,
    save_csv,
)

RISK_GROUPS = ["Low", "Medium", "High"]
BENCHMARK_GROUP = "Benchmark"
PORTFOLIO_SERIES = "Sample Portfolio"


# ---------------------------------------------------------------------------
# Benchmark data (Phase 6)
# ---------------------------------------------------------------------------
def download_benchmark_data(start, end):
    """Download daily S&P 500 prices from Yahoo Finance (needs yfinance)."""
    import yfinance as yf

    end_exclusive = (pd.Timestamp(end) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    raw = yf.download(BENCHMARK_TICKER, start=start, end=end_exclusive,
                      auto_adjust=False, progress=False)
    if raw.empty:
        raise RuntimeError("No benchmark data was downloaded.")
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [c[0] for c in raw.columns]
    raw = raw.reset_index()
    df = pd.DataFrame({
        "Date": pd.to_datetime(raw["Date"]).dt.strftime("%Y-%m-%d"),
        "Ticker": BENCHMARK_TICKER,
        "Name": BENCHMARK_NAME,
        "Open": raw["Open"].round(4),
        "High": raw["High"].round(4),
        "Low": raw["Low"].round(4),
        "Close": raw["Close"].round(4),
        "Adjusted_Close": raw["Adj Close"].round(4),
        "Volume": raw["Volume"],
    })
    save_csv(df, RAW_BENCHMARK_FILE)
    return df


def load_benchmark_data(path=RAW_BENCHMARK_FILE):
    """Load the saved S&P 500 prices and add the daily return."""
    df = pd.read_csv(path, parse_dates=["Date"])
    df = df.dropna(subset=["Adjusted_Close"]).sort_values("Date").drop_duplicates("Date")
    df = df[df["Adjusted_Close"] > 0].reset_index(drop=True)
    df["Daily_Return"] = df["Adjusted_Close"].pct_change()
    return df


# ---------------------------------------------------------------------------
# Risk measures (Phase 4 + optional Phase 13)
# ---------------------------------------------------------------------------
def annualized_return(daily_returns):
    return float(pd.Series(daily_returns).dropna().mean() * TRADING_DAYS_PER_YEAR)


def annualized_volatility(daily_returns):
    # Sample standard deviation (ddof=1), the usual choice for return data.
    return float(pd.Series(daily_returns).dropna().std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR))


def sharpe_ratio(ann_return, ann_volatility, risk_free_rate=RISK_FREE_RATE):
    if ann_volatility == 0 or np.isnan(ann_volatility):
        return np.nan
    return (ann_return - risk_free_rate) / ann_volatility


def max_drawdown(prices):
    """Largest peak-to-trough fall, as a negative decimal (-0.2 = -20%)."""
    prices = pd.Series(prices, dtype=float).dropna()
    if prices.empty:
        return np.nan
    drawdown = prices / prices.cummax() - 1
    return float(drawdown.min())


def assign_risk_groups(volatility):
    """
    Low / Medium / High by volatility terciles (lowest third = Low).
    With fewer than 3 stocks every stock is 'Medium'.
    """
    volatility = pd.Series(volatility, dtype=float)
    if len(volatility) < 3:
        return pd.Series("Medium", index=volatility.index)
    ranks = volatility.rank(method="first")
    return pd.qcut(ranks, 3, labels=RISK_GROUPS).astype(str)


def _risk_row(name, ticker, sector, daily_returns, adjusted_prices):
    ann_ret = annualized_return(daily_returns)
    ann_vol = annualized_volatility(daily_returns)
    prices = pd.Series(adjusted_prices, dtype=float).dropna()
    return {
        "Ticker": ticker,
        "Company": name,
        "Sector": sector,
        "Annualized_Return": ann_ret,
        "Annualized_Volatility": ann_vol,
        "Sharpe_Ratio": sharpe_ratio(ann_ret, ann_vol),
        "Max_Drawdown": max_drawdown(prices),
        "Total_Return": float(prices.iloc[-1] / prices.iloc[0] - 1),
    }


def calculate_risk_metrics(market_df, benchmark_df=None):
    """One row per stock (plus the S&P 500 if given) with risk measures."""
    rows = []
    for ticker, stock in market_df.sort_values("Date").groupby("Ticker"):
        rows.append(_risk_row(stock["Company"].iloc[0], ticker, stock["Sector"].iloc[0],
                              stock["Daily_Return"], stock["Adjusted_Close"]))
    risk = pd.DataFrame(rows)
    risk["Risk_Group"] = assign_risk_groups(risk["Annualized_Volatility"]).values

    if benchmark_df is not None:
        bench = _risk_row(BENCHMARK_NAME, BENCHMARK_TICKER, "Market index",
                          benchmark_df["Daily_Return"], benchmark_df["Adjusted_Close"])
        bench["Risk_Group"] = BENCHMARK_GROUP
        risk = pd.concat([risk, pd.DataFrame([bench])], ignore_index=True)

    risk["Risk_Free_Rate"] = RISK_FREE_RATE
    return risk.sort_values("Annualized_Volatility").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Benchmark comparison (Phase 6)
# ---------------------------------------------------------------------------
def build_benchmark_comparison(portfolio_value_df, benchmark_df):
    """
    Long table for one Tableau line chart: one row per date per series.
        Index_Value = value / value on the first day x 100

    The portfolio is valued at Close (price only), so the S&P 500 also uses
    its Close (price index, no dividends): a like-for-like comparison.
    """
    portfolio = portfolio_value_df.copy()
    portfolio["Date"] = pd.to_datetime(portfolio["Date"])
    bench = benchmark_df[["Date", "Close"]].copy()
    bench["Date"] = pd.to_datetime(bench["Date"])
    bench = bench[bench["Date"] >= portfolio["Date"].min()]

    merged = portfolio.merge(bench, on="Date", how="inner").sort_values("Date")
    if merged.empty:
        raise ValueError("The portfolio and the benchmark have no dates in common.")

    portfolio_rows = pd.DataFrame({
        "Date": merged["Date"],
        "Series": PORTFOLIO_SERIES,
        "Index_Value": merged["Portfolio_Value"] / merged["Portfolio_Value"].iloc[0] * 100,
        "Value_USD": merged["Portfolio_Value"],
    })
    bench_rows = pd.DataFrame({
        "Date": merged["Date"],
        "Series": BENCHMARK_NAME,
        "Index_Value": merged["Close"] / merged["Close"].iloc[0] * 100,
        "Value_USD": merged["Close"],
    })
    out = pd.concat([portfolio_rows, bench_rows], ignore_index=True)
    out["Index_Value"] = out["Index_Value"].round(4)
    out["Value_USD"] = out["Value_USD"].round(2)
    return out


def summarise_benchmark(comparison_df):
    """Total growth of each series over the comparison period (decimals)."""
    last = comparison_df.sort_values("Date").groupby("Series").tail(1).set_index("Series")
    portfolio = last.loc[PORTFOLIO_SERIES, "Index_Value"] / 100 - 1
    bench = last.loc[BENCHMARK_NAME, "Index_Value"] / 100 - 1
    return {"Portfolio_Growth": portfolio, "Benchmark_Growth": bench,
            "Excess_Return": portfolio - bench}
