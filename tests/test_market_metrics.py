"""Phase 2 tests: daily return, cumulative return and price change."""
import numpy as np
import pandas as pd
import pytest

from src.market_metrics import (
    add_cumulative_return,
    add_daily_return,
    add_price_change,
    build_tableau_market_data,
    calculate_market_metrics,
    validate_tableau_market_data,
)


def make_prices(prices_by_ticker):
    """Build a small market table: {ticker: [close, close, ...]}."""
    rows = []
    for ticker, prices in prices_by_ticker.items():
        for day, price in enumerate(prices):
            rows.append({
                "Date": pd.Timestamp("2025-01-01") + pd.Timedelta(days=day),
                "Ticker": ticker, "Company": ticker, "Sector": "Test",
                "Open": price, "High": price, "Low": price, "Close": price,
                "Adjusted_Close": price, "Volume": 100,
            })
    return pd.DataFrame(rows)


def test_daily_return_is_a_decimal():
    df = add_daily_return(make_prices({"AAA": [100, 102.5]}))
    assert df["Daily_Return"].iloc[1] == pytest.approx(0.025)  # 2.5% stored as 0.025


def test_first_day_has_no_daily_return():
    df = add_daily_return(make_prices({"AAA": [100, 110]}))
    assert np.isnan(df["Daily_Return"].iloc[0])


def test_returns_do_not_leak_between_tickers():
    df = add_daily_return(make_prices({"AAA": [100, 200], "BBB": [50, 55]}))
    first_bbb = df[df["Ticker"] == "BBB"]["Daily_Return"].iloc[0]
    assert np.isnan(first_bbb)  # BBB's first day is NOT compared with AAA's last day


def test_cumulative_return_compounds_daily_returns():
    # +10% then -10% is a 1% loss overall, not 0%.
    df = add_cumulative_return(add_daily_return(make_prices({"AAA": [100, 110, 99]})))
    assert df["Cumulative_Return"].tolist() == pytest.approx([0.0, 0.10, -0.01])


def test_cumulative_return_matches_last_over_first_price():
    prices = [100, 103, 97, 120, 118]
    df = calculate_market_metrics(make_prices({"AAA": prices}))
    assert df["Cumulative_Return"].iloc[-1] == pytest.approx(prices[-1] / prices[0] - 1)


def test_adjusted_close_is_used_for_returns_and_close_for_price_change():
    df = make_prices({"AAA": [100, 100]})
    df.loc[0, "Adjusted_Close"] = 98  # e.g. a dividend adjustment
    df = calculate_market_metrics(df)
    assert df["Daily_Return"].iloc[1] == pytest.approx(100 / 98 - 1)
    assert df["Price_Change"].iloc[1] == 0


def test_price_change_and_percentage():
    df = add_price_change(make_prices({"AAA": [200, 210]}))
    assert df["Price_Change"].iloc[1] == pytest.approx(10)
    assert df["Price_Change_Percentage"].iloc[1] == pytest.approx(5.0)  # percent, not decimal


def test_single_day_stock_has_zero_cumulative_return():
    df = calculate_market_metrics(make_prices({"AAA": [100]}))
    assert df["Cumulative_Return"].iloc[0] == 0


def test_unsorted_input_gives_same_result():
    ordered = calculate_market_metrics(make_prices({"AAA": [100, 110, 121]}))
    shuffled = calculate_market_metrics(make_prices({"AAA": [100, 110, 121]}).iloc[[2, 0, 1]])
    assert shuffled["Cumulative_Return"].tolist() == pytest.approx(ordered["Cumulative_Return"].tolist())


def test_tableau_market_data_passes_validation():
    df = build_tableau_market_data(
        calculate_market_metrics(make_prices({"AAA": [1, 2, 3], "BBB": [4, 5]})))
    assert validate_tableau_market_data(df) == []


def test_validation_catches_duplicate_rows():
    df = build_tableau_market_data(calculate_market_metrics(make_prices({"AAA": [1, 2, 3]})))
    df = pd.concat([df, df.tail(1)])
    assert "Duplicate Ticker + Date rows" in validate_tableau_market_data(df)
